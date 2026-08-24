"""
Sample FEA-Bench instances for the v3 LOO experiment, maximising subtree coverage.

Strategy (greedy set-cover):
  Priority order for rare subtrees: Var, ClsVar, ClsFunc, Class, Func, File
  Each round picks the instance that activates the most currently under-covered
  roots, breaking ties by the priority order of the roots it uniquely covers.
  Sampling continues until the target count is reached.

  Additionally, instances with cls_variables (ClsVar) and variable identifiers
  (Var) are given a bonus weight so the sample contains as many of those as
  possible while still covering all roots.

Usage
-----
    python helper_code/sample_feabench_loo.py \\
        --input  results/feabench/hints_comm_all.jsonl \\
        --output results/feabench/sample_loo_60.jsonl \\
        --n      60

    # Dry-run: print coverage stats without writing:
    python helper_code/sample_feabench_loo.py \\
        --input  results/feabench/hints_comm_all.jsonl \\
        --output results/feabench/sample_loo_60.jsonl \\
        --n      60 \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    available_rows,
    subtree_rows,
)

# Priority order: rarest roots first (based on empirical FEA-Bench frequencies)
ROOT_PRIORITY: list[str] = ["Var", "ClsVar", "ClsFunc", "Class", "Func", "File"]
ROOT_PRIORITY_RANK: dict[str, int] = {r: i for i, r in enumerate(ROOT_PRIORITY)}


def score(instance: dict, root_coverage: Counter) -> tuple:
    """
    Greedy score for an instance:
      Primary  : number of roots that are still under-covered (<= min_coverage)
                 that this instance activates  (higher = better)
      Secondary: sum of (1 / (current_coverage[root] + 1)) for all roots it
                 activates  — rewards covering rarer roots
      Tie-break: bonus for having Var or ClsVar active (rare subtrees)
    """
    active = available_rows(instance)
    active_roots = [r for r in LOO_SUBGRAPH_ROOTS if active & subtree_rows(r)]

    if not active_roots:
        return (0, 0.0, 0)

    min_cov = min(root_coverage[r] for r in LOO_SUBGRAPH_ROOTS)
    under_covered = sum(
        1 for r in active_roots if root_coverage[r] <= min_cov
    )
    rarity_sum = sum(1.0 / (root_coverage[r] + 1) for r in active_roots)

    # Bonus: +2 for Var, +1 for ClsVar/ClsFunc
    bonus = 0
    if active & subtree_rows("Var"):
        bonus += 2
    if active & subtree_rows("ClsVar"):
        bonus += 1
    if active & subtree_rows("ClsFunc"):
        bonus += 1

    return (under_covered, rarity_sum, bonus)


def sample(records: list[dict], n: int) -> list[dict]:
    """Greedy coverage sampling."""
    nonempty = [r for r in records if r.get("identifiers")]
    if n > len(nonempty):
        print(f"Warning: requested {n} but only {len(nonempty)} non-empty instances available.")
        n = len(nonempty)

    root_coverage: Counter = Counter({r: 0 for r in LOO_SUBGRAPH_ROOTS})
    remaining = list(nonempty)
    selected: list[dict] = []

    while len(selected) < n and remaining:
        # Pick the best candidate
        best = max(remaining, key=lambda inst: score(inst, root_coverage))
        selected.append(best)
        remaining.remove(best)

        # Update coverage
        active = available_rows(best)
        for root in LOO_SUBGRAPH_ROOTS:
            if active & subtree_rows(root):
                root_coverage[root] += 1

    return selected


def print_coverage(selected: list[dict]) -> None:
    root_coverage: Counter = Counter()
    entity_types: Counter = Counter()

    for inst in selected:
        active = available_rows(inst)
        for root in LOO_SUBGRAPH_ROOTS:
            if active & subtree_rows(root):
                root_coverage[root] += 1
        for ident in inst.get("identifiers", []):
            entity_types[ident.get("entity_type", "unknown")] += 1

    print(f"\nSampled {len(selected)} instances")
    print("\nSubtree root coverage (instances with each root active):")
    for root in ROOT_PRIORITY:
        bar = "█" * root_coverage[root]
        print(f"  {root:12s}: {root_coverage[root]:3d}  {bar}")

    print("\nIdentifier entity_type distribution across sample:")
    for et, cnt in entity_types.most_common():
        print(f"  {et:12s}: {cnt}")

    # How many instances have all 6 roots?
    all6 = sum(
        1 for inst in selected
        if all(available_rows(inst) & subtree_rows(r) for r in LOO_SUBGRAPH_ROOTS)
    )
    print(f"\nInstances with all 6 roots active: {all6}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample FEA-Bench instances for v3 LOO, maximising subtree coverage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Input hints JSONL (e.g. results/feabench/hints_comm_all.jsonl).",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output JSONL with sampled instances.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=60,
        help="Number of instances to sample (default: 60).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print coverage stats without writing output.",
    )
    args = parser.parse_args()

    records: list[dict] = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"Loaded {len(records)} records ({sum(1 for r in records if r.get('identifiers'))} non-empty).")

    selected = sample(records, args.n)
    print_coverage(selected)

    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            for inst in selected:
                f.write(json.dumps(inst, ensure_ascii=False) + "\n")
        print(f"\nWrote {len(selected)} instances to {args.output}")
    else:
        print("\n(dry-run — nothing written)")


if __name__ == "__main__":
    main()

# Made with Bob
