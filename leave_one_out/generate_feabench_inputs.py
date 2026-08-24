"""
generate_feabench_inputs.py
===========================
Generate two mini-SWE-agent-ready JSONL files from a FEA-Bench sample:

  1. no_hints.jsonl  — problem_statement only, hints field empty
  2. all_hints.jsonl — problem_statement + full rendered hint (all active rows)

The sample file (e.g. results/feabench/sample_loo_60.jsonl) provides the
identifier/hints data.  The FEA-Bench Lite-Standard HuggingFace dataset
provides problem_statement, base_commit, repo, and patch fields.

Output schema (matches mini-SWE-agent expectations, aligned with
generate_all_hints_v3.py):
    instance_id, problem_statement, hints, base_commit, repo,
    patch, test_patch, FAIL_TO_PASS, PASS_TO_PASS,
    _coalition_id, _active_rows, _active_roots   (all_hints only)

Usage
-----
    python leave_one_out/generate_feabench_inputs.py \\
        --sample   results/feabench/sample_loo_60.jsonl \\
        --dataset  /PATH/TO/FEA-Bench/feabench-data/FEA-Bench-v1.0-Lite-Standard \\
        --out-dir  results/feabench/agent_inputs

    # Use data/feabench/Lite-Standard if you ran get_dataset.py locally:
    python leave_one_out/generate_feabench_inputs.py \\
        --sample   results/feabench/sample_loo_60.jsonl \\
        --dataset  data/feabench/Lite-Standard \\
        --out-dir  results/feabench/agent_inputs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    available_rows,
    coalition_id,
    render_hint,
    subtree_rows,
)


def load_sample(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_feabench_index(dataset_path: Path) -> dict[str, dict]:
    """Load FEA-Bench HuggingFace dataset into instance_id -> record index."""
    try:
        from datasets import load_from_disk
    except ImportError:
        sys.exit("ERROR: 'datasets' not installed. Run: pip install datasets")

    ds = load_from_disk(str(dataset_path))
    split = ds["test"] if "test" in ds else ds[list(ds.keys())[0]]
    index = {row["instance_id"]: dict(row) for row in split}
    print(f"  Loaded {len(index)} instances from {dataset_path}")
    return index


def build_no_hints_record(hint_rec: dict, fb_rec: dict) -> dict:
    return {
        "instance_id":       hint_rec["instance_id"],
        "problem_statement": fb_rec["problem_statement"],
        "hints":             "",
        "base_commit":       fb_rec["base_commit"],
        "repo":              fb_rec["repo"],
        "patch":             fb_rec.get("patch", ""),
        "test_patch":        fb_rec.get("test_patch", ""),
        "FAIL_TO_PASS":      fb_rec.get("FAIL_TO_PASS", []),
        "PASS_TO_PASS":      fb_rec.get("PASS_TO_PASS", []),
    }


def build_all_hints_record(hint_rec: dict, fb_rec: dict) -> dict:
    coalition    = available_rows(hint_rec)
    hints_str    = render_hint(hint_rec, coalition)
    cid          = coalition_id(coalition)
    active_roots = [r for r in LOO_SUBGRAPH_ROOTS if coalition & subtree_rows(r)]

    return {
        "instance_id":       hint_rec["instance_id"],
        "problem_statement": fb_rec["problem_statement"],
        "hints":             hints_str,
        "base_commit":       fb_rec["base_commit"],
        "repo":              fb_rec["repo"],
        "patch":             fb_rec.get("patch", ""),
        "test_patch":        fb_rec.get("test_patch", ""),
        "FAIL_TO_PASS":      fb_rec.get("FAIL_TO_PASS", []),
        "PASS_TO_PASS":      fb_rec.get("PASS_TO_PASS", []),
        "_coalition_id":     cid,
        "_active_rows":      sorted(coalition),
        "_active_roots":     active_roots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate no-hints and all-hints JSONL files for FEA-Bench mini-SWE-agent runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sample", "-s",
        type=Path,
        default=Path("results/feabench/sample_loo_60.jsonl"),
        help="Sampled hints JSONL (default: results/feabench/sample_loo_60.jsonl).",
    )
    parser.add_argument(
        "--dataset", "-d",
        type=Path,
        default=Path("/PATH/TO/FEA-Bench/feabench-data/FEA-Bench-v1.0-Lite-Standard"),
        help="FEA-Bench Lite-Standard HuggingFace dataset directory.",
    )
    parser.add_argument(
        "--out-dir", "-o",
        type=Path,
        default=Path("results/feabench/agent_inputs"),
        help="Output directory (default: results/feabench/agent_inputs).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load inputs
    # ------------------------------------------------------------------
    print(f"Loading sample     : {args.sample}")
    sample = load_sample(args.sample)
    print(f"  {len(sample)} instances loaded.")

    print(f"Loading FEA-Bench  : {args.dataset}")
    fb_index = load_feabench_index(args.dataset)

    # ------------------------------------------------------------------
    # Match instances
    # ------------------------------------------------------------------
    args.out_dir.mkdir(parents=True, exist_ok=True)
    no_hints_path  = args.out_dir / "no_hints.jsonl"
    all_hints_path = args.out_dir / "all_hints.jsonl"

    n_written = n_missing = 0
    with open(no_hints_path,  "w", encoding="utf-8") as f_no, \
         open(all_hints_path, "w", encoding="utf-8") as f_all:

        for hint_rec in sample:
            iid    = hint_rec["instance_id"]
            fb_rec = fb_index.get(iid)

            if fb_rec is None:
                print(f"  WARNING: {iid} not found in FEA-Bench dataset — skipping.")
                n_missing += 1
                continue

            f_no.write( json.dumps(build_no_hints_record( hint_rec, fb_rec), ensure_ascii=False) + "\n")
            f_all.write(json.dumps(build_all_hints_record(hint_rec, fb_rec), ensure_ascii=False) + "\n")
            n_written += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\nWrote {n_written} instances ({n_missing} skipped).")
    print(f"  No-hints  : {no_hints_path}")
    print(f"  All-hints : {all_hints_path}")

    if n_missing:
        print(
            f"\n  NOTE: {n_missing} instance(s) not found in the Lite-Standard dataset.\n"
            f"  They may be in the full Standard dataset. Re-run with:\n"
            f"    --dataset /PATH/TO/FEA-Bench/feabench-data/FEA-Bench-v1.0-Standard"
        )


if __name__ == "__main__":
    main()

# Made with Bob
