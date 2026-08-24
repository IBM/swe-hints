#!/usr/bin/env python3
"""
Extract SWE-bench Pro Python instances from HuggingFace to a local JSONL file.

Python repos in SWE-bench Pro:
  - ansible/ansible
  - qutebrowser/qutebrowser
  - internetarchive/openlibrary

Usage
-----
    python helper_code/extract_swebench_pro_python.py \
        --output data/swebench_pro_python.jsonl

    # Preview only (no file written):
    python helper_code/extract_swebench_pro_python.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import load_dataset

PYTHON_REPOS = {
    "ansible/ansible",
    "qutebrowser/qutebrowser",
    "internetarchive/openlibrary",
}

HF_DATASET = "ScaleAI/SWE-bench_Pro"
HF_SPLIT   = "test"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download SWE-bench Pro from HuggingFace and save Python-only instances as JSONL."
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/swebench_pro_python.jsonl"),
        help="Output JSONL path (default: data/swebench_pro_python.jsonl).",
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

    python_instances = [
        dict(inst) for inst in dataset
        if inst.get("repo") in PYTHON_REPOS
    ]
    print(f"Python instances ({', '.join(sorted(PYTHON_REPOS))}): {len(python_instances)}")

    # Per-repo breakdown
    from collections import Counter
    counts = Counter(inst["repo"] for inst in python_instances)
    for repo, n in sorted(counts.items()):
        print(f"  {repo}: {n}")

    if args.dry_run:
        print("\n[dry-run] Sample instance IDs:")
        for inst in python_instances[:5]:
            print(f"  {inst['instance_id']}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for inst in python_instances:
            f.write(json.dumps(inst, ensure_ascii=False, default=str) + "\n")

    print(f"\nSaved {len(python_instances)} instances to {args.output}")


if __name__ == "__main__":
    main()

# Made with Bob
