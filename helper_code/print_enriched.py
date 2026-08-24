"""
Pretty-print an enriched hints JSONL, showing every weak_semantics and
strong_semantics field — including those inside cls_methods / cls_variables
sub-records.  Flags any that are still null.

Usage:
    python helper_code/print_enriched.py /tmp/enrich_test.jsonl
    python helper_code/print_enriched.py results/swe_pro/hints_communication_all_nonempty_enriched.jsonl
"""

import argparse
import json
import sys
from pathlib import Path


def _fmt(value: str | None, indent: str = "    ") -> str:
    if value is None:
        return f"{indent}\033[31m(null)\033[0m"
    return f"{indent}{value}"


def print_identifier(ident: dict, prefix: str = "  ") -> None:
    name  = ident.get("name", "?")
    etype = ident.get("entity_type", "?")
    path  = ident.get("path", "")
    weak  = ident.get("weak_semantics")
    strong = ident.get("strong_semantics")

    loc = f"  [{path}]" if path else ""
    print(f"{prefix}\033[1m{name}\033[0m  ({etype}){loc}")
    print(f"{prefix}  WEAK  : ", end="")
    if weak is None:
        print("\033[31m(null)\033[0m")
    else:
        print(weak)
    print(f"{prefix}  STRONG: ", end="")
    if strong is None:
        print("\033[31m(null)\033[0m")
    else:
        # Wrap long paragraphs at ~100 chars for readability
        words = strong.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > 100 and current:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines.append(current)
        cont_indent = " " * (len(prefix) + len("  STRONG: "))
        print(("\n" + cont_indent).join(lines))

    # Recurse into cls_methods
    for method in ident.get("cls_methods") or []:
        print(f"{prefix}  \033[2m↳ method:\033[0m")
        print_identifier(method, prefix=prefix + "    ")

    # Recurse into cls_variables
    for var in ident.get("cls_variables") or []:
        print(f"{prefix}  \033[2m↳ cls_var:\033[0m")
        print_identifier(var, prefix=prefix + "    ")


def print_record(rec: dict) -> None:
    iid   = rec.get("instance_id", "?")
    op    = rec.get("operator", "")
    level = rec.get("level", "")
    idents = rec.get("identifiers", [])

    print(f"\033[34m{'─' * 80}\033[0m")
    print(f"\033[34minstance : {iid}\033[0m")
    if op or level:
        print(f"           operator={op}  level={level}")
    print(f"           {len(idents)} identifier(s)")

    # Tally nulls (including nested)
    null_weak = null_strong = 0
    def _count(id_list):
        nonlocal null_weak, null_strong
        for ident in id_list:
            if not ident.get("weak_semantics"):
                null_weak += 1
            if not ident.get("strong_semantics"):
                null_strong += 1
            _count(ident.get("cls_methods") or [])
            _count(ident.get("cls_variables") or [])
    _count(idents)

    if null_weak or null_strong:
        print(f"           \033[31m⚠ null weak={null_weak}  null strong={null_strong}\033[0m")

    print()
    for ident in idents:
        print_identifier(ident)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretty-print enriched hints JSONL.")
    parser.add_argument("file", type=Path, help="Path to the enriched JSONL file.")
    parser.add_argument(
        "--nulls-only", action="store_true",
        help="Only show instances/identifiers that still have null semantics.",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    total_instances = total_idents = null_weak = null_strong = 0

    with open(args.file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            total_instances += 1
            total_idents += len(rec.get("identifiers", []))

            if args.nulls_only:
                # Check if any null exists anywhere in this record
                def _has_null(id_list):
                    for ident in id_list:
                        if not ident.get("weak_semantics") or not ident.get("strong_semantics"):
                            return True
                        if _has_null(ident.get("cls_methods") or []):
                            return True
                        if _has_null(ident.get("cls_variables") or []):
                            return True
                    return False
                if not _has_null(rec.get("identifiers", [])):
                    continue

            print_record(rec)

    # Summary
    print(f"\033[34m{'═' * 80}\033[0m")
    print(f"Total instances : {total_instances}")
    print(f"Total identifiers: {total_idents}")


if __name__ == "__main__":
    main()
