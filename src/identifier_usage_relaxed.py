"""
Step 1: Identifier Usage Extraction (Relaxed scope variant)

Identical to identifier_usage.py except WRITE and READ are collected at ANY
nesting depth — function bodies, nested classes, etc. — not just module-level
or class-body-level.

The taxonomy projection in step 2 (identifier_information.py) still works
correctly: names found only in function bodies will have no entry in the rich
catalogue and fall back to a minimal {name, entity_type="variable"} record.
Names that are also module-level defs will have full catalogue entries.

Use --usage src/identifier_usage_relaxed output with identifier_information.py
unchanged to compare against the scoped variant.

Usage operators
---------------
- "intersection"  : (code_read | code_write) ∩ (test_read | test_write)
- "communication" : (code_write ∩ test_read) | (code_read ∩ test_write)  — forward ∪ backward
- "forward"       : code_write ∩ test_read
- "backward"      : code_read ∩ test_write
- "code_only"     : code_read | code_write
- "test_only"     : test_read | test_write
- "union"         : all names from both patches
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, Optional, Set

from pydantic import BaseModel, model_validator
from tree_sitter_languages import get_parser
from unidiff import PatchSet

_ts_parser = get_parser("python")

UsageOperator = Literal[
    "intersection",
    "communication",
    "forward",
    "backward",
    "code_only",
    "test_only",
    "union",
]

# ---------------------------------------------------------------------------
# Low-level tree-sitter helpers
# Scope: module level OR one depth inside a class body (but not inside a
# function/method body at any nesting depth).
# ---------------------------------------------------------------------------

def _path_to_module(path: str) -> str:
    """Convert a file path to a dotted module name.

    "django/utils/helper.py"   → "django.utils.helper"
    "django/utils/__init__.py" → "django.utils"
    """
    name = path.replace("\\", "/")
    if name.endswith(".py"):
        name = name[:-3]
    name = name.replace("/", ".")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name


def _node_contains(parent, child) -> bool:
    if parent == child:
        return True
    for c in parent.children:
        if _node_contains(c, child):
            return True
    return False


def _scope_depth(node) -> tuple[bool, bool]:
    """
    Walk up the ancestor chain and determine the scope of `node`.

    Returns (is_module_level, is_class_body_level) where:
      is_module_level    — the nearest enclosing named scope is the module
      is_class_body_level — the nearest enclosing named scope is a class_definition
                            and that class itself is at module level (i.e. exactly
                            one class deep, not a method body inside a class).

    Both are False if the node is nested inside a function/method body.
    """
    current = node.parent
    # Track how many class_definition ancestors we have passed through
    # before hitting a function_definition or module.
    in_class = False

    while current is not None:
        ct = current.type
        if ct == "function_definition":
            # Inside a function/method body — not in scope for either rule.
            return False, False
        if ct == "class_definition":
            if in_class:
                # Already inside an outer class; this is a nested class body —
                # treat it as too deep (we only go one class depth).
                return False, False
            in_class = True
            # Keep walking up to see whether the class itself is at module level.
        if ct == "module":
            if in_class:
                # The class is a direct child of the module → class body depth.
                return False, True
            else:
                return True, False
        current = current.parent

    return False, False


def _in_scope(node) -> bool:
    """Return True if the node is at module level or one class body deep."""
    ml, cl = _scope_depth(node)
    return ml or cl


def _is_write(node) -> bool:
    """
    A WRITE is:
      - The name identifier of a function_definition or class_definition at any depth.
      - The left-hand side of a plain assignment at any depth.
    Import-related WRITEs are handled separately in _extract_entities.
    """
    if node.parent is None:
        return False
    parent = node.parent
    pt = parent.type
    if pt in ("function_definition", "class_definition"):
        if node == parent.child_by_field_name("name"):
            return True
    if pt == "assignment":
        left = parent.child_by_field_name("left")
        if left and _node_contains(left, node):
            return True
    return False


def _is_read(node) -> bool:
    """
    A READ is any value-consuming use of an identifier at any depth.
    Import-related READs are handled separately in _extract_entities.
    """
    if node.parent is None:
        return False
    parent = node.parent
    pt = parent.type
    if pt == "call":
        func = parent.child_by_field_name("function")
        if func and _node_contains(func, node):
            return True
    if pt == "assignment":
        right = parent.child_by_field_name("right")
        if right and _node_contains(right, node):
            return True
    if pt == "augmented_assignment":
        for side in ("right", "left"):
            s = parent.child_by_field_name(side)
            if s and _node_contains(s, node):
                return True
    if pt == "return_statement":
        return True
    if pt in (
        "binary_operator", "comparison_operator", "boolean_operator",
        "unary_operator", "not_operator", "parenthesized_expression",
        "list", "tuple", "set", "dictionary",
        "list_comprehension", "dictionary_comprehension", "set_comprehension",
        "generator_expression", "subscript", "slice",
        "if_statement", "elif_clause", "while_statement", "conditional_expression",
        "argument_list", "keyword_argument",
    ):
        return True
    if pt == "for_statement":
        right = parent.child_by_field_name("right")
        if right and _node_contains(right, node):
            return True
    if pt == "attribute":
        obj = parent.child_by_field_name("object")
        if obj and _node_contains(obj, node):
            return True
    if pt == "decorator":
        return True
    return False


def _dotted_name_text(node) -> str:
    """Return the full dotted text of a dotted_name node (e.g. 'django.utils.helper')."""
    return node.text.decode("utf-8", errors="ignore")


def _extract_import(
    stmt_node,
    local_modules: set[str],
    writes: set[str],
    reads: set[str],
) -> None:
    """
    Process a single import_statement or import_from_statement node and
    populate writes/reads when the source module is in local_modules.

    Rules:
      import X               → last component of X is WRITE
      import X as Z          → Z is WRITE
      from X import Y        → Y is WRITE
      from X import Y as Z   → Z is WRITE, Y is READ
    """
    nt = stmt_node.type

    if nt == "import_statement":
        for child in stmt_node.named_children:
            if child.type == "dotted_name":
                mod = _dotted_name_text(child)
                if mod in local_modules:
                    writes.add(mod.split(".")[-1])
            elif child.type == "aliased_import":
                parts = list(child.named_children)
                # parts[0] = dotted_name (module), parts[1] = identifier (alias)
                if len(parts) == 2:
                    mod = _dotted_name_text(parts[0])
                    if mod in local_modules:
                        writes.add(parts[1].text.decode("utf-8", errors="ignore"))

    elif nt == "import_from_statement":
        named = list(stmt_node.named_children)
        if not named:
            return
        mod = _dotted_name_text(named[0])
        if mod not in local_modules:
            return
        for child in named[1:]:
            if child.type == "dotted_name":
                writes.add(_dotted_name_text(child).split(".")[-1])
            elif child.type == "aliased_import":
                parts = list(child.named_children)
                # parts[0] = dotted_name (original name), parts[1] = identifier (alias)
                if len(parts) == 2:
                    reads.add(_dotted_name_text(parts[0]).split(".")[-1])
                    writes.add(parts[1].text.decode("utf-8", errors="ignore"))


def _entity_type(node) -> str:
    """Return the entity_type label for an identifier node (mirrors defuse2_relaxed.py)."""
    if node.parent is None:
        return "variable"
    pt = node.parent.type
    if pt == "function_definition" and node == node.parent.child_by_field_name("name"):
        return "function"
    if pt == "class_definition" and node == node.parent.child_by_field_name("name"):
        return "class"
    if pt == "attribute" and node == node.parent.child_by_field_name("attribute"):
        return "attribute"
    return "variable"


def _extract_entities(
    code: str,
    local_modules: set[str] | None = None,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """
    Return (write_tokens, read_tokens) from a Python source string, where each
    token is a (name, entity_type) pair.

    Using typed pairs instead of bare strings mirrors defuse2_relaxed.py's
    Entity-based diff: a name that existed as 'variable' but is reintroduced as
    'function' (or vice-versa) counts as a genuinely new entity.

    local_modules: set of dotted module names (e.g. {"django.utils.helper"})
                   derived from the files touched by the current patch.
                   Only imports from these modules are classified.
    """
    if local_modules is None:
        local_modules = set()

    try:
        tree = _ts_parser.parse(code.encode("utf-8", errors="ignore"))
    except Exception:
        return set(), set()

    writes: set[tuple[str, str]] = set()
    reads: set[tuple[str, str]] = set()

    def traverse(node):
        # Handle import statements before descending — identifiers inside are
        # fully consumed here, so we skip normal traversal into them.
        if node.type in ("import_statement", "import_from_statement"):
            # _extract_import works with plain string sets; wrap results as typed tokens.
            w: set[str] = set()
            r: set[str] = set()
            _extract_import(node, local_modules, w, r)
            writes.update((name, "variable") for name in w)
            reads.update((name, "variable") for name in r)
            return
        if node.type == "identifier":
            name = node.text.decode("utf-8", errors="ignore")
            etype = _entity_type(node)
            if _is_write(node):
                writes.add((name, etype))
            elif _is_read(node):
                reads.add((name, etype))
        for child in node.named_children:
            traverse(child)

    traverse(tree.root_node)
    return writes, reads


def _names(tokens: set[tuple[str, str]]) -> set[str]:
    """Extract the name component from a set of (name, entity_type) tokens."""
    return {name for name, _ in tokens}


def get_doc_content(instance: dict) -> str:
    """
    Return the documentation text used to filter out identifiers already visible
    to the agent.  Mirrors identity_selection/utils.py::get_doc_content().

    - NoCode Bench Verified : joins the 'metadata' field of each doc_changes entry.
    - FEA-Bench             : joins pr_title + pr_body from problem_info.
    - SWE-bench Pro / Re-Bench: uses problem_statement.
    """
    if "doc_changes" in instance:
        items = instance.get("doc_changes") or []
        return "\n".join(
            str(item.get("metadata", ""))
            for item in items
            if isinstance(item, dict)
        )
    if "problem_info" in instance:
        pi = instance.get("problem_info") or {}
        return "\n".join(filter(None, [pi.get("pr_title", ""), pi.get("pr_body", "")]))
    return instance.get("problem_statement", "") or ""


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(
        cmd, cwd=str(cwd), check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _reset(repo_dir: Path, commit: str) -> None:
    _run(["git", "reset", "--hard", "-q"], repo_dir)
    _run(["git", "clean", "-fdx", "-q"], repo_dir)
    _run(["git", "checkout", "-q", commit], repo_dir)
    _run(["git", "reset", "--hard", "-q"], repo_dir)
    _run(["git", "clean", "-fdx", "-q"], repo_dir)


def _apply_patch(repo_dir: Path, patch_text: str, tag: str) -> bool:
    patch_file = repo_dir / f".swebench_{tag}.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        _run(["git", "apply", "--check", patch_file.name], repo_dir)
        _run(["git", "apply", patch_file.name], repo_dir)
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        try:
            patch_file.unlink()
        except FileNotFoundError:
            pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def _py_files(patch_text: str) -> list:
    if not patch_text.strip():
        return []
    try:
        return [f for f in PatchSet(patch_text.rstrip("\n")) if f.path.endswith(".py")]
    except Exception:
        return []


def _diff_names(
    repo_dir: Path,
    base_commit: str,
    patch_text: str,
    tag: str,
) -> tuple[set[str], set[str], dict[str, dict]]:
    """
    Reset repo, record before entities, apply patch, record after entities.
    Returns:
      (new_write_names, new_read_names, rich_catalogue)
      where rich_catalogue maps identifier name -> IdentifierInformation field dict
      for ALL module-level functions/classes found in the after-state of every
      touched file (not just newly introduced ones).  This gives step 2 the
      full set of entries to look up, regardless of which operator is used.
    """
    from src.identifier_extractor import extract_rich_entities

    if not patch_text.strip():
        return set(), set(), {}

    _reset(repo_dir, base_commit)
    patched_files = _py_files(patch_text)

    # Detect new (added) files
    try:
        from unidiff import PatchSet
        added_paths = {f.path for f in PatchSet(patch_text.rstrip("\n")).added_files
                       if f.path.endswith(".py")}
    except Exception:
        added_paths = set()

    # Build the set of dotted module names for all files touched by this patch.
    # Passed into _extract_entities so imports from these modules are classified.
    local_modules = {_path_to_module(pf.path) for pf in patched_files}

    before: dict[str, tuple[set[tuple[str, str]], set[tuple[str, str]]]] = {}
    for pf in patched_files:
        code = _read(repo_dir / pf.path)
        before[pf.path] = _extract_entities(code, local_modules)

    if not _apply_patch(repo_dir, patch_text, tag):
        return set(), set(), {}

    new_writes: set[str] = set()
    new_reads: set[str] = set()
    rich_catalogue: dict[str, dict] = {}

    # New .py files are added as WRITE identifiers (their path is the name),
    # mirroring augment_comm_v3_enhanced.py's new-file tracking.
    new_writes |= added_paths

    for pf in patched_files:
        is_new = pf.path in added_paths
        code = _read(repo_dir / pf.path)
        aw, ar = _extract_entities(code, local_modules)
        bw, br = before[pf.path]
        # Diff on typed (name, entity_type) pairs so that a name reused with a
        # different type (e.g. variable → function) is treated as genuinely new,
        # matching defuse2_relaxed.py's Entity-based set difference.
        new_writes |= _names(aw - bw)
        new_reads  |= _names(ar - br)

        # Collect rich info for ALL module-level defs in the after-state.
        # This covers: newly introduced, pre-existing but modified, and
        # pre-existing unchanged — so every name in any operator's output
        # has a catalogue entry if it is a top-level function/class.
        after_rich = extract_rich_entities(code, pf.path, is_new_file=is_new)
        for name, info in after_rich.items():
            if name not in rich_catalogue:
                rich_catalogue[name] = info

    return new_writes, new_reads, rich_catalogue


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class IdentifierUsage(BaseModel):
    """
    Read/write identifier sets + rich information catalogue for newly introduced
    identifiers in code and test patches.

    Construct via IdentifierUsage.from_instance() (uses repo diff, extracts rich
    AST fields) or IdentifierUsage.from_patches() (plain strings, no repo needed).

    catalogue: name -> IdentifierInformation field dict (all taxonomy fields
               extractable from the AST: signature, location, semantics, etc.)
    """

    code_read: list[str]
    code_write: list[str]
    test_read: list[str]
    test_write: list[str]
    # Rich AST-extracted info for every newly introduced identifier.
    # Keys are identifier names; values are dicts matching IdentifierInformation fields.
    catalogue: dict[str, dict] = {}

    @model_validator(mode="before")
    @classmethod
    def _sort(cls, values: dict) -> dict:
        for k in ("code_read", "code_write", "test_read", "test_write"):
            if k in values and isinstance(values[k], (list, set)):
                values[k] = sorted(values[k])
        return values

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_instance(
        cls,
        instance: dict,
        repos_dir: Path,
    ) -> "IdentifierUsage":
        """
        Extract identifiers from a SWE-bench Pro instance by diffing against
        the cloned repo at base_commit.  Also extracts rich AST fields
        (signature, location, semantics, etc.) into catalogue.

        Args:
            instance:  A dataset record with keys:
                         repo, base_commit, test_patch, and either
                         patch (SWE-bench Pro / Re-Bench) or
                         feature_patch (NoCode Bench / Doc2Feat).
            repos_dir: Directory containing cloned repos
                       (e.g. repos/django for repo=django/django).
        """
        # SWE-rebench-V2 repos are cloned as "org__name" to avoid collisions;
        # SWE-bench Pro / v1 repos use the short name only.
        # Auto-detect: prefer the slug form when it exists.
        repo_slug = instance["repo"].replace("/", "__")
        repo_short = instance["repo"].split("/")[-1]
        repo_dir = (
            repos_dir / repo_slug
            if (repos_dir / repo_slug).exists()
            else repos_dir / repo_short
        )
        if not repo_dir.exists():
            raise FileNotFoundError(
                f"Repo not found: {repo_dir}  (instance {instance.get('instance_id')})"
            )

        base_commit = instance["base_commit"]
        # NoCode Bench / Doc2Feat uses "feature_patch"; all others use "patch".
        code_patch = instance.get("patch") or instance.get("feature_patch", "")
        test_patch = instance.get("test_patch", "")

        code_w, code_r, code_cat = _diff_names(repo_dir, base_commit, code_patch, "impl")
        test_w, test_r, test_cat = _diff_names(repo_dir, base_commit, test_patch, "test")

        # Merge catalogues; code patch wins on conflict
        catalogue = {**test_cat, **code_cat}

        # Filter out names that are already visible in the problem statement /
        # documentation — mirroring defuse2_relaxed.py's doc_content filter.
        doc = get_doc_content(instance)
        code_w = {n for n in code_w if n not in doc}
        code_r = {n for n in code_r if n not in doc}
        test_w = {n for n in test_w if n not in doc}
        test_r = {n for n in test_r if n not in doc}

        # Leave repo clean
        try:
            _reset(repo_dir, base_commit)
        except Exception:
            pass

        return cls(
            code_read=code_r,
            code_write=code_w,
            test_read=test_r,
            test_write=test_w,
            catalogue=catalogue,
        )

    @classmethod
    def from_patches(cls, code_patch: str, test_patch: str) -> "IdentifierUsage":
        """
        Lightweight factory for plain source strings (no repo needed).
        Extracts rich fields via AST but without diff (treats all entities as new).
        """
        from src.identifier_extractor import extract_rich_entities
        cw, cr = _extract_entities(code_patch)
        tw, tr = _extract_entities(test_patch)
        code_cat = extract_rich_entities(code_patch, path="<code_patch>")
        test_cat = extract_rich_entities(test_patch, path="<test_patch>")
        catalogue = {**test_cat, **code_cat}
        return cls(code_read=cr, code_write=cw, test_read=tr, test_write=tw,
                   catalogue=catalogue)

    # ------------------------------------------------------------------
    # Operator
    # ------------------------------------------------------------------

    def get_with(self, operator: UsageOperator) -> list[str]:
        """
        Return a sorted list of identifier names via the given operator.

        Operators
        ---------
        intersection  : (code_read | code_write) ∩ (test_read | test_write)
        communication : (code_write ∩ test_read) | (code_read ∩ test_write)
        forward       : code_write ∩ test_read
        backward      : code_read  ∩ test_write
        code_only     : code_read | code_write
        test_only     : test_read | test_write
        union         : all four sets
        """
        cr = set(self.code_read)
        cw = set(self.code_write)
        tr = set(self.test_read)
        tw = set(self.test_write)

        # New .py file paths stored in code_write (added by the impl patch).
        # They can never appear in test_read/test_write (those contain AST names),
        # so they are added unconditionally to any operator that includes impl
        # output — mirroring augment_comm_v3_enhanced.py's new-file behaviour.
        new_files = {n for n in cw if "/" in n}

        if operator == "intersection":
            result = (cr | cw) & (tr | tw) | new_files
        elif operator == "communication":
            result = (cw & tr) | (cr & tw) | new_files
        elif operator == "forward":
            result = cw & tr | new_files
        elif operator == "backward":
            result = cr & tw
        elif operator == "code_only":
            result = cr | cw
        elif operator == "test_only":
            result = tr | tw
        elif operator == "union":
            result = cr | cw | tr | tw
        else:
            raise ValueError(f"Unknown operator: {operator!r}")

        return sorted(result)


# ---------------------------------------------------------------------------
# CLI  (run once — stores all four sets for later use by step 2)
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Step 1: extract identifier read/write sets from a JSONL dataset.\n"
            "Stores all four sets (code_read, code_write, test_read, test_write)\n"
            "so that step 2 can apply any operator without re-running extraction.\n\n"
            "SWE-bench Pro:  pass --repos-dir for precise diff-based extraction.\n"
            "No-repo mode:   omit --repos-dir to extract directly from patch text."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Input JSONL. Each line must have: instance_id, patch, test_patch.\n"
             "SWE-bench Pro also needs: repo, base_commit.",
    )
    parser.add_argument(
        "--repos-dir", "-r",
        type=Path,
        default=None,
        help="Directory of cloned repos for diff-based extraction (SWE-bench Pro).\n"
             "Omit to extract directly from patch text (no repo needed).",
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
        help="Output JSONL file. Each line: instance_id + code_read/write + test_read/write.",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Skip instances that raise errors instead of stopping.",
    )
    args = parser.parse_args()

    from tqdm import tqdm

    # Load instances
    instances: list[dict] = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    if args.instance_id:
        instances = [i for i in instances if i.get("instance_id") == args.instance_id]
        if not instances:
            parser.error(f"instance_id {args.instance_id!r} not found in {args.input}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n_ok = n_err = 0

    with open(args.output, "w", encoding="utf-8") as out_f:
        for instance in tqdm(instances, desc="Extracting", unit="instance"):
            iid = instance.get("instance_id", "<unknown>")
            try:
                if args.repos_dir is not None:
                    usage = IdentifierUsage.from_instance(instance, args.repos_dir)
                else:
                    usage = IdentifierUsage.from_patches(
                        instance.get("patch", ""),
                        instance.get("test_patch", ""),
                    )
                record = {"instance_id": iid, **usage.model_dump()}
                n_ok += 1
            except Exception as exc:
                if not args.skip_errors:
                    raise
                tqdm.write(f"  SKIP {iid}: {exc}")
                record = {"instance_id": iid, "error": repr(exc)}
                n_err += 1

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote {n_ok} records to {args.output}" + (f" ({n_err} errors)" if n_err else ""))


if __name__ == "__main__":
    _cli()

# Made with Bob
