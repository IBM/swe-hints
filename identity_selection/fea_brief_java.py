#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
FEA-Brief identity selection for JAVA repositories.

Java counterpart of ``identity_selection/fea_brief.py``, which is itself a
faithful port of FEA-Bench's ``get_dataset.py::get_file_related_info()``.

WHY THIS IS A REWRITE, NOT A PORT
---------------------------------
``fea_brief.py`` is built on CPython's stdlib ``ast`` module.  ``ast`` cannot
parse Java at all, so no line of the parsing half survives; only the *semantics*
carry over, re-expressed on tree-sitter (``get_parser("java")``, root
``program``).  The git half -- checkout, ``git apply --whitespace=fix`` with a
``--3way`` fallback, save-originals-then-patch, ``git reset --hard`` +
``git clean -fdx`` in a ``finally`` -- is mirrored beat for beat, because that
is language-independent and defines when an instance is usable at all.

The preserved semantics:
  - checkout_to_commit -> 'git checkout --quiet <commit>'
  - apply_patch        -> writes 'patch.diff' into repo_dir, 'git apply', rm
  - parse_namespaces   -> read a file from disk, walk it, emit one record per
                          *namespace* with a dotted qualified name
                          (Python: 'Coder.prepare_to_edit';
                           Java:   'Outer.Inner.doThing')
  - compare_namespaces -> namespaces whose name is in new-file but not old-file
  - handle_new_file    -> every namespace of a brand-new file is new
  - only source files of the target language are processed; everything else
    (pom.xml, .md, resources, .py) is skipped entirely
  - no filtering against the problem statement (the original does not filter)

WHAT COUNTS AS A NAMESPACE IN JAVA
----------------------------------
The original visits exactly ``FunctionDef`` and ``ClassDef`` -- not
``AsyncFunctionDef``, and not assignments, so module-level constants are never
namespaces.  The Java analogue is:

  namespace  <-  class_declaration | interface_declaration | enum_declaration
                 | record_declaration | annotation_type_declaration     ("class")
             <-  method_declaration | constructor_declaration
                 | compact_constructor_declaration
                 | annotation_type_element_declaration                ("function")

Fields (``field_declaration`` / ``constant_declaration``) and enum constants are
NOT namespaces, exactly as Python assignments are not.  ``type`` therefore stays
in {"function", "class"} -- the same two values the Python original emits, which
keeps the downstream entity gate happy.  The Java kind (class/interface/enum/
record/annotation, method/constructor) is reported additively in ``entity_kind``,
the optional Java-only field sanctioned by ``src/lang/base.py``.

Traversal descends through method bodies, so a local class or a method of an
anonymous class is named under its enclosing namespace -- the same thing the
original does for a function nested inside a function.

