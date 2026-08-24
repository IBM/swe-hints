"""
analyze_loo_v3_runs.py
======================
Cross-run analysis for three independent LOO v3 experiments.

Reads the loo_importance.json and value_table.json produced by
collect_loo_outcomes_v3.py for each run and reports:

  1. Per-run resolve rates  — v(NONE) and v(FULL) for each run.
  2. LOO root importance    — per-run scores, mean, and std-dev across runs.
  3. Per-instance variance  — resolve outcome (0/1) under a chosen coalition
                              type for each instance across the three runs.

--coalition controls which coalition type is shown in section 3:
  full          FULL coalition (all hints)                [default]
  none          NONE coalition (no hints)
  loo_File      LOO-File coalition (File subtree removed)
  loo_Class     LOO-Class coalition
  loo_ClsFunc   LOO-ClsFunc coalition
  loo_ClsVar    LOO-ClsVar coalition
  loo_Func      LOO-Func coalition
  loo_Var       LOO-Var coalition

Usage
-----
    # Default: FULL coalition, runs r1/r2/r3
    python helper_code/analyze_loo_v3_runs.py

    # Show per-instance results under LOO-Func:
    python helper_code/analyze_loo_v3_runs.py --coalition loo_Func

    # Show per-instance results under NONE (no hints baseline):
    python helper_code/analyze_loo_v3_runs.py --coalition none

    # Custom run names:
    python helper_code/analyze_loo_v3_runs.py \
        --runs loo_helped_v3_r1 loo_helped_v3_r2 loo_helped_v3_r3 \
        --coalition loo_Class

    # Custom runs directory:
    python helper_code/analyze_loo_v3_runs.py \
        --runs-dir leave_one_out/runs \
        --runs loo_helped_v3_r1 loo_helped_v3_r2 loo_helped_v3_r3
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

LOO_SUBGRAPH_ROOTS = ["File", "Class", "ClsFunc", "ClsVar", "Func", "Var"]

VALID_COALITIONS = (
    ["full", "none"] + [f"loo_{r}" for r in LOO_SUBGRAPH_ROOTS]
)

DEFAULT_RUNS      = ["loo_helped_v3_r1", "loo_helped_v3_r2", "loo_helped_v3_r3"]
DEFAULT_RUNS_DIR  = Path("leave_one_out/runs")
DEFAULT_COALITION = "full"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _get_cid_for_instance(
    audit_rec: dict,
    coalition_type: str,
) -> str | None:
    """Return the coalition ID for the requested type, or None if not active."""
    if coalition_type == "full":
        return audit_rec["full_cid"]
    if coalition_type == "none":
        return audit_rec["none_cid"]
    # loo_<root>
    root = coalition_type[len("loo_"):]   # e.g. "File"
    return audit_rec["loo_cids"].get(root)


def analyze(runs: list[str], runs_dir: Path, coalition_type: str) -> None:
    # ── Validate paths ────────────────────────────────────────────────────────
    for run in runs:
        for fname in ("loo_importance.json", "value_table.json", "instance_audit.jsonl"):
            p = runs_dir / run / fname
            if not p.exists():
                print(f"ERROR: {p} not found. Run collect_loo_outcomes_v3.py first.")
                raise SystemExit(1)

    importances = [load_json(runs_dir / run / "loo_importance.json") for run in runs]
    tables      = [load_json(runs_dir / run / "value_table.json")    for run in runs]
    audits      = [load_jsonl(runs_dir / run / "instance_audit.jsonl") for run in runs]

    # ── 1. Per-run baseline scores ────────────────────────────────────────────
    print("=== Per-run resolve rates ===")
    header = f"  {'Run':<22}  {'v(NONE)':>8}  {'v(FULL)':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for run, imp in zip(runs, importances):
        b = imp["baselines"]
        print(f"  {run:<22}  {b['v_none']:>8.3f}  {b['v_full']:>8.3f}")

    none_scores = [imp["baselines"]["v_none"] for imp in importances]
    full_scores = [imp["baselines"]["v_full"] for imp in importances]
    print(f"  {'mean':<22}  {statistics.mean(none_scores):>8.3f}  {statistics.mean(full_scores):>8.3f}")
    if len(runs) > 1:
        print(f"  {'std':<22}  {statistics.stdev(none_scores):>8.3f}  {statistics.stdev(full_scores):>8.3f}")

    # ── 2. LOO root importance ────────────────────────────────────────────────
    print()
    print("=== LOO root importance per run ===")
    run_cols = "".join(f"  {r:<13}" for r in runs)
    print(f"  {'Root':<10}{run_cols}  {'Mean':>8}  {'StdDev':>8}")
    print("  " + "-" * (10 + 15 * len(runs) + 18))
    for root in LOO_SUBGRAPH_ROOTS:
        scores = [imp["root_importance"].get(root) for imp in importances]
        valid  = [s for s in scores if s is not None]
        mean   = statistics.mean(valid)   if valid          else float("nan")
        std    = statistics.stdev(valid)  if len(valid) > 1 else 0.0
        vals   = "".join(
            f"  {s:>+13.4f}" if s is not None else f"  {'n/a':>13}"
            for s in scores
        )
        print(f"  {root:<10}{vals}  {mean:>+8.4f}  {std:>8.4f}")

    # ── 3. Per-instance variance ──────────────────────────────────────────────
    print()
    print(f"=== Per-instance resolve rate across runs ({coalition_type} coalition) ===")
    run_hdrs = "".join(f"  {r[-2:]:>4}" for r in runs)   # r1, r2, r3
    print(f"  {'Instance':<55}{run_hdrs}  {'Var':>6}  {'Active?':>7}")
    print("  " + "-" * (55 + 6 * len(runs) + 16))

    # Use audit[0] as the canonical instance order
    all_vars: list[float] = []
    n_inactive = 0

    for i, rec in enumerate(audits[0]):
        iid  = rec["instance_id"]
        vals = []
        active = True   # False if this root is not active for this instance

        for table, audit in zip(tables, audits):
            cid = _get_cid_for_instance(audit[i], coalition_type)
            if cid is None:
                # Root not active for this instance — skip
                active = False
                break
            outcome = table["coalitions"][cid]["outcomes"].get(iid, {})
            val     = outcome.get("0")
            vals.append(1 if val is True else 0)

        if not active:
            n_inactive += 1
            val_str = "".join(f"  {'—':>4}" for _ in runs)
            print(f"  {iid[-55:]:<55}{val_str}  {'—':>6}  {'no':>7}")
            continue

        var = statistics.variance(vals) if len(vals) > 1 else 0.0
        all_vars.append(var)
        val_str = "".join(f"  {v:>4}" for v in vals)
        print(f"  {iid[-55:]:<55}{val_str}  {var:>6.3f}  {'yes':>7}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    n_active   = len(all_vars)
    n_stable   = sum(1 for v in all_vars if v == 0.0)
    n_unstable = n_active - n_stable
    print(f"Coalition: {coalition_type}")
    print(f"  Active instances  : {n_active}  (root present for this instance)")
    if n_inactive:
        print(f"  Inactive instances: {n_inactive}  (root not active — shown as —)")
    print(f"  Stable   (var=0)  : {n_stable}  (same outcome in all {len(runs)} runs)")
    print(f"  Unstable (var>0)  : {n_unstable}  (outcome differs across runs)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-run analysis for three independent LOO v3 experiments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--runs", nargs="+",
        default=DEFAULT_RUNS,
        help=f"Run directory names (default: {' '.join(DEFAULT_RUNS)})",
    )
    parser.add_argument(
        "--runs-dir", type=Path,
        default=DEFAULT_RUNS_DIR,
        help=f"Root directory containing run folders (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--coalition", "-c",
        default=DEFAULT_COALITION,
        choices=VALID_COALITIONS,
        metavar="COALITION",
        help=(
            "Coalition type to use for the per-instance section. "
            f"Choices: {', '.join(VALID_COALITIONS)}. "
            f"Default: {DEFAULT_COALITION}"
        ),
    )
    args = parser.parse_args()
    analyze(args.runs, args.runs_dir, args.coalition)


if __name__ == "__main__":
    main()

# Made with Bob
