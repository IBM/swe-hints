#!/usr/bin/env python3
"""
Generate mini-SWE-agent instance JSONL files for Doc2Feat-bench from
identity_projection outputs.

Reads a projected hints JSONL (from project_enriched.py) and the raw
doc2feat source JSONL (for problem_statement, repo, base_commit), joins
them on instance_id, renders the identifiers into a hints string, and
writes a mini-SWE-agent ready JSONL.

Output per instance:
    {
      "instance_id":       "...",
      "repo":              "owner/name",
      "problem_statement": "...",   (baked-in augmentation stripped)
      "hints":             "<rendered hints string>",
      "base_commit":       "..."
    }

Hints rendering per projection
-------------------------------

nocode
    Flat name list:
        If completing this task requires creating new files, classes, fields,
        or error messages, you may consider using the following suggested
        entity names:

        - **entity_type:** `name`

fea_brief
    Per-identifier block:
        ### `name` (entity_type) — `path`
        > weak_semantics
        Signature: `signature`

swe_pro
    Same as fea_brief plus strong_semantics paragraph.

Usage (run from repo root):
    source .venv/bin/activate

    # nocode
    python identity_projection/generate_doc2feat_instances.py \\
        --hints      identity_projection/results_projection/nocode_proj/doc2feat_nocode_proj.jsonl \\
        --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \\
        --projection nocode \\
        --output     identity_projection/mini_swe/nocode/doc2feat_nocode.jsonl

    # fea_brief
    python identity_projection/generate_doc2feat_instances.py \\
        --hints      identity_projection/results_projection/fea_brief_proj/doc2feat_fea_brief_proj.jsonl \\
        --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \\
        --projection fea_brief \\
        --output     identity_projection/mini_swe/fea_brief/doc2feat_fea_brief.jsonl

    # swe_pro
    python identity_projection/generate_doc2feat_instances.py \\
        --hints      identity_projection/results_projection/swe_pro_proj/doc2feat_swe_pro_proj.jsonl \\
        --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \\
        --projection swe_pro \\
        --output     identity_projection/mini_swe/swe_pro/doc2feat_swe_pro.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Strip baked-in augmentation from doc2feat problem_statement
# ---------------------------------------------------------------------------

_AUG_HEADER = (
    "If completing this task requires creating new files, classes, fields, "
    "or error messages, you may consider using the following suggested entity names:"
)


def _strip_augmentation(ps: str) -> str:
    idx = ps.find(_AUG_HEADER)
    if idx == -1:
        return ps
    return ps[:idx].rstrip("\n")


# ---------------------------------------------------------------------------
# Hints renderers
# ---------------------------------------------------------------------------

def _render_nameonly(identifiers: list[dict]) -> str:
    """Bare names only, de-duplicated (mirrors generate_instances.py)."""
    if not identifiers:
        return ""
    header = (
        "If completing this task requires creating new files, classes, fields, "
        "or error messages, you may consider using the following suggested entity names:"
    )
    lines, seen = [header, ""], set()
    for ident in identifiers:
        name = ident.get("name", "")
        if name and name not in seen:
            seen.add(name)
            lines.append(f"- `{name}`")
    return "\n".join(lines)


def _render_nocode(identifiers: list[dict]) -> str:
    if not identifiers:
        return ""
    lines = [_AUG_HEADER, ""]
    for ident in identifiers:
        et   = ident.get("entity_type", "")
        name = ident.get("name", "")
        if et and name:
            lines.append(f"- **{et}:** `{name}`")
        elif name:
            lines.append(f"- `{name}`")
    return "\n".join(lines)


def _render_fea_brief(identifiers: list[dict]) -> str:
    if not identifiers:
        return ""
    blocks: list[str] = []
    for ident in identifiers:
        et     = ident.get("entity_type", "")
        name   = ident.get("name", "")
        path   = ident.get("path", "")
        sig    = ident.get("signature", "")
        weak   = ident.get("weak_semantics", "")
        is_new = ident.get("is_new_file")
        header = f"### `{name}`"
        if et:
            header += f" ({et})"
        if path:
            header += f" — `{path}`" + (" [new file]" if is_new else "")
        lines = [header]
        if weak:
            lines.append(f"> {weak}")
        if sig:
            lines.append(f"Signature: `{sig}`")
        for m in ident.get("cls_methods") or []:
            ml = f"- `{m.get('name', '')}`"
            if m.get("signature"):
                ml += f": `{m['signature']}`"
            lines.append(ml)
            if m.get("weak_semantics"):
                lines.append(f"  > {m['weak_semantics']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_swe_pro(identifiers: list[dict]) -> str:
    if not identifiers:
        return ""
    blocks: list[str] = []
    for ident in identifiers:
        et     = ident.get("entity_type", "")
        name   = ident.get("name", "")
        path   = ident.get("path", "")
        sig    = ident.get("signature", "")
        weak   = ident.get("weak_semantics", "")
        strong = ident.get("strong_semantics", "")
        is_new = ident.get("is_new_file")
        header = f"### `{name}`"
        if et:
            header += f" ({et})"
        if path:
            header += f" — `{path}`" + (" [new file]" if is_new else "")
        lines = [header]
        if weak:
            lines.append(f"> {weak}")
        if sig:
            lines.append(f"Signature: `{sig}`")
        if strong:
            lines.append(strong)
        for m in ident.get("cls_methods") or []:
            ml = f"- `{m.get('name', '')}`"
            if m.get("signature"):
                ml += f": `{m['signature']}`"
            lines.append(ml)
            if m.get("weak_semantics"):
                lines.append(f"  > {m['weak_semantics']}")
            if m.get("strong_semantics"):
                lines.append(f"  {m['strong_semantics']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_declaration(identifiers: list[dict]) -> str:
    """Structural declaration per identifier: name, type, path, new-file flag, signature.
    Same layout as fea_brief but without the semantic description."""
    if not identifiers:
        return ""
    blocks = []
    for ident in identifiers:
        et, name = ident.get("entity_type", ""), ident.get("name", "")
        path, sig = ident.get("path", ""), ident.get("signature", "")
        header = f"### `{name}`"
        if et:
            header += f" ({et})"
        if path:
            header += f" — `{path}`" + (" [new file]" if ident.get("is_new_file") else "")
        lines = [header]
        if sig:
            lines.append(f"Signature: `{sig}`")
        for m in ident.get("cls_methods") or []:
            ml = f"- `{m.get('name','')}`"
            if m.get("signature"):
                ml += f": `{m['signature']}`"
            lines.append(ml)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


RENDERERS = {
    "nameonly":  _render_nameonly,
    "declaration": _render_declaration,
    "nocode":    _render_nocode,
    "fea_brief": _render_fea_brief,
    "swe_pro":   _render_swe_pro,
}


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                index[row["instance_id"]] = row
    return index


def generate(
    hints_path: Path,
    source_path: Path,
    projection: str,
) -> list[dict]:
    hints_index  = _load_jsonl(hints_path)
    source_index = _load_jsonl(source_path)

    common = sorted(set(hints_index) & set(source_index))
    print(f"  hints={len(hints_index)}  source={len(source_index)}  common={len(common)}")
    if not common:
        print("  WARNING: no overlapping instance_ids — check file paths.")
        return []

    render = RENDERERS[projection]
    instances: list[dict] = []

    for iid in common:
        hints_row  = hints_index[iid]
        source_row = source_index[iid]

        identifiers = hints_row.get("identifiers", [])
        hints_str   = render(identifiers)

        ps = _strip_augmentation(source_row.get("problem_statement", ""))

        instances.append({
            "instance_id":       iid,
            "repo":              source_row.get("repo", ""),
            "problem_statement": ps,
            "hints":             hints_str,
            "base_commit":       source_row.get("base_commit", ""),
        })

    return instances


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate doc2feat mini-SWE-agent instances from identity_projection outputs."
    )
    ap.add_argument(
        "--hints", "-H", type=Path, required=True,
        help="Projected hints JSONL from project_enriched.py ({instance_id, identifiers}).",
    )
    ap.add_argument(
        "--source", "-s", type=Path, required=True,
        help="Raw doc2feat source JSONL (problem_statement, repo, base_commit).",
    )
    ap.add_argument(
        "--projection", "-p",
        choices=list(RENDERERS),
        required=True,
        help="Projection: nocode | fea_brief | swe_pro",
    )
    ap.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Output JSONL for mini-SWE-agent.",
    )
    args = ap.parse_args()

    if not args.hints.exists():
        sys.exit(f"Hints file not found: {args.hints}")
    if not args.source.exists():
        sys.exit(f"Source file not found: {args.source}")

    print(f"projection={args.projection}")
    instances = generate(args.hints, args.source, args.projection)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")

    print(f"✓ Wrote {len(instances)} instances → {args.output}")


if __name__ == "__main__":
    main()
