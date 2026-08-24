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
        description="Merged LOO v3 analysis: SWE-bench Pro + SWErebench side-by-side.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--swe-pro-runs", nargs=3,
                        default=["loo_helped_v3_r1", "loo_helped_v3_r2", "loo_helped_v3_r3"],
                        metavar="RUN")
    parser.add_argument("--swerebench-runs", nargs=3,
                        default=["loo_swerebench_v3_r1", "loo_swerebench_v3_r2", "loo_swerebench_v3_r3"],
                        metavar="RUN")
    args = parser.parse_args()

    pro_runs = args.swe_pro_runs
    sre_runs = args.swerebench_runs

    pro_imp  = [load_importance(r) for r in pro_runs]
    sre_imp  = [load_importance(r) for r in sre_runs]

    # ── 1. Baselines ──────────────────────────────────────────────────────────
    section("1. BASELINE RESOLVE RATES")

    pro_none_vals = [d["baselines"]["v_none"] for d in pro_imp]
    pro_full_vals = [d["baselines"]["v_full"] for d in pro_imp]
    sre_none_vals = [d["baselines"]["v_none"] for d in sre_imp]
    sre_full_vals = [d["baselines"]["v_full"] for d in sre_imp]

    n_pro = pro_imp[0]["baselines"]["n_none"]
    n_sre = sre_imp[0]["baselines"]["n_none"]

    print(f"\n{'':30} {'SWE-bench Pro':>22}   {'SWErebench':>22}")
    print(f"{'':30} {'(n=' + str(n_pro) + ')':>22}   {'(n=' + str(n_sre) + ')':>22}")
    print("-" * 80)

    pro_none_m, pro_none_s = mean_std(pro_none_vals)
    sre_none_m, sre_none_s = mean_std(sre_none_vals)
    print(f"  {'No hints  (NONE)':28} {fmt(pro_none_m, pro_none_s):>22}   {fmt(sre_none_m, sre_none_s):>22}")

    pro_full_m, pro_full_s = mean_std(pro_full_vals)
    sre_full_m, sre_full_s = mean_std(sre_full_vals)
    print(f"  {'All hints (FULL)':28} {fmt(pro_full_m, pro_full_s):>22}   {fmt(sre_full_m, sre_full_s):>22}")

    pro_lift = pro_full_m - pro_none_m
    sre_lift = sre_full_m - sre_none_m
    print(f"  {'Hints lift':28} {pro_lift*100:>+18.1f} pp   {sre_lift*100:>+18.1f} pp")

    # Per-run detail
    print(f"\n  Per-run detail:")
    for i, (r_pro, r_sre) in enumerate(zip(pro_runs, sre_runs)):
        pn = pro_imp[i]["baselines"]["v_none"]
        pf = pro_imp[i]["baselines"]["v_full"]
        sn = sre_imp[i]["baselines"]["v_none"]
        sf = sre_imp[i]["baselines"]["v_full"]
        print(f"    r{i+1}  none={pn*100:.1f}%  full={pf*100:.1f}%  "
              f"(pro)     none={sn*100:.1f}%  full={sf*100:.1f}%  (sre)")

    # ── 2. LOO Root Importance ────────────────────────────────────────────────
    section("2. LOO ROOT IMPORTANCE  (v_FULL - v_LOO-root, mean ± std across 3 runs)")

    print(f"\n  {'Root':10} {'SWE-bench Pro':>22}   {'SWErebench':>22}")
    print("-" * 60)

    pro_root_vals: dict[str, list[float]] = {r: [] for r in ALL_ROOTS}
    sre_root_vals: dict[str, list[float]] = {r: [] for r in ALL_ROOTS}

    for d in pro_imp:
        for root in ALL_ROOTS:
            pro_root_vals[root].append(d["root_importance"].get(root, 0.0))
    for d in sre_imp:
        for root in ALL_ROOTS:
            sre_root_vals[root].append(d["root_importance"].get(root, 0.0))

    # Sort by mean importance across both datasets combined
    def combined_mean(root):
        return statistics.mean(pro_root_vals[root] + sre_root_vals[root])

    for root in sorted(ALL_ROOTS, key=combined_mean, reverse=True):
        pm, ps = mean_std(pro_root_vals[root])
        sm, ss = mean_std(sre_root_vals[root])
        print(f"  {root:10} {fmt(pm, ps):>22}   {fmt(sm, ss):>22}")

    # ── 3. Combined (pooled) importance ───────────────────────────────────────
    section("3. COMBINED IMPORTANCE  (pooled across both datasets, all 6 runs)")

    n_pro_total = pro_imp[0]["baselines"]["n_none"]
    n_sre_total = sre_imp[0]["baselines"]["n_none"]
    n_total = n_pro_total + n_sre_total

    def pooled_rate(pro_vals, sre_vals):
        weighted = [v * n_pro_total for v in pro_vals] + [v * n_sre_total for v in sre_vals]
        return statistics.mean(weighted) / n_total

    pooled_none = pooled_rate(pro_none_vals, sre_none_vals)
    pooled_full = pooled_rate(pro_full_vals, sre_full_vals)
    print(f"\n  Pooled baselines  (weighted by n_instances: pro={n_pro_total}, sre={n_sre_total})")
    print(f"    No hints  (NONE) : {pooled_none*100:5.1f}%")
    print(f"    All hints (FULL) : {pooled_full*100:5.1f}%")
    print(f"    Hints lift       : {(pooled_full - pooled_none)*100:+5.1f} pp")

    # Count instances where each root is active (use r1 of each dataset as representative)
    def count_active_instances(run_id: str) -> dict[str, int]:
        audit = RUNS_DIR / run_id / "instance_audit.jsonl"
        counts: dict[str, int] = {r: 0 for r in ALL_ROOTS}
        for line in audit.read_text().splitlines():
            rec = json.loads(line)
            for root in rec["active_roots"]:
                counts[root] += 1
        return counts

    pro_active = count_active_instances(pro_runs[0])
    sre_active = count_active_instances(sre_runs[0])
    combined_active = {r: pro_active[r] + sre_active[r] for r in ALL_ROOTS}

    pooled_root: dict[str, list[float]] = {}
    for root in ALL_ROOTS:
        pooled_root[root] = pro_root_vals[root] + sre_root_vals[root]

    print(f"\n  {'Root':10} {'Pooled (mean ± std, 6 runs)':>28}   {'n_instances':>12}   {'Rank':>4}")
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

    print(f"\n  SWE-bench Pro  (r1 / r2 / r3 = resolved count out of 1 rep each)")
    print(f"  {'instance_id':<55} {'r1':>4} {'r2':>4} {'r3':>4}")
    print("  " + "-" * 70)
    pro_outcomes = instance_outcomes(pro_runs, ctype="full")
    for iid, counts in sorted(pro_outcomes.items()):
        marker = " ✓" if all(c > 0 for c in counts) else ("  " if all(c == 0 for c in counts) else " ~")
        print(f"  {iid:<55} {counts[0]:>4} {counts[1]:>4} {counts[2]:>4}{marker}")

    print(f"\n  SWErebench  (r1 / r2 / r3 = resolved count out of 1 rep each)")
    print(f"  {'instance_id':<55} {'r1':>4} {'r2':>4} {'r3':>4}")
    print("  " + "-" * 70)
    sre_outcomes = instance_outcomes(sre_runs, ctype="full")
    for iid, counts in sorted(sre_outcomes.items()):
        marker = " ✓" if all(c > 0 for c in counts) else ("  " if all(c == 0 for c in counts) else " ~")
        print(f"  {iid:<55} {counts[0]:>4} {counts[1]:>4} {counts[2]:>4}{marker}")

    print()


if __name__ == "__main__":
    main()
