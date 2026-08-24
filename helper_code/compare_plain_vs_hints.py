"""
Compare two eval_results.json files to find instances where hints helped or hurt.

Computes four categories across instances common to both runs:
  hints_helped : plain wrong  → hints correct  (+)
  hints_hurt   : plain correct → hints wrong   (−)
  both_correct : correct in both runs
  both_wrong   : wrong in both runs

Output JSON schema
------------------
{
  "summary": {
    "common_instances": int,
    "both_correct":     int,
    "both_wrong":       int,
    "hints_helped":     int,
    "hints_hurt":       int
  },
  "hints_helped": [instance_id, ...],
  "hints_hurt":   [instance_id, ...],
  "both_correct": [instance_id, ...],
  "both_wrong":   [instance_id, ...]
}

Usage
-----
    python helper_code/compare_plain_vs_hints.py

    # Custom paths:
    python helper_code/compare_plain_vs_hints.py \\
        --plain  /path/to/plain/eval_results.json \\
        --hints  /path/to/hints/eval_results.json \\
        --output leave_one_out/output/plain_vs_hints_diff.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_PLAIN = Path(
    os.environ.get(
        "SWE_BENCH_PRO_PATH",
        "SWE-bench_Pro-os",
    )
) / "results/eval_deepseek_v4_flash_python_plain/eval_results.json"
_DEFAULT_HINTS = Path(
    "leave_one_out/output/eval_all_hints/eval_results.json"
)
_DEFAULT_OUTPUT = Path(
    "leave_one_out/output/plain_vs_hints_diff.json"
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def compare(
    plain_eval: dict[str, bool],
    hints_eval: dict[str, bool],
) -> dict:
    common = set(plain_eval.keys()) & set(hints_eval.keys())

    hints_helped = sorted(iid for iid in common if not plain_eval[iid] and     hints_eval[iid])
    hints_hurt   = sorted(iid for iid in common if     plain_eval[iid] and not hints_eval[iid])
    both_right   = sorted(iid for iid in common if     plain_eval[iid] and     hints_eval[iid])
    both_wrong   = sorted(iid for iid in common if not plain_eval[iid] and not hints_eval[iid])

    return {
        "summary": {
            "common_instances": len(common),
            "both_correct":     len(both_right),
            "both_wrong":       len(both_wrong),
            "hints_helped":     len(hints_helped),
            "hints_hurt":       len(hints_hurt),
        },
        "hints_helped": hints_helped,
        "hints_hurt":   hints_hurt,
        "both_correct": both_right,
        "both_wrong":   both_wrong,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare plain vs hints eval results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plain", "-p",
        type=Path,
        default=_DEFAULT_PLAIN,
        help=f"eval_results.json for the plain (no-hints) run. Default: {_DEFAULT_PLAIN}",
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        default=_DEFAULT_HINTS,
        help=f"eval_results.json for the hints run. Default: {_DEFAULT_HINTS}",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output JSON path. Default: {_DEFAULT_OUTPUT}",
    )
    args = parser.parse_args()

    plain_eval: dict[str, bool] = json.loads(args.plain.read_text())
    hints_eval: dict[str, bool] = json.loads(args.hints.read_text())

    print(f"Plain run : {len(plain_eval)} instances  ({args.plain})")
    print(f"Hints run : {len(hints_eval)} instances  ({args.hints})")

    result = compare(plain_eval, hints_eval)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))

    s = result["summary"]
    print(f"\nCommon instances : {s['common_instances']}")
    print(f"Both correct     : {s['both_correct']}")
    print(f"Both wrong       : {s['both_wrong']}")
    print(f"Hints helped (+) : {s['hints_helped']}")
    print(f"Hints hurt  (-)  : {s['hints_hurt']}")
    print(f"\nSaved -> {args.output}")


if __name__ == "__main__":
    main()

# Made with Bob
