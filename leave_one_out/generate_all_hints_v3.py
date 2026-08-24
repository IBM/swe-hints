"""
generate_all_hints_v3.py
========================
Generate a mini-SWE-agent JSONL from the LLM-enriched hints file, inserting
ALL available hint entries for every instance (full coalition — no roots left
out).

This is the "full hints" baseline used before leave-one-out experiments and
also produces the per-coalition JSONL files that run_loo_agent_v3.sh feeds into
mini-SWE-agent for every coalition in coalition_manifest.json.

Uses taxonomy_game_v3 (v3 taxonomy):
  - File, Class, Func, Var are top-level peers
  - LOO operates over subgraph roots, not individual rows

Input
-----
  --hints    Enriched hints JSONL (default: results/swe_pro/hints_communication_all_nonempty_enriched.jsonl)
  --swebench SWE-bench Pro JSONL  (default: data/swebench_pro_python.jsonl)

Output
------
  --output   SWE-agent-ready JSONL (default: leave_one_out/output/all_hints_v3.jsonl)

Each output record contains:
  instance_id, image_name, problem_statement, hints, base_commit, repo,
  _coalition_id, _active_rows, _active_roots

Usage
-----
    # Full run with defaults:
    python leave_one_out/generate_all_hints_v3.py

    # Inspect rendered hints on stdout:
    python leave_one_out/generate_all_hints_v3.py --print-hints

    # Single instance:
    python leave_one_out/generate_all_hints_v3.py \\
        --instance-id instance_ansible__ansible-395e5e20fab9cad517243372fa3c3c5d9e09ab2a-v7eee2454f617569fd6889f2211f75bc02a35f9f8

    # Custom paths:
    python leave_one_out/generate_all_hints_v3.py \\
        --hints  results/swe_pro/hints_communication_all_nonempty_enriched.jsonl \\
        --swebench data/swebench_pro_python.jsonl \\
        --output leave_one_out/output/all_hints_v3.jsonl

    # Generate per-coalition JSONL for a planned run:
    python leave_one_out/generate_all_hints_v3.py \\
        --run-dir leave_one_out/runs/loo_helped_v3_r1
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


def load_swebench_index(paths: Path | list[Path]) -> dict[str, dict]:
    """Load one or more SWE-bench JSONL files into a single index.

    Compatible with both swe_pro (no image_name field) and swerebench
    (image_name field present).  Later files overwrite earlier ones on
    duplicate instance_ids.
    """
    if isinstance(paths, Path):
        paths = [paths]
    index: dict[str, dict] = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    iid = rec.get("instance_id", "")
                    if iid:
                        index[iid] = rec
        print(f"  {path.name}: loaded {sum(1 for r in index.values())} records so far")
    return index


def _build_record(
    hint_rec: dict,
    swe_rec: dict,
    coalition: frozenset[str],
    dockerhub: str,
) -> dict:
    """Build a single agent-ready record for a given (instance, coalition).

    Image name resolution (in priority order):
      1. swe_rec["image_name"] — present in swerebench records; use as-is.
      2. get_dockerhub_image_uri() — fallback for swe_pro records which do
         not carry image_name but have repo + instance_id.
    """
    iid        = hint_rec["instance_id"]
    cid        = coalition_id(coalition)
    hints_str  = render_hint(hint_rec, coalition)
    image_name = (
        swe_rec["image_name"]
        if "image_name" in swe_rec
        else get_dockerhub_image_uri(iid, dockerhub, swe_rec.get("repo", ""))
    )

    active_roots = [
        root for root in LOO_SUBGRAPH_ROOTS
        if coalition & subtree_rows(root)
    ]

    return {
        "instance_id":       iid,
        "image_name":        image_name,
        "problem_statement": swe_rec["problem_statement"],
        "hints":             hints_str,
        "base_commit":       swe_rec["base_commit"],
        "repo":              swe_rec.get("repo", ""),
        "_coalition_id":     cid,
        "_active_rows":      sorted(coalition),
        "_active_roots":     active_roots,
    }


# ---------------------------------------------------------------------------
# Full-coalition run (default mode)
# ---------------------------------------------------------------------------

def run_full(
    hints_path: Path,
    swebench_paths: list[Path],
    output_path: Path,
    dockerhub: str,
    instance_id: str | None,
    print_hints: bool,
) -> None:
    print(f"Loading hints       : {hints_path}")
    hint_records = load_hints(hints_path)
    print(f"  {len(hint_records)} hint records loaded.")

    print(f"Loading SWE-bench   : {[str(p) for p in swebench_paths]}")
    swe_index = load_swebench_index(swebench_paths)
    print(f"  {len(swe_index)} SWE-bench records indexed total.")

    if instance_id:
        hint_records = [r for r in hint_records if r["instance_id"] == instance_id]
        if not hint_records:
            print(f"ERROR: instance_id {instance_id!r} not found in hints file.", file=sys.stderr)
            sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = n_missing = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        for hint_rec in hint_records:
            iid      = hint_rec["instance_id"]
            coalition = available_rows(hint_rec)

            if print_hints:
                active_roots = [r for r in LOO_SUBGRAPH_ROOTS if coalition & subtree_rows(r)]
                print(f"\n{'=' * 72}")
                print(f"Instance  : {iid}")
                print(f"Active rows ({len(coalition)}): {sorted(coalition)}")
                print(f"Active roots: {active_roots}")
                print(f"CoalID    : {coalition_id(coalition)}")
                print("--- hints ---")
                print(render_hint(hint_rec, coalition) or "(empty)")
                print("--- end hints ---")

            swe_rec = swe_index.get(iid)
            if swe_rec is None:
                print(f"  WARNING: {iid} not found in SWE-bench index — skipping.", file=sys.stderr)
                n_missing += 1
                continue

            record = _build_record(hint_rec, swe_rec, coalition, dockerhub)
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"\nWrote {n_written} instances -> {output_path}")
    if n_missing:
        print(f"  WARNING: {n_missing} instance(s) skipped (not in SWE-bench index).")


# ---------------------------------------------------------------------------
# Per-coalition run (--run-dir mode)
# ---------------------------------------------------------------------------

def run_for_plan(
    hints_path: Path,
    swebench_paths: list[Path],
    run_dir: Path,
    dockerhub: str,
) -> None:
    """
    Generate an agent-input JSONL for every coalition in the run's
    coalition_manifest.json (the files expected by run_loo_agent_v3.sh).
    """
    manifest_path = run_dir / "coalition_manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found. Run plan_loo_coalitions_v3.py first.",
              file=sys.stderr)
        sys.exit(1)

    manifest: dict = json.loads(manifest_path.read_text())

    print(f"Loading hints       : {hints_path}")
    hint_records = load_hints(hints_path)
    hints_index  = {r["instance_id"]: r for r in hint_records}
    print(f"  {len(hint_records)} hint records loaded.")

    print(f"Loading SWE-bench   : {[str(p) for p in swebench_paths]}")
    swe_index = load_swebench_index(swebench_paths)
    print(f"  {len(swe_index)} SWE-bench records indexed total.")

    agent_inputs_dir = run_dir / "agent_inputs"
    agent_inputs_dir.mkdir(parents=True, exist_ok=True)

    n_written = n_skipped = 0
    for cid, meta in manifest.items():
        coalition  = frozenset(meta["rows"])
        input_file = run_dir / meta["input_file"]
        input_file.parent.mkdir(parents=True, exist_ok=True)

        with open(input_file, "w", encoding="utf-8") as out_f:
            for iid in meta["instance_ids"]:
                hint_rec = hints_index.get(iid)
                swe_rec  = swe_index.get(iid)
                if hint_rec is None or swe_rec is None:
                    print(f"  WARNING: {iid} missing from hints or SWE-bench — skipping.", file=sys.stderr)
                    n_skipped += 1
                    continue
                record = _build_record(hint_rec, swe_rec, coalition, dockerhub)
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                n_written += 1

    print(f"\nWrote {n_written} instance records across {len(manifest)} coalition files.")
    if n_skipped:
        print(f"  WARNING: {n_skipped} record(s) skipped (missing from index).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate SWE-agent JSONL from enriched hints (taxonomy v3).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--hints", "-i",
        type=Path,
        default=Path("results/swe_pro/hints_communication_all_nonempty_enriched.jsonl"),
    )
    parser.add_argument(
        "--swebench", "-s",
        type=Path,
        nargs="+",
        default=[Path("data/swebench_pro_python.jsonl")],
        help=(
            "One or more SWE-bench JSONL files. Pass multiple for swerebench "
            "(e.g. -s data/swerebench_2025.jsonl data/swerebench_2026.jsonl). "
            "Default: data/swebench_pro_python.jsonl"
        ),
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("leave_one_out/output/all_hints_v3.jsonl"),
        help="Output JSONL for full-coalition mode (default: leave_one_out/output/all_hints_v3.jsonl)",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="If provided, generate per-coalition JSONL files for this run directory.",
    )
    parser.add_argument(
        "--dockerhub", "-d",
        type=str,
        default="jefzda",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default=None,
        help="Full-coalition mode only: process a single instance.",
    )
    parser.add_argument(
        "--print-hints",
        action="store_true",
        help="Full-coalition mode only: print rendered hints to stdout.",
    )
    args = parser.parse_args()

    if args.run_dir is not None:
        run_for_plan(
            hints_path=args.hints,
            swebench_paths=args.swebench,
            run_dir=args.run_dir,
            dockerhub=args.dockerhub,
        )
    else:
        run_full(
            hints_path=args.hints,
            swebench_paths=args.swebench,
            output_path=args.output,
            dockerhub=args.dockerhub,
            instance_id=args.instance_id,
            print_hints=args.print_hints,
        )


if __name__ == "__main__":
    main()

# Made with Bob
