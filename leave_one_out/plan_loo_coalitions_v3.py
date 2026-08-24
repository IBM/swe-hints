"""
plan_loo_coalitions_v3.py
=========================
Build the run-directory artefacts for a Leave-One-Out (LOO) experiment over
subgraph roots — using the v3 taxonomy (taxonomy_game_v3).

v3 LOO design
-------------
The LOO experiment uses 6 subgraph roots instead of individual rows:
    File, Class, ClsFunc, ClsVar, Func, Var

Each LOO coalition = Full minus ALL rows in one root's subtree.

Three coalition types per instance:
  - NONE  : empty coalition (no hints at all)
  - FULL  : all active rows
  - LOO-r : all active rows minus the subtree of root r, for each active root r

An "active root" is one whose subtree contains at least one active row.

This produces exactly  2 + |active_roots|  coalitions per instance
(NONE and FULL are fixed; LOO coalitions depend on how many roots are active).

Coalitions are NOT shared across instances (same logic as v2).

Outputs (written to --output-dir):
  coalition_manifest.json  — coalition_id -> {rows, instance_ids, input_file, coalition_type}
  instance_audit.jsonl     — per-instance row counts and coalition IDs
  config.json              — experiment config snapshot

Usage
-----
    python leave_one_out/plan_loo_coalitions_v3.py \\
        --hints  leave_one_out/output/hints_helped_enriched.jsonl \\
        --output-dir leave_one_out/runs/loo_helped_v3_r1

    # All instances:
    python leave_one_out/plan_loo_coalitions_v3.py \\
        --hints  results/swe_pro/hints_communication_all_nonempty_enriched.jsonl \\
        --output-dir leave_one_out/runs/loo_all_v3_r1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    available_rows,
    coalition_id,
    subtree_rows,
)


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

def plan(hint_records: list[dict], output_dir: Path) -> None:
    """
    For each instance produce:
      - NONE coalition  (empty set, no hints)
      - FULL coalition  (all active rows)
      - LOO-r coalition (FULL minus subtree(r)) for each active root r

    Every coalition is keyed by a compound ID:
        <instance_hash_8>_<coalition_hash_8>
    so there is never cross-instance sharing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # compound_key -> {rows, instance_ids, input_file, coalition_type}
    coalition_registry: dict[str, dict] = {}
    audit_records: list[dict] = []

    def _register(coalition: frozenset[str], iid: str, ctype: str) -> str:
        inst_hash = hashlib.sha256(iid.encode()).hexdigest()[:8]
        cid_part  = coalition_id(coalition)[:8]
        key       = f"{inst_hash}_{cid_part}"
        if key not in coalition_registry:
            coalition_registry[key] = {
                "rows":            sorted(coalition),
                "instance_ids":    [iid],
                "input_file":      f"agent_inputs/instances_{key}.jsonl",
                "coalition_type":  ctype,
            }
        return key

    for idx, instance in enumerate(hint_records):
        iid    = instance["instance_id"]
        active = available_rows(instance)

        # Determine which roots have at least one active row in their subtree
        active_roots = [
            root for root in LOO_SUBGRAPH_ROOTS
            if active & subtree_rows(root)
        ]

        print(f"\nInstance {idx+1}/{len(hint_records)}: ...{iid[-50:]}")
        print(f"  Active rows ({len(active)}): {sorted(active)}")
        print(f"  Active roots ({len(active_roots)}): {active_roots}")

        # NONE coalition (empty — no hints)
        none_key = _register(frozenset(), iid, "none")

        # FULL coalition
        full_key = _register(active, iid, "full")

        # LOO coalitions: full minus subtree of each active root
        loo_keys: dict[str, str] = {}  # root_name -> coalition key
        for root in active_roots:
            loo = active - subtree_rows(root)
            loo_key = _register(loo, iid, f"loo_{root}")
            loo_keys[root] = loo_key

        print(f"  Coalitions: 1 none + 1 full + {len(active_roots)} LOO = {2 + len(active_roots)}")

        audit_records.append({
            "instance_id":  iid,
            "active_rows":  sorted(active),
            "n_active":     len(active),
            "active_roots": active_roots,
            "none_cid":     none_key,
            "full_cid":     full_key,
            "loo_cids":     loo_keys,
        })

    total = len(coalition_registry)
    print(f"\nTotal coalitions (no cross-instance sharing): {total}")

    # ── coalition_manifest.json ──────────────────────────────────────────────
    manifest_path = output_dir / "coalition_manifest.json"
    manifest_path.write_text(json.dumps(coalition_registry, indent=2, ensure_ascii=False))
    print(f"Wrote coalition_manifest.json  ({manifest_path})")

    # ── instance_audit.jsonl ────────────────────────────────────────────────
    audit_path = output_dir / "instance_audit.jsonl"
    with open(audit_path, "w", encoding="utf-8") as f:
        for rec in audit_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote instance_audit.jsonl     ({audit_path})")

    # ── config.json ─────────────────────────────────────────────────────────
    config = {
        "experiment":              "leave_one_out",
        "taxonomy_version":        "v3",
        "loo_mode":                "subgraph_roots",
        "loo_roots":               list(LOO_SUBGRAPH_ROOTS),
        "n_instances":             len(hint_records),
        "total_unique_coalitions": total,
        "repetitions":             [0],
    }
    config_path = output_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"Wrote config.json              ({config_path})")

    # ── summary table ────────────────────────────────────────────────────────
    n_none = sum(1 for v in coalition_registry.values() if v["coalition_type"] == "none")
    n_full = sum(1 for v in coalition_registry.values() if v["coalition_type"] == "full")
    n_loo  = total - n_none - n_full

    print(f"\nSummary:")
    print(f"  NONE coalitions (1 per instance)           : {n_none}")
    print(f"  FULL coalitions (1 per instance)           : {n_full}")
    print(f"  LOO  coalitions (1 active root removed each): {n_loo}")
    print(f"  Total                                      : {total}")
    n_inst = len(hint_records)
    print(f"  = {n_inst} instances × (1 NONE + 1 FULL + avg {n_loo/n_inst:.1f} LOO)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan LOO coalitions (one subgraph root left out at a time) using taxonomy v3.",
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
        "--output-dir", "-o",
        type=Path,
        default=Path("leave_one_out/runs/loo_helped_v3_r1"),
        help="Run directory to write artefacts into. Default: leave_one_out/runs/loo_helped_v3_r1",
    )
    args = parser.parse_args()

    print(f"Loading hints: {args.hints}")
    records: list[dict] = []
    with open(args.hints, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"  {len(records)} instances loaded.")

    plan(records, args.output_dir)


if __name__ == "__main__":
    main()

# Made with Bob
