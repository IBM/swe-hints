#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
SWE-bench Pro style annotation (interface + requirements) for JAVA instances.

Java counterpart of identity_selection/swe_pro.py.  Same two LLM tasks, same
output schema, same CLI surface; only the language-specific parts differ:

  * public-symbol extraction runs through extract_public_symbols_java.py
    (tree-sitter Java) instead of the stdlib-`ast` Python extractor;
  * "private" means the Java access modifier, not a leading underscore —
    Java states visibility explicitly, so the rule is stricter and exact;
  * the prompts name Java constructs (interface/enum/record, throws, javadoc).

FEW-SHOT EXAMPLES ARE PYTHON, ON PURPOSE.  The gold examples in
identity_selection/swe_pro.py are hand-checked and the output FORMAT is
language-independent, so they are reused verbatim and labelled to the model as
Python examples ("The following worked examples are in Python; your task is in
Java — copy their FORMAT, not their syntax").  Rewriting them as Java examples
would mean hand-authoring new gold annotations, which is a data-collection task,
not a port.

The Python module is imported read-only for the shared plumbing (LLM call,
JSONL iteration, resume) — nothing in it is modified.

Environment: REQUIREMENTS_MODEL / REQUIREMENTS_API_BASE / REQUIREMENTS_API_KEY,
same as the Python original.

Usage
-----
    python identity_selection/swe_pro_java.py \
        --task  both \
        --input data/java/multi_swe_bench_java.jsonl \
        --output identity_selection/results_selection/java_msb/swe_pro_java.jsonl \
        --repos repos/multi_swe_java_repos
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

# Shared plumbing, imported read-only from the frozen Python module.
# NOTE: call_llm is deliberately NOT imported — see the override below.
from swe_pro import (                     # noqa: E402
    iter_instances,
    load_completed_ids,
    _REQ_FEW_SHOT_EXAMPLES,
    _IFACE_FEW_SHOT_EXAMPLES,
)
from utils import get_impl_patch, get_test_patch, find_repo_dir   # noqa: E402

# ---------------------------------------------------------------------------
# LLM call — credential-aware replacement for swe_pro.call_llm
#
# The frozen swe_pro.call_llm passes a literal api_key="YOUR_API_KEY" and never
# reads REQUIREMENTS_API_KEY, so it cannot authenticate against any endpoint.
# swe_pro.py is frozen, so the fix lives here.  Same signature, same sampling
# (temperature 1.0, reasoning_effort "high") — only credential resolution
# differs.  Mirrors src/enrich_semantics.py: an ``openrouter/`` model falls back
# to $OPENROUTER_API_KEY and sends no api_base unless one is set explicitly.
# drop_params lets litellm strip reasoning_effort for models that reject it.
# ---------------------------------------------------------------------------
import os                                 # noqa: E402
import time                               # noqa: E402

import litellm                            # noqa: E402

_PLACEHOLDERS = {"", "YOUR_API_KEY", "YOUR_API_BASE", "openai/YOUR_MODEL"}


def _llm_kwargs() -> dict:
    model = os.environ.get("REQUIREMENTS_MODEL", "")
    if model in _PLACEHOLDERS:
        raise SystemExit(
            "REQUIREMENTS_MODEL is not set. Example:\n"
            '  export REQUIREMENTS_MODEL="openrouter/anthropic/claude-haiku-4.5"'
        )
    kw: dict = {
        "model": model,
        "temperature": 1.0,
        "reasoning_effort": "high",
        "drop_params": True,
    }
    key = os.environ.get("REQUIREMENTS_API_KEY", "")
    base = os.environ.get("REQUIREMENTS_API_BASE", "")
    if model.startswith("openrouter/") and key in _PLACEHOLDERS:
        key = os.environ.get("OPENROUTER_API_KEY", "")
    if key not in _PLACEHOLDERS:
        kw["api_key"] = key
    if base not in _PLACEHOLDERS:
        kw["api_base"] = base
    return kw


def call_llm(messages: list[dict], retries: int = 3, backoff: float = 10.0) -> str:
    """Call the LLM and return the text of the first response message."""
    kwargs = _llm_kwargs()
    for attempt in range(retries):
        try:
            response = litellm.completion(messages=messages, **kwargs)
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  [warn] LLM call failed ({exc}); retrying in {wait:.0f}s …")
                time.sleep(wait)
            else:
                raise
    return ""  # unreachable

# ---------------------------------------------------------------------------
# Prompts — Java wording, Python few-shots explicitly labelled as such
# ---------------------------------------------------------------------------

_LANG_NOTE = (
    "NOTE ON THE EXAMPLES: the worked examples below are written in PYTHON, "
    "because the reference annotations for this dataset were authored in Python. "
    "The task you are given is in JAVA. Copy the FORMAT and the level of detail "
    "of the examples exactly; do not copy their syntax, naming conventions, or "
    "language-specific idioms."
)

_REQ_SYSTEM_PROMPT_JAVA = """\
You are a senior software engineer writing implementation requirements for Java code changes.

Given a GitHub issue (problem statement), the gold patch that resolves it, and the
test patch that verifies the fix, produce 4-8 concise bullet-point requirements that
precisely describe what a correct implementation MUST do.

Rules:
- Ground every requirement in what the patch actually changes - do not invent constraints
  that are not present in the diff.
- Use the test patch as evidence for exact expected behaviour: method names, return
  values, thrown exception types, edge cases, and parameter semantics asserted by the
  tests (JUnit assertions, assertThrows, @Test(expected=...)) must be reflected.
- Write requirements as implementation constraints, not issue restatements.
- Each bullet must be specific and testable.
- Mention concrete names (methods, classes, interfaces, enums, constants, packages)
  when the patch introduces them. Include the parameter list when a method is
  overloaded, since the bare name is ambiguous in Java.
- Do NOT include a header line - start directly with the first bullet (`- ...`).
- Use plain Markdown bullets only (`- `). No numbered lists.

""" + _LANG_NOTE

_IFACE_SYSTEM_PROMPT_JAVA = """\
You are a senior engineer documenting public APIs for a software benchmark dataset.

Given a GitHub issue, new public symbols extracted from the gold patch (Stage 1),
test-enforced contracts (Stage 2), the full gold patch, and the full test patch,
produce a structured interface block in SWE-bench Pro format.

Rules:
- TRUST STAGE 1 ABOVE ALL ELSE. If Stage 1 reports "(none detected by static
  analysis)", that means no new public top-level symbols were added. Output
  exactly: No new interfaces are introduced
  Do NOT invent interfaces by reading the patch yourself in this case.
- Only produce entries for symbols that Stage 1 explicitly listed. Do not add
  symbols you see in the patch that are absent from Stage 1's output.
- NEVER document non-public symbols. In Java visibility is explicit: document only
  `public` (and `protected` where the class is extensible) types and members;
  omit anything private or package-private. Unlike Python there is no naming
  convention to guess from - use the declared modifier.
- NEVER document a symbol that already existed and was merely modified or moved;
  only truly new additions count.
- One entry per top-level public type (class, interface, enum, record, annotation).
- For a type, write a single entry describing it and summarise its public members
  in a "Public API" line rather than listing them as separate entries. State what
  it extends or implements when the patch declares it.
- Use exact names, packages and paths from the test patch when available - they
  take precedence over the static analysis results.
- For each entry include: Type, Name, Path, Input, Output (or Public API), Description.
  For a method, Input is the parameter list with declared types and Output is the
  declared return type; note checked exceptions from the `throws` clause.
- Do NOT include a preamble - start directly with the first entry.

""" + _LANG_NOTE


def _relabel(messages: list[dict]) -> list[dict]:
    """Tag each reused Python few-shot turn so the model cannot mistake it for Java."""
    out = []
    for m in messages:
        if m.get("role") == "user":
            out.append({**m, "content": "[WORKED EXAMPLE - PYTHON]\n" + m["content"]})
        else:
            out.append(dict(m))
    return out


def build_requirements_prompt_java(problem_statement: str, patch: str, test_patch: str) -> list[dict]:
    messages = [{"role": "system", "content": _REQ_SYSTEM_PROMPT_JAVA}]
    for ex in _REQ_FEW_SHOT_EXAMPLES:
        messages += _relabel([
            {"role": "user", "content": (
                "## Problem statement\n" + ex["problem_statement"].strip() +
                "\n\n## Gold patch\n```diff\n" + ex["patch"].strip() + "\n```" +
                "\n\n## Test patch\n```diff\n" + ex["test_patch"].strip() + "\n```")},
            {"role": "assistant", "content": ex["requirements"].strip()},
        ])
    messages.append({"role": "user", "content": (
        "[YOUR TASK - JAVA]\n"
        "## Problem statement\n" + (problem_statement or "").strip() +
        "\n\n## Gold patch\n```diff\n" + (patch or "").strip() + "\n```" +
        "\n\n## Test patch\n```diff\n" + (test_patch or "").strip() + "\n```")})
    return messages


def build_interface_prompt_java(problem_statement: str, symbols_block: str,
                                contracts_block: str, patch: str, test_patch: str) -> list[dict]:
    messages = [{"role": "system", "content": _IFACE_SYSTEM_PROMPT_JAVA}]
    for ex in _IFACE_FEW_SHOT_EXAMPLES:
        messages += _relabel([
            {"role": "user", "content": (
                "## Problem statement\n" + ex["problem_statement"].strip() +
                "\n\n## Stage 1 - new public symbols\n" + ex.get("symbols", "").strip() +
                "\n\n## Gold patch\n```diff\n" + ex["patch"].strip() + "\n```")},
            {"role": "assistant", "content": ex["interface"].strip()},
        ])
    messages.append({"role": "user", "content": (
        "[YOUR TASK - JAVA]\n"
        "## Problem statement\n" + (problem_statement or "").strip() +
        "\n\n## Stage 1 - new public symbols (tree-sitter Java)\n" + symbols_block +
        "\n\n## Stage 2 - test-enforced contracts\n" + (contracts_block or "(none)") +
        "\n\n## Gold patch\n```diff\n" + (patch or "").strip() + "\n```" +
        "\n\n## Test patch\n```diff\n" + (test_patch or "").strip() + "\n```")})
    return messages


# ---------------------------------------------------------------------------
# Stage 1 — Java public symbols
# ---------------------------------------------------------------------------

def java_symbols_block(example: dict, repos_dir: Path | None) -> str:
    """Stage-1 block from the Java public-symbol extractor."""
    if repos_dir is None:
        return "(none detected by static analysis)"
    try:
        from extract_public_symbols_java import extract_public_symbols_java
    except Exception as exc:                                  # pragma: no cover
        return f"(static analysis unavailable: {exc})"
    try:
        repo_dir = find_repo_dir(example.get("repo", ""), repos_dir)
        symbols = extract_public_symbols_java(example, repo_dir)
    except Exception as exc:
        return f"(static analysis failed: {exc})"
    if not symbols:
        return "(none detected by static analysis)"
    lines = []
    for s in symbols:
        bits = [f"{s.get('kind','symbol')}: {s.get('name','')}"]
        if s.get("path"):
            bits.append(f"path={s['path']}")
        if s.get("signature"):
            bits.append(f"signature={s['signature']}")
        lines.append("- " + "  ".join(bits))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", choices=("requirements", "interface", "both"), default="both")
    ap.add_argument("--input", "-i", required=True)
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--repos", "-r", default=None, help="Java repos dir (Stage 1).")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--instance-id", default=None)
    ap.add_argument("--skip-errors", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Build prompts and print the first one; make no LLM calls.")
    args = ap.parse_args()

    repos_dir = Path(args.repos) if args.repos else None
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_completed_ids(str(out_path))
    if done:
        print(f"Resuming — {len(done)} instances already done.")

    n = 0
    with out_path.open("a", encoding="utf-8", buffering=1) as out:
        for example in iter_instances(args.input):
            iid = example.get("instance_id", "")
            if args.instance_id and iid != args.instance_id:
                continue
            if iid in done:
                continue
            if args.limit is not None and n >= args.limit:
                break

            problem = example.get("problem_statement", "")
            patch = get_impl_patch(example)
            test_patch = get_test_patch(example)
            rec = dict(example)

            try:
                if args.task in ("requirements", "both"):
                    msgs = build_requirements_prompt_java(problem, patch, test_patch)
                    if args.dry_run:
                        print(json.dumps(msgs[-1], indent=2)[:2000]); return
                    rec["requirements_generated"] = call_llm(msgs)
                if args.task in ("interface", "both"):
                    msgs = build_interface_prompt_java(
                        problem, java_symbols_block(example, repos_dir), "", patch, test_patch)
                    if args.dry_run:
                        print(json.dumps(msgs[-1], indent=2)[:2000]); return
                    rec["interface_generated"] = call_llm(msgs)
            except Exception as exc:
                print(f"  [error] {iid}: {exc}", file=sys.stderr)
                if not args.skip_errors:
                    raise
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            print(f"  {iid}")

    print(f"\nWrote {n} instances -> {out_path}")


if __name__ == "__main__":
    main()
