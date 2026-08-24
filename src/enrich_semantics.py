"""
Step 2.5 (post-projection): Enrich weak_semantics and strong_semantics via LLM.

Input:   results/swe_pro/hints_communication_all_nonempty.jsonl
         (from identifier_information.py --level All)
Source:  swebench_pro.jsonl  (for problem_statement, patch, test_patch)

Output:  results/swe_pro/hints_communication_all_nonempty_enriched.jsonl
         Same schema as input, but with weak_semantics and strong_semantics
         always set by the LLM (existing values, including docstring-derived
         ones, are overwritten).

Strategy
--------
One LLM call per IDENTIFIER, not per instance.
For every identifier (regardless of whether it already has semantics):
  - Summarise the identifier's structural facts (entity_type, signature, etc.)
  - Filter the patch / test_patch to ±N lines around occurrences of the name
  - Ask Claude Haiku 4.5 for:
      WEAK: <one sentence ≤ 20 words — what this entity IS and does>
      STRONG: <2-4 sentence paragraph — behaviour, edge cases, test-implied constraints>

Usage
-----
    python -m src.enrich_semantics

    # Smoke-test on one instance
    python -m src.enrich_semantics \\
        --output /tmp/smoke.jsonl \\
        --instance-id instance_ansible__ansible-395e5e20fab9cad517243372fa3c3c5d9e09ab2a-v7eee2454f617569fd6889f2211f75bc02a35f9f8

    # Dry-run (build prompts only, no LLM calls)
    python -m src.enrich_semantics --output /tmp/dry.jsonl --dry-run --limit 2

Environment variables
---------------------
  ENRICH_MODEL      litellm model string (default: openai/aws/claude-haiku-4-5)
  ENRICH_API_BASE   API base URL
  ENRICH_API_KEY    API key
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import litellm
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Model config  (mirrors the sibling scripts in SWE-bench_Pro-os/)
# ---------------------------------------------------------------------------

litellm.drop_params = True

MODEL = os.environ.get("ENRICH_MODEL", "openai/aws/claude-haiku-4-5")
API_BASE = os.environ.get(
    "ENRICH_API_BASE",
    "YOUR_API_BASE",
)
API_KEY = os.environ.get("ENRICH_API_KEY", "YOUR_API_KEY")
# Lines of context to include around each patch hit
_CONTEXT_LINES = 4

# ---------------------------------------------------------------------------
# Patch context extraction
# ---------------------------------------------------------------------------

def _filter_patch_context(patch: str, name: str, context: int = _CONTEXT_LINES) -> str:
    """
    Return the lines of `patch` that mention `name`, plus ±`context` surrounding
    lines.  Only added lines (starting with '+') and context lines are included so
    the LLM sees relevant changes rather than the full diff.

    Returns an empty string when `name` does not appear in the patch.
    """
    if not patch or not name:
        return ""

    lines = patch.splitlines()
    # Find all line indices that contain the identifier name as a whole word
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    hits: set[int] = set()
    for i, line in enumerate(lines):
        if pattern.search(line):
            hits.add(i)

    if not hits:
        return ""

    # Expand each hit into a window
    keep: set[int] = set()
    for h in hits:
        for j in range(max(0, h - context), min(len(lines), h + context + 1)):
            keep.add(j)

    selected = [lines[i] for i in sorted(keep)]
    return "\n".join(selected)


# ---------------------------------------------------------------------------
# Structural fact formatter
# ---------------------------------------------------------------------------

def _format_entity(identifier: dict) -> str:
    """
    Render an identifier's structural facts as a concise text block for the
    LLM prompt.  Mirrors the style of generate_interface.py.
    """
    parts: list[str] = []

    name   = identifier.get("name", "?")
    etype  = identifier.get("entity_type", "?")
    path   = identifier.get("path", "")
    sig    = identifier.get("signature")
    ispec  = identifier.get("input_spec")
    itypes = identifier.get("input_types")
    opt    = identifier.get("output_complete_type") or identifier.get("output_partial_type")
    super_ = identifier.get("superclass")
    gen    = identifier.get("generics")
    vtype  = identifier.get("var_type")
    vval   = identifier.get("var_value")
    exc_t  = identifier.get("exception_types")
    pub_m  = identifier.get("public_methods")
    priv_m = identifier.get("private_methods")
    imports = identifier.get("imports")

    parts.append(f"Entity type : {etype}")
    parts.append(f"Name        : {name}")
    if path:
        parts.append(f"Path        : {path}")
    if sig:
        parts.append(f"Signature   : {sig}")
    elif etype == "variable":
        if vtype:
            parts.append(f"Type        : {vtype}")
        if vval:
            # Truncate very long values (e.g. large dicts)
            vval_s = vval if len(vval) <= 200 else vval[:200] + " …"
            parts.append(f"Value       : {vval_s}")
    if ispec and ispec != sig:
        parts.append(f"Inputs      : {ispec}")
    elif itypes:
        parts.append(f"Input types : {itypes}")
    if opt:
        parts.append(f"Output type : {opt}")
    if super_:
        parts.append(f"Superclass  : {super_}")
    if gen:
        parts.append(f"Generics    : {gen}")
    if exc_t:
        parts.append(f"Raises      : {exc_t}")
    if pub_m:
        parts.append(f"Public methods  : {pub_m}")
    if priv_m:
        parts.append(f"Private methods : {priv_m}")
    if imports:
        # Keep imports short — first 300 chars
        imp_s = imports if len(imports) <= 300 else imports[:300] + " …"
        parts.append(f"File imports: {imp_s}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt builder  (one call per identifier)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are documenting a newly introduced Python identifier for a software engineering benchmark.

Given the identifier's structural facts and the relevant lines from the code/test patches \
that introduce it, write exactly two fields:

  WEAK: A single sentence (≤ 20 words) stating what this entity IS and does — purely \
behavioural, no implementation detail.
  STRONG: A paragraph of 2–4 sentences expanding on the weak description: internal \
behaviour, edge cases handled, constraints implied by the tests, and relationship to \
other identifiers in the patch.

Respond with exactly this format — nothing else, no preamble, no trailing text:
WEAK: <sentence>
STRONG: <paragraph>"""


