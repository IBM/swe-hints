#!/usr/bin/env python3
"""
analyze_loo_merged.py
=====================
Present LOO v3 results for SWE-bench Pro and SWErebench side-by-side.

Reads loo_importance.json and value_table.json from 3 runs per dataset,
then prints:
  1. Baseline resolve rates (NONE / FULL) per dataset
  2. LOO root importance — mean ± std across 3 runs, per dataset, side-by-side
  3. Per-instance outcome table for each dataset

Usage:
    python3 helper_code/analyze_loo_merged.py

    # Custom run names:
    python3 helper_code/analyze_loo_merged.py \\
        --swe-pro-runs  loo_helped_v3_r1 loo_helped_v3_r2 loo_helped_v3_r3 \\
        --swerebench-runs loo_swerebench_v3_r1 loo_swerebench_v3_r2 loo_swerebench_v3_r3
"""

import argparse
import json
import statistics
from pathlib import Path

RUNS_DIR   = Path("leave_one_out/runs")
ALL_ROOTS  = ["File", "Class", "ClsFunc", "ClsVar", "Func", "Var"]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_importance(run_id: str) -> dict:
    p = RUNS_DIR / run_id / "loo_importance.json"
    if not p.exists():
        raise FileNotFoundError(f"loo_importance.json missing for {run_id}. "
                                "Run collect_loo_outcomes_v3.py first.")
    return json.loads(p.read_text())

def load_value_table(run_id: str) -> dict:
    p = RUNS_DIR / run_id / "value_table.json"
    if not p.exists():
        raise FileNotFoundError(f"value_table.json missing for {run_id}.")
    return json.loads(p.read_text())

def mean_std(values: list[float]) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)

def fmt(mean: float, std: float) -> str:
    return f"{mean*100:5.1f}% ± {std*100:4.1f}%"

def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

# ─────────────────────────────────────────────────────────────────────────────
# Per-instance outcomes
# ─────────────────────────────────────────────────────────────────────────────

