"""
generate_all_hints.py
=====================
Generate a mini-SWE-agent JSONL from the LLM-enriched hints file, inserting
ALL available hint entries for every instance (full coalition — no rows left out).

This is the "full hints" baseline used before leave-one-out experiments.

Input
-----
  --hints    Enriched hints JSONL (default: results/swe_pro/hints_communication_all_nonempty_enriched.jsonl)
  --swebench SWE-bench Pro JSONL  (default: data/swebench_pro_python.jsonl)

Output
------
  --output   SWE-agent-ready JSONL (default: leave_one_out/output/all_hints.jsonl)

Each output record contains:
  instance_id, image_name, problem_statement, hints, base_commit, repo,
  _coalition_id, _active_rows

Usage
-----
    # Full run with defaults:
    python leave_one_out/generate_all_hints.py

    # Inspect rendered hints on stdout:
    python leave_one_out/generate_all_hints.py --print-hints

    # Single instance:
    python leave_one_out/generate_all_hints.py \\
        --instance-id instance_ansible__ansible-395e5e20fab9cad517243372fa3c3c5d9e09ab2a-v7eee2454f617569fd6889f2211f75bc02a35f9f8

    # Custom paths:
    python leave_one_out/generate_all_hints.py \\
        --hints  results/swe_pro/hints_communication_all_nonempty_enriched.jsonl \\
        --swebench data/swebench_pro_python.jsonl \\
        --output leave_one_out/output/all_hints.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from the repo root without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shapley.taxonomy_game import available_rows, coalition_id, render_hint

# ---------------------------------------------------------------------------
# Image URI helper (same as generate_shapley_instances.py)
# ---------------------------------------------------------------------------
_swe_pro_path = os.environ.get("SWE_BENCH_PRO_PATH", "")
if _swe_pro_path:
    sys.path.insert(0, _swe_pro_path)
from helper_code.image_uri import get_dockerhub_image_uri


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_hints(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_swebench_index(path: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                iid = rec.get("instance_id", "")
                if iid:
                    index[iid] = rec
    return index


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    hints_path: Path,
    swebench_path: Path,
    output_path: Path,
    dockerhub: str,
    instance_id: str | None,
    print_hints: bool,
) -> None:
    print(f"Loading hints       : {hints_path}")
    hint_records = load_hints(hints_path)
    print(f"  {len(hint_records)} hint records loaded.")

    print(f"Loading SWE-bench   : {swebench_path}")
    swe_index = load_swebench_index(swebench_path)
    print(f"  {len(swe_index)} SWE-bench records indexed.")

    if instance_id:
        hint_records = [r for r in hint_records if r["instance_id"] == instance_id]
        if not hint_records:
            print(f"ERROR: instance_id {instance_id!r} not found in hints file.", file=sys.stderr)
            sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = n_missing = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        for hint_rec in hint_records:
            iid = hint_rec["instance_id"]

            # Full coalition: every row that has a payload in this instance
            coalition = available_rows(hint_rec)
            cid       = coalition_id(coalition)
            hints_str = render_hint(hint_rec, coalition)

            if print_hints:
                print(f"\n{'=' * 72}")
                print(f"Instance  : {iid}")
                print(f"Active rows ({len(coalition)}): {sorted(coalition)}")
                print(f"CoalID    : {cid}")
                print("--- hints ---")
                print(hints_str or "(empty)")
                print("--- end hints ---")

            swe_rec = swe_index.get(iid)
            if swe_rec is None:
                print(f"  WARNING: {iid} not found in SWE-bench index — skipping.", file=sys.stderr)
                n_missing += 1
                continue

            image_name = get_dockerhub_image_uri(iid, dockerhub, swe_rec.get("repo", ""))

            record = {
                "instance_id":       iid,
                "image_name":        image_name,
                "problem_statement": swe_rec["problem_statement"],
                "hints":             hints_str,
                "base_commit":       swe_rec["base_commit"],
                "repo":              swe_rec.get("repo", ""),
                # Traceability metadata (not read by mini-SWE-agent)
                "_coalition_id":     cid,
                "_active_rows":      sorted(coalition),
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"\nWrote {n_written} instances -> {output_path}")
    if n_missing:
        print(f"  WARNING: {n_missing} instance(s) skipped (not in SWE-bench index).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate full-coalition SWE-agent JSONL from enriched hints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        default=Path("results/swe_pro/hints_communication_all_nonempty_enriched.jsonl"),
        help="Enriched hints JSONL (default: results/swe_pro/hints_communication_all_nonempty_enriched.jsonl)",
    )
    parser.add_argument(
        "--swebench", "-s",
        type=Path,
        default=Path("data/swebench_pro_python.jsonl"),
        help="SWE-bench Pro JSONL (default: data/swebench_pro_python.jsonl)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("leave_one_out/output/all_hints.jsonl"),
        help="Output JSONL (default: leave_one_out/output/all_hints.jsonl)",
    )
    parser.add_argument(
        "--dockerhub", "-d",
        type=str,
        default="jefzda",
        help="DockerHub username for image URI generation (default: jefzda)",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default=None,
        help="Process a single instance only (for inspection / debugging).",
    )
    parser.add_argument(
        "--print-hints",
        action="store_true",
        help="Print the rendered hints for each instance to stdout.",
    )
    args = parser.parse_args()

    run(
        hints_path=args.hints,
        swebench_path=args.swebench,
        output_path=args.output,
        dockerhub=args.dockerhub,
        instance_id=args.instance_id,
        print_hints=args.print_hints,
    )


if __name__ == "__main__":
    main()

# Made with Bob
