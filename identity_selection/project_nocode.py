#!/usr/bin/env python3
"""
NoCode projection — apply a uniform NoCode view to union_defuse_nocode/ files.

Reads each instance from a union_defuse_nocode/ JSONL and emits a projected
JSONL that exposes only what the NoCode projection shows: a flat list of
``{type, name}`` entity entries, regardless of which selector produced the file.

Handles three source shapes:

  augmentations — flat (nocode):
        {"header": "...", "data": [{type, name}, ...]}

  augmentations — directional (defuse2 / defuse2_relaxed):
        {"forward":  {"header": "...", "data": [...]},
         "backward": {"header": "...", "data": [...]}}

  new_components (fea_brief):
        {"path/to/file.py": [{"type": "...", "name": "...",
                               "lines": [...], "signature": "...", "doc": "..."}, ...], ...}
        → flattened to [{type, name}], stripping lines/signature/doc.

Output field ``hints`` (NoCode projection):
    {
      "header": "<NoCode augmentation header>",
      "data":   [{"type": "...", "name": "..."}, ...]
    }

The output JSONL keeps only the fields needed for downstream evaluation:
    instance_id, repo, hints

Usage (run from repo root):

    # fea_brief_sel
    python identity_selection/project_nocode.py \\
        --input  identity_selection/results_selection/fea_brief_sel/union_defuse_nocode \\
        --output identity_selection/results_selection/fea_brief_sel/projected_nocode

    # defuse2_sel
    python identity_selection/project_nocode.py \\
        --input  identity_selection/results_selection/defuse2_sel/union_defuse_nocode \\
        --output identity_selection/results_selection/defuse2_sel/projected_nocode

    # nocode_sel
    python identity_selection/project_nocode.py \\
        --input  identity_selection/results_selection/nocode_sel/union_defuse_nocode \\
        --output identity_selection/results_selection/nocode_sel/projected_nocode
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NOCODE_HEADER = (
    "If completing this task requires creating new files, classes, fields, "
    "or error messages, you may consider using the following suggested entity names:"
)


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------

def _extract_from_augmentations(augmentations: dict) -> list[dict]:
    """Return the flat [{type, name}] list from any augmentations shape."""
    if not augmentations:
        return []

    # Flat shape: {header, data}
    if "data" in augmentations:
        return [{"type": e["type"], "name": e["name"]} for e in augmentations["data"]]

    # Directional shape: {forward: {data}, backward: {data}}
    result: list[dict] = []
    for direction in ("forward", "backward"):
        sub = augmentations.get(direction, {})
        result.extend(
            {"type": e["type"], "name": e["name"]} for e in sub.get("data", [])
        )
    return result


def _extract_from_new_components(new_components: dict) -> list[dict]:
    """
    Flatten new_components {file_path: [{type, name, lines, signature, doc}]} → [{type, name}].
    Each file path key is also emitted as {"type": "file", "name": path}.
    """
    if not new_components:
        return []
    result: list[dict] = []
    for file_path, entries in new_components.items():
        result.append({"type": "file", "name": file_path})
        for e in entries:
            result.append({"type": e["type"], "name": e["name"]})
    return result


def project_instance(entry: dict) -> dict:
    """Return the projected output for a single instance."""
    if "new_components" in entry:
        data = _extract_from_new_components(entry.get("new_components") or {})
    else:
        data = _extract_from_augmentations(entry.get("augmentations") or {})

    return {
        "instance_id": entry["instance_id"],
        "repo":        entry["repo"],
        "hints": {
            "header": NOCODE_HEADER,
            "data":   data,
        },
    }


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def project_file(src: Path, dst: Path) -> None:
    """Project one JSONL file and write to dst."""
    rows_in  = 0
    rows_out = 0

    with src.open() as fh_in, dst.open("w") as fh_out:
        for line in fh_in:
            line = line.strip()
            if not line:
                continue
            rows_in += 1
            entry = json.loads(line)
            projected = project_instance(entry)
            fh_out.write(json.dumps(projected) + "\n")
            rows_out += 1

    print(f"  {src.name}: {rows_in} → {rows_out} rows  →  {dst}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="NoCode projection: extract entity hints from union_defuse_nocode/ files."
    )
    ap.add_argument(
        "--input", "-i", type=Path, required=True,
        help="Directory containing union_defuse_nocode/ JSONL files.",
    )
    ap.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Output directory for projected JSONL files (created if missing).",
    )
    args = ap.parse_args()

    if not args.input.is_dir():
        sys.exit(f"Input directory not found: {args.input}")

    jsonl_files = sorted(args.input.glob("*.jsonl"))
    if not jsonl_files:
        sys.exit(f"No .jsonl files found in: {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Projecting {len(jsonl_files)} file(s)")
    print(f"  from : {args.input}")
    print(f"  to   : {args.output}")
    print()

    for src in jsonl_files:
        dst = args.output / src.name
        project_file(src, dst)

    print("\nDone.")


if __name__ == "__main__":
    main()
