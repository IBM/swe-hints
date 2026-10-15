#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
DefUse Java — the Java port of defuse2.py.

Same public surface as defuse2.py (get_communication_hints /
add_augmentations / --input/--output/--repos-dir/--skip-errors/--instance-id)
and the same output schema::

    {..., "augmentations": {"forward":  {"header": ..., "data": [...]},
                            "backward": {"header": ..., "data": [...]}}}

with ``data`` a name-sorted list of ``{"type": ..., "name": ...}``.

The git/diff/intersection scaffolding is duplicated from defuse2.py rather
than imported, so the Python path is never entered from here.  Java-specific
tree-sitter rules live in ``java_lang.py``.

Like defuse2.py this is the RELAXED variant:
WRITE and READ are collected at ANY nesting depth, with no scope guard.

===============================================================================
RESEARCH-DESIGN NOTE 1 — Java has no module namespace
===============================================================================
defuse2's WRITE/READ model is defined against Python's MODULE namespace.  The
strict variant gates every write and every read on ``is_at_module_level`` /
``is_at_module_or_class_level``, both of which walk parents until they reach a
node of type ``module``.  That works because a Python module is simultaneously
a *file*, a *namespace*, and the *unit of import*: ``foo.py`` defines names that
``from foo import bar`` makes visible, and "module level" is a real, nameable
scope where public API lives.

Java has no such node.  ``program`` (the compilation-unit root) can contain only
a package declaration, imports, and type declarations.  There is no place to put
a field or a method at ``program`` level, so the literal transliteration --
``java_lang.is_at_compilation_unit_level``, which swaps ``module`` for
``program`` -- admits *only* type names.  Gating on it would reduce the Java
WRITE set to "class names that a patch added" and nothing else.

  THE ANALOGUE CHOSEN: the TYPE-DECLARATION body is Java's "top level".

Java's namespace triple is (package, type, member).  The package is a directory
convention, not a scope you can write code into; the *type* is the unit that
owns fields and methods, that ``import`` names, and that carries visibility
modifiers.  So the structural counterpart of "a name defined at Python module
level" is "a member declared in the body of the file's top-level type".  That is
``java_lang.is_at_type_body_level``, which returns True for a node inside at
most one type declaration and inside no callable or lambda -- i.e. fields,
method and constructor signatures, and enum constants of the outermost type,
but not method bodies and not members of nested types.

The mapping, term by term:

    Python                                Java
    ------------------------------------  ------------------------------------
    module (file == namespace)            compilation unit's top-level type
    module-level def / class              method, constructor, nested type
    module-level assignment               field declaration
    class body, one level deep            same (nested type body)
    `from m import X` binds X in m        `import p.T` names the type T
    function body (excluded by strict)    method body (excluded by strict)

HOW THIS CHANGES COMPARABILITY WITH THE PYTHON BASELINE

  * For THIS file, not at all.  This is the port of the *relaxed* variant, and
    the relaxed variant applies no scope guard: defuse2.py still
    *defines* is_at_module_level / is_at_module_or_class_level but never calls
    them (verified: the only occurrences are the definitions themselves).  Both
    predicates are likewise provided in java_lang.py and likewise uncalled here.
    So the Python-vs-Java comparison run through defuse2.py and
    defuse2_java.py is NOT confounded by the namespace mismatch -- which is the
    main reason the relaxed variant is the right one to port first.

  * For a future strict port it changes the comparison materially, and in a
    direction that must be stated: Python's module level is *flat* (a function
    and a class sit side by side in one namespace), while Java's type level is
    *nested by construction* (every method is already one level inside a type).
    Python's guard therefore admits module functions AND one level of class
    body; the Java analogue admits one level of type body only, because there is
    no zeroth level. A Java "top-level member" is thus always the peer of a
    Python *class attribute*, never of a Python *module function*.  Counts of
    "top-level writes" are consequently not commensurable across the two
    languages even after the mapping; only the derived quantities that this
    pipeline actually measures (forward/backward hint sets, and resolve-rate
    deltas computed from them) are.

