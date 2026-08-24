"""
generate_oracle_patch_jsonl.py
==============================
Generate a mini-SWE-agent input JSONL where the hints field contains the
ground-truth patch and test patch verbatim — the oracle upper bound.

No formatting, no truncation.  The raw unified-diff text is placed directly
in the ``hints`` field so the agent sees the exact solution.

Usage
-----
    python leave_one_out/generate_oracle_patch_jsonl.py \\
        --swebench data/swebench_pro_python.jsonl \\
        --output   results/miniswe_swe_pro/oracle_patch.jsonl

    # Restrict to instances present in a hints file
    python leave_one_out/generate_oracle_patch_jsonl.py \\
        --swebench data/swebench_pro_python.jsonl \\
        --hints    results/swe_pro_proj/interface_retrieved_hints_nonempty.jsonl \\
        --output   results/miniswe_swe_pro/oracle_patch_interface_retrieved.jsonl

    # Omit test patch (code patch only)
    python leave_one_out/generate_oracle_patch_jsonl.py \\
        --swebench data/swebench_pro_python.jsonl \\
        --output   results/miniswe_swe_pro/oracle_patch_codeonly.jsonl \\
        --no-test-patch
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_swe_pro_path = os.environ.get("SWE_BENCH_PRO_PATH", "")
if _swe_pro_path:
    sys.path.insert(0, _swe_pro_path)
from helper_code.image_uri import get_dockerhub_image_uri


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_swebench(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        print(f"  {path.name}: {len(rows)} records loaded so far")
    return rows


def resolve_image(swe_rec: dict, iid: str, dockerhub: str) -> str:
    if "image_name" in swe_rec:
        return swe_rec["image_name"]
    return get_dockerhub_image_uri(iid, dockerhub, swe_rec.get("repo", ""))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def generate(
    swebench_paths: list[Path],
    output_path: Path,
    dockerhub: str,
    include_test_patch: bool,
    filter_ids: set[str] | None,
) -> None:
    print(f"Loading SWE-bench : {[str(p) for p in swebench_paths]}")
    rows = load_swebench(swebench_paths)
    if filter_ids is not None:
        rows = [r for r in rows if r["instance_id"] in filter_ids]
        print(f"  {len(rows)} records after filtering to hints instances.")
    else:
        print(f"  {len(rows)} records total.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for rec in rows:
            iid        = rec["instance_id"]
            patch      = rec.get("patch", "")
            test_patch = rec.get("test_patch", "")
            image_name = resolve_image(rec, iid, dockerhub)

            if include_test_patch and test_patch:
                hints = patch + "\n" + test_patch
            else:
                hints = patch

            out.write(json.dumps({
                "instance_id":       iid,
                "image_name":        image_name,
                "problem_statement": rec["problem_statement"],
                "base_commit":       rec["base_commit"],
                "repo":              rec.get("repo", ""),
                "hints":             hints,
                "_coalition_id":     "oracle_patch",
            }, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"\nWrote {n_written} instances → {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate oracle-patch hints JSONL for mini-SWE-agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--swebench", "-s", type=Path, nargs="+", required=True,
                        help="One or more SWE-bench JSONL files.")
    parser.add_argument("--hints", "-i", type=Path, default=None,
                        help="Optional hints JSONL; restrict output to its instance_ids.")
    parser.add_argument("--output", "-o", type=Path, required=True,
                        help="Output JSONL path.")
    parser.add_argument("--dockerhub", "-d", type=str, default="jefzda",
                        help="DockerHub username for swe_pro image URI (default: jefzda).")
    parser.add_argument("--no-test-patch", action="store_true",
                        help="Omit the test patch; include only the code patch.")
    args = parser.parse_args()

    filter_ids: set[str] | None = None
    if args.hints is not None:
        filter_ids = {
            json.loads(l)["instance_id"]
            for l in args.hints.read_text(encoding="utf-8").splitlines()
            if l.strip()
        }
        print(f"Filtering to {len(filter_ids)} instance(s) from {args.hints.name}")

    generate(
        swebench_paths=args.swebench,
        output_path=args.output,
        dockerhub=args.dockerhub,
        include_test_patch=not args.no_test_patch,
        filter_ids=filter_ids,
    )


if __name__ == "__main__":
    main()

# Made with Bob
