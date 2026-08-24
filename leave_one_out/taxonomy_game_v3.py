"""
taxonomy_game_v3.py
===================
Leave-one-out version of the taxonomy game — v3 of the taxonomy.

Changes from v2
---------------
  - File is no longer a parent of Class.  File, Class, Func, and Var are all
    top-level peers (same depth in the DAG).
  - The LOO experiment only leaves out **subgraph roots**:
        File, Class, ClsFunc, ClsVar, Func, Var
    Each LOO coalition = Full minus all rows in one root's subtree.
  - Two additional special coalitions are always included:
        None  — no hints at all (empty coalition)
        Full  — all active rows

v3 taxonomy relations (A -> B means B is more revealing / specific than A):
  File -> FileLoc -> NewFile, ModifiedFile
  File -> Import
  File -> Func -> FuncName, Sign, LocParFunc, WeakSFunc, ExceptType, ParamDefault
  File -> Var  -> VarType, VarValue, LocParVar, WeakSVar
  Class -> ClassName, SuperC, Generic, FuncPub -> FuncPriv
  Class -> LocParClass -> LocCompClass
  Class -> WeakSClass  -> StrongSClass
  Class -> ClsFunc -> ClsFuncName, ClsSign, ClsLocParFunc, ClsWeakSFunc,
                      ClsExceptType -> ClsExceptValue, ClsParamDefault
           ClsSign -> ClsInS -> ClsInT, ClsInN
                   -> ClsOutPT -> ClsOutCT
           ClsLocParFunc -> ClsLocCompFunc
           ClsWeakSFunc  -> ClsStrongSFunc
  Class -> ClsVar -> ClsVarType, ClsVarValue, ClsLocParVar, ClsWeakSVar
           ClsLocParVar -> ClsLocCompVar
           ClsWeakSVar  -> ClsStrongSVar

NOTE: Func and Var are children of File (not of Class).  Class is a peer of
      File — there is no edge between File and Class.

LOO subgraph roots and their subtrees
--------------------------------------
  File    : File, FileLoc, NewFile, ModifiedFile, Import
  Class   : Class, ClassName, SuperC, Generic, FuncPub, FuncPriv,
            LocParClass, LocCompClass, WeakSClass, StrongSClass
  ClsFunc : all ClsFunc* rows  (15 rows)
  ClsVar  : all ClsVar* rows   (7 rows)
  Func    : Func, FuncName, Sign, InS, InT, InN, OutPT, OutCT,
            LocParFunc, LocCompFunc, WeakSFunc, StrongSFunc,
            ExceptType, ExceptValue, ParamDefault
  Var     : Var, VarType, VarValue, LocParVar, LocCompVar,
            WeakSVar, StrongSVar

Public API (identical to v1/v2)
---------------------------------
  ROW_SPECS          : dict[str, RowSpec]
  ROW_NAMES          : tuple[str, ...]
  ROW_INDEX          : dict[str, int]
  PRECEDENCE_EDGES   : frozenset[tuple[str, str]]
  LOO_SUBGRAPH_ROOTS : tuple[str, ...]   — the 6 roots used for LOO

  available_rows(instance)          -> frozenset[str]
  subtree_rows(root)                -> frozenset[str]
  project_rows(instance, coalition) -> dict
  render_hint(instance, coalition)  -> str
  coalition_id(coalition)           -> str
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# RowSpec
# ---------------------------------------------------------------------------

Scope = Literal["file", "class", "cls_function", "cls_variable", "function", "variable"]


@dataclass(frozen=True)
class RowSpec:
    name:       str
    scope:      Scope
    fields:     tuple[str, ...]       # incremental fields this row reveals
    parents:    tuple[str, ...] = ()  # direct parent row names (for precedence)
    structural: bool = False          # True = identity-only row, no field payload


# ---------------------------------------------------------------------------
# Row registry
# v3 key change: Class has NO parent (peer of File).
#                Func and Var are still children of File.
# ---------------------------------------------------------------------------

_ROWS: list[RowSpec] = [
    # ── File rows ─────────────────────────────────────────────────────────────
    RowSpec("File",           "file",         (),                          structural=True),
    RowSpec("FileLoc",        "file",         ("path",),                   ("File",)),
    RowSpec("NewFile",        "file",         ("is_new_file",),            ("FileLoc",)),
    RowSpec("ModifiedFile",   "file",         ("is_new_file",),            ("FileLoc",)),
    RowSpec("Import",         "file",         ("imports",),                ("File",)),

    # ── Class rows (no parent — Class is a top-level peer of File) ────────────
    RowSpec("Class",          "class",        (),                          structural=True),
    RowSpec("ClassName",      "class",        (),                          structural=False, parents=("Class",)),
    RowSpec("SuperC",         "class",        ("superclass",),             ("Class",)),
    RowSpec("Generic",        "class",        ("generics",),               ("Class",)),
    RowSpec("FuncPub",        "class",        ("public_methods",),         ("Class",)),
    RowSpec("FuncPriv",       "class",        ("private_methods",),        ("FuncPub",)),
    RowSpec("LocParClass",    "class",        ("partial_location",),       ("Class",)),
    RowSpec("LocCompClass",   "class",        ("complete_location",),      ("LocParClass",)),
    RowSpec("WeakSClass",     "class",        ("weak_semantics",),         ("Class",)),
    RowSpec("StrongSClass",   "class",        ("strong_semantics",),       ("WeakSClass",)),

    # ── Cls Function rows (methods nested under a class) ──────────────────────
    RowSpec("ClsFunc",        "cls_function", (),                          structural=True,  parents=("Class",)),
    RowSpec("ClsFuncName",    "cls_function", (),                          structural=False, parents=("ClsFunc",)),
    RowSpec("ClsSign",        "cls_function", ("signature",),              ("ClsFunc",)),
    RowSpec("ClsInS",         "cls_function", ("input_spec",),             ("ClsSign",)),
    RowSpec("ClsInT",         "cls_function", ("input_types",),            ("ClsInS",)),
    RowSpec("ClsInN",         "cls_function", ("input_names",),            ("ClsInS",)),
    RowSpec("ClsOutPT",       "cls_function", ("output_partial_type",),    ("ClsSign",)),
    RowSpec("ClsOutCT",       "cls_function", ("output_complete_type",),   ("ClsOutPT",)),
    RowSpec("ClsLocParFunc",  "cls_function", ("partial_location",),       ("ClsFunc",)),
    RowSpec("ClsLocCompFunc", "cls_function", ("complete_location",),      ("ClsLocParFunc",)),
    RowSpec("ClsWeakSFunc",   "cls_function", ("weak_semantics",),         ("ClsFunc",)),
    RowSpec("ClsStrongSFunc", "cls_function", ("strong_semantics",),       ("ClsWeakSFunc",)),
    RowSpec("ClsExceptType",  "cls_function", ("exception_types",),        ("ClsFunc",)),
    RowSpec("ClsExceptValue", "cls_function", ("exception_values",),       ("ClsExceptType",)),
    RowSpec("ClsParamDefault","cls_function", ("param_defaults",),         ("ClsFunc",)),

    # ── Cls Variable rows (class-level variables nested under a class) ────────
    RowSpec("ClsVar",         "cls_variable", (),                          structural=True,  parents=("Class",)),
    RowSpec("ClsVarType",     "cls_variable", ("var_type",),               ("ClsVar",)),
    RowSpec("ClsVarValue",    "cls_variable", ("var_value",),              ("ClsVar",)),
    RowSpec("ClsLocParVar",   "cls_variable", ("partial_location",),       ("ClsVar",)),
    RowSpec("ClsLocCompVar",  "cls_variable", ("complete_location",),      ("ClsLocParVar",)),
    RowSpec("ClsWeakSVar",    "cls_variable", ("weak_semantics",),         ("ClsVar",)),
    RowSpec("ClsStrongSVar",  "cls_variable", ("strong_semantics",),       ("ClsWeakSVar",)),

    # ── Function rows (top-level, under File) ─────────────────────────────────
    RowSpec("Func",           "function",     (),                          structural=True,  parents=("File",)),
    RowSpec("FuncName",       "function",     (),                          structural=False, parents=("Func",)),
    RowSpec("Sign",           "function",     ("signature",),              ("Func",)),
    RowSpec("InS",            "function",     ("input_spec",),             ("Sign",)),
    RowSpec("InN",            "function",     ("input_names",),            ("InS",)),
    RowSpec("InT",            "function",     ("input_types",),            ("InS",)),
    RowSpec("OutPT",          "function",     ("output_partial_type",),    ("Sign",)),
    RowSpec("OutCT",          "function",     ("output_complete_type",),   ("OutPT",)),
    RowSpec("LocParFunc",     "function",     ("partial_location",),       ("Func",)),
    RowSpec("LocCompFunc",    "function",     ("complete_location",),      ("LocParFunc",)),
    RowSpec("WeakSFunc",      "function",     ("weak_semantics",),         ("Func",)),
    RowSpec("StrongSFunc",    "function",     ("strong_semantics",),       ("WeakSFunc",)),
    RowSpec("ExceptType",     "function",     ("exception_types",),        ("Func",)),
    RowSpec("ExceptValue",    "function",     ("exception_values",),       ("ExceptType",)),
    RowSpec("ParamDefault",   "function",     ("param_defaults",),         ("Func",)),

    # ── Variable rows (top-level, under File) ─────────────────────────────────
    RowSpec("Var",            "variable",     (),                          structural=True,  parents=("File",)),
    RowSpec("VarType",        "variable",     ("var_type",),               ("Var",)),
    RowSpec("VarValue",       "variable",     ("var_value",),              ("Var",)),
    RowSpec("LocParVar",      "variable",     ("partial_location",),       ("Var",)),
    RowSpec("LocCompVar",     "variable",     ("complete_location",),      ("LocParVar",)),
    RowSpec("WeakSVar",       "variable",     ("weak_semantics",),         ("Var",)),
    RowSpec("StrongSVar",     "variable",     ("strong_semantics",),       ("WeakSVar",)),
]

ROW_SPECS:  dict[str, RowSpec] = {r.name: r for r in _ROWS}
ROW_NAMES:  tuple[str, ...]    = tuple(r.name for r in _ROWS)
ROW_INDEX:  dict[str, int]     = {n: i for i, n in enumerate(ROW_NAMES)}

PRECEDENCE_EDGES: frozenset[tuple[str, str]] = frozenset(
    (parent, row.name)
    for row in _ROWS
    for parent in row.parents
)

# Rows scoped to cls_function / cls_variable sub-records
_CLS_FUNC_ROWS: frozenset[str] = frozenset(r.name for r in _ROWS if r.scope == "cls_function")
_CLS_VAR_ROWS:  frozenset[str] = frozenset(r.name for r in _ROWS if r.scope == "cls_variable")


# ---------------------------------------------------------------------------
# LOO subgraph roots and their subtrees
# ---------------------------------------------------------------------------

# Each root and the complete set of rows that belong to its subtree.
# Leaving out a root removes ALL rows in its subtree from the coalition.
_SUBTREE: dict[str, frozenset[str]] = {
    "File": frozenset(r.name for r in _ROWS if r.scope == "file"),
    "Class": frozenset(
        r.name for r in _ROWS
        if r.scope == "class" and r.name not in _CLS_FUNC_ROWS and r.name not in _CLS_VAR_ROWS
    ),
    "ClsFunc": _CLS_FUNC_ROWS,
    "ClsVar":  _CLS_VAR_ROWS,
    "Func": frozenset(r.name for r in _ROWS if r.scope == "function"),
    "Var":  frozenset(r.name for r in _ROWS if r.scope == "variable"),
}

# The 6 roots used in the LOO experiment, in a stable display order
LOO_SUBGRAPH_ROOTS: tuple[str, ...] = ("File", "Class", "ClsFunc", "ClsVar", "Func", "Var")


def subtree_rows(root: str) -> frozenset[str]:
    """Return all row names that belong to the subtree rooted at `root`."""
    if root not in _SUBTREE:
        raise ValueError(f"Unknown LOO root: {root!r}. Must be one of {LOO_SUBGRAPH_ROOTS}")
    return _SUBTREE[root]


# ---------------------------------------------------------------------------
# coalition_id
# ---------------------------------------------------------------------------

def coalition_id(coalition: frozenset[str]) -> str:
    """Stable 16-char hex hash of the sorted row names."""
    payload = json.dumps(sorted(coalition), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# available_rows
# ---------------------------------------------------------------------------

def available_rows(instance: dict) -> frozenset[str]:
    """
    Return the set of taxonomy rows that have at least one non-empty payload
    in the given instance's identifiers (including nested cls_methods /
    cls_variables sub-records).
    """
    identifiers  = instance.get("identifiers", [])
    entity_types = {ident.get("entity_type", "") for ident in identifiers}

    active: set[str] = set()

    # Structural roots
    if identifiers:
        active.add("File")
    if "class"    in entity_types: active.update(("Class", "ClassName"))
    if "function" in entity_types: active.update(("Func",  "FuncName"))
    if "variable" in entity_types: active.add("Var")

    # File-level detail
    if any(i.get("path")              for i in identifiers): active.add("FileLoc")
    if any(i.get("imports")           for i in identifiers): active.add("Import")
    if any(i.get("is_new_file") is True  for i in identifiers): active.add("NewFile")
    if any(i.get("is_new_file") is False for i in identifiers): active.add("ModifiedFile")

    # Top-level entity rows: active iff ≥1 scoped identifier has a nonempty value
    for row in _ROWS:
        if row.scope in ("cls_function", "cls_variable"):
            continue   # handled separately below
        if row.structural or row.name in ("ClassName", "FuncName"):
            continue
        for fname in row.fields:
            for ident in identifiers:
                if ident.get("entity_type") == row.scope and ident.get(fname):
                    active.add(row.name)

    # Cls Function rows: scan cls_methods sub-records inside class identifiers
    cls_methods_all = [
        m
        for ident in identifiers
        if ident.get("entity_type") == "class"
        for m in (ident.get("cls_methods") or [])
    ]
    if cls_methods_all:
        active.update(("ClsFunc", "ClsFuncName"))
        for row in _ROWS:
            if row.scope != "cls_function" or row.structural or row.name == "ClsFuncName":
                continue
            for fname in row.fields:
                if any(m.get(fname) for m in cls_methods_all):
                    active.add(row.name)

    # Cls Variable rows: scan cls_variables sub-records inside class identifiers
    cls_vars_all = [
        v
        for ident in identifiers
        if ident.get("entity_type") == "class"
        for v in (ident.get("cls_variables") or [])
    ]
    if cls_vars_all:
        active.add("ClsVar")
        for row in _ROWS:
            if row.scope != "cls_variable" or row.structural:
                continue
            for fname in row.fields:
                if any(v.get(fname) for v in cls_vars_all):
                    active.add(row.name)

    return frozenset(active)


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------

def _opaque_id(entity_type: str, path: str, name: str, counters: dict) -> str:
    prefix = {"file": "F", "class": "C", "function": "FN", "variable": "V"}.get(entity_type, "X")
    key = (entity_type, path, name)
    if key not in counters:
        existing = [k for k in counters if k[0] == entity_type]
        counters[key] = len(existing) + 1
    return f"{prefix}{counters[key]}"


def canonicalize_instance(instance: dict) -> dict:
    """
    Deduplicate file-level fields and assign stable opaque IDs.
    Each entity dict retains cls_methods / cls_variables lists for downstream
    projection.
    """
    identifiers = instance.get("identifiers", [])

    files_by_path: dict[str, dict] = {}
    for ident in identifiers:
        path = ident.get("path", "")
        if path and path not in files_by_path:
            files_by_path[path] = {
                "path":        path,
                "is_new_file": ident.get("is_new_file"),
                "imports":     ident.get("imports") or "",
            }

    sorted_paths = sorted(files_by_path)
    file_opaque: dict[str, str] = {}
    canonical_files = []
    for i, path in enumerate(sorted_paths, 1):
        oid = f"F{i}"
        file_opaque[path] = oid
        canonical_files.append({**files_by_path[path], "opaque_id": oid})

    entity_key_seen: dict[tuple, dict] = {}
    for ident in identifiers:
        etype = ident.get("entity_type", "")
        if etype == "file":
            continue
        path = ident.get("path", "")
        name = ident.get("name", "")
        key  = (etype, path, name)
        if key not in entity_key_seen:
            entity_key_seen[key] = dict(ident)

    entity_order = {"class": 0, "function": 1, "variable": 2}
    sorted_keys  = sorted(entity_key_seen,
                          key=lambda k: (k[1], entity_order.get(k[0], 9), k[2]))

    counters: dict = {}
    canonical_entities = []
    for key in sorted_keys:
        etype, path, name = key
        oid = _opaque_id(etype, path, name, counters)
        canonical_entities.append({
            **entity_key_seen[key],
            "opaque_id":      oid,
            "file_opaque_id": file_opaque.get(path, ""),
        })

    return {"files": canonical_files, "entities": canonical_entities}


# ---------------------------------------------------------------------------
# project_rows
# ---------------------------------------------------------------------------

def _strip_weak_prefix(strong: str, weak: str) -> str:
    if strong and weak and strong.startswith(weak):
        return strong[len(weak):].lstrip("\n .:")
    return strong


def _project_sub_records(
    sub_records: list[dict],
    coalition: frozenset[str],
    cls_rows: frozenset[str],
    name_row: str,
    show_path: bool,
    mask_name_row: str | None = None,
) -> list[dict]:
    """Project a list of cls_methods or cls_variables sub-records."""
    active_cls = coalition & cls_rows
    if not active_cls:
        return []

    results = []
    for sub in sub_records:
        proj: dict = {}

        if name_row in coalition:
            proj["name"] = sub.get("name", "")

        for row in _ROWS:
            if row.scope not in ("cls_function", "cls_variable"):
                continue
            if row.name not in coalition:
                continue
            for fname in row.fields:
                val = sub.get(fname)
                if not val:
                    continue
                if fname == "strong_semantics":
                    weak = sub.get("weak_semantics", "")
                    val  = _strip_weak_prefix(str(val), str(weak))
                    if not val:
                        continue
                if fname in ("partial_location", "complete_location") and not show_path:
                    val = re.sub(r"^[^\s:]+\.py:", "", str(val)).strip()
                if fname == "signature" and mask_name_row and mask_name_row not in coalition:
                    name = sub.get("name", "")
                    if name and name in str(val):
                        val = str(val).replace(name, "<METHOD>", 1)
                proj[fname] = val

        if proj:
            results.append(proj)

    return results


# Rows that "gate" each entity type — if none of these are in the coalition,
# the entire entity (including all sub-records) is suppressed.
# NOTE: ClsFunc / ClsVar rows are intentionally NOT in the class gate.
#       Removing the Class subtree must suppress the entire class entity
#       (including nested methods/variables) even if ClsFunc/ClsVar rows remain.
_CLASS_ROWS:    frozenset[str] = frozenset(r.name for r in _ROWS if r.scope == "class")
_FUNC_ROWS:     frozenset[str] = frozenset(r.name for r in _ROWS if r.scope == "function")
_VAR_ROWS:      frozenset[str] = frozenset(r.name for r in _ROWS if r.scope == "variable")

_ENTITY_GATE: dict[str, frozenset[str]] = {
    "class":    _CLASS_ROWS,   # only Class-scope rows gate the class entity
    "function": _FUNC_ROWS,
    "variable": _VAR_ROWS,
}


def project_rows(instance: dict, coalition: frozenset[str]) -> dict:
    """
    Return a canonicalized instance projected to only the fields unlocked by
    the given coalition, including cls_methods / cls_variables sub-records.

    Suppression rule: if NO row from an entity type's gate set is in the
    coalition, the entire entity is omitted from the output — including any
    cls_methods / cls_variables sub-records it would otherwise carry.
    Concretely: removing the Class subtree hides all class entities and their
    nested ClsFunc / ClsVar content, even if ClsFunc rows are still active.
    """
    canon = canonicalize_instance(instance)

    show_path     = "FileLoc"     in coalition
    show_new_file = ("NewFile" in coalition or "ModifiedFile" in coalition)
    show_imports  = "Import"      in coalition

    proj_files = []
    for fe in canon["files"]:
        pf: dict = {"opaque_id": fe["opaque_id"]}
        if show_path:
            pf["path"] = fe["path"]
        if show_new_file and fe["is_new_file"] is not None:
            pf["is_new_file"] = fe["is_new_file"]
        if show_imports and fe["imports"]:
            pf["imports"] = fe["imports"]
        proj_files.append(pf)

    proj_entities = []
    for ent in canon["entities"]:
        etype = ent.get("entity_type", "")

        # Suppress the entire entity if none of its gate rows are active.
        gate = _ENTITY_GATE.get(etype, frozenset())
        if gate and not (coalition & gate):
            continue

        projected: dict = {
            "opaque_id":      ent["opaque_id"],
            "file_opaque_id": ent["file_opaque_id"],
            "entity_type":    etype,
        }

        # Name
        show_name = (
            (etype == "class"    and "ClassName" in coalition) or
            (etype == "function" and "FuncName"  in coalition) or
            (etype == "variable" and "Var"       in coalition)
        )
        if show_name:
            projected["name"] = ent.get("name", "")

        # Top-level fields (non-Cls* rows)
        for row in _ROWS:
            if row.scope in ("cls_function", "cls_variable"):
                continue
            if row.scope != etype or row.name not in coalition:
                continue
            for fname in row.fields:
                val = ent.get(fname)
                if not val:
                    continue
                if fname == "strong_semantics":
                    weak = ent.get("weak_semantics", "")
                    val  = _strip_weak_prefix(str(val), str(weak))
                    if not val:
                        continue
                if fname in ("partial_location", "complete_location") and not show_path:
                    val = re.sub(r"^[^\s:]+\.py:", "", str(val)).strip()
                if fname == "signature" and "FuncName" not in coalition:
                    name = ent.get("name", "")
                    if name and name in str(val):
                        val = str(val).replace(name, "<FUNCTION>", 1)
                projected[fname] = val

        # Cls methods sub-records (only for class entities)
        if etype == "class" and (coalition & _CLS_FUNC_ROWS):
            raw_methods = ent.get("cls_methods") or []
            proj_methods = _project_sub_records(
                raw_methods, coalition, _CLS_FUNC_ROWS,
                name_row="ClsFuncName", show_path=show_path,
                mask_name_row="ClsFuncName",
            )
            if proj_methods:
                projected["cls_methods"] = proj_methods

        # Cls variables sub-records (only for class entities)
        if etype == "class" and (coalition & _CLS_VAR_ROWS):
            raw_vars = ent.get("cls_variables") or []
            proj_vars = _project_sub_records(
                raw_vars, coalition, _CLS_VAR_ROWS,
                name_row="ClsVar", show_path=show_path,
            )
            if proj_vars:
                projected["cls_variables"] = proj_vars

        proj_entities.append(projected)

    return {"files": proj_files, "entities": proj_entities}


# ---------------------------------------------------------------------------
# render_hint
# ---------------------------------------------------------------------------

_FIELD_LABELS: dict[str, str] = {
    "path":                 "Path",
    "is_new_file":          "Status",
    "imports":              "Imports",
    "superclass":           "Superclass",
    "generics":             "Generics",
    "public_methods":       "Public methods",
    "private_methods":      "Private methods",
    "partial_location":     "Partial location",
    "complete_location":    "Complete location",
    "weak_semantics":       "Description",
    "strong_semantics":     "Details",
    "signature":            "Signature",
    "input_spec":           "Input",
    "input_names":          "Input names",
    "input_types":          "Input types",
    "output_partial_type":  "Output type",
    "output_complete_type": "Output type (full)",
    "exception_types":      "Exception types",
    "exception_values":     "Exception values",
    "param_defaults":       "Parameter defaults",
    "var_type":             "Type",
    "var_value":            "Value",
}

_ENTITY_FIELD_ORDER: list[str] = [
    "name",
    "superclass", "generics",
    "public_methods", "private_methods",
    "signature", "input_spec", "input_names", "input_types",
    "output_partial_type", "output_complete_type",
    "partial_location", "complete_location",
    "exception_types", "exception_values",
    "param_defaults",
    "var_type", "var_value",
    "weak_semantics", "strong_semantics",
]


def _render_sub_records(sub_records: list[dict], heading: str, indent: str = "    ") -> list[str]:
    """Render cls_methods or cls_variables as indented sub-sections."""
    lines: list[str] = []
    for i, sub in enumerate(sub_records, 1):
        name = sub.get("name")
        label = f"{name}" if name else f"{heading} {i}"
        lines.append(f"\n{indent}#### {heading}: {label}")
        for fname in _ENTITY_FIELD_ORDER:
            val = sub.get(fname)
            if val is None or fname == "name":
                continue
            field_label = _FIELD_LABELS.get(fname, fname)
            lines.append(f"{indent}- {field_label}: {val}")
    return lines


def render_hint(instance: dict, coalition: frozenset[str]) -> str:
    """
    Render the projected instance to a markdown hints string for mini-SWE-agent.
    Returns "" for the empty coalition.
    """
    if not coalition:
        return ""

    projected = project_rows(instance, coalition)
    files     = {fe["opaque_id"]: fe for fe in projected["files"]}
    entities  = projected["entities"]

    by_file: dict[str, list] = defaultdict(list)
    for ent in entities:
        by_file[ent["file_opaque_id"]].append(ent)

    lines: list[str] = []

    for fid, fe in sorted(files.items()):
        has_file_fields = any(k in fe for k in ("path", "is_new_file", "imports"))
        has_entities    = bool(by_file.get(fid))
        if not has_file_fields and not has_entities:
            continue

        # Only emit the ## File header when the File subtree contributed at
        # least one field (path, status, imports).  If the File subtree was
        # left out (LOO-File), entities still render but without the file
        # container header — consistent with how LOO-Class suppresses the
        # ### Class header when the Class subtree is absent.
        if has_file_fields:
            lines.append(f"## File {fid}")
            if "path" in fe:
                lines.append(f"- Path: {fe['path']}")
            if "is_new_file" in fe:
                status = "new file" if fe["is_new_file"] else "modified file"
                lines.append(f"- Status: {status}")
            if "imports" in fe:
                lines.append(f"- Imports: {fe['imports']}")

        for ent in by_file.get(fid, []):
            etype   = ent.get("entity_type", "")
            eid     = ent["opaque_id"]
            heading = {"class": "Class", "function": "Function", "variable": "Variable"}.get(etype, etype.title())
            lines.append(f"\n### {heading} {eid}")

            for fname in _ENTITY_FIELD_ORDER:
                val = ent.get(fname)
                if val is None:
                    continue
                label = _FIELD_LABELS.get(fname, fname)
                if fname == "name":
                    lines.append(f"- Name: {val}")
                else:
                    lines.append(f"- {label}: {val}")

            # Render nested cls_methods
            cls_methods = ent.get("cls_methods")
            if cls_methods:
                lines.extend(_render_sub_records(cls_methods, "Method"))

            # Render nested cls_variables
            cls_variables = ent.get("cls_variables")
            if cls_variables:
                lines.extend(_render_sub_records(cls_variables, "Variable"))

        lines.append("")

    return "\n".join(lines).strip()


# Made with Bob