def build_prompt(
    identifier: dict,
    problem_statement: str,
    patch_context: str,
    test_context: str,
) -> list[dict]:
    entity_block = _format_entity(identifier)

    user_parts = [
        "## Structural facts",
        entity_block,
        "",
        "## Problem being solved",
        problem_statement.strip() if problem_statement else "(not available)",
    ]
    if patch_context:
        user_parts += ["", "## Relevant patch lines", "```diff", patch_context, "```"]
    if test_context:
        user_parts += ["", "## Relevant test lines", "```diff", test_context, "```"]

    user_content = "\n".join(user_parts)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]


# ---------------------------------------------------------------------------
# LLM call + response parser
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], retries: int = 3, backoff: float = 10.0) -> str:
    for attempt in range(retries):
        try:
            response = litellm.completion(
                model=MODEL,
                api_base=API_BASE,
                api_key=API_KEY,
                temperature=0.3,
                max_tokens=300,
                messages=messages,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                tqdm.write(f"    [warn] LLM error ({exc}); retrying in {wait:.0f}s …")
                time.sleep(wait)
            else:
                raise
    return ""


def parse_response(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse 'WEAK: ...\nSTRONG: ...' from the LLM response.
    Returns (weak, strong) — either may be None if parsing fails.
    """
    weak = strong = None

    # Try line-by-line parse first (most common case)
    lines = text.splitlines()
    strong_lines: list[str] = []
    in_strong = False
    for line in lines:
        if line.startswith("WEAK:"):
            weak = line[len("WEAK:"):].strip()
            in_strong = False
        elif line.startswith("STRONG:"):
            strong_lines = [line[len("STRONG:"):].strip()]
            in_strong = True
        elif in_strong and line.strip():
            strong_lines.append(line.strip())

    if strong_lines:
        strong = " ".join(strong_lines)

    # Fallback: regex
    if weak is None:
        m = re.search(r'WEAK:\s*(.+?)(?=STRONG:|$)', text, re.DOTALL)
        if m:
            weak = m.group(1).strip()
    if strong is None:
        m = re.search(r'STRONG:\s*(.+)', text, re.DOTALL)
        if m:
            strong = m.group(1).strip()

    return weak or None, strong or None


# ---------------------------------------------------------------------------
# Per-identifier enrichment
# ---------------------------------------------------------------------------

def enrich_identifier(
    identifier: dict,
    problem_statement: str,
    patch: str,
    test_patch: str,
    dry_run: bool = False,
) -> dict:
    """
    Return a copy of `identifier` with weak_semantics / strong_semantics always
    regenerated by the LLM, overwriting any existing values (including docstring-
    derived ones).
    On dry_run, builds the prompt but makes no LLM call.
    """
    name = identifier.get("name", "")
    patch_ctx = _filter_patch_context(patch,      name)
    test_ctx  = _filter_patch_context(test_patch, name)

    messages = build_prompt(identifier, problem_statement, patch_ctx, test_ctx)

    if dry_run:
        tqdm.write(f"    [dry-run] Would call LLM for {name!r}")
        tqdm.write("    Prompt user content (first 300 chars):")
        tqdm.write("    " + messages[1]["content"][:300].replace("\n", "\n    "))
        return identifier  # unchanged

    raw = call_llm(messages)
    weak_new, strong_new = parse_response(raw)

    result = dict(identifier)
    if weak_new:
        result["weak_semantics"] = weak_new
    if strong_new:
        result["strong_semantics"] = strong_new

    # Recurse into cls_methods sub-records
    if identifier.get("cls_methods"):
        result["cls_methods"] = [
            enrich_identifier(m, problem_statement, patch, test_patch, dry_run=dry_run)
            for m in identifier["cls_methods"]
        ]

    # Recurse into cls_variables sub-records
    if identifier.get("cls_variables"):
        result["cls_variables"] = [
            enrich_identifier(v, problem_statement, patch, test_patch, dry_run=dry_run)
            for v in identifier["cls_variables"]
        ]

    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def load_swebench_index(source_path: Path) -> dict[str, dict]:
    """Index swebench_pro.jsonl by instance_id."""
    index: dict[str, dict] = {}
    with open(source_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                iid = row.get("instance_id")
                if iid:
                    index[iid] = row
    return index


def load_completed_ids(output_path: Path) -> set[str]:
    done: set[str] = set()
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["instance_id"])
                except Exception:
                    pass
    return done


def run(
    hints_path: Path,
    source_path: Path,
    output_path: Path,
    instance_id: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    skip_errors: bool = False,
) -> None:
    # Load SWE-bench source for patch / test_patch / problem_statement
    tqdm.write(f"Loading SWE-bench source from {source_path} …")
    swe_index = load_swebench_index(source_path)
    tqdm.write(f"  {len(swe_index)} instances indexed.")

    # Load hints records
    hints_records: list[dict] = []
    with open(hints_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                hints_records.append(json.loads(line))

    # Filter
    if instance_id:
        hints_records = [r for r in hints_records if r["instance_id"] == instance_id]
        if not hints_records:
            raise ValueError(f"instance_id {instance_id!r} not found in {hints_path}")

    # Resume support
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_completed_ids(output_path)
    if done_ids:
        tqdm.write(f"Resuming — {len(done_ids)} instances already done.")
    hints_records = [r for r in hints_records if r["instance_id"] not in done_ids]

    if limit is not None:
        hints_records = hints_records[:limit]

    # Count total identifiers to enrich (all of them — LLM always regenerates)
    total_to_enrich = sum(
        len(rec.get("identifiers", [])) for rec in hints_records
    )
    tqdm.write(
        f"Processing {len(hints_records)} instances, "
        f"{total_to_enrich} identifiers to enrich."
    )

    n_ok = n_err = n_skipped_source = 0

    with open(output_path, "a", encoding="utf-8", buffering=1) as out_f:
        for rec in tqdm(hints_records, unit="inst"):
            iid = rec["instance_id"]
            swe_row = swe_index.get(iid)

            if swe_row is None:
                tqdm.write(f"  [skip] {iid} — not found in source JSONL")
                n_skipped_source += 1
                # Write record unchanged so we don't lose it
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            problem_statement = swe_row.get("problem_statement", "")
            patch             = swe_row.get("patch", "")
            test_patch        = swe_row.get("test_patch", "")

            enriched_identifiers: list[dict] = []
            instance_ok = True

            for ident in rec.get("identifiers", []):
                name = ident.get("name", "?")
                try:
                    enriched = enrich_identifier(
                        ident, problem_statement, patch, test_patch,
                        dry_run=dry_run,
                    )
                    enriched_identifiers.append(enriched)
                except Exception as exc:
                    tqdm.write(f"  [error] {iid}/{name}: {exc}")
                    enriched_identifiers.append(ident)  # keep original
                    if not skip_errors:
                        instance_ok = False
                        n_err += 1
                        break

            out_rec = {**rec, "identifiers": enriched_identifiers}
            out_f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")

            if instance_ok:
                n_ok += 1
            else:
                n_err += 1

    print(
        f"\nDone. ok={n_ok}  errors={n_err}  "
        f"skipped_no_source={n_skipped_source}  output={output_path}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Step 2.5: Enrich weak_semantics / strong_semantics via LLM.\n\n"
            "Reads hints_communication_all_nonempty.jsonl and fills any identifier\n"
            "records whose weak_semantics or strong_semantics are None by calling\n"
            "Claude Haiku 4.5 with focused patch context."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        default=Path("results/swe_pro/hints_communication_all_nonempty.jsonl"),
        help="Input hints JSONL (output of step 2). Default: results/swe_pro/hints_communication_all_nonempty.jsonl",
    )
    parser.add_argument(
        "--source", "-s",
        type=Path,
        default=Path("data/swebench_pro_python.jsonl"),
        help="SWE-bench Pro JSONL (provides patch, test_patch, problem_statement). "
             "Default: data/swebench_pro_python.jsonl",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("results/swe_pro/hints_communication_all_nonempty_enriched.jsonl"),
        help="Output enriched JSONL. Default: results/swe_pro/hints_communication_all_nonempty_enriched.jsonl",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default=None,
        help="Only process this instance (for debugging).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N instances (useful for smoke-testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts but do not call the LLM. Prints prompt previews.",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="On LLM error, keep the original identifier record and continue.",
    )
    args = parser.parse_args()

    run(
        hints_path=args.hints,
        source_path=args.source,
        output_path=args.output,
        instance_id=args.instance_id,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_errors=args.skip_errors,
    )


if __name__ == "__main__":
    _cli()

# Made with Bob