===============================================================================
RESEARCH-DESIGN NOTE 2 — the READ set is structurally broader in Java
===============================================================================
Three grammar facts (bare method calls do not exist, bare field access does not
exist, and type *uses* are a distinct node type from identifiers) mean a literal
port of the Python read table returns an empty intersection for every Java
instance.  The three deliberate divergences, the reasoning, and the switches
that turn them off are documented in java_lang.py under D-1 / D-2 / D-3.  Pass
``--strict-python-mirror`` to run with all three disabled.

===============================================================================
Input
===============================================================================
Any benchmark row with ``repo`` / ``base_commit`` / ``patch`` / ``test_patch``
(SWE-bench Multilingual Java, SWE-bench Pro, SWE-rebench, FEA-Bench medium,
NoCode Bench).  Dataset field differences are absorbed by utils.get_impl_patch /
get_test_patch / get_doc_content, shared with the Python baselines.

Usage:
    python identity_selection/defuse2_java.py \\
        --input  data/java/swebench_multilingual_java.jsonl \\
        --output identity_selection/results_selection/defuse2_java_sel/raw/swebench_multilingual_java.jsonl \\
        --repos-dir repos/java_repos \\
        --skip-errors
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

from tqdm import tqdm
from unidiff import PatchSet

sys.path.insert(0, str(Path(__file__).resolve().parent))

import java_lang as J
from utils import (
    load_jsonl,
    dump_jsonl,
    find_repo_dir,
    get_impl_patch,
    get_test_patch,
    get_doc_content,
)

# Headers are byte-identical to defuse2.py's so that a Java row and a
# Python row render the same prompt scaffolding.
AUGMENTATION_HEADER_FORWARD = (
    "The following entities are defined in the implementation and used in tests "
    "(forward communication - new APIs/functions/classes):"
)
AUGMENTATION_HEADER_BACKWARD = (
    "The following entities are used in the implementation but defined in tests "
    "(backward communication - test fixtures/mocks):"
)


# ---------------------------------------------------------------------------
# Data structures — identical to defuse2.py
# ---------------------------------------------------------------------------

class AccessType(Enum):
    READ = "read"
    WRITE = "write"


@dataclass
class Entity:
    name: str
    access_type: AccessType
    entity_type: str   # 'function', 'class', 'variable', 'attribute', 'error_msg', 'file'
    file_path: str = ""

    def __hash__(self):
        return hash((self.file_path, self.name, self.access_type, self.entity_type))

    def __eq__(self, other):
        return (self.file_path == other.file_path
                and self.name == other.name
                and self.access_type == other.access_type
                and self.entity_type == other.entity_type)


# ---------------------------------------------------------------------------
# Git helpers — duplicated from defuse2.py
# ---------------------------------------------------------------------------

def run_cmd(command: List[str], cwd: Optional[Path] = None) -> str:
    """Run a shell command, fail loudly, and return stdout."""
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def reset_repo(repo_dir: Path, base_commit: str) -> None:
    """Return repo to a clean base commit."""
    if not (repo_dir / ".git").exists():
        raise FileNotFoundError(f"Not a git repo: {repo_dir}")

    run_cmd(["git", "reset", "--hard", "-q"], cwd=repo_dir)
    run_cmd(["git", "clean", "-fdx", "-q"], cwd=repo_dir)
    run_cmd(["git", "checkout", "-q", base_commit], cwd=repo_dir)
    run_cmd(["git", "reset", "--hard", "-q"], cwd=repo_dir)
    run_cmd(["git", "clean", "-fdx", "-q"], cwd=repo_dir)


