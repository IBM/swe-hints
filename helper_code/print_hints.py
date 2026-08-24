"""
Print hints from a mini-SWE-agent input JSONL for manual inspection.

Usage
-----
    # Print all instances (paged)
    python helper_code/print_hints.py --input leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl

    # Print a specific instance
    python helper_code/print_hints.py --input leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl \
        --instance-id relekang__python-semantic-release-21

    # Compare two files side by side for the same instances
    python helper_code/print_hints.py \
        --input  leave_one_out/output/swerebench_v2_300_all_hints_v3.jsonl \
        --compare leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl

    # Limit to first N instances
    python helper_code/print_hints.py --input leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl \
        --limit 10
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def divider(char: str = "=", width: int = 72) -> str:
    return char * width


def print_record(idx: int, rec: dict, compare_rec: dict | None = None) -> None:
    iid   = rec["instance_id"]
    hints = rec.get("hints", "")

    print(divider())
    print(f"[{idx}] {iid}")
    print(divider())

    if compare_rec is None:
        print(hints if hints else "(empty — no hints)")
    else:
        left  = hints if hints else "(empty)"
        right = compare_rec.get("hints", "") if compare_rec.get("hints") else "(empty)"
        print("<<< LEFT >>>")
        print(left)
        print()
        print("<<< RIGHT >>>")
        print(right)

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print hints from a mini-SWE-agent JSONL for manual inspection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",  "-i", type=Path, required=True,
                        help="Input JSONL file.")
    parser.add_argument("--compare", "-c", type=Path, default=None,
                        help="Optional second JSONL to compare hints side by side.")
    parser.add_argument("--instance-id", type=str, default=None,
                        help="Print only this instance_id.")
    parser.add_argument("--limit", "-n", type=int, default=None,
                        help="Stop after N instances.")
    args = parser.parse_args()

    records = load_jsonl(args.input)

    compare_index: dict[str, dict] = {}
    if args.compare:
        for r in load_jsonl(args.compare):
            compare_index[r["instance_id"]] = r

    if args.instance_id:
        records = [r for r in records if r["instance_id"] == args.instance_id]
        if not records:
            print(f"instance_id {args.instance_id!r} not found in {args.input}")
            return

    if args.limit:
        records = records[: args.limit]

    for idx, rec in enumerate(records, 1):
        compare_rec = compare_index.get(rec["instance_id"]) if compare_index else None
        print_record(idx, rec, compare_rec)


if __name__ == "__main__":
    main()
