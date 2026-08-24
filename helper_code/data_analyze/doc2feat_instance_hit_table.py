#!/usr/bin/env python3
"""
doc2feat_instance_hit_table.py
===============================
Per-instance statistics across 3 no-hint and 3 full-hint runs on
Doc2Feat-bench_Verified, mirroring swerebench_instance_hit_table.py.

For each instance shows:
  - no_hint_wrong/3    : how many of the 3 no-hint runs did NOT resolve it
  - full_hint_correct/3: how many of the 3 full-hint runs DID resolve it
  - fv_no  / fv_full   : mean FV score across 3 runs (passed F2P / total F2P)
  - fv_no_std / fv_full_std : std of FV across 3 runs
  - fl_no  / fl_full   : mean FL score across 3 runs (1 if files localised correctly)
  - fl_no_std / fl_full_std : std of FL across 3 runs

Usage:
    python helper_code/doc2feat_instance_hit_table.py
"""

import json
import math
from pathlib import Path
from unidiff import PatchSet

EVAL_DIR   = Path("results/doc2feat/eval")
TASKS_FILE = Path("data/doc2feat_bench_tasks.jsonl")
REPS       = [1, 2, 3]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_resolved(cond: str, rep: int) -> set[str]:
    p = EVAL_DIR / f"{cond}_r{rep}" / "report.json"
    if not p.exists():
        print(f"  WARNING: {p} not found — treating as empty")
        return set()
    return set(json.loads(p.read_text())["resolved_ids"])


def load_details(cond: str, rep: int) -> dict[str, dict]:
    p = EVAL_DIR / f"{cond}_r{rep}" / "evaluation_details.jsonl"
    if not p.exists():
        return {}
    index = {}
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                index[r["instance_id"]] = r
    return index


