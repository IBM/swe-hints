#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Java read/write scanner — CONTRACT 3 of src/lang/base.py.

This is the Java counterpart of ``_extract_entities`` / ``_is_write`` / ``_is_read``
in ``src/identifier_usage.py``.  Nothing here imports from it, so the Python
path is unaffected by the Java scanner.

Public API
----------
``extract_entities(code, local_modules=None, ...) -> (writes, reads)``
    Typed tokens ``(name, entity_type)`` with
    ``entity_type in {"function", "class", "variable", "attribute"}``.
    Callers project to bare names (``names()``), exactly like the Python path.
``path_to_module(path, code=None) -> str``
    Fully-qualified compilation-unit name ("com.example.core.Widget").
``local_module_keys(files) -> set[str]``
    The Java analogue of ``{_path_to_module(p) for p in patched_files}``.
``JavaUsageAdapter`` / ``ADAPTER``
    LanguageAdapter surface; self-registers with ``src.lang.registry`` **only if**
    no "java" adapter is registered yet (so ``src/lang/java_extractor.py`` —
    which owns rich extraction and is imported first by ``registry._load`` — wins).

WRITE (a declaration or an assignment target)
---------------------------------------------
* ``class_declaration`` / ``interface_declaration`` / ``enum_declaration`` /
  ``record_declaration`` / ``annotation_type_declaration`` name  -> ("class")
* ``method_declaration`` / ``constructor_declaration`` /
  ``compact_constructor_declaration`` / ``annotation_type_element_declaration``
  name -> ("function")
* ``variable_declarator`` name — this single rule covers ``field_declaration``,
  ``constant_declaration`` (interface fields), ``local_variable_declaration`` and
  ``spread_parameter`` -> ("variable")
* ``enum_constant`` name, ``formal_parameter`` / ``catch_formal_parameter`` /
  ``resource`` name, ``enhanced_for_statement`` name, ``instanceof_expression``
  pattern name, lambda parameters (bare ``identifier`` or ``inferred_parameters``)
  -> ("variable")
* the target of a plain ``assignment_expression`` (operator ``=``).

