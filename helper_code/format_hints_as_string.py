#!/usr/bin/env python3
"""
Convert an enriched hints JSONL (output of src/enrich_semantics.py) into a
JSONL whose ``hints`` field is a plain human-readable string, ready for
generate_doc2feat_instances.py --hints_file.

Each identifier is rendered as:

  <entity_type>: <name>
    <weak_semantics>
    [<strong_semantics>]

Class methods / variables are indented one level further.

Usage
-----
    python helper_code/format_hints_as_string.py \\
        --input  results/doc2feat/hints_communication_all_nonempty_enriched.jsonl \\
        --output results/doc2feat/hints_string.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_identifier(ident: dict, indent: str = "") -> list[str]:
    """Render one identifier (and any nested cls_methods/cls_variables) as lines."""
    lines: list[str] = []

    name   = ident.get("name", "?")
    etype  = ident.get("entity_type", "?")
    weak   = ident.get("weak_semantics") or ""
    strong = ident.get("strong_semantics") or ""

    lines.append(f"{indent}{etype}: {name}")
    if weak:
        lines.append(f"{indent}  {weak}")
    if strong:
        lines.append(f"{indent}  {strong}")

    sub_indent = indent + "  "
    for method in ident.get("cls_methods") or []:
        lines.extend(_fmt_identifier(method, indent=sub_indent))
    for var in ident.get("cls_variables") or []:
        lines.extend(_fmt_identifier(var, indent=sub_indent))

    return lines


def identifiers_to_hints_string(identifiers: list[dict]) -> str:
    """Convert a list of identifier dicts into a single hints string."""
    if not identifiers:
        return ""
    lines: list[str] = []
    for ident in identifiers:
        lines.extend(_fmt_identifier(ident))
        lines.append("")          # blank line between identifiers
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert enriched hints JSONL to a plain hints-string JSONL "
            "compatible with generate_doc2feat_instances.py --hints_file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Enriched hints JSONL (output of src/enrich_semantics.py).",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output JSONL with a 'hints' string field per instance.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_total = n_nonempty = 0
    with open(args.input, encoding="utf-8") as in_f, \
         open(args.output, "w", encoding="utf-8") as out_f:
        for line in in_f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            hints_str = identifiers_to_hints_string(rec.get("identifiers") or [])
            out_rec = {
                "instance_id": rec["instance_id"],
                "hints":       hints_str,
            }
            out_f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            n_total += 1
            if hints_str:
                n_nonempty += 1

    print(f"Total: {n_total}  |  Non-empty hints: {n_nonempty}  |  Empty: {n_total - n_nonempty}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()

# Made with Bob
