#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
NoCode identity selection, JAVA — port of identity_selection/nocode.py
(itself a faithful port of NoCode-bench's construction/augmentation/augment.py).

ADDITIVE ONLY.  This file does not import-and-mutate anything; the language
neutral constants (SEPARATOR, AUGMENTATION_HEADER) and the git shell helper are
imported *read-only* from the frozen ``nocode`` module so the two encodings can
never drift.

------------------------------------------------------------------------------
The algorithm is unchanged from nocode.py
------------------------------------------------------------------------------
  1. git clean -fdx -> git reset --hard HEAD -> git checkout <base_commit>
  2. parse every patched source file (BEFORE)
  3. write the patch to PATCH_FILE, ``git apply`` it (no --check, errors ignored)
  4. parse every patched source file (AFTER)
  5. new entities = AFTER minus BEFORE, matched on the (type, name) PAIR
  6. feature entities are kept only if their NAME also occurs among the test
     patch's new entities (name intersection, not pair intersection)
  7. new source files from the impl patch are appended AFTER that filter,
     encoded as SEPARATOR.join([path, "file", path])
  8. anything whose name already appears verbatim in doc_content is dropped
  9. output schema is unchanged: {**example, "augmentations": {header, data}}

Everything language-specific is confined to three places, all below:
  * SOURCE_SUFFIX      ".py"  -> ".java"
  * get_all_identifiers        rewritten for the Java grammar
  * the error-message scanner  rewritten for `throw` / JUnit / AssertJ / Truth

------------------------------------------------------------------------------
Java -> nocode's flat vocabulary {"function", "class", "field", "error_msg"}
------------------------------------------------------------------------------
Verified against tree_sitter_languages 1.10.2 / tree-sitter 0.21.3.

Java declaration NAMES are plain ``identifier`` nodes (``type_identifier`` is
only ever a type *reference*), so augment.py's parent-type dispatch ports over
with ONE added guard — the node must also be the parent's ``name`` FIELD:

    node is the `name` field of                      -> flat type
      method_declaration, constructor_declaration,      "function"
      compact_constructor_declaration
      class_declaration, interface_declaration,         "class"
      enum_declaration, record_declaration,
      annotation_type_declaration
    anything else (identifier or type_identifier)       "field"

The ``name``-field guard is NOT optional.  ``public Ratio divide(int a)`` hangs
the RETURN TYPE (``type_identifier 'Ratio'``) directly under
``method_declaration``, so parent-type alone reports a spurious
("function", "Ratio").  Python has no separate return-type child, so augment.py
never needed the guard.  Verified: this bug was live until the guard was added.

``type_identifier`` is collected on purpose.  In Python a type reference IS an
``identifier`` (``x: Foo`` / ``Foo()``), so augment.py already records it as
"field"; excluding Java's separate node would make a patch that introduces
``NewThing t = new NewThing()`` invisible.  Java also names the enum constant,
the field declarator, and the formal parameter with a bare ``identifier`` whose
parent is not a declaration node, so those land on "field" exactly as their
Python counterparts do.

error_msg has four anchors (Python has two: ``raise_statement`` and the
``with_clause`` holding ``pytest.raises``):

    A. throw_statement            throw new X("msg")            <- impl side
    B. method_invocation named in _EXC_MESSAGE_METHODS          <- AssertJ /
       (assertThrows, assertThatThrownBy, hasMessage, ...)         JUnit fluent
    C. catch_clause               the try { f(); fail(); }      <- JUnit 4
       -> any assert*/fail call    catch (X e) { assertEquals("msg", ...) }
    D. method_invocation named in _MESSAGE_TERMINALS whose RECEIVER CHAIN
       calls a message accessor:                                 <- Google Truth
       assertThat(e).hasMessageThat().isEqualTo("msg")              / AssertJ
       assertThat(e.getMessage()).isEqualTo("msg")

B, C and D are a DESIGNED analogue, not a mechanical port: Java has no single
dominant `pytest.raises(..., match=...)` idiom that carries the expected
message in one node, so the three dominant JUnit/AssertJ/Truth spellings each
need their own anchor.  D was added after observing that Google Truth's
``assertThat(e).hasMessageThat().isEqualTo(...)`` is the majority idiom in gson
and was invisible to B.  All four anchors only ever ADD to the test-side name
set, so step 6's filter is monotone — a missed anchor loses hints, it never
invents them.  See "Known asymmetries" at the bottom of this docstring.

The "last string wins" quirk of augment.py's ``traverse()`` is preserved:
``string_node`` is reassigned on every terminal hit, so the LAST fragment in
document order is returned, so ``"a " + x + " b"`` yields ``" b"`` in both
languages.  ONE deviation is deliberate: tree-sitter-java splits a literal on
every ``escape_sequence`` while tree-sitter-python does not, so the winning
fragment is widened to its parent ``string_literal`` (see ``_literal_payload``)
and ``"x\\ny"`` yields ``"x\\ny"`` in both languages instead of ``"y"``.

------------------------------------------------------------------------------
flat_skip_scopes
------------------------------------------------------------------------------
Run the Python scanner shape over a Java parse and every component of
``package com.example.app;`` becomes a "field" entity ('com', 'example', 'app').
Python has no package statement at all, so skipping ``package_declaration``
restores symmetry rather than breaking it.  ``import_declaration`` is NOT
skipped by default: ``import java.util.List`` is the analogue of
``from java.util import List``, and augment.py keeps both the qualifier
components and the imported name for Python.  Override with
``--flat-skip-scopes`` ("" disables, comma-separated to add more).

------------------------------------------------------------------------------
Known asymmetries vs. the Python path (disclosed, not fixed)
------------------------------------------------------------------------------
* Overloading is invisible here.  This module's vocabulary is nocode's flat
  (type, name) pair; ``doThing(String)`` and ``doThing(int)`` collapse to one
  ("function", "doThing") entity.  That is CORRECT for this baseline — the
  hint it renders is a bare name — and is deliberately different from the
  ``name#arity`` catalogue key that src/lang/base.py mandates for step 1.
* Java constructors are reported as "function" under the class's own name, so
  a new class usually contributes both ("class", "Foo") and ("function", "Foo").
  Python's ``__init__`` contributes ("function", "__init__") instead.
* error_msg round-trips far less often in Java.  The impl side writes
  ``throw new X("msg")`` but the test side usually asserts on
  ``e.getMessage()`` in a separate statement, so step 6's name intersection
  drops the message unless anchor B, C or D catches it.  Worse, both sides
  routinely build the message by concatenation (``"Failed parsing '" + s +
  "' as URL; at path "``), and the inherited last-wins rule truncates each side
  to a DIFFERENT trailing fragment, so those never intersect.  Measured on
  gson: error_msg entities are produced on both sides but survive step 6 only
  when the message is a single unconcatenated literal.
* Javadoc is not read at all (nocode never read docstrings either).

------------------------------------------------------------------------------
What is reused from java_lang.py, and what is deliberately NOT
------------------------------------------------------------------------------
REUSED — the verified grammar TABLES, so the two Java ports cannot drift on a
fact about the grammar:
    JAVA_EXTENSIONS, IDENTIFIER_NODES, TYPE_DECL_NODES, CALLABLE_DECL_NODES,
    STRING_FRAGMENT_NODES, JUNIT_THROWS_ASSERTIONS,
    NON_TYPE_TYPE_IDENTIFIERS, get_java_parser

NOT REUSED — two functions that look like what this file needs but encode a
different contract.  Both were read before being rejected:

  * ``java_lang.get_raise_string`` / ``_walk_to_fragment`` are FIRST-wins:
    ``if found["node"] is not None: return`` stops at the first fragment.
    augment.py is LAST-wins — its ``traverse()`` REASSIGNS ``string_node`` on
    every terminal hit — so adopting it would silently change every
    concatenated message (``"a " + x + " b"`` -> ``"a "`` instead of ``" b"``)
    and break parity with the Python port this file must mirror.  It also does
    not prune lambdas, so ``assertThrows(X.class, () -> f("inner"), "outer")``
    returns ``"inner"``.  That is fine for defuse2's purposes; it is wrong here.
  * ``java_lang.classify_entity_type`` returns src/lang/base.py's vocabulary
    {function, class, variable, attribute}.  nocode's vocabulary is
    {function, class, field, error_msg} and disagrees in two places by design:
    a ``type_identifier`` is "class" there and "field" here, and a
    ``method_invocation`` name is "function" there and "field" here (augment.py
    types a Python call site as "field").

So ``get_all_identifiers``, ``_last_string_fragment`` and ``_literal_payload``
stay local ON PURPOSE.  They are not duplication to be consolidated later.

------------------------------------------------------------------------------
Usage (run from the repo root, with the repo venv active)
------------------------------------------------------------------------------
    python identity_selection/nocode_java.py \
        --input  data/java/swebench_multilingual_java.jsonl \
        --output identity_selection/results_selection/nocode_sel/raw/multilingual_java_nocode.jsonl \
        --repos  repos/multilingual_java_repos

    # single instance
    python identity_selection/nocode_java.py -i ... -o /tmp/x.jsonl -r ... \
        --instance-id google__gson-2134
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tqdm import tqdm
from unidiff import PatchSet

from utils import load_jsonl, dump_jsonl, find_repo_dir, get_impl_patch, get_test_patch, get_doc_content

# Language-neutral constants + the git helper come from the frozen Python port
# so the two encodings cannot drift.  Importing nocode has no side effects
# beyond building the Python parser (its main() is under a __main__ guard).
from nocode import SEPARATOR, AUGMENTATION_HEADER, run_cmd  # noqa: F401

# Verified Java node tables are shared with defuse2_java via java_lang so the
# grammar facts live in exactly one place.  Only TABLES are reused — see
# "What is deliberately NOT reused from java_lang" in the docstring above.
from java_lang import (
    JAVA_EXTENSIONS,
    IDENTIFIER_NODES,
    TYPE_DECL_NODES,
    CALLABLE_DECL_NODES,
    STRING_FRAGMENT_NODES,
    JUNIT_THROWS_ASSERTIONS,
    NON_TYPE_TYPE_IDENTIFIERS,
    get_java_parser,
)

ts_parser = get_java_parser()

SOURCE_SUFFIX = JAVA_EXTENSIONS[0]
PATCH_FILE = str(Path(__file__).parent / "nocode_java_identity.patch")

# --------------------------------------------------------------------------
# Java grammar constants (verified with tree_sitter_languages 1.10.2)
# --------------------------------------------------------------------------

#: a node that IS the `name` field of one of these declares a callable
#: (java_lang.CALLABLE_DECL_NODES also covers annotation_type_element_declaration,
#: i.e. ``@interface Marker { String value(); }``)
_FUNCTION_PARENTS = CALLABLE_DECL_NODES

#: a node that IS the `name` field of one of these declares a type
_CLASS_PARENTS = TYPE_DECL_NODES

#: node types that carry a recordable identifier (type_identifier is always
#: a type *reference*, so it can only ever be classified "field")
_NAME_NODE_TYPES = IDENTIFIER_NODES

#: `var x = ...` parses as a type_identifier but names no entity; recording it
#: would put the literal token "var" in the suggested-name list.  Python has no
#: analogue, so dropping it restores symmetry rather than breaking it.
_SKIP_NAMES = NON_TYPE_TYPE_IDENTIFIERS

#: subtrees not descended into during flat identifier collection
DEFAULT_FLAT_SKIP_SCOPES = ("package_declaration",)

#: terminal string payload nodes (the grammar excludes the surrounding quotes)
_STRING_FRAGMENT_TYPES = STRING_FRAGMENT_NODES

#: throw_statement -> object_creation_expression -> argument_list -> ... -> fragment
_THROW_PATH = ("throw_statement", "object_creation_expression", "argument_list",
               "string_literal", "string_fragment")

#: anchored on the method_invocation itself, so slot 0 is unconstrained
_INVOKE_PATH = (None, "method_invocation", "argument_list",
                "string_literal", "string_fragment")

#: descending into these would pick up a string from the code under test
#: (``assertThrows(X.class, () -> obj.doIt("inner"), "outer msg")``)
_ARG_SKIP_TYPES = frozenset({"lambda_expression", "method_reference"})

#: invocation names that carry an EXPECTED EXCEPTION MESSAGE as an argument.
#: Derived from java_lang's shared set so the two ports cannot drift, plus the
#: spellings nocode additionally needs (Truth's hasMessageThat, the AssertJ
#: variants defuse2 does not use).
_EXC_MESSAGE_METHODS = JUNIT_THROWS_ASSERTIONS | frozenset({
    "hasMessageThat",              # Google Truth
    "hasMessageMatching",          # AssertJ
    "hasMessageContainingAll",     # AssertJ
    "withMessageStartingWith",     # AssertJ
    "withFailMessage",             # AssertJ
})

#: inside a catch_clause, these calls carry the asserted message
_CATCH_ASSERT_PREFIXES = ("assert",)
_CATCH_ASSERT_NAMES = frozenset({"fail"})

#: Google Truth / AssertJ chain: assertThat(e).hasMessageThat().isEqualTo("msg")
#: The message sits on the TERMINAL call, so the terminal only counts when a
#: message accessor appears somewhere in its receiver chain.
_MESSAGE_CHAIN_MARKERS = frozenset({
    "hasMessageThat", "getMessage", "getLocalizedMessage",
})
_MESSAGE_TERMINALS = frozenset({
    "isEqualTo", "contains", "startsWith", "endsWith", "matches", "isAnyOf",
})


# ---------------------------------------------------------------------------
# AST: error message extraction — Java analogue of augment.py _get_raise_string
# ---------------------------------------------------------------------------

def _last_string_fragment(node, path: Sequence[Optional[str]], pos: int,
                          skip_types=frozenset()) -> Optional[str]:
    """
    Positional descent, mirroring augment.py's traverse():

      * positions 0..len(path)-3 are type-gated against ``path[p]``
        (a None entry in ``path`` means "do not gate this slot"),
      * deeper positions are unconstrained, so string concatenation
        (``binary_expression``) and nested calls are still reached,
      * every terminal hit REASSIGNS the result, so the LAST fragment in
        document order wins — this is augment.py's behaviour, not an accident.

    ``skip_types`` prunes subtrees; augment.py has no equivalent because a
    Python ``with_clause`` cannot contain the body under test, while a Java
    ``assertThrows(..., () -> f("inner"), "outer")`` can.
    """
    gate_limit = len(path) - 2          # == 3 for a 5-slot path -> gates 0,1,2
    found = None

    def traverse(n, p):
        nonlocal found
        if p < gate_limit and path[p] is not None and n.type != path[p]:
            return
        if n.type in _STRING_FRAGMENT_TYPES:
            found = n
            return
        if n.type in skip_types:
            return
        for child in n.named_children:
            traverse(child, p + 1)

    traverse(node, pos)
    if found is None:
        return None
    return _literal_payload(found)


def _literal_payload(fragment_node) -> str:
    """
    Return the WHOLE payload of the string_literal that owns ``fragment_node``.

    tree-sitter-java splits a literal on every ``escape_sequence``, so
    ``"x\\ny"`` parses as string_fragment('x') + escape_sequence + string_fragment('y')
    and the last-wins rule would return just ``'y'``.  tree-sitter-python does
    NOT split — its ``string_content`` spans the escape — so augment.py returns
    ``'x\\ny'``.  Widening to the parent literal restores that symmetry without
    disturbing the last-wins rule ACROSS literals (``"a " + x + " b"`` still
    yields ``' b'``, because the winning fragment's parent is the ``" b"``
    literal, matching Python).
    """
    parent = fragment_node.parent
    if parent is None or parent.type != "string_literal":
        return fragment_node.text.decode()
    txt = parent.text.decode()
    if len(txt) >= 6 and txt.startswith('"""') and txt.endswith('"""'):
        return txt[3:-3]
    if len(txt) >= 2 and txt.startswith('"') and txt.endswith('"'):
        return txt[1:-1]
    return fragment_node.text.decode()


def _invocation_name(node) -> Optional[str]:
    """Simple name of a method_invocation: ``a.b.doIt(x)`` -> ``doIt``."""
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return name_node.text.decode()


def _iter_descendants(node):
    for child in node.named_children:
        yield child
        yield from _iter_descendants(child)


def _catch_clause_messages(node) -> List[str]:
    """
    JUnit-3/4 idiom:  try { f(); fail(); } catch (X e) { assertEquals("m", ...) }
    Collect one message per assert*/fail call inside the catch body.
    """
    out = []
    for desc in _iter_descendants(node):
        if desc.type != "method_invocation":
            continue
        name = _invocation_name(desc)
        if not name:
            continue
        if name.startswith(_CATCH_ASSERT_PREFIXES) or name in _CATCH_ASSERT_NAMES:
            msg = _last_string_fragment(desc, _INVOKE_PATH, 1,
                                        skip_types=_ARG_SKIP_TYPES)
            if msg is not None:
                out.append(msg)
    return out


def _receiver_mentions_message(node) -> bool:
    """True when the receiver chain of ``node`` calls a message accessor.

    Covers both Truth spellings seen in gson:
        assertThat(e).hasMessageThat().isEqualTo("msg")   -> object is hasMessageThat()
        assertThat(e.getMessage()).isEqualTo("msg")       -> getMessage() sits in the args
    A plain ``assertThat(x).isEqualTo("plain value")`` is correctly ignored.
    """
    receiver = node.child_by_field_name("object")
    if receiver is None:
        return False
    if receiver.type == "method_invocation" and _invocation_name(receiver) in _MESSAGE_CHAIN_MARKERS:
        return True
    for desc in _iter_descendants(receiver):
        if desc.type == "method_invocation" and _invocation_name(desc) in _MESSAGE_CHAIN_MARKERS:
            return True
    return False


def get_error_messages(node) -> List[str]:
    """Return the error-message strings anchored at ``node`` (not recursive)."""
    if node.type == "throw_statement":
        msg = _last_string_fragment(node, _THROW_PATH, 0)
        return [msg] if msg is not None else []

    if node.type == "method_invocation":
        name = _invocation_name(node)
        if name in _EXC_MESSAGE_METHODS or (
            name in _MESSAGE_TERMINALS and _receiver_mentions_message(node)
        ):
            msg = _last_string_fragment(node, _INVOKE_PATH, 1,
                                        skip_types=_ARG_SKIP_TYPES)
            return [msg] if msg is not None else []
        return []

    if node.type == "catch_clause":
        return _catch_clause_messages(node)

    return []


# ---------------------------------------------------------------------------
# AST: flat identifier extraction — Java analogue of get_all_identifers()
# ---------------------------------------------------------------------------

def _is_declared_name(node, parent) -> bool:
    """
    True only when ``node`` is the ``name`` field of its parent declaration.

    Parent-type alone is NOT enough, which is the one place the Python port does
    not transfer.  ``public Ratio divide(int a)`` puts the RETURN TYPE
    (``type_identifier 'Ratio'``) directly under ``method_declaration``, so a
    bare parent-type test reports a spurious ("function", "Ratio").  Python has
    no separate return-type child, so augment.py never hits this.

    ``child_by_field_name('name')`` is present on every declaration node in
    tree-sitter-java (class / interface / enum / record / annotation_type /
    method / constructor / compact_constructor — all verified).  Byte spans are
    compared rather than node identity: ``Node.__eq__`` works but ``is`` does
    not, because each accessor builds a fresh wrapper object.
    """
    name_node = parent.child_by_field_name("name")
    if name_node is None:
        return False
    return (name_node.start_byte == node.start_byte
            and name_node.end_byte == node.end_byte)


def get_all_identifiers(root, flat_skip_scopes: Sequence[str] = DEFAULT_FLAT_SKIP_SCOPES) -> List[dict]:
    """
    Flat (name, type) records over a Java parse tree.
    Types: 'function', 'class', 'field', 'error_msg' — nocode's vocabulary.
    """
    skip = frozenset(flat_skip_scopes or ())
    res: List[dict] = []

    def traverse(node):
        if node.type in skip:
            return

        if node.type in _NAME_NODE_TYPES and node.text.decode() not in _SKIP_NAMES:
            id_type = "field"
            parent = node.parent
            if parent is not None and _is_declared_name(node, parent):
                if parent.type in _FUNCTION_PARENTS:
                    id_type = "function"
                elif parent.type in _CLASS_PARENTS:
                    id_type = "class"
            res.append({
                "name": node.text.decode(),
                "type": id_type,
            })

        for msg in get_error_messages(node):
            res.append({"name": msg, "type": "error_msg"})

        for child in node.named_children:
            traverse(child)

    traverse(root)
    return res


def parse_identifiers(code: str,
                      flat_skip_scopes: Sequence[str] = DEFAULT_FLAT_SKIP_SCOPES) -> List[dict]:
    root = ts_parser.parse(code.encode()).root_node
    return get_all_identifiers(root, flat_skip_scopes)


# ---------------------------------------------------------------------------
# Diff entity extraction — mirrors augment.py's get_diff_entities()
# ---------------------------------------------------------------------------

def get_diff_entities(impl_patch: str, test_patch: str,
                      base_commit: str, repo_dir: str,
                      patch_type: str = "feature",
                      flat_skip_scopes: Sequence[str] = DEFAULT_FLAT_SKIP_SCOPES) -> set:
    """Same control flow as nocode.get_diff_entities; only the suffix and the
    parser differ."""
    def read_code(file_path):
        if not os.path.exists(file_path):
            return ""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    run_cmd("git clean -fdx", repo_dir)
    run_cmd("git reset --hard HEAD", repo_dir)
    run_cmd(f"git checkout {base_commit}", repo_dir)

    patch_content = impl_patch if patch_type == "feature" else test_patch
    patch_set = PatchSet(patch_content)
    patched_files = [i for i in patch_set if i.path.endswith(SOURCE_SUFFIX)]

    diff_ids = {}
    for patched_file in patched_files:
        fpath = patched_file.path
        before_code = read_code(os.path.join(repo_dir, fpath))
        root = ts_parser.parse(before_code.encode()).root_node
        before_ids = get_all_identifiers(root, flat_skip_scopes)
        diff_ids[fpath] = {"before": before_ids}

    with open(PATCH_FILE, "w", encoding="utf-8") as f:
        f.write(patch_content)
    run_cmd(f"git apply {PATCH_FILE}", repo_dir)

    for patched_file in patched_files:
        fpath = patched_file.path
        after_code = read_code(os.path.join(repo_dir, fpath))
        root = ts_parser.parse(after_code.encode()).root_node
        after_ids = get_all_identifiers(root, flat_skip_scopes)
        diff_ids[fpath]["after"] = after_ids

    entity_ids = set()
    for fpath, ids in diff_ids.items():
        old_ids = ids["before"]
        new_ids = ids.get("after", [])
        for new_id in new_ids:
            flag = True
            for old_id in old_ids:
                if new_id["type"] == old_id["type"] and new_id["name"] == old_id["name"]:
                    flag = False
                    break
            if flag:
                entity_ids.add(SEPARATOR.join([fpath, new_id["type"], new_id["name"]]))

    return entity_ids


# ---------------------------------------------------------------------------
# Core per-instance logic — mirrors augment.py's get_new_entities()
# ---------------------------------------------------------------------------

def _resolve_repo_dir(example: dict, repos_dir: Path) -> str:
    """nocode.py uses ``repo.split('/')[-1]`` unconditionally.  Keep that as the
    primary path (identical behaviour when the directory exists) and only fall
    back to utils.find_repo_dir for the owner__name / owner/name layouts."""
    repo = example["repo"]
    primary = repos_dir / repo.split("/")[-1]
    if primary.exists():
        return str(primary)
    return str(find_repo_dir(repo, repos_dir))


def get_new_entities(example: dict, repos_dir: Path,
                     flat_skip_scopes: Sequence[str] = DEFAULT_FLAT_SKIP_SCOPES) -> set:
    repo_dir = _resolve_repo_dir(example, repos_dir)

    impl_patch = get_impl_patch(example)
    test_patch = get_test_patch(example)
    base_commit = example["base_commit"]

    feature_patch_set = PatchSet(impl_patch)
    new_files_entities = [
        {"name": i.path, "type": "file"}
        for i in feature_patch_set.added_files
        if i.path.endswith(SOURCE_SUFFIX)
    ]

    feature_entities = get_diff_entities(impl_patch, test_patch, base_commit,
                                         repo_dir, "feature", flat_skip_scopes)
    test_entities = get_diff_entities(impl_patch, test_patch, base_commit,
                                      repo_dir, "test", flat_skip_scopes)

    test_entities_names = {i.split(SEPARATOR)[-1] for i in test_entities}
    new_ids_filter_by_test = [
        i for i in feature_entities
        if i.split(SEPARATOR)[-1] in test_entities_names
    ]

    new_ids_filter_by_test += [
        SEPARATOR.join([i["name"], i["type"], i["name"]])
        for i in new_files_entities
    ]

    doc_content = get_doc_content(example)
    new_entities = set()
    for i in new_ids_filter_by_test:
        if i.split(SEPARATOR)[-1] not in doc_content:
            new_entities.add(i)

    return new_entities


def process_instance(example: dict, repos_dir: Path,
                     flat_skip_scopes: Sequence[str] = DEFAULT_FLAT_SKIP_SCOPES) -> dict:
    entities = get_new_entities(example, repos_dir, flat_skip_scopes)
    res = []
    for i in entities:
        parts = i.split(SEPARATOR)
        res.append({"type": parts[1], "name": parts[2]})

    result = dict(example)
    result["augmentations"] = {
        "header": AUGMENTATION_HEADER,
        "data": res,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="NoCode identity selection for JAVA — test-filtered new entity hints."
    )
    ap.add_argument("--input", "-i", type=Path, required=True,
                    help="Input JSONL with patch/test_patch/base_commit/repo.")
    ap.add_argument("--output", "-o", type=Path, required=True,
                    help="Output JSONL with augmentations field added.")
    ap.add_argument("--repos", "-r", type=Path, required=True,
                    help="Directory containing cloned Java repos.")
    ap.add_argument("--skip-errors", action="store_true",
                    help="Skip failed instances instead of crashing.")
    ap.add_argument("--instance-id", type=str, default=None,
                    help="Process a single instance_id (for debugging).")
    ap.add_argument("--flat-skip-scopes", type=str,
                    default=",".join(DEFAULT_FLAT_SKIP_SCOPES),
                    help="Comma-separated node types whose subtrees are not "
                         "scanned for identifiers. Pass '' to disable. "
                         f"Default: {','.join(DEFAULT_FLAT_SKIP_SCOPES)}")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")
    if not args.repos.is_dir():
        sys.exit(f"Repos directory not found: {args.repos}")

    flat_skip_scopes = tuple(s for s in args.flat_skip_scopes.split(",") if s.strip())

    examples = load_jsonl(args.input)
    if args.instance_id:
        examples = [e for e in examples if e.get("instance_id") == args.instance_id]
        if not examples:
            sys.exit(f"No instance with id={args.instance_id!r}")

    output_rows = []
    errors = []

    for ex in tqdm(examples, desc="NoCode-Java"):
        iid = ex.get("instance_id", "<unknown>")
        try:
            output_rows.append(process_instance(ex, args.repos, flat_skip_scopes))
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
        print(f"Wrote {len(errors)} errors → {err_path}")

    try:
        os.remove(PATCH_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