READ (a value-consuming or type-consuming use)
----------------------------------------------
``method_invocation`` name (function) and object (variable), ``field_access``
field (attribute) and object (variable), the RHS of ``=``, BOTH sides of a
compound assignment (``+=``, mirroring Python's ``augmented_assignment``),
arguments, return / throw / assert / yield operands, ``condition`` nodes,
and every *type* usage — declaration types, ``type_arguments``, ``superclass``,
``super_interfaces`` / ``extends_interfaces``, ``throws``, ``catch_type``,
casts, ``instanceof``, ``new``, annotations and method references.

Deliberate divergences from the Python scanner (all documented, none of them
touch the Python path)
----------------------------------------------------------------------------
1. **Same-package siblings are treated as implicit imports.**  Python binds a
   cross-module name with ``from x import Y`` and ``_extract_import`` turns that
   into a WRITE.  Java has no such statement when the user and the used type sit
   in the *same package*: ``src/test/java/com/e/FooTest.java`` uses ``Foo`` with
   no import at all, so a purely import-gated port silently loses every
   same-package edge — and in these benchmarks the test almost always lives in
   the package of the class it tests.  Rule implemented here: a simple name that
   (a) is read in this file, (b) is not explicitly imported here, and
   (c) matches ``f"{pkg}.{name}"`` in ``local_modules`` for the file's OWN
   package or for a locally wildcard-imported package, is also emitted as a
   WRITE ``(name, "class")`` — i.e. exactly what ``import <pkg>.<Name>;`` would
   have produced.  ``local_modules`` still gates it, so a file that the patch did
   not touch can never inject a token.  Disable with ``same_package=False``.
2. **``field_access`` field names are captured** as ``(name, "attribute")`` reads.
   Python's ``_is_read`` only accepts the *object* half of an ``attribute`` node,
   so Python never records attribute reads at all.
3. **Assignment targets are resolved precisely.** In ``obj.f = 8`` only ``f`` is a
   WRITE (``obj`` is a read); in ``arr[i] = 7`` neither ``arr`` nor ``i`` is a
   write.  Python's coarse ``_node_contains(left, node)`` marks every direct child
   of the assignment.
4. **Generic type parameters are dropped** from both sets.  ``<R>``, ``<T>``,
   ``<K, V>`` are compile-time-only names with no catalogue entry and no Python
   analogue; keeping them floods every operator with single letters.  The
   declaration name of a real type/method is never dropped, even on a collision.
5. ``scoped_identifier`` / ``scoped_type_identifier`` are atomic leaves: only the
   last dotted component is emitted, and the subtree is not descended into.
   Without this, ``com``/``example``/``java``/``util`` flood the sets.
   ``package_declaration`` and ``import_declaration`` subtrees are likewise never
   descended into (imports are consumed by ``_extract_import`` first).
6. ``ubiquitous_names`` (java.lang + common java.util) is an OPT-IN post filter
   (``filter_ubiquitous=True``); the default is off so ``extract_entities`` stays
   a faithful reading of the grammar.
"""

from __future__ import annotations

from typing import Iterable, Optional

from tree_sitter_languages import get_parser

_ts_parser = get_parser("java")

JAVA_EXTENSIONS: tuple[str, ...] = (".java",)

# Maven/Gradle source roots stripped by the path-only fallback of path_to_module.
_SOURCE_ROOTS: tuple[str, ...] = (
    "src/main/java/",
    "src/test/java/",
    "src/main/kotlin/",
    "src/test/kotlin/",
    "src/main/",
    "src/test/",
    "src/java/",
    "src/",
    "java/",
    "test/",
    "tests/",
    "main/",
)

_TYPE_DECLS = frozenset({
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
})

_CALLABLE_DECLS = frozenset({
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
    "annotation_type_element_declaration",
})

# Parents whose identifier children are value/type reads.  _is_write() runs
# first, so container nodes that hold BOTH a declared name and a read (e.g.
# variable_declarator, formal_parameter, method_declaration) are safe here.
_READ_PARENTS = frozenset({
    # expressions
    "binary_expression", "unary_expression", "ternary_expression",
    "parenthesized_expression", "update_expression", "cast_expression",
    "instanceof_expression", "array_access", "array_initializer",
    "array_creation_expression", "dimensions_expr", "argument_list",
    "annotation_argument_list", "element_value_pair",
    "element_value_array_initializer", "object_creation_expression",
    "method_invocation", "field_access", "lambda_expression",
    "explicit_constructor_invocation", "class_literal", "template_expression",
    "string_interpolation", "switch_expression", "switch_label", "switch_rule",
    "switch_block_statement_group",
    # statements
    "expression_statement", "return_statement", "throw_statement",
    "assert_statement", "yield_statement", "synchronized_statement",
    "condition", "for_statement", "enhanced_for_statement",
    "local_variable_declaration", "resource_specification", "resource",
    "catch_formal_parameter", "catch_type",
    # declarations that carry a type
    "field_declaration", "constant_declaration", "variable_declarator",
    "formal_parameter", "spread_parameter", "method_declaration",
    "annotation_type_element_declaration", "record_declaration",
    # type syntax
    "generic_type", "type_arguments", "type_list", "array_type",
    "annotated_type", "wildcard", "type_bound", "scoped_type_identifier",
    "superclass", "super_interfaces", "extends_interfaces", "permits",
    "throws",
    # annotations (the Java analogue of Python's decorator rule)
    "marker_annotation", "annotation",
})

_TYPE_CONTEXT_PARENTS = frozenset({
    "generic_type", "type_arguments", "type_list", "array_type",
    "annotated_type", "wildcard", "type_bound", "scoped_type_identifier",
    "superclass", "super_interfaces", "extends_interfaces", "permits",
    "throws", "catch_type", "object_creation_expression", "cast_expression",
    "class_literal", "marker_annotation", "annotation",
})

# `var` is a contextual keyword that tree-sitter reports as a type_identifier.
_PSEUDO_TYPES = frozenset({"var", "yield", "record", "sealed", "permits"})

# Opt-in noise filter (see divergence 6).
UBIQUITOUS_NAMES = frozenset({
    # java.lang (implicitly imported in every compilation unit)
    "Object", "String", "StringBuilder", "StringBuffer", "CharSequence",
    "Integer", "Long", "Short", "Byte", "Double", "Float", "Boolean",
    "Character", "Number", "Math", "System", "Class", "Enum", "Record",
    "Thread", "Runnable", "Comparable", "Iterable", "Throwable", "Exception",
    "RuntimeException", "Error", "IllegalArgumentException",
    "IllegalStateException", "NullPointerException", "UnsupportedOperationException",
    "IndexOutOfBoundsException", "ClassCastException", "NumberFormatException",
    "Override", "Deprecated", "SuppressWarnings", "SafeVarargs",
    "FunctionalInterface", "Void", "Cloneable", "AutoCloseable",
    # java.util / java.io staples
    "List", "ArrayList", "LinkedList", "Map", "HashMap", "LinkedHashMap",
    "TreeMap", "Set", "HashSet", "LinkedHashSet", "TreeSet", "Collection",
    "Collections", "Arrays", "Objects", "Optional", "Iterator", "Comparator",
    "Stream", "Collectors", "IOException", "InputStream", "OutputStream",
    "Reader", "Writer", "File",
})


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _text(node) -> str:
    return node.text.decode("utf-8", errors="ignore")


def _node_contains(parent, child) -> bool:
    """
    Structural containment, mirroring identifier_usage._node_contains.

    Implemented as an upward walk instead of that module's downward recursion:
    real Java files (generated JFlex scanners in Lucene, 1.8 MB of nested array
    initialisers) reach an AST depth of ~1000 and blow CPython's recursion limit
    on any downward walk.  The result is identical.
    """
    cur = child
    while cur is not None:
        if cur == parent:
            return True
        cur = cur.parent
    return False


def _first_child_of_type(node, type_name: str):
    for c in node.named_children:
        if c.type == type_name:
            return c
    return None


def parse(code: str):
    """Parse Java source; returns a tree-sitter Tree (or None on failure)."""
    try:
        return _ts_parser.parse(code.encode("utf-8", errors="ignore"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Packages / module keys
# ---------------------------------------------------------------------------

def package_of(code: str) -> str:
    """Return the declared package of a compilation unit ("" for the default package)."""
    tree = parse(code)
    if tree is None:
        return ""
    return _package_of_root(tree.root_node)


def _package_of_root(root) -> str:
    for child in root.named_children:
        if child.type == "package_declaration":
            for c in child.named_children:
                if c.type in ("scoped_identifier", "identifier"):
                    return _text(c)
            return ""
        # package_declaration, when present, is the first named child; a
        # block_comment/line_comment may precede it, nothing else.
        if child.type not in ("line_comment", "block_comment"):
            break
    return ""


def _type_name_from_path(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name[: -len(".java")] if name.endswith(".java") else name


def path_to_module(path: str, code: Optional[str] = None) -> str:
    """
    Fully-qualified compilation-unit name — the Java analogue of
    ``identifier_usage._path_to_module``.

    Java does NOT use the dotted-path-from-filename rule: the package comes from
    the ``package_declaration``, and the directory prefix ("src/main/java/") is
    build-tool convention, not language semantics.  So when ``code`` is
    available the package is read out of the AST:

        src/main/java/com/example/Foo.java  (package com.example)  -> com.example.Foo

    ``code=None`` falls back to stripping a known source root and dotted-joining
    the remainder, which is right for Maven/Gradle layouts and is only ever used
    for a file that could not be read (e.g. deleted by the patch).
    """
    clean = path.replace("\\", "/").lstrip("./")
    type_name = _type_name_from_path(clean)

    if code is not None:
        pkg = package_of(code)
        return f"{pkg}.{type_name}" if pkg else type_name

    rest = clean
    for root in _SOURCE_ROOTS:
        idx = rest.find(root)
        if idx != -1:
            rest = rest[idx + len(root):]
            break
    if rest.endswith(".java"):
        rest = rest[: -len(".java")]
    return rest.replace("/", ".")


def package_of_module(module: str) -> str:
    """"com.example.Foo" -> "com.example";  "Foo" -> ""."""
    return module.rsplit(".", 1)[0] if "." in module else ""


def local_module_keys(files: dict) -> set:
    """
    Build the ``local_modules`` set from ``{path: code}``.

    Values may be ``None`` when the file does not exist in that state (added or
    deleted by the patch); the path-only fallback is used for those.
    """
    keys: set = set()
    for path, code in files.items():
        if not path.endswith(JAVA_EXTENSIONS):
            continue
        keys.add(path_to_module(path, code))
    return keys


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

def _extract_import(
    stmt_node,
    local_modules: set,
    writes: set,
    reads: set,
    explicit_names: set,
    wildcard_packages: set,
) -> None:
    """
    Process one ``import_declaration``.  The Java counterpart of
    ``identifier_usage._extract_import``.

      import a.b.C;             -> WRITE "C"          if "a.b.C" is local
      import static a.b.C.m;    -> WRITE "m"          if "a.b.C" is local
      import a.b.*;             -> remembered as a wildcard package (no names)
      import static a.b.C.*;    -> nothing (members are not enumerable)

    Every explicitly imported simple name is recorded in ``explicit_names`` so
    the same-package rule cannot double-bind a name that came from elsewhere.
    Java has no ``import ... as ...``, so there is no alias READ (the Python
    ``from X import Y as Z`` case).
    """
    is_static = any(
        (c.type == "static") or (not c.is_named and c.text == b"static")
        for c in stmt_node.children
    )
    is_wildcard = any(c.type == "asterisk" for c in stmt_node.children)

    path_node = None
    for c in stmt_node.named_children:
        if c.type in ("scoped_identifier", "identifier"):
            path_node = c
            break
    if path_node is None:
        return

    fqn = _text(path_node)

    if is_wildcard:
        if not is_static:
            # import a.b.*;  -> a.b becomes an implicitly available package.
            wildcard_packages.add(fqn)
        return

    simple = fqn.rsplit(".", 1)[-1]
    explicit_names.add(simple)

    if is_static:
        owner = fqn.rsplit(".", 1)[0] if "." in fqn else ""
        if owner in local_modules:
            # Static member of a locally touched type: a field or a method — we
            # cannot tell which from the import alone, so use the neutral
            # "variable" tag (all four instance-level sets are bare names).
            writes.add((simple, "variable"))
    else:
        if fqn in local_modules:
            writes.add((simple, "class"))


# ---------------------------------------------------------------------------
# Token classification
# ---------------------------------------------------------------------------

def _entity_type(node) -> str:
    """Return the entity_type label for an identifier-ish node."""
    parent = node.parent
    if parent is None:
        return "variable"
    pt = parent.type

    if pt in _CALLABLE_DECLS and node == parent.child_by_field_name("name"):
        return "function"
    if pt in _TYPE_DECLS and node == parent.child_by_field_name("name"):
        return "class"
    if pt == "method_invocation" and node == parent.child_by_field_name("name"):
        return "function"
    if pt == "field_access" and node == parent.child_by_field_name("field"):
        return "attribute"
    if pt in ("marker_annotation", "annotation") and node == parent.child_by_field_name("name"):
        return "class"
    if node.type in ("type_identifier", "scoped_type_identifier"):
        return "class"
    if pt in _TYPE_CONTEXT_PARENTS and node.type == "scoped_identifier":
        return "class"
    return "variable"


def _assignment_write(node) -> bool:
    """
    True when ``node`` is the assigned target of a plain ``=``.

    Walks out through ``field_access`` (field half only) and parentheses, so
    ``this.name = n`` writes ``name`` while ``obj.f = 8`` writes ``f`` and reads
    ``obj``.  ``arr[i] = 7`` writes nothing (both ``arr`` and ``i`` are reads).
    """
    cur = node
    parent = cur.parent
    while parent is not None:
        pt = parent.type
        if pt == "assignment_expression":
            left = parent.child_by_field_name("left")
            op = parent.child_by_field_name("operator")
            op_text = _text(op) if op is not None else "="
            if op_text != "=":
                return False          # compound assignment: both sides are reads
            return left is not None and (left == cur or _node_contains(left, cur))
        if pt == "field_access":
            if cur != parent.child_by_field_name("field"):
                return False          # the object half is a read
            cur, parent = parent, parent.parent
            continue
        if pt == "parenthesized_expression":
            cur, parent = parent, parent.parent
            continue
        return False
    return False


def _is_write(node) -> bool:
    """A WRITE is a declaration name or the target of a plain assignment."""
    parent = node.parent
    if parent is None:
        return False
    pt = parent.type

    if pt in _CALLABLE_DECLS and node == parent.child_by_field_name("name"):
        return True
    if pt in _TYPE_DECLS and node == parent.child_by_field_name("name"):
        return True
    if pt in (
        "variable_declarator", "enum_constant", "formal_parameter",
        "catch_formal_parameter", "resource", "enhanced_for_statement",
        "instanceof_expression",
    ) and node == parent.child_by_field_name("name"):
        return True
    if pt == "inferred_parameters":
        return True                                   # (p, q) -> ...
    if pt == "lambda_expression" and node == parent.child_by_field_name("parameters"):
        return True                                   # x -> ...
    return _assignment_write(node)


def _is_read(node) -> bool:
    """A READ is any value- or type-consuming use of a name, at any depth."""
    parent = node.parent
    if parent is None:
        return False
    pt = parent.type

    if pt == "assignment_expression":
        op = parent.child_by_field_name("operator")
        op_text = _text(op) if op is not None else "="
        if op_text == "=":
            right = parent.child_by_field_name("right")
            return right is not None and (right == node or _node_contains(right, node))
        return True                                   # x += 1 reads x and 1
    if pt == "method_reference":
        return True
    if pt in _READ_PARENTS:
        return True
    return False


def _type_parameter_names(root) -> set:
    """Collect every generic type-parameter name declared in the file."""
    names: set = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "type_parameter":
            first = _first_child_of_type(node, "type_identifier")
            if first is not None:
                names.add(_text(first))
        stack.extend(node.named_children)
    return names


def _declared_names(root) -> set:
    """Simple names of the types declared in this compilation unit."""
    names: set = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in _TYPE_DECLS:
            n = node.child_by_field_name("name")
            if n is not None:
                names.add(_text(n))
        stack.extend(node.named_children)
    return names


# ---------------------------------------------------------------------------
# CONTRACT 3 entry point
# ---------------------------------------------------------------------------

def extract_entities(
    code: str,
    local_modules: Optional[set] = None,
    *,
    same_package: bool = True,
    filter_ubiquitous: bool = False,
) -> tuple:
    """
    Return ``(write_tokens, read_tokens)`` from a Java source string, where each
    token is a ``(name, entity_type)`` pair with entity_type in
    {"function", "class", "variable", "attribute"}.

    local_modules: fully-qualified compilation-unit names of the files touched by
                   the current patch (e.g. {"com.example.core.Widget"}), built by
                   ``local_module_keys``.  Only imports of — and same-package
                   references to — those units are turned into WRITEs.
    same_package:  apply the implicit same-package import rule (divergence 1).
    filter_ubiquitous: drop java.lang / java.util staples from both sets.
    """
    if local_modules is None:
        local_modules = set()

    tree = parse(code)
    if tree is None:
        return set(), set()
    root = tree.root_node

    writes: set = set()
    reads: set = set()
    explicit_names: set = set()
    wildcard_packages: set = set()

    tparams = _type_parameter_names(root)
    own_package = _package_of_root(root)

    def emit(node, name: str) -> None:
        if not name:
            return
        if name in tparams and not _is_declaration_name(node):
            return                                    # divergence 4
        if _is_write(node):
            writes.add((name, _entity_type(node)))
        elif _is_read(node):
            reads.add((name, _entity_type(node)))

    def _is_declaration_name(node) -> bool:
        parent = node.parent
        if parent is None:
            return False
        return (
            (parent.type in _TYPE_DECLS or parent.type in _CALLABLE_DECLS)
            and node == parent.child_by_field_name("name")
        )

    def traverse(node) -> None:
        """Iterative pre-order walk (see _node_contains for why not recursive)."""
        stack = [node]
        while stack:
            _visit(stack.pop(), stack)

    def _visit(node, stack) -> None:
        nt = node.type

        # Imports/packages are consumed whole — never descended into, or the
        # package components (com, example, java, util) flood both sets.
        if nt == "import_declaration":
            _extract_import(node, local_modules, writes, reads,
                            explicit_names, wildcard_packages)
            return
        if nt == "package_declaration":
            return
        if nt in ("line_comment", "block_comment"):
            return

        # Dotted names are atomic leaves: only the last component is emitted.
        if nt in ("scoped_identifier", "scoped_type_identifier"):
            emit(node, _text(node).rsplit(".", 1)[-1].strip())
            return

        if nt == "method_reference":
            # Foo::new  /  this::helper  /  obj::method
            raw = _text(node)
            after = raw.rsplit("::", 1)[-1].strip() if "::" in raw else ""
            for child in node.named_children:
                if child.type not in ("identifier", "type_identifier", "scoped_type_identifier"):
                    continue
                cname = _text(child).rsplit(".", 1)[-1]
                if cname in tparams:
                    continue
                if cname == after and after != "new":
                    reads.add((cname, "function"))
                else:
                    reads.add((cname, "class" if child.type != "identifier" else "variable"))
            return

        if nt in ("identifier", "type_identifier"):
            name = _text(node)
            if not (nt == "type_identifier" and name in _PSEUDO_TYPES):
                emit(node, name)
            # identifiers have no named children worth visiting
            return

        stack.extend(node.named_children)

    traverse(root)

    # --- divergence 1: same-package siblings behave like implicit imports ----
    if same_package and local_modules:
        available = set(wildcard_packages)
        available.add(own_package)          # "" == default package
        declared_here = _declared_names(root)
        for name, _etype in list(reads):
            if name in explicit_names or name in declared_here:
                continue
            for pkg in available:
                fqn = f"{pkg}.{name}" if pkg else name
                if fqn in local_modules:
                    writes.add((name, "class"))
                    break

    if filter_ubiquitous:
        writes = {t for t in writes if t[0] not in UBIQUITOUS_NAMES}
        reads = {t for t in reads if t[0] not in UBIQUITOUS_NAMES}

    return writes, reads


def names(tokens: Iterable) -> set:
    """Project typed tokens to bare names (mirrors identifier_usage._names)."""
    return {name for name, _ in tokens}


# ---------------------------------------------------------------------------
# LanguageAdapter surface
# ---------------------------------------------------------------------------

class JavaUsageAdapter:
    """Read/write half of the Java LanguageAdapter (see src/lang/base.py)."""

    name = "java"
    extensions = JAVA_EXTENSIONS

    @staticmethod
    def parse(code: str):
        return parse(code)

    @staticmethod
    def extract_entities(code: str, local_modules: Optional[set] = None) -> tuple:
        return extract_entities(code, local_modules)

    @staticmethod
    def path_to_module(path: str, code: Optional[str] = None) -> str:
        return path_to_module(path, code)

    @staticmethod
    def local_module_keys(files: dict) -> set:
        return local_module_keys(files)

    @staticmethod
    def extract_rich_entities(code: str, file_path: str, is_new_file: bool = False) -> dict:
        """Delegate to src/lang/java_extractor.py when it is present (CONTRACT 1)."""
        try:
            from src.lang.java_extractor import extract_rich_entities as _rich
        except Exception:
            return {}
        return _rich(code, file_path, is_new_file)


ADAPTER = JavaUsageAdapter()


def _register_if_absent() -> None:
    """
    Register with src.lang.registry only when nothing owns "java" yet.

    registry._load() imports java_extractor BEFORE java_usage, so a full adapter
    from that module always wins; this fallback only matters while
    java_extractor.py does not exist.
    """
    try:
        from src.lang import registry
    except Exception:
        return
    try:
        if "java" not in getattr(registry, "_ADAPTERS", {}):
            registry.register(ADAPTER)
    except Exception:
        pass


_register_if_absent()
