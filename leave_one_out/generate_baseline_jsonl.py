"""
generate_baseline_jsonl.py
==========================
Generate two flat mini-SWE-agent input files for a given hints JSONL:

  1. all_hints  — full coalition (all active rows rendered as hint text)
  2. no_hints   — empty coalition (hints field is ""; no hint context)

These are the FULL and NONE baselines used to bracket LOO experiments.
Unlike the per-coalition files written by generate_all_hints_v3.py --run-dir,
these are standalone flat JSONLs suitable for direct use with mini-extra.

Compatible with both swe_pro and swerebench datasets:
  - swerebench records carry an image_name field that is used as-is.
  - swe_pro records do not; image_name is built via get_dockerhub_image_uri.

Output filenames default to:
  <output-dir>/<stem>_all_hints_v3.jsonl
  <output-dir>/<stem>_no_hints_v3.jsonl
where <stem> is the hints filename without extension.

Usage
-----
    # SWErebench (2025 + 2026):
    python leave_one_out/generate_baseline_jsonl.py \\
        --hints    results/swerebench/hints_communication_all_nonempty_merged.jsonl \\
        --swebench data/swerebench_2025.jsonl data/swerebench_2026.jsonl \\
        --output-dir leave_one_out/output

    # SWE-bench Pro:
    python leave_one_out/generate_baseline_jsonl.py \\
        --hints    leave_one_out/output/hints_helped_enriched.jsonl \\
        --swebench data/swebench_pro_python.jsonl \\
        --output-dir leave_one_out/output

    # Custom output filenames:
    python leave_one_out/generate_baseline_jsonl.py \\
        --hints    results/swerebench/hints_communication_all_nonempty_merged.jsonl \\
        --swebench data/swerebench_2025.jsonl data/swerebench_2026.jsonl \\
        --all-hints-out leave_one_out/output/swerebench_all_hints_v3.jsonl \\
        --no-hints-out  leave_one_out/output/swerebench_no_hints_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
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

_swe_pro_path = os.environ.get("SWE_BENCH_PRO_PATH", "")
if _swe_pro_path:
    sys.path.insert(0, _swe_pro_path)
from helper_code.image_uri import get_dockerhub_image_uri


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_hints(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_swebench_index(paths: list[Path]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                iid = rec.get("instance_id", "")
                if iid:
                    index[iid] = rec
        print(f"  {path.name}: {len(index)} records indexed so far")
    return index


def resolve_image(swe_rec: dict, iid: str, dockerhub: str) -> str:
    """Use embedded image_name (swerebench) or build it (swe_pro)."""
    if "image_name" in swe_rec:
        return swe_rec["image_name"]
    return get_dockerhub_image_uri(iid, dockerhub, swe_rec.get("repo", ""))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def generate(
    hints_path: Path,
    swebench_paths: list[Path],
    all_hints_out: Path,
    no_hints_out: Path,
    dockerhub: str,
) -> None:
    print(f"Loading hints       : {hints_path}")
    hint_records = load_hints(hints_path)
    print(f"  {len(hint_records)} hint records loaded.")

    print(f"Loading SWE-bench   : {[str(p) for p in swebench_paths]}")
    swe_index = load_swebench_index(swebench_paths)
    print(f"  {len(swe_index)} records indexed total.")

    all_hints_out.parent.mkdir(parents=True, exist_ok=True)
    no_hints_out.parent.mkdir(parents=True, exist_ok=True)

    n_written = n_missing = 0

    with open(all_hints_out, "w", encoding="utf-8") as fa, \
         open(no_hints_out,  "w", encoding="utf-8") as fn:

        for hint_rec in hint_records:
            iid     = hint_rec["instance_id"]
            swe_rec = swe_index.get(iid)
            if swe_rec is None:
                print(f"  WARNING: {iid} not in SWE-bench index — skipping.",
                      file=sys.stderr)
                n_missing += 1
                continue

            coalition    = available_rows(hint_rec)
            active_roots = [r for r in LOO_SUBGRAPH_ROOTS if coalition & subtree_rows(r)]
            image_name   = resolve_image(swe_rec, iid, dockerhub)

            base = {
                "instance_id":       iid,
                "image_name":        image_name,
                "problem_statement": swe_rec["problem_statement"],
                "base_commit":       swe_rec["base_commit"],
                "repo":              swe_rec.get("repo", ""),
            }

            # ── all hints ────────────────────────────────────────────────────
            fa.write(json.dumps({
                **base,
                "hints":           render_hint(hint_rec, coalition),
                "_coalition_id":   coalition_id(coalition),
                "_active_rows":    sorted(coalition),
                "_active_roots":   active_roots,
            }, ensure_ascii=False) + "\n")

            # ── no hints ─────────────────────────────────────────────────────
            fn.write(json.dumps({
                **base,
                "hints":           "",
                "_coalition_id":   "none",
                "_active_rows":    [],
                "_active_roots":   [],
            }, ensure_ascii=False) + "\n")

            n_written += 1

    print(f"\nWrote {n_written} instances.")
    print(f"  All hints : {all_hints_out}")
    print(f"  No hints  : {no_hints_out}")
    if n_missing:
        print(f"  WARNING: {n_missing} instance(s) skipped (not in SWE-bench index).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate all-hints and no-hints baseline JSONLs for mini-SWE-agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        required=True,
        help="Enriched hints JSONL.",
    )
    parser.add_argument(
        "--swebench", "-s",
        type=Path,
        nargs="+",
        required=True,
        help=(
            "One or more SWE-bench JSONL files. "
            "Pass both swerebench years: -s data/swerebench_2025.jsonl data/swerebench_2026.jsonl"
        ),
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=None,
        help=(
            "Directory to write output files. "
            "Filenames are derived from the hints filename. "
            "Ignored if --all-hints-out / --no-hints-out are set."
        ),
    )
    parser.add_argument(
        "--all-hints-out",
        type=Path,
        default=None,
        help="Explicit output path for the all-hints JSONL.",
    )
    parser.add_argument(
        "--no-hints-out",
        type=Path,
        default=None,
        help="Explicit output path for the no-hints JSONL.",
    )
    parser.add_argument(
        "--dockerhub", "-d",
        type=str,
        default="jefzda",
        help="DockerHub username for swe_pro image URI fallback (default: jefzda).",
    )
    args = parser.parse_args()

    # Resolve output paths
    stem = args.hints.stem   # e.g. "hints_communication_all_nonempty_merged"
    if args.all_hints_out and args.no_hints_out:
        all_hints_out = args.all_hints_out
        no_hints_out  = args.no_hints_out
    elif args.output_dir:
        all_hints_out = args.output_dir / f"{stem}_all_hints_v3.jsonl"
        no_hints_out  = args.output_dir / f"{stem}_no_hints_v3.jsonl"
    else:
        parser.error("Provide either --output-dir or both --all-hints-out and --no-hints-out.")

    generate(
        hints_path=args.hints,
        swebench_paths=args.swebench,
        all_hints_out=all_hints_out,
        no_hints_out=no_hints_out,
        dockerhub=args.dockerhub,
    )


if __name__ == "__main__":
    main()

# Made with Bob
