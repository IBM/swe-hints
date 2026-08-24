"""
Step 2: Identifier Information

Given a list of identifier names (from step 1), look them up in the augmentation
data and return structured IdentifierInformation records.

Each record is a flat Pydantic model where every taxonomy field is Optional[str].
None means "not available" for this identifier; fields absent from the source data
stay None and are excluded from serialisation by default.

The hierarchy is encoded in LEVEL_FIELDS — a table mapping each TaxonomyNode to
the set of model fields it unlocks (including all ancestor nodes implicitly).
Use with_level(node) to get a projected copy that retains only those fields.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Taxonomy node literal
# ---------------------------------------------------------------------------

TaxonomyNode = Literal[
    # File level
    "File", "FileLoc", "NewFile", "ModifiedFile", "Import",
    # Class level
    "Class", "ClassName", "SuperC", "Generic",
    "LocParClass", "LocCompClass", "WeakSClass", "StrongSClass",
    "FuncPub", "FuncPriv",
    # Cls Function level (method under class)
    "ClsFunc", "ClsFuncName", "ClsSign", "ClsInS", "ClsInT", "ClsInN",
    "ClsOutPT", "ClsOutCT", "ClsLocParFunc", "ClsLocCompFunc",
    "ClsWeakSFunc", "ClsStrongSFunc", "ClsExceptValue", "ClsExceptType",
    "ClsParamDefault",
    # Cls Variable level (variable under class)
    "ClsVar", "ClsVarType", "ClsVarValue",
    "ClsLocParVar", "ClsLocCompVar", "ClsWeakSVar", "ClsStrongSVar",
    # Function level (top-level)
    "Func", "FuncName", "Sign", "InS", "InT", "InN", "OutPT", "OutCT",
    "LocParFunc", "LocCompFunc",
    "WeakSFunc", "StrongSFunc",
    "ExceptValue", "ExceptType", "ParamDefault",
    # Variable level (top-level)
    "Var", "VarType", "VarValue", "LocParVar", "LocCompVar",
    "WeakSVar", "StrongSVar",
    # Special
    "All",
]


# ---------------------------------------------------------------------------
# Level table
# ---------------------------------------------------------------------------
# Each entry lists the CUMULATIVE fields exposed at that node.
#
# Main streams (v2):
#   File -> Class / File -> Func / File -> Var
#   Class -> ClsFunc / Class -> ClsVar
#
# Fields on the model
# -------------------
#   name              — always kept
#   entity_type       — "function" | "class" | "variable"
#   path              — file path
#   is_new_file       — True = new file, False = modified file
#   imports           — import statements in the file
#   superclass        — base class name(s)
#   generics          — generic type parameters
#   public_methods    — public method names (name-only, for FuncPub/FuncPriv)
#   private_methods   — private method names (name-only)
#   partial_location  — file:start_line
#   complete_location — file:start_line-end_line
#   weak_semantics    — short natural-language description (LLM placeholder)
#   strong_semantics  — detailed description (LLM placeholder)
#   signature         — function signature string
#   input_spec        — combined input description
#   input_names       — parameter names only
#   input_types       — parameter types only
#   output_partial_type  — return type (partial)
#   output_complete_type — return type (fully qualified)
#   exception_types   — exception class names that may be raised
#   exception_values  — exception message strings
#   param_defaults    — default values for parameters
#   var_type          — variable type annotation
#   var_value         — variable RHS value
#   cls_methods       — list of rich method dicts (for ClsFunc nodes)
#   cls_variables     — list of rich variable dicts (for ClsVar nodes)

# Helper sets reused across cls_* nodes — these fields come from the
# sub-record dicts inside cls_methods / cls_variables, not top-level fields.
# The projection logic for Cls* nodes works differently: with_level() on a
# class identifier retains cls_methods/cls_variables and then sub-projects
# each sub-record. See with_level() for implementation.
_CLS_FUNC_BASE   = frozenset({"name", "entity_type", "cls_methods"})
_CLS_VAR_BASE    = frozenset({"name", "entity_type", "cls_variables"})

LEVEL_FIELDS: dict[str, frozenset[str]] = {
    # ---- File level ----
    "File":          frozenset({"name", "entity_type"}),
    "FileLoc":       frozenset({"name", "entity_type", "path"}),
    "NewFile":       frozenset({"name", "entity_type", "path", "is_new_file"}),
    "ModifiedFile":  frozenset({"name", "entity_type", "path", "is_new_file"}),
    "Import":        frozenset({"name", "entity_type", "path", "imports"}),

    # ---- Class level ----
    "Class":         frozenset({"name", "entity_type"}),
    "ClassName":     frozenset({"name", "entity_type"}),
    "SuperC":        frozenset({"name", "entity_type", "superclass"}),
    "Generic":       frozenset({"name", "entity_type", "generics"}),
    "FuncPub":       frozenset({"name", "entity_type", "public_methods"}),
    "FuncPriv":      frozenset({"name", "entity_type", "public_methods", "private_methods"}),
    "LocParClass":   frozenset({"name", "entity_type", "path", "partial_location"}),
    "LocCompClass":  frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "WeakSClass":    frozenset({"name", "entity_type", "weak_semantics"}),
    "StrongSClass":  frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),

    # ---- Cls Function level (method under class) ----
    # These nodes expose cls_methods; each sub-record is projected to the
    # corresponding function fields when serialised.
    "ClsFunc":        _CLS_FUNC_BASE,
    "ClsFuncName":    _CLS_FUNC_BASE,
    "ClsSign":        _CLS_FUNC_BASE,
    "ClsInS":         _CLS_FUNC_BASE,
    "ClsInN":         _CLS_FUNC_BASE,
    "ClsInT":         _CLS_FUNC_BASE,
    "ClsOutPT":       _CLS_FUNC_BASE,
    "ClsOutCT":       _CLS_FUNC_BASE,
    "ClsLocParFunc":  _CLS_FUNC_BASE,
    "ClsLocCompFunc": _CLS_FUNC_BASE,
    "ClsWeakSFunc":   _CLS_FUNC_BASE,
    "ClsStrongSFunc": _CLS_FUNC_BASE,
    "ClsExceptType":  _CLS_FUNC_BASE,
    "ClsExceptValue": _CLS_FUNC_BASE,
    "ClsParamDefault":_CLS_FUNC_BASE,

    # ---- Cls Variable level (variable under class) ----
    "ClsVar":         _CLS_VAR_BASE,
    "ClsVarType":     _CLS_VAR_BASE,
    "ClsVarValue":    _CLS_VAR_BASE,
    "ClsLocParVar":   _CLS_VAR_BASE,
    "ClsLocCompVar":  _CLS_VAR_BASE,
    "ClsWeakSVar":    _CLS_VAR_BASE,
    "ClsStrongSVar":  _CLS_VAR_BASE,

    # ---- Function level (top-level) ----
    "Func":          frozenset({"name", "entity_type"}),
    "FuncName":      frozenset({"name", "entity_type"}),
    "Sign":          frozenset({"name", "entity_type", "signature"}),
    "InS":           frozenset({"name", "entity_type", "signature", "input_spec"}),
    "InN":           frozenset({"name", "entity_type", "signature", "input_spec", "input_names"}),
    "InT":           frozenset({"name", "entity_type", "signature", "input_spec", "input_types"}),
    "OutPT":         frozenset({"name", "entity_type", "signature", "output_partial_type"}),
    "OutCT":         frozenset({"name", "entity_type", "signature", "output_partial_type", "output_complete_type"}),
    "LocParFunc":    frozenset({"name", "entity_type", "path", "partial_location"}),
    "LocCompFunc":   frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "WeakSFunc":     frozenset({"name", "entity_type", "weak_semantics"}),
    "StrongSFunc":   frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),
    "ExceptType":    frozenset({"name", "entity_type", "exception_types"}),
    "ExceptValue":   frozenset({"name", "entity_type", "exception_types", "exception_values"}),
    "ParamDefault":  frozenset({"name", "entity_type", "param_defaults"}),

    # ---- Variable level (top-level) ----
    "Var":           frozenset({"name", "entity_type"}),
    "VarType":       frozenset({"name", "entity_type", "var_type"}),
    "VarValue":      frozenset({"name", "entity_type", "var_value"}),
    "LocParVar":     frozenset({"name", "entity_type", "path", "partial_location"}),
    "LocCompVar":    frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "WeakSVar":      frozenset({"name", "entity_type", "weak_semantics"}),
    "StrongSVar":    frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),

    # ---- Special: every field ----
    "All":           frozenset({
        "name", "entity_type",
        "path", "is_new_file", "imports",
        "superclass", "generics", "public_methods", "private_methods",
        "partial_location", "complete_location",
        "weak_semantics", "strong_semantics",
        "signature", "input_spec", "input_names", "input_types",
        "output_partial_type", "output_complete_type",
        "exception_types", "exception_values", "param_defaults",
        "var_type", "var_value",
        "cls_methods", "cls_variables",
    }),
}

# Maps each ClsFunc node to the function-level fields it should expose
# within each sub-record in cls_methods.
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

# Maps each ClsVar node to the variable-level fields it should expose
# within each sub-record in cls_variables.
CLS_VAR_NODE_FIELDS: dict[str, frozenset[str]] = {
    "ClsVar":         frozenset({"name", "entity_type"}),
    "ClsVarType":     frozenset({"name", "entity_type", "var_type"}),
    "ClsVarValue":    frozenset({"name", "entity_type", "var_value"}),
    "ClsLocParVar":   frozenset({"name", "entity_type", "path", "partial_location"}),
    "ClsLocCompVar":  frozenset({"name", "entity_type", "path", "partial_location", "complete_location"}),
    "ClsWeakSVar":    frozenset({"name", "entity_type", "weak_semantics"}),
    "ClsStrongSVar":  frozenset({"name", "entity_type", "weak_semantics", "strong_semantics"}),
}


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class IdentifierInformation(BaseModel):
    """
    All taxonomy fields for a single identifier.  Every field is Optional —
    None means the data is not available.  Serialise with to_dict() which
    drops None fields by default.

    Use with_level(node) to project down to the fields unlocked by a given
    taxonomy node (and all its ancestors).  Use with_nodes(nodes) for a
    union of multiple nodes.
    """

    name:                 Optional[str]       = None
    entity_type:          Optional[str]       = None   # "function"|"class"|"variable"

    # File level
    path:                 Optional[str]       = None
    is_new_file:          Optional[bool]      = None
    imports:              Optional[str]       = None

    # Class level
    superclass:           Optional[str]       = None
    generics:             Optional[str]       = None
    public_methods:       Optional[str]       = None   # name-only, for FuncPub/FuncPriv
    private_methods:      Optional[str]       = None

    # Class rich sub-records (for ClsFunc / ClsVar nodes)
    cls_methods:          Optional[list]      = None   # list of function field dicts
    cls_variables:        Optional[list]      = None   # list of variable field dicts

    # Shared: class + function + variable
    partial_location:     Optional[str]       = None
    complete_location:    Optional[str]       = None
    weak_semantics:       Optional[str]       = None
    strong_semantics:     Optional[str]       = None

    # Variable level
    var_type:             Optional[str]       = None
    var_value:            Optional[str]       = None

    # Function level
    signature:            Optional[str]       = None
    input_spec:           Optional[str]       = None
    input_names:          Optional[str]       = None
    input_types:          Optional[str]       = None
    output_partial_type:  Optional[str]       = None
    output_complete_type: Optional[str]       = None
    exception_types:      Optional[str]       = None
    exception_values:     Optional[str]       = None
    param_defaults:       Optional[str]       = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_augmentation_entry(cls, entry: dict[str, Any]) -> "IdentifierInformation":
        """
        Build from a raw augmentation data dict (from the reference script).

        Key mapping:
          type        -> entity_type
          path        -> path
          description -> weak_semantics  (narrative description = coarse semantics)
          input       -> input_spec
          output      -> output_partial_type
        """
        return cls(
            name=entry.get("name"),
            entity_type=entry.get("type"),
            path=entry.get("path"),
            weak_semantics=entry.get("description") or entry.get("semantics"),
            input_spec=entry.get("input"),
            output_partial_type=entry.get("output"),
        )

    # ------------------------------------------------------------------
    # Taxonomy-aware projection
    # ------------------------------------------------------------------

    def with_level(self, node: TaxonomyNode) -> "IdentifierInformation":
        """
        Return a projected copy retaining only the fields unlocked by `node`.

        For ClsFunc/ClsVar nodes, cls_methods/cls_variables sub-records are
        also projected to only the fields relevant to that node.

        Example
        -------
        rec.with_level("ClsSign")
        # keeps: name, entity_type, cls_methods (each sub-record projected to
        #        {name, entity_type, signature})
        """
        keep = LEVEL_FIELDS.get(node, frozenset({"name"}))
        nulled: dict[str, Any] = {
            f: None for f in self.__class__.model_fields if f not in keep
        }

        # Sub-project cls_methods if a ClsFunc node is active
        if node in CLS_FUNC_NODE_FIELDS and self.cls_methods:
            sub_keep = CLS_FUNC_NODE_FIELDS[node]
            nulled["cls_methods"] = [
                {k: v for k, v in m.items() if k in sub_keep and v is not None}
                for m in self.cls_methods
            ]

        # Sub-project cls_variables if a ClsVar node is active
        if node in CLS_VAR_NODE_FIELDS and self.cls_variables:
            sub_keep = CLS_VAR_NODE_FIELDS[node]
            nulled["cls_variables"] = [
                {k: v for k, v in v_.items() if k in sub_keep and v_ is not None}
                for v_ in self.cls_variables
            ]

        return self.model_copy(update=nulled)

    def with_nodes(self, nodes: list[TaxonomyNode]) -> "IdentifierInformation":
        """
        Return a projected copy retaining the union of fields from multiple nodes.

        Example
        -------
        rec.with_nodes(["WeakSFunc", "Sign"])
        # keeps: name, entity_type, weak_semantics, signature
        """
        keep: set[str] = {"name"}
        for node in nodes:
            keep |= LEVEL_FIELDS.get(node, frozenset())
        nulled = {f: None for f in self.__class__.model_fields if f not in keep}
        return self.model_copy(update=nulled)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, exclude_none: bool = True) -> dict[str, Any]:
        """Serialise to a plain dict, dropping None fields by default."""
        return self.model_dump(exclude_none=exclude_none)


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------

def lookup_identifiers(
    names: list[str],
    augmentations: dict[str, Any],
) -> list[IdentifierInformation]:
    """
    Given identifier names (from IdentifierUsage.get_with()) and an instance's
    augmentations dict, return one IdentifierInformation per matched name.

    Supports both augmentation shapes:
      {"forward": {"data": [...]}, "backward": {"data": [...]}}   <- reference script
      {"data": [...]}                                              <- flat / legacy
    """
    index: dict[str, dict[str, Any]] = {}

    def _index(data: list[dict[str, Any]]) -> None:
        for entry in data:
            if not isinstance(entry, dict):
                continue
            entry_name = entry.get("name")
            if entry_name and entry_name not in index:
                index[entry_name] = entry

    if "data" in augmentations:
        _index(augmentations["data"])
    for key in ("forward", "backward"):
        section = augmentations.get(key, {})
        if isinstance(section, dict):
            _index(section.get("data", []))

    return [
        IdentifierInformation.from_augmentation_entry(index[n])
        for n in names
        if n in index
    ]


# ---------------------------------------------------------------------------
# CLI  (loads step 1 output + augmentation data, applies operator + taxonomy)
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    import json
    from pathlib import Path

    _valid_nodes = list(TaxonomyNode.__args__)  # type: ignore[attr-defined]
    _valid_ops   = ["intersection", "communication", "forward", "backward",
                    "code_only", "test_only", "union"]

    parser = argparse.ArgumentParser(
        description=(
            "Step 2: given step 1 output (identifier sets) and augmentation data,\n"
            "apply a usage operator then project each identifier to a taxonomy level.\n\n"
            "Reads two files:\n"
            "  --usage      : JSONL from step 1 (identifier_usage.py)\n"
            "  --augmented  : JSONL with augmentations field (from reference script)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--usage", "-u",
        type=Path,
        required=True,
        help="Step 1 output JSONL (instance_id, code_read, code_write, test_read, test_write).",
    )
    parser.add_argument(
        "--operator", "-op",
        choices=_valid_ops,
        required=True,
        help="Usage operator to select which identifiers to expose.",
    )
    parser.add_argument(
        "--level", "-l",
        choices=_valid_nodes,
        required=True,
        help="Taxonomy node controlling how much information to reveal per identifier.",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default=None,
        help="Only process this instance (for debugging).",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output JSONL: one record per instance with projected identifier information.",
    )
    parser.add_argument(
        "--dataset", "-ds",
        type=Path,
        default=None,
        help="Original dataset JSONL.  When provided, identifiers already visible in the\n"
             "agent's input are filtered out:\n"
             "  doc_changes present (NoCode/Doc2Feat) → filter against joined doc_changes text.\n"
             "  no doc_changes (SWE-bench Pro etc.)   → filter against problem_statement.",
    )
    parser.add_argument(
        "--drop-uncatalogued",
        action="store_true",
        help="Drop identifiers with no catalogue entry (i.e. no module-level AST data).\n"
             "Recommended with the relaxed identifier_usage_relaxed.py variant to prevent\n"
             "local variables from creating noise in the taxonomy tree.",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Skip instances that raise errors instead of stopping.",
    )
    args = parser.parse_args()

    # Load step 1 output: instance_id -> full record (sets + catalogue)
    from src.identifier_usage import IdentifierUsage  # avoid circular at module level

    usage_index: dict[str, dict] = {}
    with open(args.usage, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                usage_index[rec["instance_id"]] = rec

    # Load dataset index for visibility filter (optional)
    dataset_index: dict[str, dict] = {}
    if args.dataset:
        with open(args.dataset, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    dataset_index[row["instance_id"]] = row

    def _visible_text(iid: str) -> str:
        """Return the text already visible to the agent for this instance."""
        row = dataset_index.get(iid, {})
        if not row:
            return ""
        if "doc_changes" in row:
            # NoCode / Doc2Feat: problem_statement = joined doc_changes metadata
            items = row.get("doc_changes") or []
            return "\n".join(
                str(item.get("metadata", ""))
                for item in items
                if isinstance(item, dict)
            )
        # FEA-Bench: no problem_statement — use pr_title + pr_body from problem_info
        if "problem_info" in row:
            pi = row.get("problem_info") or {}
            return "\n".join(filter(None, [pi.get("pr_title", ""), pi.get("pr_body", "")]))
        # SWE-bench Pro / SWE Re-Bench: use problem_statement
        return row.get("problem_statement", "")

    instance_ids = sorted(usage_index.keys())
    if args.instance_id:
        if args.instance_id not in usage_index:
            parser.error(f"instance_id {args.instance_id!r} not found in {args.usage}")
        instance_ids = [args.instance_id]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_ok = n_err = 0

    with open(args.output, "w", encoding="utf-8") as out_f:
        for iid in instance_ids:
            try:
                usage_data = usage_index[iid]
                if "error" in usage_data:
                    raise ValueError(f"Step 1 error: {usage_data['error']}")

                usage = IdentifierUsage(
                    code_read=usage_data["code_read"],
                    code_write=usage_data["code_write"],
                    test_read=usage_data["test_read"],
                    test_write=usage_data["test_write"],
                    catalogue=usage_data.get("catalogue", {}),
                )
                names = usage.get_with(args.operator)  # type: ignore[arg-type]

                # Filter out names already visible to the agent.
                if args.dataset:
                    visible = _visible_text(iid)
                    if visible:
                        names = [n for n in names if n not in visible]

                catalogue = usage.catalogue

                # Drop names with no catalogue entry (no module-level AST data).
                # Useful with the relaxed extraction variant to prevent local
                # variables from adding structural noise to the taxonomy tree.
                if args.drop_uncatalogued:
                    names = [n for n in names if n in catalogue]

                # Build IdentifierInformation from catalogue.
                # For names not in the catalogue (e.g. local variables that happen
                # to cross the communication boundary), emit a minimal fallback
                # record so the instance is not silently dropped.
                records = []
                for n in names:
                    if n in catalogue:
                        records.append(IdentifierInformation.model_validate(catalogue[n]))
                    else:
                        records.append(IdentifierInformation(name=n, entity_type="variable"))
                projected = [r.with_level(args.level).to_dict() for r in records]  # type: ignore[arg-type]

                record = {
                    "instance_id": iid,
                    "operator": args.operator,
                    "level": args.level,
                    "identifiers": projected,
                }
                n_ok += 1
            except Exception as exc:
                if not args.skip_errors:
                    raise
                print(f"  SKIP {iid}: {exc}")
                record = {"instance_id": iid, "error": repr(exc)}
                n_err += 1

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote {n_ok} records to {args.output}" + (f" ({n_err} errors)" if n_err else ""))


if __name__ == "__main__":
    _cli()

# Made with Bob
