#!/usr/bin/env python3
"""
Taxonomy projections for enriched identifier hints.

Reads a hints_communication_all_nonempty_enriched.jsonl (output of
src.enrich_semantics) and writes a projected JSONL where each identifier
is reduced to the fields appropriate for the target benchmark.

Three projections
-----------------

nocode
    {name, entity_type}
    Mirrors the original nocode.py augmentation format: just the name nudge.
    No structural detail — the agent must derive implementation from docs.

fea_brief
    {name, entity_type, path, is_new_file, signature, weak_semantics}
    Mirrors the fea_brief.py new_components schema:
      name          ← identifier name
      entity_type   ← Type
      path          ← Path  (groups by file, as in new_components)
      is_new_file   ← whether the file is new (handle_new_file path)
      signature     ← the def line (= Input+Output in one precise string)
      weak_semantics← Description / doc  (short one-liner)

swe_pro
    {name, entity_type, path, is_new_file, signature, weak_semantics,
     strong_semantics}
    Mirrors the swe_pro interface schema + adds strong_semantics:
      name          ← Name
      entity_type   ← Type
      path          ← Path
      is_new_file   ← (not in interface; additive)
      signature     ← Input + Output collapsed to one precise string
      weak_semantics← Description
      strong_semantics ← (not in interface; additive — complements requirements)

For class identifiers, cls_methods and cls_variables sub-records are also
projected to the same field subset (minus path/is_new_file which are
inherited from the parent class identifier).

Usage (run from repo root):

    python identity_selection/project_enriched.py \\
        --input   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \\
        --output  results/swe_pro_proj/projected_nocode.jsonl \\
        --projection nocode

    python identity_selection/project_enriched.py \\
        --input   results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl \\
        --output  results/feabench_proj/projected_fea_brief.jsonl \\
        --projection fea_brief

    python identity_selection/project_enriched.py \\
        --input   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \\
        --output  results/swe_pro_proj/projected_swe_pro.jsonl \\
        --projection swe_pro
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Field sets per projection
# ---------------------------------------------------------------------------

# Top-level identifier fields kept by each projection
_NOCODE_FIELDS    = frozenset({"name", "entity_type"})

_FEA_BRIEF_FIELDS = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
    "weak_semantics",
})

_SWE_PRO_FIELDS   = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
    "weak_semantics",
    "strong_semantics",
})

# Sub-record fields for cls_methods entries (functions inside a class)
_CLS_METHOD_NOCODE    = frozenset({"name", "entity_type"})
_CLS_METHOD_FEA_BRIEF = frozenset({"name", "entity_type", "signature", "weak_semantics"})
_CLS_METHOD_SWE_PRO   = frozenset({"name", "entity_type", "signature", "weak_semantics", "strong_semantics"})

# Sub-record fields for cls_variables entries (class-level variables)
_CLS_VAR_NOCODE    = frozenset({"name", "entity_type"})
_CLS_VAR_FEA_BRIEF = frozenset({"name", "entity_type", "weak_semantics"})
_CLS_VAR_SWE_PRO   = frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"})

PROJECTIONS: dict[str, dict] = {
    "nocode": {
        "top":        _NOCODE_FIELDS,
        "cls_method": _CLS_METHOD_NOCODE,
        "cls_var":    _CLS_VAR_NOCODE,
        "flat":       True,   # nocode is a flat {name, entity_type} list; no nesting
    },
    "fea_brief": {
        "top":        _FEA_BRIEF_FIELDS,
        "cls_method": _CLS_METHOD_FEA_BRIEF,
        "cls_var":    _CLS_VAR_FEA_BRIEF,
    },
    "swe_pro": {
        "top":        _SWE_PRO_FIELDS,
        "cls_method": _CLS_METHOD_SWE_PRO,
        "cls_var":    _CLS_VAR_SWE_PRO,
    },
}

# ---------------------------------------------------------------------------
# Projection logic
# ---------------------------------------------------------------------------

def _project_subrecords(items: list[dict], keep: frozenset[str]) -> list[dict]:
    """Project a list of sub-record dicts (cls_methods / cls_variables)."""
    return [
        {k: v for k, v in item.items() if k in keep and v is not None}
        for item in items
    ]


def project_identifier(ident: dict, proj: dict) -> dict:
    """
    Project a single identifier dict to the fields defined by `proj`.

    For class identifiers, cls_methods and cls_variables sub-records are also
    projected to their respective sub-field sets — unless the projection is
    nocode, which is a flat {name, entity_type} format with no nesting.
    """
    top_keep    = proj["top"]
    method_keep = proj["cls_method"]
    var_keep    = proj["cls_var"]
    flat        = proj.get("flat", False)

    result = {k: v for k, v in ident.items() if k in top_keep and v is not None}

    if flat:
        return result

    # Project cls_methods sub-records if present and projection exposes them
    if ident.get("cls_methods") and ident.get("entity_type") == "class":
        projected_methods = _project_subrecords(ident["cls_methods"], method_keep)
        if projected_methods:
            result["cls_methods"] = projected_methods

    # Project cls_variables sub-records if present and projection exposes them
    if ident.get("cls_variables") and ident.get("entity_type") == "class":
        projected_vars = _project_subrecords(ident["cls_variables"], var_keep)
        if projected_vars:
            result["cls_variables"] = projected_vars

    return result


def project_record(record: dict, proj: dict) -> dict:
    """Project one instance record (all its identifiers)."""
    identifiers = [
        project_identifier(ident, proj)
        for ident in record.get("identifiers", [])
    ]
    return {
        "instance_id": record["instance_id"],
        "identifiers": identifiers,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Project enriched identifier hints to nocode / fea_brief / swe_pro views."
    )
    ap.add_argument(
        "--input", "-i", type=Path, required=True,
        help="Input JSONL: hints_communication_all_nonempty_enriched.jsonl",
    )
    ap.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Output JSONL with projected identifiers.",
    )
    ap.add_argument(
        "--projection", "-p",
        choices=list(PROJECTIONS),
        required=True,
        help="Projection to apply: nocode | fea_brief | swe_pro",
    )
    ap.add_argument(
        "--instance-id", type=str, default=None,
        help="Process a single instance_id (for debugging).",
    )
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")

    proj = PROJECTIONS[args.projection]
    args.output.parent.mkdir(parents=True, exist_ok=True)

    n_in = n_out = 0
    with args.input.open(encoding="utf-8") as fh_in, \
         args.output.open("w", encoding="utf-8") as fh_out:
        for line in fh_in:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if args.instance_id and record.get("instance_id") != args.instance_id:
                continue
            n_in += 1
            projected = project_record(record, proj)
            fh_out.write(json.dumps(projected, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"[{args.projection}]  {n_in} records read → {n_out} written → {args.output}")


if __name__ == "__main__":
    main()
