#!/usr/bin/env python3
"""
Generate a mini-SWE-agent instance JSONL file from the Doc2Feat-bench dataset.

Each instance written to the JSONL contains exactly the fields that
mini-extra doc2feat reads:

  - instance_id        unique identifier
  - problem_statement  main task input (the masked doc diff)
  - hints              optional hints string; empty string = no hints shown
  - repo               original repo field (e.g. "psf/requests")
  - base_commit        base commit SHA (informational, kept for eval compatibility)

The ``hints`` field is the single control point.  When it is absent or ""
the agent receives no hints section at all.  Use one of the --hints_* flags
to populate it.

Usage examples
--------------
  # No hints (plain doc diff only)
  python generate_doc2feat_instances.py --hints_none

  # Augmentation hints from the HuggingFace dataset (entity names)
  python generate_doc2feat_instances.py --hints_augmentations

  # Custom hints from an external JSONL (keyed by instance_id)
  python generate_doc2feat_instances.py --hints_file /path/to/my_hints.jsonl --hints_field my_hints_key

Running with mini-extra doc2feat (batch):
  mini-extra doc2feat \\
    -c doc2feat.yaml \\
    --subset /path/to/doc2feat_instances.jsonl \\
    --split train \\
    --output ./results/my_run
"""

import argparse
import json
import os
from pathlib import Path

from datasets import load_dataset


DATASET_MAPPING = {
    "verified": "Doc2Feat-bench/Doc2Feat-bench_Verified",
    "full": "Doc2Feat-bench/Doc2Feat-bench_Full",
}

# The header string Doc2Feat-bench appends to problem_statement when
# augmentations are non-empty.  Everything from "\n\n<HEADER>" onward is
# the baked-in augmentation block that we strip for the "base" variant.
_AUG_HEADER = (
    "If completing this task requires creating new files, classes, fields, "
    "or error messages, you may consider using the following suggested entity names:"
)


def strip_augmentation(problem_statement: str) -> str:
    """Remove the baked-in augmentation block from problem_statement, if present.

    Doc2Feat-bench appends the augmentation section directly to
    problem_statement as '\n\n<header>\n[...]'.  This function returns the
    pure doc diff with that block removed.
    """
    idx = problem_statement.find(_AUG_HEADER)
    if idx == -1:
        return problem_statement
    # Walk back over the preceding blank line(s)
    return problem_statement[:idx].rstrip("\n")


# ---------------------------------------------------------------------------
# Hints strategies
# ---------------------------------------------------------------------------

def hints_none(_instance: dict) -> str:
    """No hints — agent sees only the doc diff."""
    return ""


def hints_augmentations(instance: dict) -> str:
    """Entity-name hints from the ``augmentations`` field of the HF dataset.

    The augmentations field contains a header string and a list of suggested
    entity names (new classes, fields, error messages, …) that help avoid
    false-negative misses due to naming issues.
    """
    aug = instance.get("augmentations") or {}
    data = aug.get("data") or []
    if not data:
        return ""
    header = aug.get("header", "You may consider using the following suggested entity names:")
    lines = [header]
    for entry in data:
        etype = entry.get("type", "")
        name = entry.get("name", "")
        lines.append(f"  - {etype}: {name}" if etype else f"  - {name}")
    return "\n".join(lines)


