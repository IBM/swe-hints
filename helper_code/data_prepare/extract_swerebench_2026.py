"""
Extract SWE-rebench-leaderboard instances from the 2026_01, 2026_02, and 2026_03
splits and save them as a JSONL file compatible with the src/ pipeline.

Output fields match data/swebench_pro_python.jsonl:
    repo, instance_id, base_commit, patch, test_patch, problem_statement

Usage:
    python helper_code/extract_swerebench_2026.py \
        --output data/swerebench_2026.jsonl

    # Custom splits
    python helper_code/extract_swerebench_2026.py \
        --splits 2026_01 2026_02 2026_03 \
        --output data/swerebench_2026.jsonl

    # Python-only filter (default: on)
    python helper_code/extract_swerebench_2026.py \
        --no-python-filter \
        --output data/swerebench_2026_all.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract SWE-rebench-leaderboard instances to a pipeline-compatible JSONL."
    )
    parser.add_argument(
        "--splits", nargs="+",
        default=["2026_01", "2026_02", "2026_03"],
        help="HuggingFace dataset splits to extract (default: 2026_01 2026_02 2026_03).",
    )
    parser.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Output JSONL path.",
    )
    parser.add_argument(
        "--no-python-filter", action="store_true",
        help="Include non-Python instances (default: Python only, detected via patch content).",
    )
    args = parser.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        raise SystemExit("datasets package not found. Run: pip install datasets")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    total = skipped = 0

    with open(args.output, "w", encoding="utf-8") as out_f:
        for split in args.splits:
            print(f"Loading split: {split} ...", flush=True)
            try:
                ds = load_dataset(
                    "nebius/SWE-rebench-leaderboard",
                    split=split,
                    streaming=True,
                )
            except Exception as e:
                print(f"  WARNING: could not load split {split!r}: {e}")
                continue

            n_split = 0
            for row in ds:
                patch      = row.get("patch", "") or ""
                test_patch = row.get("test_patch", "") or ""

                # Python filter: at least one .py file in the patch
                if not args.no_python_filter:
                    if ".py" not in patch and ".py" not in test_patch:
                        skipped += 1
                        continue

                record = {
                    "repo":              row["repo"],
                    "instance_id":       row["instance_id"],
                    "base_commit":       row["base_commit"],
                    "patch":             patch,
                    "test_patch":        test_patch,
                    "problem_statement": row.get("problem_statement", "") or "",
                    # Extra fields available in SWE-rebench (kept for reference)
                    "image_name":        row.get("image_name", "") or "",
                    "FAIL_TO_PASS":      row.get("FAIL_TO_PASS", "") or "",
                    "PASS_TO_PASS":      row.get("PASS_TO_PASS", "") or "",
                    "created_at":        row.get("created_at", "") or "",
                    "split":             split,
                }
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                total += 1
                n_split += 1

            print(f"  {split}: {n_split} instances written")

    print(f"\nDone. Total written: {total}  |  Skipped (non-Python): {skipped}")
    print(f"Output: {args.output}")
    if total:
        print(f"\nNext steps:")
        print(f"  # Step 1 — extract identifier catalogue")
        print(f"  .venv/bin/python -m src.identifier_usage \\")
        print(f"    --input      {args.output} \\")
        print(f"    --repos-dir  repos/swerebench_repos \\")
        print(f"    --output     results/swerebench/extracted_hints.jsonl \\")
        print(f"    --skip-errors")
        print(f"\n  # Step 2 — apply communication operator")
        print(f"  .venv/bin/python -m src.identifier_information \\")
        print(f"    --usage    results/swerebench/extracted_hints.jsonl \\")
        print(f"    --operator communication \\")
        print(f"    --level    All \\")
        print(f"    --output   results/swerebench/hints_communication_all.jsonl")


if __name__ == "__main__":
    main()

# Made with Bob