def load_gt_files(tasks_file: Path) -> dict[str, set[str]]:
    """Map instance_id -> set of .py files touched in the ground-truth feature_patch."""
    gt = {}
    with open(tasks_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            try:
                gt[r["instance_id"]] = {
                    fi.path for fi in PatchSet(r["feature_patch"])
                    if fi.path.endswith(".py")
                }
            except Exception:
                gt[r["instance_id"]] = set()
    return gt


def applied(detail: dict) -> int:
    """1 if the model patch was successfully applied, else 0."""
    return int(detail.get("applied", False))


def fv_score(detail: dict) -> float:
    """Per-instance FV = passed F2P tests / total F2P tests (0.0 if none)."""
    f2p = detail.get("F2P", {})
    ok  = len(f2p.get("success", []))
    fail = len(f2p.get("failure", [])) + len(f2p.get("fail", []))
    total = ok + fail
    return ok / total if total > 0 else 0.0


def fl_match(detail: dict, gt_files: set[str]) -> bool:
    """True if the model patch covers all ground-truth .py files."""
    mp = detail.get("model_patch", "")
    if not mp:
        return False
    try:
        pred_files = {fi.path for fi in PatchSet(mp)}
    except Exception:
        return False
    return gt_files.issubset(pred_files)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    gt_files = load_gt_files(TASKS_FILE)

    no_resolved  = [load_resolved("no_hint",   r) for r in REPS]
    full_resolved = [load_resolved("full_hint", r) for r in REPS]
    no_details   = [load_details("no_hint",   r) for r in REPS]
    full_details  = [load_details("full_hint", r) for r in REPS]

    all_ids = sorted(
        gt_files.keys() |
        {iid for s in no_resolved   for iid in s} |
        {iid for s in full_resolved for iid in s}
    )

    rows = []
    for iid in all_ids:
        no_wrong   = sum(1 for r in no_resolved   if iid not in r)
        full_cor   = sum(1 for r in full_resolved if iid in r)

        def _mean(xs): return sum(xs) / len(xs) if xs else 0.0
        def _std(xs):
            if len(xs) < 2: return 0.0
            m = _mean(xs)
            return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

        # Applied: mean +/- std across runs
        no_app_scores   = [applied(d[iid]) for d in no_details   if iid in d]
        full_app_scores = [applied(d[iid]) for d in full_details if iid in d]
        no_app,   no_app_std   = _mean(no_app_scores),   _std(no_app_scores)
        full_app, full_app_std = _mean(full_app_scores), _std(full_app_scores)

        # FV: mean +/- std across runs
        no_fv_scores   = [fv_score(d[iid]) for d in no_details   if iid in d]
        full_fv_scores = [fv_score(d[iid]) for d in full_details if iid in d]
        no_fv,   no_fv_std   = _mean(no_fv_scores),   _std(no_fv_scores)
        full_fv, full_fv_std = _mean(full_fv_scores), _std(full_fv_scores)

        # FL: mean +/- std across runs
        gt = gt_files.get(iid, set())
        no_fl_scores   = [int(fl_match(d[iid], gt)) for d in no_details   if iid in d]
        full_fl_scores = [int(fl_match(d[iid], gt)) for d in full_details if iid in d]
        no_fl,   no_fl_std   = _mean(no_fl_scores),   _std(no_fl_scores)
        full_fl, full_fl_std = _mean(full_fl_scores), _std(full_fl_scores)

        rows.append((iid, no_wrong, full_cor,
                     no_app, no_app_std, full_app, full_app_std,
                     no_fv, no_fv_std, full_fv, full_fv_std,
                     no_fl, no_fl_std, full_fl, full_fl_std))

    # Sort: most interesting first (no_hints always wrong, full_hints always correct)
    rows.sort(key=lambda x: (-x[1], -x[2], x[0]))

    # Print table
    hdr = (f"{'instance_id':<45} {'no_w/3':>6} {'full_c/3':>8} "
           f"{'app_no':>6} {'+-':>6} {'app_full':>8} {'+-':>6} "
           f"{'fv_no':>7} {'+-':>6} {'fv_full':>7} {'+-':>6} "
           f"{'fl_no':>6} {'+-':>6} {'fl_full':>6} {'+-':>6}")
    print(hdr)
    print("-" * len(hdr))
    for (iid, nw, fc,
         nap, nap_s, fap, fap_s,
         nfv, nfv_s, ffv, ffv_s,
         nfl, nfl_s, ffl, ffl_s) in rows:
        print(f"{iid:<45} {nw:>6} {fc:>8} "
              f"{nap:>6.3f} {nap_s:>6.3f} {fap:>8.3f} {fap_s:>6.3f} "
              f"{nfv:>7.3f} {nfv_s:>6.3f} {ffv:>7.3f} {ffv_s:>6.3f} "
              f"{nfl:>6.3f} {nfl_s:>6.3f} {ffl:>6.3f} {ffl_s:>6.3f}")

    print()
    n = len(rows)

    def _global_mean(idx): return sum(r[idx] for r in rows) / n
    def _global_std(idx):
        m = _global_mean(idx)
        return math.sqrt(sum((r[idx] - m) ** 2 for r in rows) / n)

    print(f"Total instances                          : {n}")
    print(f"Always wrong  no-hint  (3/3)             : {sum(1 for r in rows if r[1]==3)}")
    print(f"Always correct full-hint (3/3)           : {sum(1 for r in rows if r[2]==3)}")
    print(f"Hints helped (no=3/3 wrong, full=3/3 ok) : {sum(1 for r in rows if r[1]==3 and r[2]==3)}")
    print()
    print(f"Mean Applied no-hint  : {_global_mean(3):.4f} +/- {_global_std(3):.4f}")
    print(f"Mean Applied full-hint: {_global_mean(5):.4f} +/- {_global_std(5):.4f}")
    print(f"Mean FV no-hint       : {_global_mean(7):.4f} +/- {_global_std(7):.4f}")
    print(f"Mean FV full-hint     : {_global_mean(9):.4f} +/- {_global_std(9):.4f}")
    print(f"Mean FL no-hint       : {_global_mean(11):.4f} +/- {_global_std(11):.4f}")
    print(f"Mean FL full-hint     : {_global_mean(13):.4f} +/- {_global_std(13):.4f}")


if __name__ == "__main__":
    main()

# Made with Bob
