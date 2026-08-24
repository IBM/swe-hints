#!/usr/bin/env python3
"""
Extract Doc2Feat-bench_Verified from HuggingFace to a local JSONL file
compatible with the src/ pipeline.

Key normalisation:
  - feature_patch  → patch        (pipeline reads "patch")
  - problem_statement = joined doc_changes path names
                                   (the original field is a git diff, not prose;
                                    the paths are the closest human-readable label
                                    for what documentation was changed)

Usage
-----
    python helper_code/extract_doc2feat_verified.py \
        --output data/doc2feat_verified.jsonl

    # Preview only (no file written):
    python helper_code/extract_doc2feat_verified.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import load_dataset

HF_DATASET = "Doc2Feat-bench/Doc2Feat-bench_Verified"
HF_SPLIT   = "test"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Doc2Feat-bench_Verified from HuggingFace and save as pipeline-compatible JSONL."
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/doc2feat_verified.jsonl"),
        help="Output JSONL path (default: data/doc2feat_verified.jsonl).",
    )
    parser.add_argument(
        "--split",
        default=HF_SPLIT,
        help=f"HuggingFace dataset split (default: {HF_SPLIT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats and sample instance IDs without writing any file.",
    )
    args = parser.parse_args()

    print(f"Loading {HF_DATASET} ({args.split} split) from HuggingFace...")
    dataset = load_dataset(HF_DATASET, split=args.split)
    print(f"Total instances: {len(dataset)}")

    def _doc_paths(inst: dict) -> str:
        dc = inst.get("doc_changes") or []
        if isinstance(dc, str):
            import json as _json
            dc = _json.loads(dc)
        return ", ".join(entry["path"] for entry in dc)

    if args.dry_run:
        print("\n[dry-run] Sample instance IDs:")
        for i in range(min(5, len(dataset))):
            inst = dataset[i]
            print(f"  {inst['instance_id']}  doc_changes={_doc_paths(inst)!r}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for i in range(len(dataset)):
            inst = dataset[i]
            doc_paths = _doc_paths(inst)
            record = {
                "repo":              inst["repo"],
                "instance_id":       inst["instance_id"],
                "base_commit":       inst["base_commit"],
                "patch":             inst["feature_patch"],
                "test_patch":        inst["test_patch"],
                "problem_statement": doc_paths,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(dataset)} instances to {args.output}")


if __name__ == "__main__":
    main()

# Made with Bob