def write_and_apply_patch(repo_dir: Path, patch_content: str, patch_type: str) -> None:
    """
    Write the patch inside repo_dir, then apply it.

    Silent-on-error by design: patches that cannot apply at base_commit are
    skipped, so the after-state equals the before-state and no new entities are
    reported for that file.
    """
    patch_path = repo_dir / f".nocode_{patch_type}.patch"
    patch_path.write_text(patch_content, encoding="utf-8")

    try:
        subprocess.run(
            f"git apply {patch_path.name}",
            shell=True,
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        try:
            patch_path.unlink()
        except FileNotFoundError:
            pass


def read_code(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Scope predicates
#
# Re-exported from java_lang.py so this module's surface matches
# defuse2.py's, which also defines both and calls neither.  See
# RESEARCH-DESIGN NOTE 1 in the module docstring.
# ---------------------------------------------------------------------------

is_at_module_level = J.is_at_compilation_unit_level
is_at_module_or_class_level = J.is_at_type_body_level


# ---------------------------------------------------------------------------
# AST helpers: READ / WRITE classification
# ---------------------------------------------------------------------------

_node_contains = J.node_contains
is_write_context = J.is_write_context
is_read_context = J.is_read_context


def _path_to_module(path: str) -> str:
    """Java stand-in for defuse2's _path_to_module: path -> fully-qualified name.

    "src/main/java/com/x/Foo.java" -> "com.x.Foo"
    """
    return J.path_to_fqn(path)


def _extract_import(
    stmt_node,
    local_modules: Set[str],
    file_path: str,
    results: List["Entity"],
) -> None:
    """
    Classify import names when the imported type belongs to a file touched by
    the current patch.

    Python rules and their Java counterparts:

      import X                 -> last component of X is WRITE
        Java: `import p.q.T;`  -> T is WRITE when "p.q.T" is a patched file.

      from X import Y          -> Y is WRITE
        Java: `import static p.q.T.m;` -> m is WRITE when "p.q.T" is patched.
              (the member is named directly, exactly like `from X import Y`)

      import X as Z            -> Z is WRITE
      from X import Y as Z     -> Z is WRITE, Y is READ
        Java: NO ANALOGUE.  Java has no import aliasing, so the two aliased
        branches of the Python function are unreachable here and the "original
        name becomes a READ" behaviour has no Java counterpart.  This is a
        genuine gap in the mapping, not an omission.

      (no Python analogue)     -> wildcard
        Java: `import p.q.*;`  -> every patched file in package p.q contributes
        its simple name as a WRITE.  Python's `from X import *` is not handled
        by the Python baseline either, but Java wildcards are common enough
        (and resolvable, since local_modules enumerates the patched files) that
        dropping them would lose real edges.
    """
    if stmt_node.type != "import_declaration":
        return

    target = J.import_target(stmt_node)
    if not target:
        return

    is_static = J.is_static_import(stmt_node)
    is_wildcard = J.is_wildcard_import(stmt_node)

    if is_wildcard and not is_static:
        # import p.q.*;  -> target is the PACKAGE
        prefix = target + "."
        for fqn in local_modules:
            if fqn.startswith(prefix) and "." not in fqn[len(prefix):]:
                results.append(Entity(fqn.rsplit(".", 1)[-1],
                                      AccessType.WRITE, "variable", file_path))
        return

    if is_static:
        # import static p.q.T.m;  -> target is "p.q.T.m"
        # import static p.q.T.*;  -> target is "p.q.T"
        if is_wildcard:
            if target in local_modules:
                results.append(Entity(target.rsplit(".", 1)[-1],
                                      AccessType.WRITE, "variable", file_path))
            return
        owner, _, member = target.rpartition(".")
        if owner in local_modules and member:
            results.append(Entity(member, AccessType.WRITE, "variable", file_path))
        return

    # import p.q.T;
    if target in local_modules:
        results.append(Entity(target.rsplit(".", 1)[-1],
                              AccessType.WRITE, "variable", file_path))


def _get_raise_string(node) -> Optional[str]:
    """Java analogue of defuse2's _get_raise_string.

    Python matches `raise_statement` and `with_clause` (pytest.raises).
    Java matches `throw_statement` and the JUnit exception assertions
    (assertThrows / expectMessage / hasMessageContaining / ...).  Implemented
    in java_lang.get_raise_string with the same positional walk.
    """
    return J.get_raise_string(node)


def get_all_identifiers_with_access(
    root,
    file_path: str = "",
    local_modules: Optional[Set[str]] = None,
) -> List[Entity]:
    """Extract all identifiers with READ/WRITE classification.

    local_modules: fully-qualified names for the .java files touched by the
    current patch.  Imports naming those files are classified; every other
    import is skipped entirely.

    Differences from the Python original, all forced by the grammar:
      * visits `type_identifier` as well as `identifier` (see java_lang D-3);
      * intercepts `import_declaration` and `package_declaration` where Python
        intercepts `import_statement` / `import_from_statement`;
      * harvests error messages from `throw_statement` and JUnit assertion
        calls where Python uses `raise_statement` / `with_clause`.
    """
    if local_modules is None:
        local_modules = set()
    results: List[Entity] = []

    def traverse(node):
        # Intercept import/package statements — consume them, skip descent.
        if node.type == "import_declaration":
            _extract_import(node, local_modules, file_path, results)
            return
        if node.type == "package_declaration":
            return

        if node.type == "throw_statement" or node.type == "method_invocation":
            raise_str = _get_raise_string(node)
            if raise_str is not None:
                results.append(Entity(
                    name=raise_str,
                    access_type=AccessType.WRITE,
                    entity_type="error_msg",
                    file_path=file_path,
                ))

        if node.type in J.IDENTIFIER_NODES:
            name = node.text.decode("utf-8", errors="ignore")

            entity_type = J.classify_entity_type(node)

            is_write = is_write_context(node)
            is_read = is_read_context(node)

            if is_write:
                results.append(Entity(name, AccessType.WRITE, entity_type, file_path))
            if is_read:
                results.append(Entity(name, AccessType.READ, entity_type, file_path))

        for child in node.named_children:
            traverse(child)

    traverse(root)
    return results


def extract_entities_from_code(
    code: str,
    file_path: str = "",
    local_modules: Optional[Set[str]] = None,
) -> Set[Entity]:
    """Extract entities from Java code with read/write classification."""
    try:
        tree = J.parse(code)
        entities = get_all_identifiers_with_access(
            tree.root_node, file_path, local_modules=local_modules
        )
        return set(entities)
    except Exception:
        return set()


def filter_entities_by_access(entities: Set[Entity], access_type: AccessType) -> Set[Entity]:
    return {e for e in entities if e.access_type == access_type}


# Deterministic precedence when one name arrives with several entity types.
#
# The Python original resolves this with "prefer function/class over anything
# else" and leaves function-vs-class to set iteration order.  That is safe in
# Python, where a class and a function of the same name in one module is
# pathological.  In Java it is GUARANTEED: every constructor_declaration has
# the same name as its class_declaration, so `new Foo()`'s target always
# arrives as both {"class", "Foo"} and {"function", "Foo"}.  Left to set order
# the rendered type flips between runs (str hashing is randomised per process),
# making the output irreproducible — verified by running the same instance six
# times and seeing 'function'/'class' alternate.
#
# Ranking agrees with the Python rule everywhere the Python rule is defined
# (function/class beat variable/attribute) and gives the undefined cases a
# fixed answer.  class outranks function because a Java constructor is not an
# entity distinct from its type: naming the class is the more informative hint.
_ENTITY_TYPE_RANK = {
    "class": 0,
    "function": 1,
    "file": 2,
    "error_msg": 3,
    "attribute": 4,
    "variable": 5,
}


def entities_to_dict(entities: Set[Entity]) -> List[Dict[str, str]]:
    """Convert Entity objects to dict format.

    Deduplicates by name only — file_path is internal bookkeeping and the hint
    consumer only sees the name.  Prefers 'function'/'class' entity_type over
    'variable' when the same name appears from multiple files/contexts, and
    breaks remaining ties deterministically (see _ENTITY_TYPE_RANK).

    NOTE (Java overloading): names stay BARE here, deliberately.  The
    "name#arity" discriminator of src/lang/base.py CONTRACT 2 applies to the
    *catalogue*, not to these sets — a call site cannot recover parameter types,
    so keying these on anything richer than the name would make every
    intersection empty.  Two overloads therefore collapse to one hint entry.
    """
    def rank(entity: Entity):
        # file_path and entity_type included so the sort is a total order and
        # the result cannot depend on set iteration order.
        return (_ENTITY_TYPE_RANK.get(entity.entity_type, 99),
                entity.file_path,
                entity.entity_type)

    key_to_entity: Dict[str, Entity] = {}
    for entity in entities:
        key = entity.name
        existing = key_to_entity.get(key)
        if existing is None or rank(entity) < rank(existing):
            key_to_entity[key] = entity

    result = [{"type": e.entity_type, "name": e.name} for e in key_to_entity.values()]
    result.sort(key=lambda x: x["name"])
    return result


# ---------------------------------------------------------------------------
# Diff entity extraction
# ---------------------------------------------------------------------------

def java_files_from_patch(patch_content: str):
    """Java counterpart of python_files_from_patch."""
    if not patch_content.strip():
        return []
    patch_set = PatchSet(patch_content)
    return [pf for pf in patch_set if J.is_java_path(pf.path)]


def get_diff_entities_with_access(example: dict, repo_dir: Path,
                                  patch_type: str) -> Set[Entity]:
    """
    Compute entities introduced by either impl_patch or test_patch with
    READ/WRITE info.  Mirrors defuse2.py's function of the same name.
    """
    base_commit = example["base_commit"]
    patch_content = get_impl_patch(example) if patch_type == "feature" else get_test_patch(example)

    reset_repo(repo_dir, base_commit)

    patched_files = java_files_from_patch(patch_content)

    patch_set = PatchSet(patch_content) if patch_content.strip() else PatchSet("")
    new_files = [f for f in patch_set.added_files if J.is_java_path(f.path)]

    # Fully-qualified names for every .java file touched by this patch.
    # Used to gate import classification — only imports of these types count.
    local_modules = {_path_to_module(pf.path) for pf in patched_files}

    diff_entities = {}

    for patched_file in patched_files:
        fpath = patched_file.path
        before_code = read_code(repo_dir / fpath)
        before_entities = extract_entities_from_code(before_code, fpath, local_modules)

        diff_entities[fpath] = {
            "before": before_entities,
            "after": set(),
        }

    if patch_content.strip():
        write_and_apply_patch(repo_dir, patch_content, patch_type)

    for patched_file in patched_files:
        fpath = patched_file.path
        after_code = read_code(repo_dir / fpath)
        after_entities = extract_entities_from_code(after_code, fpath, local_modules)
        diff_entities[fpath]["after"] = after_entities

    new_entities: Set[Entity] = set()
    for fpath, entities in diff_entities.items():
        old_entities = entities["before"]
        new_entities_in_file = entities["after"] - old_entities
        new_entities.update(new_entities_in_file)

    for new_file in new_files:
        new_entities.add(Entity(
            name=new_file.path,
            access_type=AccessType.WRITE,
            entity_type="file",
            file_path=new_file.path,
        ))

    return new_entities


# ---------------------------------------------------------------------------
# Core per-instance logic
# ---------------------------------------------------------------------------

# Minimum normalized length before an error message is allowed to match the
# test patch.  Short strings ("timeout") collide with unrelated test code.
_MIN_ERR_MSG_CHARS = 12


# Interpolation holes: `{}` / `{0}` (slf4j, MessageFormat) and `%s` / `%d`
# (String.format).  Java's third shape, `"a " + x + " b"`, needs no pattern —
# the grammar splits it into separate string literals and get_raise_string
# keeps the first, which is the stable literal prefix.
_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}|%[-#0-9.]*[sdrfgex]")


def _norm_text(text: str) -> str:
    """Case-fold and collapse whitespace.  Nothing else."""
    return " ".join(text.lower().split())


def _msg_fragments(text: str) -> List[str]:
    r"""Split a message into its literal segments, dropping interpolation holes.

    WHY THIS DIVERGES FROM defuse2.py's _norm_msg
    ---------------------------------------------
    The Python original applies `re.sub(r"\{[^}]*\}", " ", ...)` to BOTH the
    message and the whole test patch, so an f-string hole in the raise site and
    the same hole in the assertion cancel out.  Applying that to a *Java* test
    patch is catastrophic: `{` ... `}` is Java's block delimiter, so the regex
    eats every method body it meets.  Verified on the fixture — the impl throws
    "key must not be null", the raw test patch contains "key must not be null",
    and yet `_norm_msg(msg) in _norm_msg(test_patch)` is False, because the
    brace of `public void testNullKeyRejected() {` swallowed the assertion up
    to the method's closing brace.  Every Java error-message hint would be
    silently dropped.

    The fix keeps the intent and drops the collision: strip placeholders from
    the MESSAGE only, splitting it into literal segments, and match those
    segments against a blob that is only case-folded and whitespace-collapsed.
    With no placeholders this degrades to exactly the Python behaviour (one
    fragment, plain substring test); with placeholders it is strictly more
    precise, since a surviving segment is real literal text on both sides.
    """
    return [_norm_text(fragment)
            for fragment in _PLACEHOLDER_RE.split(text)]


def _message_reaches_test(msg: str, test_blob: str) -> bool:
    """True when a literal segment of `msg` (long enough to be meaningful)
    appears in the normalized test patch."""
    return any(len(fragment) >= _MIN_ERR_MSG_CHARS and fragment in test_blob
               for fragment in _msg_fragments(msg))


def get_communication_hints(example: dict, repos_dir: Path) -> Dict[str, Set[Entity]]:
    """Compute forward and backward communication hints."""
    repo = example.get("repo", "")
    repo_dir = find_repo_dir(repo, repos_dir)

    feature_entities = get_diff_entities_with_access(example, repo_dir, "feature")
    test_entities    = get_diff_entities_with_access(example, repo_dir, "test")

    new_files = {e for e in feature_entities if e.entity_type == "file"}

    feature_entities_for_matching = {e for e in feature_entities if e.entity_type != "file"}
    test_entities_for_matching    = {e for e in test_entities    if e.entity_type != "file"}

    code_write = filter_entities_by_access(feature_entities_for_matching, AccessType.WRITE)
    test_read  = filter_entities_by_access(test_entities_for_matching,    AccessType.READ)

    code_write_names = {e.name for e in code_write}
    test_read_names  = {e.name for e in test_read}
    forward_names    = code_write_names & test_read_names

    forward_hints: Set[Entity] = {e for e in code_write if e.name in forward_names}
    forward_hints.update(new_files)

    # Error messages are WRITE on both sides — the impl throws the message and
    # the test asserts on it — so they can never survive the WRITE n READ
    # intersection above.  Inject them the way new files are injected, but only
    # when the message text actually reaches the test patch, so the "the tests
    # exercise this" contract still holds.  (Carried over from
    # defuse2.py.)
    test_blob = _norm_text(get_test_patch(example))
    for e in code_write:
        if e.entity_type != "error_msg":
            continue
        if _message_reaches_test(e.name, test_blob):
            forward_hints.add(e)

    code_read  = filter_entities_by_access(feature_entities_for_matching, AccessType.READ)
    test_write = filter_entities_by_access(test_entities_for_matching,    AccessType.WRITE)

    code_read_names  = {e.name for e in code_read}
    test_write_names = {e.name for e in test_write}
    backward_names   = code_read_names & test_write_names

    backward_hints_from_test = {e for e in test_write if e.name in backward_names}
    backward_hints_from_code = {e for e in code_read  if e.name in backward_names}

    backward_hints: Set[Entity] = set()
    for name in backward_names:
        from_test = [e for e in backward_hints_from_test if e.name == name]
        from_code = [e for e in backward_hints_from_code if e.name == name]

        best_entity: Optional[Entity] = None
        for e in from_test + from_code:
            if best_entity is None:
                best_entity = e
            elif (e.entity_type in ["function", "class"]
                  and best_entity.entity_type not in ["function", "class"]):
                best_entity = e

        if best_entity:
            backward_hints.add(best_entity)

    # Filter out entities mentioned in documentation
    doc_content = get_doc_content(example)
    forward_hints  = {e for e in forward_hints  if e.name not in doc_content}
    backward_hints = {e for e in backward_hints if e.name not in doc_content}

    try:
        reset_repo(repo_dir, example["base_commit"])
    except Exception:
        pass

    return {"forward": forward_hints, "backward": backward_hints}


def add_augmentations(example: dict, repos_dir: Path) -> dict:
    hints = get_communication_hints(example, repos_dir)

    forward_data  = entities_to_dict(hints["forward"])
    backward_data = entities_to_dict(hints["backward"])

    example["augmentations"] = {
        "forward": {
            "header": AUGMENTATION_HEADER_FORWARD,
            "data": forward_data,
        },
        "backward": {
            "header": AUGMENTATION_HEADER_BACKWARD,
            "data": backward_data,
        },
    }
    return example


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    input_path: Path,
    output_path: Path,
    repos_dir: Path,
    skip_errors: bool = False,
    instance_id: Optional[str] = None,
) -> None:
    examples = load_jsonl(input_path)

    if instance_id is not None:
        examples = [ex for ex in examples if ex.get("instance_id") == instance_id]
        if not examples:
            raise ValueError(f"No example found with instance_id={instance_id!r}")

    output_rows = []
    errors = []

    for example in tqdm(examples):
        iid = example.get("instance_id", "<unknown>")

        try:
            output_rows.append(add_augmentations(example, repos_dir))
        except Exception as exc:
            if not skip_errors:
                raise

            errors.append({"instance_id": iid, "error": repr(exc)})
            output_rows.append(example)

    dump_jsonl(output_rows, output_path)

    if errors:
        err_path = output_path.with_suffix(output_path.suffix + ".errors.jsonl")
        dump_jsonl(errors, err_path)
        print(f"Wrote {len(errors)} errors to {err_path}")

    print(f"Wrote augmented output to {output_path}")


if __name__ == "__main__":
    argp = argparse.ArgumentParser(
        description="Generate communication-based augmentation hints for Java (DefUse2)"
    )
    argp.add_argument("--input",  "-i", type=Path, required=True,
                      help="Input JSONL with repo/base_commit/patch/test_patch.")
    argp.add_argument("--output", "-o", type=Path, required=True,
                      help="Output JSONL path.")
    argp.add_argument("--repos-dir", "-r", type=Path, required=True,
                      help="Directory containing cloned repos.")
    argp.add_argument("--skip-errors", action="store_true",
                      help="Continue on failed instances and write an .errors.jsonl file.")
    argp.add_argument("--instance-id", type=str, default=None,
                      help="Optional single instance_id for debugging.")
    argp.add_argument("--strict-python-mirror", action="store_true",
                      help="Disable the three Java-specific READ divergences "
                           "(java_lang D-1/D-2/D-3) and use the literal "
                           "transliteration of the Python rules.  Produces "
                           "near-empty hints; provided so that arm of the "
                           "experiment is reproducible.")

    args = argp.parse_args()

    if args.strict_python_mirror:
        J.set_strict_python_mirror(True)

    main(
        input_path=args.input,
        output_path=args.output,
        repos_dir=args.repos_dir,
        skip_errors=args.skip_errors,
        instance_id=args.instance_id,
    )
