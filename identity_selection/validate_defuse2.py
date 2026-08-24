#!/usr/bin/env python3
"""
Validate that defuse2.py output matches src/ pipeline hints_communication_all.jsonl.

The src/ pipeline (identifier_information.py) stores per-instance:
    identifiers: [{"name": ..., ...}, ...]   (already filtered by communication operator)

defuse2.py output stores:
    augmentations.forward.data  [{"type": ..., "name": ...}, ...]
    augmentations.backward.data [{"type": ..., "name": ...}, ...]

This script compares the name sets for every instance that appears in both
files, and reports:
  - exact matches
  - instances where src has names defuse2 doesn't (src_only)
  - instances where defuse2 has names src doesn't (defuse2_only)
  - instances missing from one side

Usage:
    python identity_selection/validate_defuse2.py \\
        --src     results/doc2featv2/hints_communication_all.jsonl \\
        --defuse2 identity_selection/data_selection/ncbench_defuse2.jsonl

    # Show full diff for a specific instance:
    python identity_selection/validate_defuse2.py \\
        --src     results/doc2featv2/hints_communication_all.jsonl \\
        --defuse2 identity_selection/data_selection/ncbench_defuse2.jsonl \\
        --instance-id <instance_id>

    # Show all mismatching instances (not just summary):
    python identity_selection/validate_defuse2.py \\
        --src     results/doc2featv2/hints_communication_all.jsonl \\
        --defuse2 identity_selection/data_selection/ncbench_defuse2.jsonl \\
        --verbose
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


def load_jsonl(path: Path) -> dict[str, dict]:
    index = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                index[row["instance_id"]] = row
    return index


def src_names(row: dict) -> set[str]:
    """Names from hints_communication_all.jsonl (already operator-filtered)."""
    return {entry["name"] for entry in row.get("identifiers", []) if entry.get("name")}


def defuse2_names(row: dict) -> set[str]:
    """Forward ∪ backward names from defuse2 augmentations."""
    aug = row.get("augmentations", {})
    names = set()
    for section in ("forward", "backward"):
        data = aug.get(section, {}).get("data", [])
        for entry in data:
            if isinstance(entry, dict) and entry.get("name"):
                names.add(entry["name"])
    return names


def main():
    ap = argparse.ArgumentParser(
        description="Validate defuse2.py output against src/ extracted_hints."
    )
    ap.add_argument("--src",     "-s", type=Path, required=True,
                    help="hints_communication_all.jsonl from src/identifier_information.py")
    ap.add_argument("--defuse2", "-d", type=Path, required=True,
                    help="Output JSONL from identity_selection/defuse2.py")
    ap.add_argument("--instance-id", type=str, default=None,
                    help="Inspect a single instance_id in detail.")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print diff for every mismatching instance.")
    args = ap.parse_args()

    src_index     = load_jsonl(args.src)
    defuse2_index = load_jsonl(args.defuse2)

    all_ids  = sorted(set(src_index) | set(defuse2_index))
    src_only_ids     = sorted(set(src_index)     - set(defuse2_index))
    defuse2_only_ids = sorted(set(defuse2_index) - set(src_index))
    common_ids       = sorted(set(src_index)     & set(defuse2_index))

    # ── Single-instance debug mode ──────────────────────────────────────────
    if args.instance_id:
        iid = args.instance_id
        s_row = src_index.get(iid)
        d_row = defuse2_index.get(iid)

        if s_row is None:
            print(f"[MISSING] {iid} not in src file")
        else:
            sn = src_names(s_row)
            print(f"src   communication names ({len(sn)}): {sorted(sn)}")

        if d_row is None:
            print(f"[MISSING] {iid} not in defuse2 file")
        else:
            dn = defuse2_names(d_row)
            aug = d_row.get("augmentations", {})
            fwd = [e["name"] for e in aug.get("forward",  {}).get("data", []) if isinstance(e, dict)]
            bwd = [e["name"] for e in aug.get("backward", {}).get("data", []) if isinstance(e, dict)]
            print(f"defuse2 names ({len(dn)}): {sorted(dn)}")
            print(f"  forward  : {sorted(fwd)}")
            print(f"  backward : {sorted(bwd)}")

        if s_row and d_row:
            sn = src_names(s_row)
            dn = defuse2_names(d_row)
            only_src     = sn - dn
            only_defuse2 = dn - sn
            print(f"\nsrc_only     ({len(only_src)}):     {sorted(only_src)}")
            print(f"defuse2_only ({len(only_defuse2)}): {sorted(only_defuse2)}")
            print(f"match: {'✓ EXACT' if sn == dn else '✗ DIFFER'}")
        return

    # ── Full comparison ─────────────────────────────────────────────────────
    n_exact   = 0
    n_differ  = 0
    total_src_only     = 0
    total_defuse2_only = 0

    for iid in common_ids:
        sn = src_names(src_index[iid])
        dn = defuse2_names(defuse2_index[iid])

        if sn == dn:
            n_exact += 1
        else:
            n_differ += 1
            only_src     = sn - dn
            only_defuse2 = dn - sn
            total_src_only     += len(only_src)
            total_defuse2_only += len(only_defuse2)

            if args.verbose:
                print(f"[DIFFER] {iid}")
                if only_src:
                    print(f"  src_only     ({len(only_src)}): {sorted(only_src)}")
                if only_defuse2:
                    print(f"  defuse2_only ({len(only_defuse2)}): {sorted(only_defuse2)}")

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Total instances in src:     {len(src_index)}")
    print(f"Total instances in defuse2: {len(defuse2_index)}")
    print(f"  Only in src:     {len(src_only_ids)}")
    print(f"  Only in defuse2: {len(defuse2_only_ids)}")
    print(f"  Common:          {len(common_ids)}")
    print()
    print(f"Of {len(common_ids)} common instances:")
    print(f"  Exact match:  {n_exact} ({100*n_exact/max(len(common_ids),1):.1f}%)")
    print(f"  Differ:       {n_differ} ({100*n_differ/max(len(common_ids),1):.1f}%)")
    if n_differ:
        print(f"    Total names only in src:     {total_src_only}")
        print(f"    Total names only in defuse2: {total_defuse2_only}")
    print(f"{'='*60}")

    if src_only_ids:
        print(f"\nInstances only in src ({len(src_only_ids)}):")
        for iid in src_only_ids[:10]:
            print(f"  {iid}")
        if len(src_only_ids) > 10:
            print(f"  ... and {len(src_only_ids)-10} more")

    if defuse2_only_ids:
        print(f"\nInstances only in defuse2 ({len(defuse2_only_ids)}):")
        for iid in defuse2_only_ids[:10]:
            print(f"  {iid}")
        if len(defuse2_only_ids) > 10:
            print(f"  ... and {len(defuse2_only_ids)-10} more")


if __name__ == "__main__":
    main()
