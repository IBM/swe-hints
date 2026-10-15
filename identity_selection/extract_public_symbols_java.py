#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Java counterpart of ``identity_selection/extract_public_symbols.py``.

Stage 1 of the interface reconstruction pipeline, for Java repositories.
Given a gold patch applied to a local repo checkout, extract every NEW public
API symbol and return a structured list suitable for feeding into the LLM
rendering stage.

WHY THIS IS A REWRITE, NOT A PORT
---------------------------------
The Python original is built on CPython's stdlib ``ast`` module, which cannot
parse Java at all, so nothing is shared but the *semantics*.  This module keeps
those semantics and re-implements them on tree-sitter (``tree_sitter_languages``
``get_parser("java")``, root node ``program``):

  1. Grouping   — a new type is ONE entry; its public members are listed under
                  ``public_methods``, not as separate top-level entries.
  2. Filtering  — non-public symbols are dropped.
  3. Diffing    — a symbol counts as new when its name is absent from the
                  pre-patch file; for a type that already existed, only its
                  genuinely new public members are surfaced (``Method`` for a
                  callable, ``Field`` for a field or enum constant).
                  Types compare by bare name, MEMBERS by ``name#arity``
                  (src/lang/base.py CONTRACT 2) so a newly added public
                  overload is not masked by its existing namesake.

"PUBLIC" IS EXACT IN JAVA, UNLIKE PYTHON
----------------------------------------
The Python original has to guess: it calls a name private when it starts with a
single underscore (``_x``, ``__x``) and re-admits dunders (``__init__``) by hand,
because Python has no access control -- ``_x`` is a *convention*, and a module
can still export it.  Java has real access modifiers, so the API surface is
decidable from the syntax tree, and this module decides it from ``modifiers``:

  * ``public``    -> in the API surface.
  * ``protected`` -> in the API surface (subclass-visible => part of the
                     contract a caller/extender can rely on).
  * ``private``   -> never.
  * package-private (no access modifier) -> excluded by default, because it is
    not reachable outside the declaring package; ``--include-package-private``
    flips this for repos that treat the package as the unit of API.

  * Two grammatical exceptions, where Java's *implicit* modifiers matter and the
    ``modifiers`` node is usually absent from the source: every member of an
    ``interface_declaration`` and of an ``annotation_type_declaration`` is
    implicitly public, and every ``enum_constant`` is implicitly public.  These
    are treated as public even with no ``modifiers`` node.  A member explicitly
    marked ``private`` inside an interface (legal since Java 9) is still dropped.

  * ``constructor_declaration`` is reported as a member named after the type
    (Java's constructor spelling), the closest analogue of Python ``__init__``.

DOCSTRING EXTRACTION IS STRUCTURALLY DIFFERENT
----------------------------------------------
Python's docstring is the first string statement *inside* the body, reachable
via ``ast.get_docstring``.  A Javadoc comment is a ``block_comment`` node that
*precedes* the declaration as a sibling (before its ``modifiers``/annotations),
so it is found by walking previous siblings, not by descending into the body.
Only ``/** ... */`` comments count as Javadoc; ``/* ... */`` is ignored.  The
leading ``*`` of each line, inline ``{@link ...}`` wrappers and block tags
(``@param`` / ``@return`` / ...) are stripped, and only the first paragraph is
kept -- mirroring the original's ``_first_para``.

OUTPUT SCHEMA (identical keys to the Python original)
-----------------------------------------------------
    {
        "type":           "Class" | "Function" | "Method" | "Field",
        "name":           str,      # bare Java identifier
        "file_path":      str,      # repo-relative path
        "signature":      str,      # declaration header, no body, no comments
        "docstring":      str,      # first Javadoc paragraph, or ""
        "class_context":  str,      # containing type name, or ""
        "bases":          [str],    # only for type=="Class": extends + implements
        "public_methods": [{"name", "signature", "docstring"}],
        "entity_kind":    str,      # NEW, Java-only: class|interface|enum|
                                    # record|annotation  (only on "Class")
    }

``"Function"`` never occurs in Java output -- Java has no top-level functions --
but the key stays in the union so a downstream consumer written against the
Python schema needs no change.  ``"Field"`` is the Java-only addition: a public
field or enum constant added to a type that ALREADY existed (Java's API surface
includes ``public static final`` constants and enum constants, Python's
``public_methods`` never did).  Members of a brand-new type are grouped under
that type's ``public_methods`` (see ``_group_members``) and are not emitted
separately, whatever their kind.

Standalone usage (for inspection/debugging):
    python identity_selection/extract_public_symbols_java.py \\
        --instance_id <id> \\
        --input data/java/swebench_multilingual_java.jsonl \\
        --repos repos/java_repos

    # or, with no repo at all, dump the public API of one file:
    python identity_selection/extract_public_symbols_java.py --file Foo.java
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from tree_sitter_languages import get_parser
from unidiff import PatchSet

# ---------------------------------------------------------------------------
# tree-sitter plumbing
# ---------------------------------------------------------------------------

_PARSER = None


def _parser():
    """Memoised Java parser (get_parser re-reads the shared library each call)."""
    global _PARSER
    if _PARSER is None:
        _PARSER = get_parser("java")
    return _PARSER


# Declarations that introduce a *type* namespace.
TYPE_NODES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}

