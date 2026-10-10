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
# entity_kind carries the Java declared kind (interface/enum/record/annotation/
# constructor) alongside entity_type, which stays in the four-value vocabulary the
# downstream _ENTITY_GATE recognises.  Python never sets it, so exclude_none
# serialisation keeps every Python projection byte-identical.
_KIND = frozenset({"entity_kind"})

# Name Only: the identifier names and nothing else (no type, path, signature or text).
_NAMEONLY_FIELDS  = frozenset({"name"})
_NOCODE_FIELDS    = frozenset({"name", "entity_type"}) | _KIND

_FEA_BRIEF_FIELDS = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
    "weak_semantics",
}) | _KIND

# Ours: nocode + structural location and interface, and deliberately NO semantics.
# Everything here is an interface fact recoverable from a declaration line - where the
# entity lives and how it is called - with no natural-language description of behaviour.
# See README for why weak_/strong_semantics are excluded rather than merely optional.
# The DECLARATION projection: everything readable off a declaration line — what it
# is called, what kind of thing it is, which file declares it (and whether that file
# is new), and how it is called.  Classes are included in full: entity_type "class"
# plus each method's signature via _CLS_METHOD_OURS.  What it does NOT carry is the
# inheritance clause (superclass/generics) and the line range — see the commented-out
# variants below, which measured identically and were retired.
_DECLARATION_FIELDS = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
})

# RETIRED — ours_v2 added superclass + generics.  Measured 12/68, identical to the
# declaration projection (p=1.000; 2-for-2 on the 11 instances whose prompt it changed).
# _OURS_V2_FIELDS   = _DECLARATION_FIELDS | frozenset({"superclass", "generics"})

# RETIRED — ours_v3 added partial_/complete_location (Tier-2 "solution shape": it
# exceeds SWE-bench Pro's own published `interface`, which carries Path but no line
# range).  Measured 10/68; net zero on the 39 instances whose prompt it changed.
# _OURS_V3_FIELDS   = _OURS_V2_FIELDS | frozenset({"partial_location", "complete_location"})

# DECLARATION v2 — the definition from the alternate project_enriched.py:
#   top        {name, entity_type, path, is_new_file, signature}
#   cls_method {name, entity_type, signature}
#   cls_var    {name, entity_type}
# NOTE: as specified this is field-for-field identical to `declaration` (= the `ours`
# run, 12/68).  It is kept as its own constant so a v2 that actually differs is a
# one-line edit here; until then declaration_v2 output is byte-identical to ours.
_DECLARATION_V2_FIELDS = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
})
_CLS_METHOD_DECLARATION_V2 = frozenset({"name", "entity_type", "signature"})
_CLS_VAR_DECLARATION_V2    = frozenset({"name", "entity_type"})

# Name + behaviour, nothing else - not even entity_type.  This sits one step BELOW the
# nocode base (which is name + entity_type), so nocode -> semantics_only is not a pure
# addition: it trades the type label for the descriptions.  Compare it against the
# name_only condition rather than against nocode.
_SEMANTICS_ONLY_FIELDS = frozenset({
    "name",
    "weak_semantics", "strong_semantics",
})

_SWE_PRO_FIELDS   = frozenset({
    "name", "entity_type",
    "path", "is_new_file",
    "signature",
    "weak_semantics",
    "strong_semantics",
}) | _KIND

# Sub-record fields for cls_methods entries (functions inside a class)
_CLS_METHOD_NOCODE    = frozenset({"name", "entity_type"})
_CLS_METHOD_OURS      = frozenset({"name", "entity_type", "signature"})
_CLS_METHOD_FEA_BRIEF = frozenset({"name", "entity_type", "signature", "weak_semantics"})
_CLS_METHOD_SWE_PRO   = frozenset({"name", "entity_type", "signature", "weak_semantics", "strong_semantics"})

# Sub-record fields for cls_variables entries (class-level variables)
_CLS_VAR_NOCODE    = frozenset({"name", "entity_type"})
_CLS_VAR_OURS      = frozenset({"name", "entity_type"})
_CLS_VAR_FEA_BRIEF = frozenset({"name", "entity_type", "weak_semantics"})
_CLS_VAR_SWE_PRO   = frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"})

PROJECTIONS: dict[str, dict] = {
    "nameonly": {
        "top":        _NAMEONLY_FIELDS,
        "cls_method": frozenset({"name"}),
        "cls_var":    frozenset({"name"}),
        "flat":       True,   # a flat list of names; no nesting
    },
    "nocode": {
        "top":        _NOCODE_FIELDS,
        "cls_method": _CLS_METHOD_NOCODE,
        "cls_var":    _CLS_VAR_NOCODE,
        "flat":       True,   # nocode is a flat {name, entity_type} list; no nesting
    },
    "declaration": {
        "top":        _DECLARATION_FIELDS,
        "cls_method": _CLS_METHOD_OURS,
        "cls_var":    _CLS_VAR_OURS,
    },
    "declaration_v2": {
        "top":        _DECLARATION_V2_FIELDS,
        "cls_method": _CLS_METHOD_DECLARATION_V2,
        "cls_var":    _CLS_VAR_DECLARATION_V2,
    },
    # "ours_v2": {
    #     "top":        _OURS_V2_FIELDS,
    #     "cls_method": _CLS_METHOD_OURS,
    #     "cls_var":    _CLS_VAR_OURS,
    # },
    # "ours_v3": {
    #     "top":        _OURS_V3_FIELDS,
    #     "cls_method": _CLS_METHOD_OURS,
    #     "cls_var":    _CLS_VAR_OURS,
    # },
    "semantics_only": {
        "top":        _SEMANTICS_ONLY_FIELDS,
        "cls_method": frozenset({"name", "weak_semantics", "strong_semantics"}),
        "cls_var":    frozenset({"name", "weak_semantics", "strong_semantics"}),
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
