"""
Filter a hints JSONL file to only records that have at least one identifier.

Usage:
    python helper_code/filter_nonempty_identifiers.py \
        --input  results/swe_pro/hints_communication_all.jsonl \
        --output results/swe_pro/hints_communication_all_nonempty.jsonl
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep only records with non-empty identifiers.")
    parser.add_argument("--input",  "-i", type=Path, required=True, help="Input JSONL file.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output JSONL file.")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_total = n_kept = 0
    with open(args.input, encoding="utf-8") as in_f, \
         open(args.output, "w", encoding="utf-8") as out_f:
        for line in in_f:
            line = line.strip()
            if not line:
                continue
            n_total += 1
            record = json.loads(line)
            if record.get("identifiers"):
                out_f.write(line + "\n")
                n_kept += 1

    print(f"Total: {n_total}  |  Kept (non-empty): {n_kept}  |  Dropped: {n_total - n_kept}")


if __name__ == "__main__":
    main()
