"""
Statistics over entries in a hints JSONL file.

Organises output around the 6 taxonomy subtree roots from taxonomy_game_v3.py:
  File, Class, ClsFunc, ClsVar, Func, Var

For each subtree root reports:
  - how many instances have at least one row from that subtree available
  - for each row in the subtree: how many instances have it

Also reports:
  - identifier counts per instance (min / mean / max)
  - entity_type distribution

Usage:
    python helper_code/hint_entry_stats.py \\
        --input results/swerebench/hints_communication_all_nonempty.jsonl
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    ROW_SPECS,
    available_rows,
    subtree_rows,
)

import json


def _sep(width: int) -> str:
    return "-" * width


def main() -> None:
    parser = argparse.ArgumentParser(description="Taxonomy-subtree statistics over hint records.")
    parser.add_argument("--input", "-i", type=Path, required=True,
                        help="Input JSONL (e.g. hints_communication_all_nonempty.jsonl).")
    args = parser.parse_args()

    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    n_instances = len(records)
    if n_instances == 0:
        print("No records found.")
        return

    all_identifiers = [ident for r in records for ident in r.get("identifiers", [])]
    n_identifiers   = len(all_identifiers)
    counts_per      = [len(r.get("identifiers", [])) for r in records]

    # Compute available rows per instance once
    instance_rows = [available_rows(r) for r in records]

    # ── summary header ────────────────────────────────────────────────────────
    print(f"{'='*60}")
    print(f"  File              : {args.input}")
    print(f"  Instances         : {n_instances}")
    print(f"  Total identifiers : {n_identifiers}")
    print(f"  Per instance  min:{min(counts_per)}  "
          f"mean:{sum(counts_per)/n_instances:.1f}  "
          f"max:{max(counts_per)}")
    print(f"{'='*60}")

    # ── entity_type distribution ──────────────────────────────────────────────
    entity_counter: Counter = Counter(
        i.get("entity_type", "unknown") for i in all_identifiers
    )
    print("\nEntity type distribution:")
    print(f"  {'Type':<14}  {'Count':>6}  {'%':>6}")
    print(f"  {_sep(14)}  {_sep(6)}  {_sep(6)}")
    for etype, cnt in entity_counter.most_common():
        print(f"  {etype:<14}  {cnt:>6}  {100*cnt/n_identifiers:>5.1f}%")

    # ── subtree coverage ──────────────────────────────────────────────────────
    # For each of the 6 LOO roots, show: how many instances have the root
    # available, then each row in the subtree.

    # Subtree display labels
    subtree_labels = {
        "File":    "File",
        "Class":   "Class",
        "ClsFunc": "Class Function (ClsFunc)",
        "ClsVar":  "Class Variable (ClsVar)",
        "Func":    "Function (top-level)",
        "Var":     "Variable (top-level)",
    }

    # Stable row order within each subtree: use ROW_SPECS insertion order
    all_row_names = list(ROW_SPECS.keys())

    print(f"\nSubtree coverage ({n_instances} instances):")

    for root in LOO_SUBGRAPH_ROOTS:
        rows_in_subtree = subtree_rows(root)

        # Instances where the root itself is available
        n_root = sum(1 for ar in instance_rows if root in ar)

        print(f"\n  ┌─ {subtree_labels[root]}  —  {n_root}/{n_instances} instances "
              f"({100*n_root/n_instances:.1f}%)")

        # Each row in the subtree, ordered by taxonomy definition order
        ordered = [r for r in all_row_names if r in rows_in_subtree]
        for row_name in ordered:
            n_row = sum(1 for ar in instance_rows if row_name in ar)
            bar_filled = int(30 * n_row / n_instances)
            bar = "█" * bar_filled + "░" * (30 - bar_filled)
            spec = ROW_SPECS[row_name]
            fields_str = ", ".join(spec.fields) if spec.fields else "(structural)"
            print(f"  │  {row_name:<18}  {n_row:>4}/{n_instances}  "
                  f"({100*n_row/n_instances:>5.1f}%)  [{bar}]  {fields_str}")

    # ── per-instance table ────────────────────────────────────────────────────
    print(f"\n\nPer-instance table ({n_instances} instances):")
    col_iid = 55
    root_headers = "  ".join(f"{r:<7}" for r in LOO_SUBGRAPH_ROOTS)
    print(f"  {'instance_id':<{col_iid}}  {'#id':>3}  {root_headers}")
    print(f"  {_sep(col_iid)}  {_sep(3)}  " +
          "  ".join(_sep(7) for _ in LOO_SUBGRAPH_ROOTS))

    for r, ar in zip(records, instance_rows):
        iid    = r.get("instance_id", "")
        n_id   = len(r.get("identifiers", []))
        iid_d  = (iid[:col_iid-3] + "...") if len(iid) > col_iid else iid
        root_cols = "  ".join(
            f"{'✓':<7}" if root in ar else f"{'':7}"
            for root in LOO_SUBGRAPH_ROOTS
        )
        print(f"  {iid_d:<{col_iid}}  {n_id:>3}  {root_cols}")

    print()


if __name__ == "__main__":
    main()

# Made with Bob