# Declarations that introduce a *callable* member.
CALLABLE_NODES = {
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
    "annotation_type_element_declaration",
}

# Declarations that introduce a *field* member.
# (interfaces spell their fields `constant_declaration`, classes `field_declaration`)
FIELD_NODES = {"field_declaration", "constant_declaration"}

# Bodies whose members are implicitly public even with no `modifiers` node.
_IMPLICITLY_PUBLIC_OWNERS = {"interface_declaration", "annotation_type_declaration"}

# Every body node that can hold members, per type kind.
_BODY_TYPES = {
    "class_body",
    "interface_body",
    "enum_body",
    "enum_body_declarations",
    "annotation_type_body",
}


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _child_of_type(node, *types: str):
    for child in node.children:
        if child.type in types:
            return child
    return None


def _name_of(node) -> str:
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named)
    ident = _child_of_type(node, "identifier")
    return _text(ident) if ident is not None else ""


def _arity(node) -> int:
    """
    Declared parameter count -- the member-identity discriminator for Java
    overloads (src/lang/base.py CONTRACT 2: callables are keyed "name#arity").
    A `receiver_parameter` (`void m(C this, int x)`) is not an argument and is
    not counted.  A field, enum constant or compact constructor has arity 0.
    """
    params = node.child_by_field_name("parameters") or _child_of_type(node, "formal_parameters")
    if params is None:
        return 0
    return sum(1 for c in params.children
               if c.type in ("formal_parameter", "spread_parameter"))


# ---------------------------------------------------------------------------
# Access control -- the part Python cannot do precisely
# ---------------------------------------------------------------------------

def _modifier_words(node) -> set[str]:
    mods = _child_of_type(node, "modifiers")
    if mods is None:
        return set()
    # `modifiers` mixes anonymous keyword tokens (public/static/final/...) with
    # named annotation nodes (marker_annotation/annotation); keep the keywords.
    return {c.type for c in mods.children if not c.is_named}


def is_public_api(node, owner_type: Optional[str] = None,
                  include_package_private: bool = False) -> bool:
    """
    True when `node` belongs to the API surface of its compilation unit.

    Java's access modifiers make this exact, unlike Python's `_name` convention:
      public / protected  -> yes
      private             -> no
      (none)              -> package-private: no, unless the owning body makes
                             members implicitly public (interface / @interface),
                             or --include-package-private was passed.
    """
    words = _modifier_words(node)
    if "private" in words:
        return False
    if "public" in words or "protected" in words:
        return True
    if owner_type in _IMPLICITLY_PUBLIC_OWNERS:
        return True  # JLS: interface & annotation members are implicitly public
    if node.type == "enum_constant":
        return True  # enum constants are implicitly public static final
    return include_package_private


# ---------------------------------------------------------------------------
# Javadoc -- a preceding block_comment, not a first statement inside the body
# ---------------------------------------------------------------------------

_JAVADOC_TAG_RE = re.compile(r"^\s*@\w+")
_INLINE_TAG_RE = re.compile(r"\{@\w+\s+([^}]*)\}")
_HTML_TAG_RE = re.compile(r"</?(?:p|br|code|b|i|em|tt|pre|ul|ol|li)\s*/?>", re.I)


