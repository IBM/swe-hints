#!/usr/bin/env python3
"""
Project SWE-Pro LLM hints (requirements and interfaces) to NoCode entity hints using LLM.

Uses the same LLM client configuration as swe_pro.py (`openai/aws/claude-haiku-4-5` via litellm)
with multi-stage robust JSON parsing to gracefully handle LLM formatting fluctuations
(e.g., markdown code blocks, trailing commas, preamble/postamble text, loose key names).

Usage:
    # Process a single directory of JSONL files (e.g. swe_pro_sel/union_defuse_nocode)
    python identity_selection/project_swe_pro_nocode_llm.py \
        --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode \
        --output identity_selection/results_selection/swe_pro_sel/projected_nocode

    # Process single file or limit instances (smoke test)
    python identity_selection/project_swe_pro_nocode_llm.py \
        --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/swebench_pro_official.jsonl \
        --output identity_selection/results_selection/swe_pro_sel/projected_nocode/swebench_pro_official.jsonl \
        --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator

import litellm
from tqdm import tqdm

litellm.drop_params = True

# ---------------------------------------------------------------------------
# LLM Model Configuration (matching identity_selection/swe_pro.py)
# ---------------------------------------------------------------------------

MODEL = os.environ.get("REQUIREMENTS_MODEL", "openai/YOUR_MODEL")
API_BASE = os.environ.get(
    "REQUIREMENTS_API_BASE",
    "YOUR_API_BASE",
)
API_KEY = os.environ.get("REQUIREMENTS_API_KEY", "YOUR_API_KEY")

NOCODE_HEADER = (
    "If completing this task requires creating new files, classes, fields, "
    "or error messages, you may consider using the following suggested entity names:"
)

ALLOWED_TYPES = {"file", "class", "function", "method", "variable", "field"}

BUILTIN_EXCLUDES = {
    "true", "false", "none", "str", "int", "float", "bool", "dict", "list", "set",
    "tuple", "any", "optional", "union", "iterable", "sequence", "callable",
    "valueerror", "typeerror", "exception", "path"
}

# ---------------------------------------------------------------------------
# Robust JSON Parsing & Normalization
# ---------------------------------------------------------------------------

def clean_and_parse_json(text: str) -> dict | list | None:
    """Robustly parse JSON output from LLM, handling markdown formatting, loose text, etc."""
    if not text:
        return None
    
    text = text.strip()

    # 1. Direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. Extract content inside ```json ... ``` or ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if code_block_match:
        block_text = code_block_match.group(1).strip()
        try:
            return json.loads(block_text)
        except Exception:
            text = block_text

    # 3. Find first [ ... ] or { ... } substring
    bracket_match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if bracket_match:
        json_candidate = bracket_match.group(1).strip()
        try:
            return json.loads(json_candidate)
        except Exception:
            # Clean trailing commas before closing brackets
            cleaned = re.sub(r",\s*([\]}])", r"\1", json_candidate)
            try:
                return json.loads(cleaned)
            except Exception:
                pass

    return None


def normalize_entities(raw_data: list | dict) -> list[dict]:
    """Validate, normalize, and filter entities extracted by LLM or regex fallback."""
    items = []
    if isinstance(raw_data, dict):
        # Look for typical list keys in LLM output dictionary
        items = raw_data.get("data") or raw_data.get("entities") or raw_data.get("hints") or []
    elif isinstance(raw_data, list):
        items = raw_data

    if not isinstance(items, list):
        items = []

    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        
        etype = str(item.get("type", "")).strip().lower()
        ename = str(item.get("name", "")).strip()

        if not ename or not etype:
            continue

        # Normalize entity type
        if etype in ("file", "filepath", "path", "module"):
            etype = "file"
        elif etype in ("class", "interface"):
            etype = "class"
        elif etype in ("function", "func"):
            etype = "function"
        elif etype in ("method", "classmethod", "staticmethod"):
            etype = "method"
        elif etype in ("variable", "var", "field", "attr", "attribute", "property", "parameter"):
            etype = "variable"
        else:
            etype = "variable"

        # Exclude common builtins/primitives
        if ename.lower() in BUILTIN_EXCLUDES:
            continue

        # Clean trailing () or quotes
        ename = re.sub(r"\(\)$", "", ename)
        ename = ename.strip("`'\"")

        key = (etype, ename)
        if key not in seen:
            seen.add(key)
            normalized.append({"type": etype, "name": ename})

    return normalized


def regex_fallback_extraction(requirements: str, interface: str) -> list[dict]:
    """Deterministic fallback if LLM produces unusable output."""
    entities: list[dict] = []
    
    # Extract from interface_generated
    if interface and "No new interfaces" not in interface:
        for block in re.split(r'\n(?=Type:|Name:|patch:)', interface.strip()):
            lines = block.strip().splitlines()
            kv = {}
            for line in lines:
                if ":" in line:
                    k, v = line.split(":", 1)
                    kv[k.strip().lower()] = v.strip()
            name = kv.get("name")
            if name:
                itype = kv.get("type", "function").lower()
                path = kv.get("path") or kv.get("pathfile") or kv.get("location")
                if path:
                    entities.append({"type": "file", "name": path})
                entities.append({"type": "function" if "function" in itype else "class" if "class" in itype else "method", "name": name})

    # Extract backtick tokens from requirements_generated
    if requirements:
        tokens = re.findall(r'`([^`\n]+)`', requirements)
        for token in tokens:
            token = token.strip()
            if not token or token.lower() in BUILTIN_EXCLUDES:
                continue
            if token.endswith(".py") or "/" in token:
                entities.append({"type": "file", "name": token})
            elif "." in token and not token.startswith("."):
                parts = token.split(".")
                if len(parts) == 2 and parts[0][0].isupper():
                    entities.append({"type": "class", "name": parts[0]})
                    entities.append({"type": "method", "name": parts[1].replace("()", "")})
            elif token.endswith("()"):
                entities.append({"type": "function", "name": token[:-2]})
            elif re.match(r'^[A-Z][a-zA-Z0-9]+$', token):
                entities.append({"type": "class", "name": token})
            elif re.match(r'^[a-z_][a-z0-9_]*$', token):
                entities.append({"type": "variable", "name": token})

    return normalize_entities(entities)

# ---------------------------------------------------------------------------
# LLM Prompt & Call Execution
# ---------------------------------------------------------------------------

PROMPT_SYSTEM = """\
You are an expert static analysis assistant. Your task is to analyze natural language implementation requirements and interface specifications, and extract all concrete software entity names (files, classes, functions, methods, variables/fields).

