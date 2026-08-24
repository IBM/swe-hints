"""
show_class_row_hint.py
======================
Show what the rendered hint looks like WITH and WITHOUT the Class row
(and all its sub-rows: ClassName, SuperC, LocParClass, LocCompClass,
WeakSClass, StrongSClass) for a chosen instance.

Useful for understanding what information each taxonomy row contributes.

Usage
-----
    # Default: first instance in hints_helped_enriched.jsonl that has Class
    python helper_code/show_class_row_hint.py

    # Specific instance:
    python helper_code/show_class_row_hint.py \\
        --instance-id instance_ansible__ansible-489156378c8e97374...

    # Different hints file:
    python helper_code/show_class_row_hint.py \\
        --hints results/swe_pro/hints_communication_all_nonempty_enriched.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shapley.taxonomy_game import available_rows, render_hint

# All taxonomy rows that belong to the Class family
_CLASS_ROWS = frozenset({
    "Class", "ClassName", "SuperC", "Generic",
    "LocParClass", "LocCompClass",
    "WeakSClass", "StrongSClass",
    "FuncPub", "FuncPriv",
    "LocVarClass",
})


def find_instance(hints_path: Path, instance_id: str | None) -> dict:
    with open(hints_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if instance_id:
                if rec["instance_id"] == instance_id:
                    return rec
            else:
                # First instance that has at least one Class row active
                rows = available_rows(rec)
                if rows & _CLASS_ROWS:
                    return rec
    raise ValueError(
        f"No suitable instance found in {hints_path}"
        + (f" with id {instance_id!r}" if instance_id else " with Class rows active")
    )


def print_section(title: str, content: str) -> None:
    bar = "─" * 72
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)
    print(content if content else "(empty — no hints rendered)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show hint WITH vs WITHOUT Class rows for one instance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        default=Path("leave_one_out/output/hints_helped_enriched.jsonl"),
        help="Enriched hints JSONL. Default: leave_one_out/output/hints_helped_enriched.jsonl",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default=None,
        help="Specific instance ID to show. Default: first instance with Class rows active.",
    )
    args = parser.parse_args()

    rec = find_instance(args.hints, args.instance_id)
    iid  = rec["instance_id"]
    all_rows = available_rows(rec)
    class_rows_active = all_rows & _CLASS_ROWS

    print(f"Instance   : {iid}")
    print(f"All active rows ({len(all_rows)}): {sorted(all_rows)}")
    print(f"Class rows active ({len(class_rows_active)}): {sorted(class_rows_active)}")

    classes = [id for id in rec.get("identifiers", []) if id.get("entity_type") == "class"]
    print(f"Class identifiers: {[c['name'] for c in classes]}")

    # --- FULL hint (all active rows) ---
    hint_full = render_hint(rec, all_rows)
    print_section("HINT — WITH all Class rows", hint_full)

    # --- Without all Class rows ---
    rows_no_class = all_rows - _CLASS_ROWS
    hint_no_class = render_hint(rec, rows_no_class)
    print_section(
        f"HINT — WITHOUT Class rows ({sorted(class_rows_active)})",
        hint_no_class,
    )

    # --- Without each Class row individually ---
    for row in sorted(class_rows_active):
        rows_minus_one = all_rows - {row}
        hint_minus = render_hint(rec, rows_minus_one)
        print_section(f"HINT — WITHOUT '{row}' only", hint_minus)


if __name__ == "__main__":
    main()

# Made with Bob