def _javadoc_of(node) -> str:
    """
    Return the first paragraph of the Javadoc attached to `node`, or "".

    Structural note: unlike a Python docstring (first string statement INSIDE
    the body), Javadoc is a sibling `block_comment` that PRECEDES the whole
    declaration -- including its annotations and `modifiers`.  Line comments in
    between are skipped; any other node breaks the association.
    """
    sib = node.prev_sibling
    while sib is not None and sib.type == "line_comment":
        sib = sib.prev_sibling
    if sib is None or sib.type != "block_comment":
        return ""
    raw = _text(sib)
    if not raw.startswith("/**"):
        return ""  # a plain /* ... */ block is not Javadoc
    body = raw[3:]
    if body.endswith("*/"):
        body = body[:-2]

    lines: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if _JAVADOC_TAG_RE.match(line):
            break  # @param/@return/... end the description
        lines.append(line)

    text = "\n".join(lines).strip()
    if not text:
        return ""
    # First paragraph only (mirrors the Python original's _first_para).
    para = re.split(r"\n\s*\n", text)[0]
    para = _INLINE_TAG_RE.sub(r"\1", para)
    para = _HTML_TAG_RE.sub(" ", para)
    return re.sub(r"\s+", " ", para).strip()


# ---------------------------------------------------------------------------
# Signatures -- header only, body stripped
# ---------------------------------------------------------------------------

