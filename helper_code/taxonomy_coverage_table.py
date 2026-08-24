"""
Taxonomy node coverage table.

For each taxonomy node, reports:
  - which fields it exposes
  - how many identifiers have at least one non-trivial exposed field (coverage)
  - how many instances have at least one such identifier
  - for Cls* nodes: how many sub-records are non-empty

Rows = taxonomy nodes (in DAG order).
Columns = fields_exposed | #idents_covered | %idents | #instances_covered | %instances

Usage:
    python helper_code/taxonomy_coverage_table.py \
        --input results/swe_pro/hints_communication_all_nonempty.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Inline taxonomy definition (mirrors identifier_information.py)
# ---------------------------------------------------------------------------

# Canonical node order (DAG top-to-bottom)
NODES_ORDERED = [
    # File level
    ("File",          "File",                     frozenset({"name", "entity_type"})),
    ("FileLoc",       "File Location",             frozenset({"name", "entity_type", "path"})),
    ("NewFile",       "New File",                  frozenset({"name", "entity_type", "path", "is_new_file"})),
    ("ModifiedFile",  "Modified File",             frozenset({"name", "entity_type", "path", "is_new_file"})),
    ("Import",        "Import Statement",          frozenset({"name", "entity_type", "path", "imports"})),
    # Class level
    ("Class",         "Class",                     frozenset({"name", "entity_type"})),
    ("ClassName",     "Class Name",                frozenset({"name", "entity_type"})),
    ("SuperC",        "Super Class",               frozenset({"name", "entity_type", "superclass"})),
    ("Generic",       "Generic",                   frozenset({"name", "entity_type", "generics"})),
    ("FuncPub",       "Public Functions",          frozenset({"name", "entity_type", "public_methods"})),
    ("FuncPriv",      "Private Functions",         frozenset({"name", "entity_type", "public_methods", "private_methods"})),
    ("LocParClass",   "Cls Partial Location",      frozenset({"name", "entity_type", "path", "partial_location"})),
    ("LocCompClass",  "Cls Complete Location",     frozenset({"name", "entity_type", "path", "partial_location", "complete_location"})),
    ("WeakSClass",    "Cls Weak Semantics",        frozenset({"name", "entity_type", "weak_semantics"})),
    ("StrongSClass",  "Cls Strong Semantics",      frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"})),
    # Cls Function level
    ("ClsFunc",       "Cls Function",              frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsFuncName",   "Cls Function Name",         frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsSign",       "Cls Func Signature",        frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsInS",        "Cls Func Input Spec",       frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsInT",        "Cls Func Input Type",       frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsInN",        "Cls Func Input Name",       frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsOutPT",      "Cls Func Output PT",        frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsOutCT",      "Cls Func Output CT",        frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsLocParFunc", "Cls Func Partial Loc",      frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsLocCompFunc","Cls Func Complete Loc",     frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsWeakSFunc",  "Cls Func Weak Sem",         frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsStrongSFunc","Cls Func Strong Sem",       frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsExceptType", "Cls Func Except Type",      frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsExceptValue","Cls Func Except Value",     frozenset({"name", "entity_type", "cls_methods"})),
    ("ClsParamDefault","Cls Func Param Default",   frozenset({"name", "entity_type", "cls_methods"})),
    # Cls Variable level
    ("ClsVar",        "Cls Variable",              frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsVarType",    "Cls Variable Type",         frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsVarValue",   "Cls Variable Value",        frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsLocParVar",  "Cls Var Partial Loc",       frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsLocCompVar", "Cls Var Complete Loc",      frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsWeakSVar",   "Cls Var Weak Sem",          frozenset({"name", "entity_type", "cls_variables"})),
    ("ClsStrongSVar", "Cls Var Strong Sem",        frozenset({"name", "entity_type", "cls_variables"})),
    # Function level (top-level)
    ("Func",          "Function",                  frozenset({"name", "entity_type"})),
    ("FuncName",      "Function Name",             frozenset({"name", "entity_type"})),
    ("Sign",          "Signature",                 frozenset({"name", "entity_type", "signature"})),
    ("InS",           "Input Spec",                frozenset({"name", "entity_type", "signature", "input_spec"})),
    ("InT",           "Input Type",                frozenset({"name", "entity_type", "signature", "input_spec", "input_types"})),
    ("InN",           "Input Name",                frozenset({"name", "entity_type", "signature", "input_spec", "input_names"})),
    ("OutPT",         "Output Partial Type",       frozenset({"name", "entity_type", "signature", "output_partial_type"})),
    ("OutCT",         "Output Complete Type",      frozenset({"name", "entity_type", "signature", "output_partial_type", "output_complete_type"})),
    ("LocParFunc",    "Func Partial Location",     frozenset({"name", "entity_type", "path", "partial_location"})),
    ("LocCompFunc",   "Func Complete Location",    frozenset({"name", "entity_type", "path", "partial_location", "complete_location"})),
    ("WeakSFunc",     "Func Weak Semantics",       frozenset({"name", "entity_type", "weak_semantics"})),
    ("StrongSFunc",   "Func Strong Semantics",     frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"})),
    ("ExceptType",    "Exception Type",            frozenset({"name", "entity_type", "exception_types"})),
    ("ExceptValue",   "Exception Value",           frozenset({"name", "entity_type", "exception_types", "exception_values"})),
    ("ParamDefault",  "Parameter Default",         frozenset({"name", "entity_type", "param_defaults"})),
    # Variable level (top-level)
    ("Var",           "Variable",                  frozenset({"name", "entity_type"})),
    ("VarType",       "Variable Type",             frozenset({"name", "entity_type", "var_type"})),
    ("VarValue",      "Variable Value",            frozenset({"name", "entity_type", "var_value"})),
    ("LocParVar",     "Var Partial Location",      frozenset({"name", "entity_type", "path", "partial_location"})),
    ("LocCompVar",    "Var Complete Location",     frozenset({"name", "entity_type", "path", "partial_location", "complete_location"})),
    ("WeakSVar",      "Var Weak Semantics",        frozenset({"name", "entity_type", "weak_semantics"})),
    ("StrongSVar",    "Var Strong Semantics",      frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"})),
]

# Sub-field projection for Cls* nodes
CLS_FUNC_NODE_FIELDS: dict[str, frozenset[str]] = {
    "ClsFunc":        frozenset({"name", "entity_type"}),
    "ClsFuncName":    frozenset({"name", "entity_type"}),
    "ClsSign":        frozenset({"name", "entity_type", "signature"}),
    "ClsInS":         frozenset({"name", "entity_type", "signature", "input_spec"}),
    "ClsInN":         frozenset({"name", "entity_type", "signature", "input_spec", "input_names"}),
    "ClsInT":         frozenset({"name", "entity_type", "signature", "input_spec", "input_types"}),
    "ClsOutPT":       frozenset({"name", "entity_type", "signature", "output_partial_type"}),
    "ClsOutCT":       frozenset({"name", "entity_type", "signature", "output_partial_type", "output_complete_type"}),
    "ClsLocParFunc":  frozenset({"name", "entity_type", "path", "partial_location"}),
    "ClsLocCompFunc": frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "ClsWeakSFunc":   frozenset({"name", "entity_type", "weak_semantics"}),
    "ClsStrongSFunc": frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),
    "ClsExceptType":  frozenset({"name", "entity_type", "exception_types"}),
    "ClsExceptValue": frozenset({"name", "entity_type", "exception_types", "exception_values"}),
    "ClsParamDefault":frozenset({"name", "entity_type", "param_defaults"}),
}

CLS_VAR_NODE_FIELDS: dict[str, frozenset[str]] = {
    "ClsVar":         frozenset({"name", "entity_type"}),
    "ClsVarType":     frozenset({"name", "entity_type", "var_type"}),
    "ClsVarValue":    frozenset({"name", "entity_type", "var_value"}),
    "ClsLocParVar":   frozenset({"name", "entity_type", "path", "partial_location"}),
    "ClsLocCompVar":  frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "ClsWeakSVar":    frozenset({"name", "entity_type", "weak_semantics"}),
    "ClsStrongSVar":  frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),
}

# Exclude always-present fields from "meaningful" coverage check
TRIVIAL_FIELDS = {"name", "entity_type"}


def _has(v) -> bool:
    return v is not None and v != [] and v != ""


def _meaningful_fields(fields: frozenset[str]) -> frozenset[str]:
    """Fields beyond just name+entity_type."""
    return fields - TRIVIAL_FIELDS


def _sub_record_coverage(sub_records: list[dict], sub_fields: frozenset[str]) -> int:
    """Count sub-records that have at least one meaningful field from sub_fields."""
    meaningful = sub_fields - TRIVIAL_FIELDS
    if not meaningful:
        return len(sub_records)  # name+entity_type always present
    return sum(
        1 for r in sub_records
        if any(_has(r.get(f)) for f in meaningful)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Taxonomy node coverage table over hint records."
    )
    parser.add_argument("--input", "-i", type=Path, required=True)
    args = parser.parse_args()

    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    n_instances = len(records)
    all_identifiers = [i for r in records for i in r.get("identifiers", [])]
    n_identifiers = len(all_identifiers)

    # Build per-instance identifier lists for instance-level counting
    instance_identifiers = [r.get("identifiers", []) for r in records]

    print(f"Input   : {args.input}")
    print(f"Instances: {n_instances}   Identifiers: {n_identifiers}")
    print()

    # Column widths
    cw_node  = 18
    cw_label = 26
    cw_fields = 46
    cw_n  = 7
    cw_pct = 6

    header = (
        f"{'Node':<{cw_node}}  "
        f"{'Label':<{cw_label}}  "
        f"{'Exposed fields (beyond name+type)':<{cw_fields}}  "
        f"{'#ident':>{cw_n}}  "
        f"{'%ident':>{cw_pct}}  "
        f"{'#inst':>{cw_n}}  "
        f"{'%inst':>{cw_pct}}  "
        f"{'#sub':>{cw_n}}"
    )
    sep = "-" * len(header)

    print(header)
    print(sep)

    last_section = ""
    sections = {
        "File": "── File level ──",
        "Class": "── Class level ──",
        "ClsFunc": "── Cls Function level ──",
        "ClsVar": "── Cls Variable level ──",
        "Func": "── Function level (top-level) ──",
        "Var": "── Variable level (top-level) ──",
    }

    for node_id, label, top_fields in NODES_ORDERED:
        # Print section divider
        if node_id in sections and node_id != last_section:
            last_section = node_id
            print(f"\n  {sections[node_id]}")

        meaningful = _meaningful_fields(top_fields)
        exposed_str = ", ".join(sorted(meaningful)) if meaningful else "(name, entity_type only)"

        # For Cls* nodes, the coverage is on class identifiers that have
        # non-empty sub-records after projection.
        if node_id in CLS_FUNC_NODE_FIELDS:
            sub_fields = CLS_FUNC_NODE_FIELDS[node_id]
            sub_meaningful = sub_fields - TRIVIAL_FIELDS
            # Count class identifiers with at least one method sub-record
            # that has a meaningful field
            n_ident_covered = sum(
                1 for ident in all_identifiers
                if isinstance(ident.get("cls_methods"), list)
                and _sub_record_coverage(ident["cls_methods"], sub_fields) > 0
            )
            n_inst_covered = sum(
                1 for inst_idents in instance_identifiers
                if any(
                    isinstance(i.get("cls_methods"), list)
                    and _sub_record_coverage(i["cls_methods"], sub_fields) > 0
                    for i in inst_idents
                )
            )
            # Count total sub-records covered
            n_sub = sum(
                _sub_record_coverage(i["cls_methods"], sub_fields)
                for i in all_identifiers
                if isinstance(i.get("cls_methods"), list)
            )
            exposed_str = ", ".join(sorted(sub_meaningful)) if sub_meaningful else "(name, entity_type only)"

        elif node_id in CLS_VAR_NODE_FIELDS:
            sub_fields = CLS_VAR_NODE_FIELDS[node_id]
            sub_meaningful = sub_fields - TRIVIAL_FIELDS
            n_ident_covered = sum(
                1 for ident in all_identifiers
                if isinstance(ident.get("cls_variables"), list)
                and _sub_record_coverage(ident["cls_variables"], sub_fields) > 0
            )
            n_inst_covered = sum(
                1 for inst_idents in instance_identifiers
                if any(
                    isinstance(i.get("cls_variables"), list)
                    and _sub_record_coverage(i["cls_variables"], sub_fields) > 0
                    for i in inst_idents
                )
            )
            n_sub = sum(
                _sub_record_coverage(i["cls_variables"], sub_fields)
                for i in all_identifiers
                if isinstance(i.get("cls_variables"), list)
            )
            exposed_str = ", ".join(sorted(sub_meaningful)) if sub_meaningful else "(name, entity_type only)"

        else:
            # Standard top-level field check
            if not meaningful:
                # name+entity_type always present → all identifiers covered
                n_ident_covered = n_identifiers
                n_inst_covered  = n_instances
            else:
                n_ident_covered = sum(
                    1 for ident in all_identifiers
                    if any(_has(ident.get(f)) for f in meaningful)
                )
                n_inst_covered = sum(
                    1 for inst_idents in instance_identifiers
                    if any(
                        any(_has(i.get(f)) for f in meaningful)
                        for i in inst_idents
                    )
                )
            n_sub = 0

        pct_ident = 100 * n_ident_covered / n_identifiers if n_identifiers else 0
        pct_inst  = 100 * n_inst_covered  / n_instances  if n_instances  else 0

        sub_str = str(n_sub) if n_sub else "-"

        # Truncate exposed_str to fit
        if len(exposed_str) > cw_fields:
            exposed_str = exposed_str[:cw_fields - 3] + "..."

        print(
            f"{node_id:<{cw_node}}  "
            f"{label:<{cw_label}}  "
            f"{exposed_str:<{cw_fields}}  "
            f"{n_ident_covered:>{cw_n}}  "
            f"{pct_ident:>{cw_pct}.1f}%  "
            f"{n_inst_covered:>{cw_n}}  "
            f"{pct_inst:>{cw_pct}.1f}%  "
            f"{sub_str:>{cw_n}}"
        )

    print()


if __name__ == "__main__":
    main()

# Made with Bob