OVERLOADING
-----------
Java lets one class declare ``doThing(String)`` and ``doThing(int)``.  Both have
the dotted name ``Cls.doThing``, so the original's
``{ns["name"]: ns for ns in namespaces}`` would silently keep only the last one
and a patch that ADDS an overload would look like a no-op.  Per
``src/lang/base.py`` CONTRACT 2, callables are compared under ``name#arity``
(``Cls.doThing#1``) while the emitted ``name`` field stays the bare dotted path,
so the output schema is unchanged and rendered hints are unaffected.  Types and
everything else compare under the bare name.

DOCS
----
Javadoc is a ``block_comment`` node PRECEDING the declaration (and preceding its
annotations/``modifiers``), not a first string statement inside the body as in
Python -- so extraction is structurally different and written fresh.  ``doc``
holds the WHOLE Javadoc description with the ``*`` margin stripped, including
``@param``/``@return`` blocks, because that is what ``ast.get_docstring`` returns
for Python: the whole docstring, not a summary.  (``extract_public_symbols_java``
deliberately differs and keeps only the first paragraph, mirroring
``extract_public_symbols.py``'s ``_first_para``.)

OUTPUT SCHEMA (per file, mirrors get_dataset.py's new_components field)
-----------------------------------------------------------------------
    {
      "new_components": {
        "path/to/File.java": [
          {"type": "function"|"class", "name": "Outer.Inner.doThing",
           "lines": [start, end], "signature": "...", "doc": "...",
           "entity_kind": "method"},
          ...
        ]
      }
    }

DIFFERENCES FROM fea_brief.py THAT ARE DELIBERATE
-------------------------------------------------
  * ``--feabench`` / HuggingFace / GitHub-PR-diff fetching is dropped:
    FEA-Bench is a Python-only dataset, so a Java run always has a local JSONL
    carrying ``patch`` (or ``feature_patch``).
  * ``lines[1]`` is the declaration's true end line (tree-sitter ``end_point``).
    The Python original reports ``max(lineno)`` over ``ast.walk`` -- a maximum of
    *start* lines, which undershoots by design.  Reproducing that artefact on a
    concrete syntax tree would be deliberate damage, so it is not reproduced.

Usage:
    python identity_selection/fea_brief_java.py \\
        --input  data/java/swebench_multilingual_java.jsonl \\
        --output results/java_fea_brief.jsonl \\
        --repos  repos/java_repos

    # debug a single instance
    python identity_selection/fea_brief_java.py -i <in> -o <out> -r <repos> \\
        --instance-id <id>

    # debug with no repo at all
    python identity_selection/fea_brief_java.py --dump-file Foo.java
    python identity_selection/fea_brief_java.py --compare Old.java New.java
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

from tqdm import tqdm
from tree_sitter_languages import get_parser
from unidiff import PatchSet

# `fea_brief.py` does a bare `from utils import ...`, which only resolves when
# the script's own directory is sys.path[0].  Make it work when imported too.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_jsonl, dump_jsonl, find_repo_dir, get_impl_patch  # noqa: E402


# ---------------------------------------------------------------------------
# tree-sitter plumbing
# ---------------------------------------------------------------------------

_PARSER = None


def _parser():
    """Memoised Java parser (get_parser re-loads the shared library each call)."""
    global _PARSER
    if _PARSER is None:
        _PARSER = get_parser("java")
    return _PARSER


# type_node -> entity_kind ; all map to namespace type "class"
TYPE_DECLS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}

# callable_node -> entity_kind ; all map to namespace type "function"
CALLABLE_DECLS = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "compact_constructor_declaration": "constructor",
    "annotation_type_element_declaration": "method",
}

# Nodes that end a declaration header (where a signature stops).
_BODY_STOPS = {
    "class_body", "interface_body", "enum_body", "annotation_type_body",
    "block", "constructor_body", ";",
}


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _child_of_type(node, *types: str):
    for child in node.children:
        if child.type in types:
            return child
    return None


def _decl_name(node) -> str:
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named)
    ident = _child_of_type(node, "identifier")
    return _text(ident) if ident is not None else ""


# ---------------------------------------------------------------------------
# Signature / doc extraction
# ---------------------------------------------------------------------------