Return ONLY a JSON list of objects, where each object has:
- "type": One of ["file", "class", "function", "method", "variable"]
- "name": The exact identifier or relative file path

Rules:
1. "file": Any file path (e.g. "qutebrowser/utils/urlutils.py").
2. "class": Class names (e.g. "HostBlocker").
3. "function": Standalone function names (e.g. "widened_hostnames").
4. "method": Class method names (e.g. "matches_filter").
5. "variable": Parameter names, configuration options, field names, or constants (e.g. "default_size").
6. Do NOT include built-in Python primitives or typing keywords (str, int, dict, list, bool, Optional, Union, True, False, None).
7. Return ONLY valid JSON block. No explanation or preamble."""

def call_llm_project(requirements: str, interface: str, retries: int = 3) -> list[dict]:
    """Call LLM to project text hints to entity list, with retries and fallback."""
    user_prompt = (
        "## Interface Specification\n"
        f"{interface.strip() if interface else '(none)'}\n\n"
        "## Implementation Requirements\n"
        f"{requirements.strip() if requirements else '(none)'}\n\n"
        "Extract all target software entities as JSON list."
    )

    messages = [
        {"role": "system", "content": PROMPT_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(retries):
        try:
            response = litellm.completion(
                model=MODEL,
                api_base=API_BASE,
                api_key=API_KEY,
                temperature=0.0,
                messages=messages,
            )
            raw_text = response.choices[0].message.content
            parsed = clean_and_parse_json(raw_text)
            if parsed is not None:
                entities = normalize_entities(parsed)
                if entities:
                    return entities
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))

    # Fallback to deterministic regex parsing if LLM call or JSON parsing failed
    return regex_fallback_extraction(requirements, interface)

# ---------------------------------------------------------------------------
# Processing Helpers
# ---------------------------------------------------------------------------

def project_instance_llm(entry: dict) -> dict:
    reqs = entry.get("requirements_generated", "")
    iface = entry.get("interface_generated", "")

    data = call_llm_project(reqs, iface)

    return {
        "instance_id": entry["instance_id"],
        "repo": entry.get("repo", ""),
        "hints": {
            "header": NOCODE_HEADER,
            "data": data,
        },
    }


def process_jsonl_file(src_path: Path, dst_path: Path, limit: int | None = None) -> None:
    print(f"\nProcessing {src_path.name} -> {dst_path}")
    
    entries = []
    with open(src_path) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    if limit is not None:
        entries = entries[:limit]

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dst_path, "w") as out_f:
        for entry in tqdm(entries, desc=src_path.name, unit="inst"):
            projected = project_instance_llm(entry)
            out_f.write(json.dumps(projected, ensure_ascii=False) + "\n")

    print(f"Finished {src_path.name}: wrote {len(entries)} projected instances.")

# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-based NoCode Projection for SWE-Pro generated requirements and interfaces."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        type=Path,
        help="Input JSONL file or directory containing union_defuse_nocode files.",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        type=Path,
        help="Output JSONL file or output directory for projected files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of instances per file (for testing).",
    )
    args = parser.parse_args()

    input_path: Path = args.input
    output_path: Path = args.output

    if input_path.is_file():
        process_jsonl_file(input_path, output_path, limit=args.limit)
    elif input_path.is_dir():
        output_path.mkdir(parents=True, exist_ok=True)
        jsonl_files = sorted(input_path.glob("*.jsonl"))
        if not jsonl_files:
            sys.exit(f"No .jsonl files found in {input_path}")
        
        for src_file in jsonl_files:
            dst_file = output_path / src_file.name
            process_jsonl_file(src_file, dst_file, limit=args.limit)
    else:
        sys.exit(f"Input path does not exist: {input_path}")


if __name__ == "__main__":
    main()
