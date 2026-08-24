"""
collect_loo_outcomes.py
=======================
Consolidate all eval_results.json files from a LOO run into a single
value_table.json, then compute the LOO importance of each taxonomy row:

    importance(r) = v(FULL) - v(FULL \\ {r})

where v(coalition) = fraction of instances resolved under that coalition.

Output files (written to <run_dir>/):
  value_table.json        — raw outcomes per coalition × instance × repetition
  loo_importance.json     — per-row importance scores, sorted descending

Usage
-----
    python leave_one_out/collect_loo_outcomes.py loo_helped_r1

    # With a custom run directory root:
    python leave_one_out/collect_loo_outcomes.py loo_helped_r1 \\
        --runs-dir leave_one_out/runs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HINTS_DIR  = Path(__file__).resolve().parent.parent
RUNS_DIR   = HINTS_DIR / "leave_one_out" / "runs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _coalition_score(
    outcomes: dict[str, dict[str, bool | None]],
    repetitions: list[int],
) -> float:
    """
    Mean resolve-rate across instances and repetitions.
    Missing outcomes (None) are counted as unresolved (False).
    """
    total = resolved = 0
    for iid_outcomes in outcomes.values():
        for rep in repetitions:
            val = iid_outcomes.get(str(rep))
            total += 1
            if val is True:
                resolved += 1
    return resolved / total if total else 0.0


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def collect(run_dir: Path) -> int:
    manifest_path = run_dir / "coalition_manifest.json"
    config_path   = run_dir / "config.json"
    audit_path    = run_dir / "instance_audit.jsonl"

    for p in (manifest_path, config_path):
        if not p.exists():
            print(f"ERROR: {p} not found. Run plan_loo_coalitions.py first.",
                  file=sys.stderr)
            return 1

    manifest:    dict = json.loads(manifest_path.read_text())
    config:      dict = json.loads(config_path.read_text())
    repetitions: list[int] = config["repetitions"]

    all_instances: list[str] = sorted({
        iid
        for meta in manifest.values()
        for iid in meta["instance_ids"]
    })

    print(f"Run        : {run_dir.name}")
    print(f"Coalitions : {len(manifest)}")
    print(f"Instances  : {len(all_instances)}")
    print(f"Repetitions: {repetitions}")

    # ── build value_table ────────────────────────────────────────────────────
    eval_base    = run_dir / "eval_results"
    coalitions_out: dict = {}
    warnings: list[str] = []

    for cid, meta in manifest.items():
        rows         = meta["rows"]
        instance_ids = meta["instance_ids"]

        outcomes: dict[str, dict[str, bool | None]] = {iid: {} for iid in instance_ids}

        for rep in repetitions:
            rep_str   = str(rep)
            eval_path = eval_base / cid / f"repeat_{rep}" / "eval_results.json"
            result_map = _load_json(eval_path)

            for iid in instance_ids:
                if result_map is None:
                    outcomes[iid][rep_str] = None
                    warnings.append(f"MISSING  cid={cid} rep={rep} iid={iid[-30:]}")
                elif iid not in result_map:
                    outcomes[iid][rep_str] = None
                    warnings.append(f"ABSENT   cid={cid} rep={rep} iid={iid[-30:]}")
                else:
                    raw = result_map[iid]
                    outcomes[iid][rep_str] = raw if isinstance(raw, bool) else None

        coalitions_out[cid] = {"rows": rows, "outcomes": outcomes}

    table = {
        "run_id":      run_dir.name,
        "repetitions": repetitions,
        "instances":   all_instances,
        "coalitions":  coalitions_out,
    }

    table_path = run_dir / "value_table.json"
    table_path.write_text(json.dumps(table, indent=2))
    print(f"\nWrote {table_path}")

    if warnings:
        print(f"\n{len(warnings)} warning(s) (first 20):")
        for w in warnings[:20]:
            print(f"  {w}")
        if len(warnings) > 20:
            print(f"  ... ({len(warnings) - 20} more)")

    # ── LOO importance ───────────────────────────────────────────────────────
    # Load per-instance full_cid and loo_cids from instance_audit.jsonl
    if not audit_path.exists():
        print("\nWARNING: instance_audit.jsonl not found — skipping LOO importance.",
              file=sys.stderr)
        return 0

    full_cid_per_instance: dict[str, str] = {}
    loo_cids_per_instance: dict[str, dict[str, str]] = {}  # iid -> {row -> cid}

    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            iid = rec["instance_id"]
            full_cid_per_instance[iid] = rec["full_cid"]
            loo_cids_per_instance[iid] = rec["loo_cids"]

    # Collect all rows that appear across all instances
    all_rows: set[str] = set()
    for loo_map in loo_cids_per_instance.values():
        all_rows.update(loo_map.keys())

    # For each row, compute importance per instance then average
    # importance_i(r) = score(full_i) - score(full_i \ {r})
    row_importances: dict[str, list[float]] = {r: [] for r in all_rows}

    for iid in all_instances:
        full_cid = full_cid_per_instance.get(iid)
        if full_cid is None or full_cid not in coalitions_out:
            continue
        full_score = _coalition_score(
            {iid: coalitions_out[full_cid]["outcomes"].get(iid, {})},
            repetitions,
        )

        for row, loo_cid in loo_cids_per_instance.get(iid, {}).items():
            if loo_cid not in coalitions_out:
                continue
            loo_score = _coalition_score(
                {iid: coalitions_out[loo_cid]["outcomes"].get(iid, {})},
                repetitions,
            )
            row_importances[row].append(full_score - loo_score)

    # Average per row
    importance: dict[str, float] = {
        row: sum(vals) / len(vals)
        for row, vals in row_importances.items()
        if vals
    }

    # Sort descending
    importance_sorted = dict(
        sorted(importance.items(), key=lambda kv: kv[1], reverse=True)
    )

    importance_path = run_dir / "loo_importance.json"
    importance_path.write_text(json.dumps(importance_sorted, indent=2))
    print(f"Wrote {importance_path}")

    # Human-readable full names for every taxonomy row.
    _ROW_FULL_NAME: dict[str, str] = {
        # File level
        "File":            "File",
        "FileLoc":         "File Location",
        "Import":          "Import Statement",
        "NewFile":         "New File",
        "ModifiedFile":    "Modified File",
        # Class level
        "Class":           "Class",
        "ClassName":       "Class Name",
        "SuperC":          "Super Class",
        "Generic":         "Generic",
        "LocParClass":     "Cls Partial Location",
        "LocCompClass":    "Cls Complete Location",
        "WeakSClass":      "Cls Weak Semantics",
        "StrongSClass":    "Cls Strong Semantics",
        "FuncPub":         "Public Functions",
        "FuncPriv":        "Private Functions",
        # Cls Function level
        "ClsFunc":         "Cls Function",
        "ClsFuncName":     "Cls Function Name",
        "ClsSign":         "Cls Function Signature",
        "ClsInS":          "Cls Function Input Spec",
        "ClsInT":          "Cls Function Input Type",
        "ClsInN":          "Cls Function Input Name",
        "ClsOutPT":        "Cls Function Output Partial Type",
        "ClsOutCT":        "Cls Function Output Complete Type",
        "ClsLocParFunc":   "Cls Function Partial Location",
        "ClsLocCompFunc":  "Cls Function Complete Location",
        "ClsWeakSFunc":    "Cls Function Weak Semantics",
        "ClsStrongSFunc":  "Cls Function Strong Semantics",
        "ClsExceptValue":  "Cls Function Exception Value",
        "ClsExceptType":   "Cls Function Exception Type",
        "ClsParamDefault": "Cls Function Parameter Default Value",
        # Cls Variable level
        "ClsVar":          "Cls Variable",
        "ClsVarType":      "Cls Variable Type",
        "ClsVarValue":     "Cls Variable Value",
        "ClsLocParVar":    "Cls Var Partial Location",
        "ClsLocCompVar":   "Cls Var Complete Location",
        "ClsWeakSVar":     "Cls Var Weak Semantics",
        "ClsStrongSVar":   "Cls Var Strong Semantics",
        # Function level
        "Func":            "Function",
        "FuncName":        "Function Name",
        "Sign":            "Signature",
        "InS":             "Input Spec",
        "InT":             "Input Type",
        "InN":             "Input Name",
        "OutPT":           "Output Partial Type",
        "OutCT":           "Output Complete Type",
        "LocParFunc":      "Func Partial Location",
        "LocCompFunc":     "Func Complete Location",
        "WeakSFunc":       "Func Weak Semantics",
        "StrongSFunc":     "Func Strong Semantics",
        "ExceptValue":     "Exception Value",
        "ExceptType":      "Exception Type",
        "ParamDefault":    "Parameter Default Value",
        # Variable level
        "Var":             "Variable",
        "VarType":         "Variable Type",
        "VarValue":        "Variable Value",
        "LocParVar":       "Var Partial Location",
        "LocCompVar":      "Var Complete Location",
        "WeakSVar":        "Var Weak Semantics",
        "StrongSVar":      "Var Strong Semantics",
        # Cls variable list (taxonomy_game uses LocVarClass/LocVarFunc)
        "LocVarClass":     "Cls Variable List",
        "LocVarFunc":      "Func Local Variables",
    }

    print(f"\nLOO row importance (v(FULL) - v(FULL\\{{row}})):")
    print(f"  {'Row':<15} {'Full name':<50} {'Importance':>10}  {'N':>4}")
    print(f"  {'-'*15}  {'-'*50}  {'-'*10}  {'-'*4}")
    for row, score in importance_sorted.items():
        n         = len(row_importances[row])
        full_name = _ROW_FULL_NAME.get(row, row)
        print(f"  {row:<15}  {full_name:<50}  {score:>10.4f}  {n:>4}")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect LOO eval results and compute row importance scores.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("run_id", help="Run directory name (e.g. loo_helped_r1)")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=RUNS_DIR,
        help=f"Root directory of LOO runs. Default: {RUNS_DIR}",
    )
    args = parser.parse_args()

    run_dir = args.runs_dir / args.run_id
    if not run_dir.exists():
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    sys.exit(collect(run_dir))


if __name__ == "__main__":
    main()

# Made with Bob
