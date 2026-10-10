#!/usr/bin/env python3
"""
Generate mini-SWE-agent instance JSONL files from identity_projection outputs.

Reads a projected hints JSONL (from project_enriched.py) and a source benchmark
JSONL (for problem_statement, repo, base_commit, image_name / dockerhub_tag),
joins them on instance_id, renders the identifiers into a hints string, and
writes a mini-SWE-agent ready JSONL.

Output per instance:
    {
      "instance_id":       "...",
      "repo":              "owner/name",
      "problem_statement": "...",
      "hints":             "<rendered hints string>",
      "base_commit":       "...",
      "image_name":        "..."   (swebench_pro / swerebench only)
    }

Hints rendering per projection
-------------------------------

nocode
    Flat name list — same format as the existing mini_swe files:
        - **entity_type:** `name`

fea_brief
    Per identifier:
        ### `name` (entity_type) — path
        > weak_semantics
        Signature: `signature`
        [cls_methods listed as sub-bullets]

swe_pro
    Per identifier:
        ### `name` (entity_type) — path
        > weak_semantics
        Signature: `signature`
        strong_semantics paragraph
        [cls_methods listed as sub-bullets with their weak/strong semantics]

Supported benchmarks
--------------------
  swebench_pro   — source has dockerhub_tag; image built as
                   <dockerhub_username>/sweap-images:<tag>
  swerebench     — source has image_name directly

doc2feat is handled by generate_doc2feat_instances.py — not covered here.

Usage (run from repo root):
    source .venv/bin/activate

    # nocode — swebench_pro
    python identity_projection/generate_instances.py \\
        --hints      identity_projection/results_projection/nocode_proj/swe_pro_nocode_proj.jsonl \\
        --source     identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \\
        --benchmark  swebench_pro \\
        --projection nocode \\
        --dockerhub_username jefzda \\
        --output     identity_projection/mini_swe/nocode/swe_pro_nocode.jsonl

    # fea_brief — swerebench
    python identity_projection/generate_instances.py \\
        --hints      identity_projection/results_projection/fea_brief_proj/swerebench_fea_brief_proj.jsonl \\
        --source     identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \\
        --benchmark  swerebench \\
        --projection fea_brief \\
        --output     identity_projection/mini_swe/fea_brief/swerebench_fea_brief.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Hints rendering
# ---------------------------------------------------------------------------

def _render_nocode(identifiers: list[dict]) -> str:
    """Flat name list — mirrors existing mini_swe hints format."""
    if not identifiers:
        return ""
    header = (
        "If completing this task requires creating new files, classes, fields, "
        "or error messages, you may consider using the following suggested entity names:"
    )
    lines = [header, ""]
    for ident in identifiers:
        et   = ident.get("entity_type", "")
        name = ident.get("name", "")
        if et and name:
            lines.append(f"- **{et}:** `{name}`")
        elif name:
            lines.append(f"- `{name}`")
    return "\n".join(lines)


def _render_nameonly(identifiers: list[dict]) -> str:
    """Bare names only, de-duplicated. Same header as nocode so the arms differ
    only in what is revealed per identifier, not in framing."""
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


def _render_ours(identifiers: list[dict]) -> str:
    """The DECLARATION projection: name, entity_type, path [new file], signature.

    Base/Type parameters/Location lines below are gated on presence and never fire
    for `declaration` — they are retained so the retired ours_v2/ours_v3 variants
    render correctly if they are ever uncommented.

    Same block shape as fea_brief minus the `> weak_semantics` line, so the two
    differ by exactly one variable when compared.
    """
    if not identifiers:
        return ""
    blocks: list[str] = []
    for ident in identifiers:
        et     = ident.get("entity_type", "")
        name   = ident.get("name", "")
        path   = ident.get("path", "")
        sig    = ident.get("signature", "")
        is_new = ident.get("is_new_file")

        header = f"### `{name}`"
        kind = ident.get("entity_kind") or et      # Java: interface/enum/record; Python: None
        if kind:
            header += f" ({kind})"
        if path:
            new_tag = " [new file]" if is_new else ""
            header += f" — `{path}`{new_tag}"
        lines = [header]

        if sig:
            lines.append(f"Signature: `{sig}`")
        # ours_v2 only — absent from the projected record under ours_v1, so the
        # two projections share this renderer and differ purely by field set.
        if ident.get("superclass"):
            lines.append(f"Base: `{ident['superclass']}`")
        if ident.get("generics"):
            lines.append(f"Type parameters: `{ident['generics']}`")
        # ours_v3 only.  complete_location subsumes partial_location, so show one line.
        loc = ident.get("complete_location") or ident.get("partial_location")
        if loc:
            lines.append(f"Location: `{loc}`")

        for m in ident.get("cls_methods") or []:
            mname = m.get("name", "")
            msig  = m.get("signature", "")
            ml = f"- `{mname}`"
            if msig:
                ml += f": `{msig}`"
            lines.append(ml)

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _render_semantics_only(identifiers: list[dict]) -> str:
    """Per-identifier block: name plus weak + strong semantics.

    Deliberately carries no entity_type, path, signature, or location - the bare
    name is the only structural fact exposed.
    """
    if not identifiers:
        return ""
    blocks: list[str] = []
    for ident in identifiers:
        name   = ident.get("name", "")
        weak   = ident.get("weak_semantics", "")
        strong = ident.get("strong_semantics", "")

        lines = [f"### `{name}`"]
        if weak:
            lines.append(f"> {weak}")
        if strong:
            lines.append(strong)

        for m in ident.get("cls_methods") or []:
            ml = f"- `{m.get('name','')}`"
            if m.get("weak_semantics"):
                ml += f": {m['weak_semantics']}"
            lines.append(ml)

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _render_fea_brief(identifiers: list[dict]) -> str:
    """Per-identifier block: name, path, signature, weak_semantics, cls_methods."""
    if not identifiers:
        return ""
    blocks: list[str] = []
    for ident in identifiers:
        et       = ident.get("entity_type", "")
        name     = ident.get("name", "")
        path     = ident.get("path", "")
        sig      = ident.get("signature", "")
        weak     = ident.get("weak_semantics", "")
        is_new   = ident.get("is_new_file")

        # Header line
        header = f"### `{name}`"
        kind = ident.get("entity_kind") or et      # Java: interface/enum/record; Python: None
        if kind:
            header += f" ({kind})"
        if path:
            new_tag = " [new file]" if is_new else ""
            header += f" — `{path}`{new_tag}"
        lines = [header]

        if weak:
            lines.append(f"> {weak}")
        if sig:
            lines.append(f"Signature: `{sig}`")

        # cls_methods sub-bullets
        for m in ident.get("cls_methods") or []:
            mname = m.get("name", "")
            msig  = m.get("signature", "")
            mweak = m.get("weak_semantics", "")
            ml = f"- `{mname}`"
            if msig:
                ml += f": `{msig}`"
            lines.append(ml)
            if mweak:
                lines.append(f"  > {mweak}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _render_swe_pro(identifiers: list[dict]) -> str:
    """Per-identifier block: name, path, signature, weak_semantics,
    strong_semantics, cls_methods (with weak + strong)."""
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
        kind = ident.get("entity_kind") or et      # Java: interface/enum/record; Python: None
        if kind:
            header += f" ({kind})"
        if path:
            new_tag = " [new file]" if is_new else ""
            header += f" — `{path}`{new_tag}"
        lines = [header]

        if weak:
            lines.append(f"> {weak}")
        if sig:
            lines.append(f"Signature: `{sig}`")
        if strong:
            lines.append(strong)

        # cls_methods sub-bullets
        for m in ident.get("cls_methods") or []:
            mname   = m.get("name", "")
            msig    = m.get("signature", "")
            mweak   = m.get("weak_semantics", "")
            mstrong = m.get("strong_semantics", "")
            ml = f"- `{mname}`"
            if msig:
                ml += f": `{msig}`"
            lines.append(ml)
            if mweak:
                lines.append(f"  > {mweak}")
            if mstrong:
                lines.append(f"  {mstrong}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


RENDERERS = {
    "nameonly":  _render_nameonly,
    "nocode":    _render_nocode,
    "declaration":     _render_ours,
    "declaration_v2":  _render_ours,   # same block shape; field set differs only if _DECLARATION_V2_FIELDS does
    # "ours_v2":       _render_ours,   # retired — see project_enriched.py
    # "ours_v3":       _render_ours,   # retired — see project_enriched.py
    "semantics_only":  _render_semantics_only,
    "fea_brief": _render_fea_brief,
    "swe_pro":   _render_swe_pro,
}


# ---------------------------------------------------------------------------
# Image name helpers
# ---------------------------------------------------------------------------

def _build_image_multi_swe_bench(base_row: dict, _unused: str = "") -> str:
    """mswebench/{org}_m_{repo}:pr-{number} — mirrors multi_swe_bench/harness/image.py."""
    repo = base_row.get("repo", "")
    org, _, name = repo.partition("/")
    number = base_row.get("number")
    if not (org and name and number):
        return ""
    return f"mswebench/{org}_m_{name}:pr-{number}".lower()


def _build_image_swebench_pro(base_row: dict, dockerhub_username: str) -> str:
    """Build image URI from dockerhub_tag — mirrors get_dockerhub_image_uri()."""
    tag = base_row.get("dockerhub_tag", "")
    return f"{dockerhub_username}/sweap-images:{tag}" if tag else ""


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
    benchmark: str,
    projection: str,
    dockerhub_username: str,
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

        ps = source_row.get("problem_statement", "")

        if benchmark == "swebench_pro":
            image_name = _build_image_swebench_pro(source_row, dockerhub_username)
        elif benchmark == "multi_swe_bench":
            image_name = _build_image_multi_swe_bench(source_row)
        else:  # swerebench
            image_name = source_row.get("image_name", "")

        inst: dict = {
            "instance_id":       iid,
            "repo":              source_row.get("repo", ""),
            "problem_statement": ps,
            "hints":             hints_str,
            "base_commit":       source_row.get("base_commit", ""),
            "image_name":        image_name,
        }

        instances.append(inst)

    return instances


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate mini-SWE-agent instances from identity_projection outputs."
    )
    ap.add_argument(
        "--hints", "-H", type=Path, required=True,
        help="Projected hints JSONL from project_enriched.py ({instance_id, identifiers}).",
    )
    ap.add_argument(
        "--source", "-s", type=Path, required=True,
        help="Raw benchmark JSONL (problem_statement, repo, base_commit, image_name / dockerhub_tag).",
    )
    ap.add_argument(
        "--benchmark", "-b",
        choices=["swebench_pro", "swerebench", "multi_swe_bench"],
        required=True,
        help="Benchmark type: swebench_pro or swerebench. "
             "doc2feat is handled by generate_doc2feat_instances.py.",
    )
    ap.add_argument(
        "--projection", "-p",
        choices=list(RENDERERS),
        required=True,
        help="Projection used to produce the hints file: nocode | fea_brief | swe_pro",
    )
    ap.add_argument(
        "--dockerhub_username", "-d",
        default="",
        help="Docker Hub username — required for --benchmark swebench_pro.",
    )
    ap.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Output JSONL for mini-SWE-agent.",
    )
    args = ap.parse_args()

    if args.benchmark == "swebench_pro" and not args.dockerhub_username:
        ap.error("--dockerhub_username is required for --benchmark swebench_pro")
    if not args.hints.exists():
        sys.exit(f"Hints file not found: {args.hints}")
    if not args.source.exists():
        sys.exit(f"Source file not found: {args.source}")

    print(f"benchmark={args.benchmark}  projection={args.projection}")
    instances = generate(
        args.hints,
        args.source,
        args.benchmark,
        args.projection,
        args.dockerhub_username,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")

    print(f"✓ Wrote {len(instances)} instances → {args.output}")


if __name__ == "__main__":
    main()