def instance_outcomes(runs: list[str], ctype: str = "full") -> dict[str, list[int]]:
    """
    Returns {instance_id: [resolved_count_r1, resolved_count_r2, resolved_count_r3]}
    resolved_count = number of repetitions (within one run) where instance resolved.
    """
    all_iids: set[str] = set()
    run_data = []
    for run_id in runs:
        vt = load_value_table(run_id)
        run_data.append(vt)
        all_iids.update(vt["instances"])

    result: dict[str, list[int]] = {}
    for iid in sorted(all_iids):
        counts = []
        for vt in run_data:
            resolved = 0
            total = 0
            for cid, cdata in vt["coalitions"].items():
                if cdata["coalition_type"] != ctype:
                    continue
                if iid not in cdata["outcomes"]:
                    continue
                for rep, outcome in cdata["outcomes"][iid].items():
                    total += 1
                    if outcome:
                        resolved += 1
            counts.append(resolved)
        result[iid] = counts
    return result

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Merged LOO v3 analysis: SWE-bench Pro + SWErebench + FEA-bench side-by-side.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--swe-pro-runs", nargs=3,
                        default=["loo_helped_v3_r1", "loo_helped_v3_r2", "loo_helped_v3_r3"],
                        metavar="RUN")
    parser.add_argument("--swerebench-runs", nargs=3,
                        default=["loo_swerebench_v3_r1", "loo_swerebench_v3_r2", "loo_swerebench_v3_r3"],
                        metavar="RUN")
    parser.add_argument("--feabench-runs", nargs=3,
                        default=["loo_feabench_v3_r1", "loo_feabench_v3_r2", "loo_feabench_v3_r3"],
                        metavar="RUN")
    parser.add_argument("--skip-missing", action="store_true",
                        help="Skip datasets whose run files do not exist yet.")
    args = parser.parse_args()

    candidates = [
        ("SWE-bench Pro", args.swe_pro_runs),
        ("SWErebench", args.swerebench_runs),
        ("FEA-bench", args.feabench_runs),
    ]

    datasets = []
    for name, runs in candidates:
        try:
            imps = [load_importance(r) for r in runs]
            datasets.append((name, runs, imps))
        except FileNotFoundError as err:
            if args.skip_missing:
                continue
            raise err

    if not datasets:
        print("No datasets loaded.")
        return

    # ── 1. Baselines ──────────────────────────────────────────────────────────
    section("1. BASELINE RESOLVE RATES")

    header_names = "".join(f"{name:>22}   " for name, _, _ in datasets)
    header_n = "".join(f"{'(n=' + str(imps[0]['baselines']['n_none']) + ')':>22}   " for name, _, imps in datasets)

    print(f"\n{'':30} {header_names}")
    print(f"{'':30} {header_n}")
    print("-" * (32 + 25 * len(datasets)))

    none_str = "  " + f"{'No hints  (NONE)':28}"
    full_str = "  " + f"{'All hints (FULL)':28}"
    lift_str = "  " + f"{'Hints lift':28}"

    for name, runs, imps in datasets:
        none_vals = [d["baselines"]["v_none"] for d in imps]
        full_vals = [d["baselines"]["v_full"] for d in imps]
        none_m, none_s = mean_std(none_vals)
        full_m, full_s = mean_std(full_vals)
        lift = full_m - none_m

        none_str += f"{fmt(none_m, none_s):>22}   "
        full_str += f"{fmt(full_m, full_s):>22}   "
        lift_str += f"{lift*100:>+18.1f} pp   "

    print(none_str)
    print(full_str)
    print(lift_str)

    # Per-run detail
    print(f"\n  Per-run detail:")
    for ds_name, runs, imps in datasets:
        print(f"    [{ds_name}]")
        for i, r in enumerate(runs):
            pn = imps[i]["baselines"]["v_none"]
            pf = imps[i]["baselines"]["v_full"]
            print(f"      r{i+1} ({r}): none={pn*100:.1f}%  full={pf*100:.1f}%")

    # ── 2. LOO Root Importance ────────────────────────────────────────────────
    section("2. LOO ROOT IMPORTANCE  (v_FULL - v_LOO-root, mean ± std across 3 runs)")

    print(f"\n  {'Root':10} {header_names}")
    print("-" * (12 + 25 * len(datasets)))

    ds_root_vals: dict[str, dict[str, list[float]]] = {
        ds_name: {r: [] for r in ALL_ROOTS} for ds_name, _, _ in datasets
    }

    for ds_name, _, imps in datasets:
        for d in imps:
            for root in ALL_ROOTS:
                ds_root_vals[ds_name][root].append(d["root_importance"].get(root, 0.0))

    def combined_mean(root):
        all_vals = []
        for ds_name, _, _ in datasets:
            all_vals.extend(ds_root_vals[ds_name][root])
        return statistics.mean(all_vals)

    for root in sorted(ALL_ROOTS, key=combined_mean, reverse=True):
        row_str = f"  {root:10} "
        for ds_name, _, _ in datasets:
            m, s = mean_std(ds_root_vals[ds_name][root])
            row_str += f"{fmt(m, s):>22}   "
        print(row_str)

    # ── 3. Combined (pooled) importance ───────────────────────────────────────
    section("3. COMBINED IMPORTANCE  (pooled across all loaded datasets and runs)")

    total_instances = sum(imps[0]["baselines"]["n_none"] for _, _, imps in datasets)
    pooled_root: dict[str, list[float]] = {r: [] for r in ALL_ROOTS}
    combined_active: dict[str, int] = {r: 0 for r in ALL_ROOTS}

    def count_active_instances(run_id: str) -> dict[str, int]:
        audit = RUNS_DIR / run_id / "instance_audit.jsonl"
        counts: dict[str, int] = {r: 0 for r in ALL_ROOTS}
        if audit.exists():
            for line in audit.read_text().splitlines():
                rec = json.loads(line)
                for root in rec.get("active_roots", []):
                    counts[root] += 1
        return counts

    for ds_name, runs, imps in datasets:
        active = count_active_instances(runs[0])
        for r in ALL_ROOTS:
            combined_active[r] += active[r]
            pooled_root[r].extend(ds_root_vals[ds_name][r])

    print(f"\n  {'Root':10} {'Pooled (mean ± std)':>28}   {'n_instances':>12}   {'Rank':>4}")
    print("-" * 68)
    for rank, root in enumerate(
        sorted(ALL_ROOTS, key=lambda r: statistics.mean(pooled_root[r]), reverse=True), 1
    ):
        m, s = mean_std(pooled_root[root])
        n_inst = combined_active[root]
        bar = "█" * max(0, round(m * 20))
        print(f"  {root:10} {fmt(m, s):>28}   {n_inst:>12}   #{rank}  {bar}")

    # ── 4. Per-instance outcomes ──────────────────────────────────────────────
    section("4. PER-INSTANCE OUTCOMES UNDER FULL HINTS  (resolved count per run)")

    for ds_name, runs, _ in datasets:
        print(f"\n  [{ds_name}]  (r1 / r2 / r3 = resolved count out of 1 rep each)")
        print(f"  {'instance_id':<55} {'r1':>4} {'r2':>4} {'r3':>4}")
        print("  " + "-" * 70)
        outcomes = instance_outcomes(runs, ctype="full")
        for iid, counts in sorted(outcomes.items()):
            marker = " ✓" if all(c > 0 for c in counts) else ("  " if all(c == 0 for c in counts) else " ~")
            print(f"  {iid:<55} {counts[0]:>4} {counts[1]:>4} {counts[2]:>4}{marker}")

    print()

    print()


if __name__ == "__main__":
    main()
