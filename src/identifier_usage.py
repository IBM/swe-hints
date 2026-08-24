"""
Step 1: Identifier Usage Extraction

Given a SWE-bench Pro instance (with `patch`, `test_patch`, `base_commit`, and a
cloned repo), computes the *newly introduced* identifiers in each patch, classifies
them as READ or WRITE, and exposes them via a configurable operator.

The extraction mirrors augment_swebench_pro_comm_v3_enhanced_fb.py:
  - Reset repo to base_commit
  - Record entities BEFORE applying patch
  - Apply patch
  - Record entities AFTER
  - diff = after − before  →  new entities only

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
# Low-level tree-sitter helpers  (module-level WRITE + any READ, same as ref)
# ---------------------------------------------------------------------------

def _node_contains(parent, child) -> bool:
    if parent == child:
        return True
    for c in parent.children:
        if _node_contains(c, child):
            return True
    return False


def _is_at_module_level(node) -> bool:
    current = node.parent
    while current is not None:
        if current.type in ("function_definition", "class_definition"):
            return False
        if current.type == "module":
            return True
        current = current.parent
    return False


def _is_write(node) -> bool:
    if node.parent is None:
        return False
    parent = node.parent
    pt = parent.type
    if pt in ("function_definition", "class_definition"):
        if node == parent.child_by_field_name("name"):
            return _is_at_module_level(parent)
    if pt == "assignment":
        left = parent.child_by_field_name("left")
        if left and _node_contains(left, node):
            return _is_at_module_level(parent)
    return False


def _is_read(node) -> bool:
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
    return False


def _extract_entities(code: str) -> tuple[set[str], set[str]]:
    """
    Return (write_names, read_names) from a Python source string.
    Only module-level definitions count as WRITE.
    """
    try:
        tree = _ts_parser.parse(code.encode("utf-8", errors="ignore"))
    except Exception:
        return set(), set()

    writes: set[str] = set()
    reads: set[str] = set()

    def traverse(node):
        if node.type == "identifier":
            name = node.text.decode("utf-8", errors="ignore")
            w = _is_write(node)
            r = _is_read(node)
            if w:
                writes.add(name)
            if r:
                reads.add(name)
            if not w and not r:
                reads.add(name)
        for child in node.named_children:
            traverse(child)

    traverse(tree.root_node)
    return writes, reads


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

    before: dict[str, tuple[set[str], set[str]]] = {}
    for pf in patched_files:
        code = _read(repo_dir / pf.path)
        before[pf.path] = _extract_entities(code)

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
        aw, ar = _extract_entities(code)
        bw, br = before[pf.path]
        new_writes |= aw - bw
        new_reads  |= ar - br

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
            instance:  A SWE-bench Pro record with keys:
                         repo, base_commit, patch, test_patch
            repos_dir: Directory containing cloned repos
                       (e.g. repos/django for repo=django/django).
        """
        repo_name = instance["repo"].split("/")[-1]
        repo_dir = repos_dir / repo_name
        if not repo_dir.exists():
            raise FileNotFoundError(
                f"Repo not found: {repo_dir}  (instance {instance.get('instance_id')})"
            )

        base_commit = instance["base_commit"]
        code_patch = instance.get("patch", "")
        test_patch = instance.get("test_patch", "")

        code_w, code_r, code_cat = _diff_names(repo_dir, base_commit, code_patch, "impl")
        test_w, test_r, test_cat = _diff_names(repo_dir, base_commit, test_patch, "test")

        # Merge catalogues; code patch wins on conflict
        catalogue = {**test_cat, **code_cat}

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