def remove_comments_and_whitespace(text: str) -> str:
    """
    Java analogue of get_dataset.py's remove_comments_and_whitespace(), which
    strips Python `#` comments.  Java has two comment forms, so both go.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _signature(node) -> str:
    """
    The declaration header: first token up to (not including) the body.

    The original slices source lines `[node.lineno-1 : first_body_stmt.lineno-1]`
    and joins them.  In Java the body is an explicit child node, so the cut is
    exact rather than line-approximate.
    """
    end = node.end_byte
    for child in node.children:
        if child.type in _BODY_STOPS:
            end = child.start_byte
            break
    raw = node.text[: end - node.start_byte].decode("utf-8", errors="replace")
    return remove_comments_and_whitespace(raw)


def _javadoc(node) -> str:
    """
    Whole Javadoc description attached to `node`, `*` margin stripped, or "".

    Structural difference from Python: a docstring is the first string statement
    INSIDE the body and is reachable with ast.get_docstring; Javadoc is a sibling
    `block_comment` that PRECEDES the entire declaration, annotations included.
    Only `/** ... */` counts; a plain `/* ... */` is not Javadoc.
    Block tags (@param/@return/...) are KEPT -- ast.get_docstring keeps the whole
    docstring, so the Java analogue keeps the whole comment.
    """
    sib = node.prev_sibling
    while sib is not None and sib.type == "line_comment":
        sib = sib.prev_sibling
    if sib is None or sib.type != "block_comment":
        return ""
    raw = _text(sib)
    if not raw.startswith("/**"):
        return ""
    body = raw[3:]
    if body.endswith("*/"):
        body = body[:-2]
    lines = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:]
            if line.startswith(" "):
                line = line[1:]
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _arity(node) -> int:
    """
    Declared parameter count; a compact constructor / annotation element is 0.

    A `receiver_parameter` (`void m(C this, int x)`, legal since Java 8 for
    receiver type annotations) is NOT an argument and is not counted, so
    `m(C this, int x)` has arity 1 -- the arity a call site would produce.
    """
    params = node.child_by_field_name("parameters") or _child_of_type(node, "formal_parameters")
    if params is None:
        return 0
    return sum(1 for c in params.children
               if c.type in ("formal_parameter", "spread_parameter"))


# ---------------------------------------------------------------------------
# Namespace extraction -- Java analogue of get_dataset.py's parse_namespaces()
# ---------------------------------------------------------------------------

def parse_namespaces_source(source: str) -> List[dict]:
    """
    Every namespace in one Java compilation unit, in source order.

    Mirrors parse_namespaces()'s NamespaceVisitor: a dotted `current_namespace`
    stack pushed on entry and popped on exit, `generic_visit` in between, so
    declarations at any depth (including inside method bodies and anonymous
    class bodies) are reached and named under their enclosing namespace.

    Each record additionally carries a private `_key` used only for the
    old/new comparison: `name#arity` for callables (CONTRACT 2 in
    src/lang/base.py -- Java overloads share a dotted name), bare `name` for
    types.  `_key` is stripped before the record is emitted.
    """
    tree = _parser().parse(source.encode("utf-8"))
    namespaces: List[dict] = []
    stack: List[str] = []

    # Explicit stack rather than recursion: the visitor descends into method
    # bodies, and a machine-generated Java file can nest far deeper than
    # CPython's 1000-frame limit (gson's deepest real file is 46).
    # A ("pop", None) sentinel is pushed BEFORE a declaration's children, so it
    # is processed after all of them -- the exact scope of `stack.pop()` in the
    # original's recursive `_handle_namespace`.
    work = [(tree.root_node, False)]
    while work:
        node, is_sentinel = work.pop()
        if is_sentinel:
            stack.pop()
            continue

        kind = TYPE_DECLS.get(node.type)
        type_ = "class"
        if kind is None:
            kind = CALLABLE_DECLS.get(node.type)
            type_ = "function"

        name = _decl_name(node) if kind is not None else ""
        if kind is None or not name:
            # Not a namespace (or an unnamed body, which these node types should
            # never be): descend without pushing a component, so nothing is
            # silently dropped.
            work.extend((child, False) for child in reversed(node.children))
            continue

        dotted = ".".join(stack + [name])
        key = f"{dotted}#{_arity(node)}" if type_ == "function" else dotted
        namespaces.append({
            "type": type_,
            "name": dotted,
            "lines": (node.start_point[0] + 1, node.end_point[0] + 1),
            "signature": _signature(node),
            "doc": _javadoc(node),
            "entity_kind": kind,
            "_key": key,
        })

        stack.append(name)
        work.append((node, True))
        work.extend((child, False) for child in reversed(node.children))

    return namespaces


def parse_namespaces(file_path) -> List[dict]:
    """
    Path-taking wrapper, same call shape as get_dataset.py's parse_namespaces().
    Reads with utf-8-sig, exactly like the original (Java sources routinely
    carry a BOM).
    """
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
        source = f.read()
    return parse_namespaces_source(source)


def _strip_keys(namespaces: List[dict]) -> List[dict]:
    return [{k: v for k, v in ns.items() if k != "_key"} for ns in namespaces]


def compare_namespaces(old_file_path, new_file_path) -> List[dict]:
    """
    Namespaces added by the patch: present in new, absent in old.

    Mirrors get_dataset.py's compare_namespaces(), but keyed on `_key` so an
    added OVERLOAD (`doThing(int)` next to an existing `doThing(String)`) is
    reported instead of being masked by the pre-existing dotted name.
    """
    old_namespaces = parse_namespaces(old_file_path) if old_file_path else []
    new_namespaces = parse_namespaces(new_file_path)

    old_keys = {ns["_key"] for ns in old_namespaces}
    seen: set = set()
    added = []
    for ns in new_namespaces:
        if ns["_key"] in old_keys or ns["_key"] in seen:
            continue
        seen.add(ns["_key"])
        added.append(ns)
    return _strip_keys(added)


def handle_new_file(file_path) -> List[dict]:
    """Whole file is new -> every namespace in it is new.  Mirrors the original."""
    return _strip_keys(parse_namespaces(file_path))


# ---------------------------------------------------------------------------
# Git helpers -- mirrors fea_brief.py / get_dataset.py exactly
# ---------------------------------------------------------------------------

def run_command(command, cwd=None, check=True):
    try:
        return subprocess.run(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=check,
        )
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}:")
        print("Standard Output:", e.stdout)
        print("Standard Error:", e.stderr)
        raise


def checkout_to_commit(repo_dir, commit_sha):
    run_command(["git", "checkout", "--quiet", commit_sha], cwd=repo_dir)


def apply_patch(repo_dir, patch_content):
    patch_file = os.path.join(repo_dir, "patch.diff")
    with open(patch_file, "w") as f:
        f.write(patch_content)
    try:
        run_command(["git", "apply", "--whitespace=fix", "patch.diff"], cwd=repo_dir)
    except subprocess.CalledProcessError:
        run_command(["git", "apply", "--3way", "--whitespace=fix", "patch.diff"], cwd=repo_dir)
    finally:
        if os.path.exists(patch_file):
            os.remove(patch_file)


# ---------------------------------------------------------------------------
# On-the-fly new_components computation (Java variant of get_file_related_info)
# ---------------------------------------------------------------------------

def compute_new_components(repo_dir: str, patch_content: str,
                           base_commit_sha: str) -> Dict[str, list]:
    """
    Checkout at base_commit_sha, apply patch_content, AST-diff the .java files.
    Returns {file_path: [namespace_dict, ...]}.  Non-Java files are skipped.
    """
    testbed_dir = Path(repo_dir)

    # `git apply` on an empty diff exits 128 ("No valid patches in input").
    # fea_brief.py has no such guard and crashes; extract_public_symbols.py DOES
    # guard (`if not patch_content.strip(): return []`), so this follows the
    # sibling that gets it right.  An implementation patch that touches only
    # test files is common enough in Java benchmarks to matter, and "no impl
    # patch" means "no new namespaces", not "instance failed".
    if not patch_content.strip():
        return {}

    run_command(["git", "reset", "--hard", "HEAD"], cwd=repo_dir)
    run_command(["git", "clean", "-fdx"], cwd=repo_dir)

    checkout_to_commit(repo_dir, base_commit_sha)

    files: Dict[str, Optional[str]] = {}
    for hunk in PatchSet(patch_content):
        file_path = hunk.path
        if not file_path.endswith(".java"):
            continue
        full_file_path = testbed_dir / file_path
        if os.path.exists(full_file_path):
            files[file_path] = full_file_path.read_text(encoding="utf-8-sig", errors="replace")
        else:
            files[file_path] = None

    try:
        apply_patch(repo_dir, patch_content)

        new_components = defaultdict(list)
        for file_path, original_content in files.items():
            new_full_file_path = testbed_dir / file_path

            if original_content is None and new_full_file_path.exists():
                added_namespaces = handle_new_file(str(new_full_file_path))
            elif original_content is not None and new_full_file_path.exists():
                with TemporaryDirectory() as temp_dir:
                    old_file_path = Path(temp_dir) / "old.java"
                    new_file_path = Path(temp_dir) / "new.java"
                    old_file_path.write_text(original_content, encoding="utf-8")
                    new_file_path.write_text(
                        new_full_file_path.read_text(encoding="utf-8-sig", errors="replace"),
                        encoding="utf-8",
                    )
                    added_namespaces = compare_namespaces(str(old_file_path),
                                                          str(new_file_path))
            else:
                continue

            if added_namespaces:
                new_components[file_path].extend(added_namespaces)
    finally:
        run_command(["git", "reset", "--hard", "HEAD"], cwd=repo_dir)
        run_command(["git", "clean", "-fdx"], cwd=repo_dir)

    return dict(new_components)


# ---------------------------------------------------------------------------
# Core per-instance logic
# ---------------------------------------------------------------------------

def process_instance(example: dict, repos_root: Path) -> dict:
    repo = example.get("repo", "")
    base_commit = example["base_commit"]
    repo_dir = str(find_repo_dir(repo, repos_root))

    impl_patch = get_impl_patch(example)
    new_components = compute_new_components(repo_dir, impl_patch, base_commit)

    result = dict(example)
    result.pop("augmentations", None)
    result["new_components"] = new_components
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="FEA-Brief identity selection for Java — AST-diff new "
                    "method/class namespaces via tree-sitter."
    )
    ap.add_argument("--input", "-i", type=Path, default=None,
                    help="Input JSONL carrying repo / base_commit / patch.")
    ap.add_argument("--output", "-o", type=Path, default=None,
                    help="Output JSONL with new_components added.")
    ap.add_argument("--repos", "-r", type=Path, default=None,
                    help="Directory containing cloned Java repos.")
    ap.add_argument("--skip-errors", action="store_true",
                    help="Skip failed instances instead of crashing.")
    ap.add_argument("--instance-id", type=str, default=None,
                    help="Process a single instance_id (for debugging).")
    ap.add_argument("--dump-file", type=Path, default=None,
                    help="Debug: print every namespace of one .java file and exit.")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"), default=None,
                    help="Debug: print namespaces added between two .java files "
                         "and exit.")
    args = ap.parse_args()

    if args.dump_file:
        print(json.dumps(handle_new_file(args.dump_file), indent=2, ensure_ascii=False))
        return
    if args.compare:
        print(json.dumps(compare_namespaces(args.compare[0], args.compare[1]),
                         indent=2, ensure_ascii=False))
        return

    if args.input is None or args.output is None or args.repos is None:
        ap.error("--input, --output and --repos are required "
                 "(unless --dump-file / --compare is used).")
    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")
    if not args.repos.is_dir():
        sys.exit(f"Repos directory not found: {args.repos}")

    examples = load_jsonl(args.input)

    if args.instance_id:
        examples = [e for e in examples if e.get("instance_id") == args.instance_id]
        if not examples:
            sys.exit(f"No instance with id={args.instance_id!r}")

    output_rows = []
    errors = []

    for ex in tqdm(examples, desc="FEA-Brief-Java"):
        iid = ex.get("instance_id", "<unknown>")
        try:
            output_rows.append(process_instance(ex, args.repos))
        except Exception as exc:
            print(f"\n[ERROR] {iid}: {exc}", file=sys.stderr)
            if not args.skip_errors:
                raise
            errors.append({"instance_id": iid, "error": repr(exc)})
            output_rows.append(ex)

    dump_jsonl(output_rows, args.output)
    print(f"Wrote {len(output_rows)} rows → {args.output}")

    if errors:
        err_path = args.output.with_suffix(args.output.suffix + ".errors.jsonl")
        dump_jsonl(errors, err_path)
        print(f"\n{len(errors)} errors:")
        for e in errors:
            print(f"  {e['instance_id']}: {e['error']}")
        print(f"Wrote {len(errors)} errors → {err_path}")


if __name__ == "__main__":
    main()