def _strip_comments_ws(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _signature(node) -> str:
    """
    Header of a declaration: everything from its first token up to (but not
    including) the body / the terminating `;`.

    The Python original slices source lines from `node.lineno` to the line
    before the first body statement.  Java's body is an explicit child node
    (`class_body` / `block` / `constructor_body` / `;`), so the cut is exact
    instead of line-based.
    """
    stop_types = _BODY_TYPES | {"block", "constructor_body", ";"}
    end = node.end_byte
    for child in node.children:
        if child.type in stop_types:
            end = child.start_byte
            break
    raw = node.text[: end - node.start_byte].decode("utf-8", errors="replace")
    return _strip_comments_ws(raw)


def _bases_of(node) -> list[str]:
    """extends + implements, as flat type names (Python original: ast.unparse(base))."""
    bases: list[str] = []
    superclass = node.child_by_field_name("superclass") or _child_of_type(node, "superclass")
    if superclass is not None:
        bases.append(_strip_comments_ws(_text(superclass)).removeprefix("extends ").strip())
    # class -> `super_interfaces`; interface -> `extends_interfaces`
    # (interface_declaration exposes NO `interfaces` field, hence the child scan)
    for holder_type in ("super_interfaces", "extends_interfaces", "interfaces"):
        holder = _child_of_type(node, holder_type)
        if holder is None:
            continue
        type_list = _child_of_type(holder, "type_list")
        source = type_list if type_list is not None else holder
        for child in source.children:
            if child.is_named and child.type not in ("modifiers",):
                bases.append(_strip_comments_ws(_text(child)))
    return [b for b in bases if b]


# ---------------------------------------------------------------------------
# Member enumeration
# ---------------------------------------------------------------------------

def _body_of(type_node):
    body = type_node.child_by_field_name("body")
    if body is not None:
        return body
    return _child_of_type(type_node, *sorted(_BODY_TYPES))


def _member_nodes(body):
    """Direct members of a type body (descends through `enum_body_declarations`)."""
    if body is None:
        return
    for child in body.children:
        if child.type == "enum_body_declarations":
            yield from _member_nodes(child)
        elif child.is_named:
            yield child


# An inline initializer can be an entire anonymous class (gson has a 1067-char
# one).  Keep short initializers, drop long ones -- a signature is a header.
_MAX_INITIALIZER = 120


def _field_entries(node, owner_type: str, include_package_private: bool) -> list[dict]:
    """
    One entry per `variable_declarator`: `public int a = 1, b = 2;` declares two
    fields, so it yields two entries, each with its own reconstructed header
    (`public int a = 1` / `public int b = 2`) rather than the shared source line.
    """
    if not is_public_api(node, owner_type, include_package_private):
        return []
    mods = _child_of_type(node, "modifiers")
    prefix_parts = []
    if mods is not None:
        prefix_parts.append(_strip_comments_ws(_text(mods)))
    type_node = node.child_by_field_name("type")
    if type_node is not None:
        prefix_parts.append(_strip_comments_ws(_text(type_node)))
    prefix = " ".join(p for p in prefix_parts if p)

    doc = _javadoc_of(node)
    out = []
    for decl in node.children:
        if decl.type != "variable_declarator":
            continue
        name = _text(decl.child_by_field_name("name"))
        sig = f"{prefix} {name}".strip()
        value = decl.child_by_field_name("value")
        if value is not None:
            value_text = _strip_comments_ws(_text(value))
            if len(value_text) <= _MAX_INITIALIZER:
                sig = f"{sig} = {value_text}"
        out.append({"name": name, "signature": sig, "docstring": doc,
                    "_key": name, "_type": "Field"})
    return out


def _group_members(type_node, include_package_private: bool) -> list[dict]:
    """
    Public members of a type, one level deep -- mirrors the Python original's
    `ast.iter_child_nodes(node)` scan for FunctionDef children of a ClassDef.
    Nested types are NOT recursed into (same as the original skipping nested
    classes).  Constructors, enum constants and public fields are included:
    in Java they are as much of the API surface as methods are.

    Each member carries a private `_key` -- `name#arity` for callables, bare
    `name` otherwise -- used only by `diff_public_symbols` to tell overloads
    apart (src/lang/base.py CONTRACT 2).  It is stripped before emit, so the
    output schema stays identical to the Python original's.
    """
    owner_type = type_node.type
    members: list[dict] = []
    for member in _member_nodes(_body_of(type_node)):
        if member.type in CALLABLE_NODES:
            if not is_public_api(member, owner_type, include_package_private):
                continue
            name = _name_of(member)
            members.append({
                "name": name,
                "signature": _signature(member),
                "docstring": _javadoc_of(member),
                "_key": f"{name}#{_arity(member)}",
                "_type": "Method",
            })
        elif member.type in FIELD_NODES:
            members.extend(_field_entries(member, owner_type, include_package_private))
        elif member.type == "enum_constant":
            name = _name_of(member)
            members.append({
                "name": name,
                # `_signature` stops at the constant's optional class_body, so
                # `FOO { ... 700 chars ... }` renders as just `FOO`.
                "signature": _signature(member),
                "docstring": _javadoc_of(member),
                "_key": name,
                "_type": "Field",
            })
    return members


_PRIVATE_MEMBER_KEYS = ("_key", "_type")


def _strip_keys(members: list[dict]) -> list[dict]:
    return [{k: v for k, v in m.items() if k not in _PRIVATE_MEMBER_KEYS}
            for m in members]


# ---------------------------------------------------------------------------
# File-level public symbol extraction
# ---------------------------------------------------------------------------

def _top_level_types(root):
    """Top-level type declarations of a compilation unit (children of `program`)."""
    for child in root.children:
        if child.type in TYPE_NODES:
            yield child


def _parse_public_symbols_keyed(source: str,
                                include_package_private: bool = False) -> list[dict]:
    """`parse_public_symbols`, but members keep their private `_key`."""
    tree = _parser().parse(source.encode("utf-8"))
    symbols: list[dict] = []
    for type_node in _top_level_types(tree.root_node):
        if not is_public_api(type_node, None, include_package_private):
            continue
        symbols.append({
            "type": "Class",
            "name": _name_of(type_node),
            "signature": _signature(type_node),
            "docstring": _javadoc_of(type_node),
            "class_context": "",
            "bases": _bases_of(type_node),
            "public_methods": _group_members(type_node, include_package_private),
            "entity_kind": TYPE_NODES[type_node.type],
        })
    return symbols


def parse_public_symbols(source: str, include_package_private: bool = False) -> list[dict]:
    """
    Return every public top-level symbol of one Java compilation unit.

    Java equivalent of the original's `_parse_public_symbols`.  Parse errors do
    not raise: tree-sitter always yields a tree, and a tree containing ERROR
    nodes simply produces fewer symbols -- matching the original's
    `except SyntaxError: return []` in spirit while salvaging what parsed.
    """
    return [
        {**sym, "public_methods": _strip_keys(sym["public_methods"])}
        for sym in _parse_public_symbols_keyed(source, include_package_private)
    ]


def diff_public_symbols(old_source: Optional[str], new_source: str,
                        include_package_private: bool = False) -> list[dict]:
    """
    Public symbols present in `new_source` but absent from `old_source`.

    Same two-tier rule as the Python original:
      * a top-level type whose name is new       -> emitted whole (type "Class")
      * a top-level type that already existed    -> emit only its genuinely new
                                                    public members (type "Method")

    Types are compared by bare name (a type cannot be overloaded).  MEMBERS are
    compared by `name#arity`, the CONTRACT 2 discriminator: keying members by
    bare name -- what the Python original does, correctly, since Python has no
    overloading -- would hide a newly added public overload
    (`foo(String, int)` next to an existing `foo(String)`), which is a genuine
    API addition.  Two overloads that differ only in parameter TYPES at the same
    arity are still indistinguishable here; see the report's gap list.
    """
    old_syms = _parse_public_symbols_keyed(old_source or "", include_package_private)
    new_syms = _parse_public_symbols_keyed(new_source, include_package_private)

    old_top_names = {s["name"] for s in old_syms}
    old_type_members = {
        s["name"]: {m["_key"] for m in s.get("public_methods", [])}
        for s in old_syms
        if s["type"] == "Class"
    }

    results: list[dict] = []
    for sym in new_syms:
        if sym["name"] not in old_top_names:
            sym = {**sym, "public_methods": _strip_keys(sym.get("public_methods", []))}
            results.append(sym)
        elif sym["type"] == "Class" and sym["name"] in old_type_members:
            known = old_type_members[sym["name"]]
            for m in sym.get("public_methods", []):
                if m["_key"] in known:
                    continue
                results.append({
                    # A Java type's API surface holds fields and enum constants
                    # as well as callables; label each for what it is instead of
                    # calling every new member a "Method".
                    "type": m.get("_type", "Method"),
                    "name": m["name"],
                    "signature": m["signature"],
                    "docstring": m["docstring"],
                    "class_context": sym["name"],
                    "file_path": sym.get("file_path", ""),
                    "public_methods": [],
                })
    return results


# ---------------------------------------------------------------------------
# Git helpers (same shape as the Python original)
# ---------------------------------------------------------------------------

def _run(cmd, cwd, check=True):
    result = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


def checkout(repo_dir: Path, commit: str):
    try:
        _run(["git", "checkout", "--quiet", commit], cwd=repo_dir)
    except subprocess.CalledProcessError:
        _run(["git", "reset", "--hard"], cwd=repo_dir, check=False)
        _run(["git", "clean", "-fdx", "--quiet"], cwd=repo_dir, check=False)
        _run(["git", "checkout", "--quiet", commit], cwd=repo_dir)


def apply_patch(repo_dir: Path, patch_content: str):
    patch_file = repo_dir / "_tmp_patch_java.diff"
    patch_file.write_text(patch_content, encoding="utf-8")
    try:
        _run(["git", "apply", "_tmp_patch_java.diff"], cwd=repo_dir)
    finally:
        patch_file.unlink(missing_ok=True)


def _get_default_branch(repo_dir: Path) -> str:
    result = _run(["git", "remote", "show", "origin"], cwd=repo_dir, check=False)
    for line in result.stdout.splitlines():
        if "HEAD branch:" in line:
            return line.split()[-1]
    return "main"


def reset_repo(repo_dir: Path, commit: str):
    _run(["git", "reset", "--hard", "HEAD"], cwd=repo_dir, check=False)
    _run(["git", "clean", "-fdx", "--quiet"], cwd=repo_dir, check=False)
    default_branch = _get_default_branch(repo_dir)
    result = _run(["git", "checkout", "--quiet", default_branch], cwd=repo_dir, check=False)
    if result.returncode != 0:
        _run(["git", "checkout", "-b", default_branch, f"origin/{default_branch}"],
             cwd=repo_dir, check=False)


# ---------------------------------------------------------------------------
# Per-instance extraction (public API of this module)
# ---------------------------------------------------------------------------

def extract_public_symbols(instance: dict, repo_dir: Path,
                           include_package_private: bool = False) -> list[dict]:
    """
    Java entry point, signature-compatible with the Python original.

    Returns [] when the instance touches no `.java` file, when the patch cannot
    be parsed, or when the patch does not apply.
    """
    patch_content = instance.get("patch", "") or instance.get("feature_patch", "") or ""
    base_commit = instance["base_commit"]

    if not patch_content.strip():
        return []

    checkout(repo_dir, base_commit)

    old_sources: dict[str, Optional[str]] = {}
    try:
        patch_set = PatchSet(patch_content)
    except Exception:
        reset_repo(repo_dir, base_commit)
        return []

    for hunk in patch_set:
        fpath = hunk.path
        if not fpath.endswith(".java"):
            continue
        full = repo_dir / fpath
        old_sources[fpath] = (
            full.read_text(encoding="utf-8", errors="replace") if full.is_file() else None
        )

    if not old_sources:
        reset_repo(repo_dir, base_commit)
        return []

    try:
        apply_patch(repo_dir, patch_content)
    except subprocess.CalledProcessError:
        reset_repo(repo_dir, base_commit)
        return []

    symbols: list[dict] = []
    for fpath, old_src in old_sources.items():
        new_full = repo_dir / fpath
        if not new_full.is_file():
            continue
        new_src = new_full.read_text(encoding="utf-8", errors="replace")
        for sym in diff_public_symbols(old_src, new_src, include_package_private):
            sym["file_path"] = fpath
            symbols.append(sym)

    reset_repo(repo_dir, base_commit)
    return symbols


def repo_slug_to_dir(repo: str, repos_root: Path) -> Path:
    if "/" in repo:
        owner, name = repo.split("/", 1)
        candidates = [repos_root / name, repos_root / f"{owner}__{name}",
                      repos_root / owner / name]
    else:
        candidates = [repos_root / repo]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Cannot find local repo for '{repo}' under {repos_root}.")


# ---------------------------------------------------------------------------
# CLI for debugging
# ---------------------------------------------------------------------------

def _format_symbol(sym: dict) -> str:
    lines = [f"Type: {sym['type']}"]
    lines.append(f"Name: {sym['name']}")
    if sym.get("entity_kind"):
        lines.append(f"Kind: {sym['entity_kind']}")
    if sym.get("file_path"):
        lines.append(f"Path: {sym['file_path']}")
    if sym.get("class_context"):
        lines.append(f"Class: {sym['class_context']}")
    if sym.get("signature"):
        lines.append(f"Signature: {sym['signature']}")
    if sym.get("docstring"):
        lines.append(f"Javadoc: {sym['docstring']}")
    if sym.get("bases"):
        lines.append(f"Bases: {', '.join(sym['bases'])}")
    if sym.get("public_methods"):
        names = ", ".join(m["name"] for m in sym["public_methods"])
        lines.append(f"Public members: {names}")
    return "\n  ".join(lines)


def main():
    p = argparse.ArgumentParser(
        description="Extract public Java symbols from a gold patch (debug)")
    p.add_argument("--instance_id")
    p.add_argument("--input", default="data/java/swebench_multilingual_java.jsonl")
    p.add_argument("--repos", default="repos/")
    p.add_argument("--file", type=Path,
                   help="Skip the repo entirely; dump the public API of one .java file.")
    p.add_argument("--include-package-private", action="store_true",
                   help="Treat package-private members as API too.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = p.parse_args()

    if args.file:
        symbols = parse_public_symbols(
            args.file.read_text(encoding="utf-8", errors="replace"),
            args.include_package_private,
        )
        for sym in symbols:
            sym["file_path"] = str(args.file)
    else:
        if not args.instance_id:
            sys.exit("Either --file or --instance_id is required.")
        instance = None
        with open(args.input) as f:
            for line in f:
                row = json.loads(line)
                if row.get("instance_id") == args.instance_id:
                    instance = row
                    break
        if not instance:
            sys.exit(f"Instance not found: {args.instance_id}")
        repo_dir = repo_slug_to_dir(instance["repo"], Path(args.repos))
        symbols = extract_public_symbols(instance, repo_dir, args.include_package_private)

    if args.json:
        print(json.dumps(symbols, indent=2, ensure_ascii=False))
        return

    print(f"Found {len(symbols)} public symbol(s):\n")
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}] {_format_symbol(sym)}")
        print()


if __name__ == "__main__":
    main()