def make_hints_from_file(hints_index: dict, field: str):
    """Return a hints function that looks up hints from an external JSONL index.

    Args:
        hints_index: dict mapping instance_id -> record dict
        field:       key inside each record that holds the hints string
    """
    def _get(instance: dict) -> str:
        record = hints_index.get(instance["instance_id"], {})
        return record.get(field) or ""
    return _get


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def load_hints_jsonl(path: str) -> dict:
    """Load a JSONL file into a dict keyed by instance_id."""
    index = {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Hints file not found: {path}")
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            index[rec["instance_id"]] = rec
    return index


def generate_instances(
    dataset_path: str,
    split: str,
    hints_fn,
    *,
    clean_problem_statement: bool = True,
) -> list[dict]:
    """Load the Doc2Feat-bench dataset and build mini-SWE-agent instances.

    Args:
        dataset_path:            HuggingFace dataset name or local JSONL path.
        split:                   Dataset split (usually "test").
        hints_fn:                Callable(instance_dict) -> str for hints.
        clean_problem_statement: If True (default), strip the baked-in
                                 augmentation block from problem_statement so
                                 the agent sees a pure doc diff.  Set to False
                                 to preserve the original HF field verbatim.

    Returns:
        List of instance dicts ready to be written to JSONL.
    """
    print(f"Loading dataset {dataset_path!r}, split={split!r} ...")
    if dataset_path.endswith(".jsonl") or dataset_path.endswith(".json"):
        raw = list(load_dataset("json", data_files=dataset_path, split="train"))
    else:
        raw = list(load_dataset(dataset_path, split=split))
    print(f"  {len(raw)} instances loaded.")

    instances = []
    for row in raw:
        ps = row["problem_statement"]
        if clean_problem_statement:
            ps = strip_augmentation(ps)
        instance = {
            "instance_id": row["instance_id"],
            "problem_statement": ps,
            "hints": hints_fn(row),
            "repo": row.get("repo", ""),
            "base_commit": row.get("base_commit", ""),
        }
        instances.append(instance)

    return instances


def write_jsonl(instances: list[dict], output_path: str) -> None:
    """Write instances to a JSONL file (one JSON object per line)."""
    d = os.path.dirname(output_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(output_path, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
    print(f"✓ Wrote {len(instances)} instances to {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a mini-SWE-agent JSONL from Doc2Feat-bench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- Dataset selection ---
    parser.add_argument(
        "--subset",
        default="verified",
        choices=list(DATASET_MAPPING) + ["full"],
        help="Doc2Feat-bench subset to use: 'verified' (default) or 'full'",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Dataset split (default: test)",
    )

    # --- Output ---
    parser.add_argument(
        "--output_path",
        default="doc2feat_instances.jsonl",
        help="Output JSONL file path (default: doc2feat_instances.jsonl)",
    )

    # --- Hints strategy (mutually exclusive) ---
    hints_group = parser.add_mutually_exclusive_group(required=True)
    parser.add_argument(
        "--no_clean",
        action="store_true",
        default=False,
        help="Keep the baked-in augmentation text in problem_statement verbatim. "
             "By default it is stripped so the agent sees a pure doc diff.",
    )

    hints_group.add_argument(
        "--hints_none",
        action="store_true",
        help="No hints — agent sees only the doc diff.",
    )
    hints_group.add_argument(
        "--hints_augmentations",
        action="store_true",
        help="Populate hints from the 'augmentations' field in the HF dataset "
             "(suggested entity names to reduce false negatives).",
    )
    hints_group.add_argument(
        "--hints_file",
        metavar="PATH",
        default=None,
        help="Path to an external JSONL (keyed by instance_id) that provides hints. "
             "Use --hints_field to specify which key to read (default: 'hints').",
    )

    parser.add_argument(
        "--hints_field",
        default="hints",
        metavar="KEY",
        help="Key inside each record of --hints_file to use as the hints string "
             "(default: 'hints'). Ignored unless --hints_file is set.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve dataset path
    dataset_path = DATASET_MAPPING.get(args.subset, args.subset)

    # Resolve hints function
    if args.hints_none:
        hints_fn = hints_none
        strategy = "none"
    elif args.hints_augmentations:
        hints_fn = hints_augmentations
        strategy = "augmentations"
    else:  # --hints_file
        index = load_hints_jsonl(args.hints_file)
        hints_fn = make_hints_from_file(index, args.hints_field)
        strategy = f"file:{args.hints_file} field:{args.hints_field}"

    print(f"Hints strategy: {strategy}")

    instances = generate_instances(
        dataset_path,
        args.split,
        hints_fn,
        clean_problem_statement=not args.no_clean,
    )
    write_jsonl(instances, args.output_path)

    print()
    print("Run with mini-extra doc2feat:")
    print(f"  mini-extra doc2feat \\")
    print(f"    -c doc2feat.yaml \\")
    print(f"    --subset {args.output_path} \\")
    print(f"    --split train \\")
    print(f"    --output ./results/my_run")


if __name__ == "__main__":
    main()
