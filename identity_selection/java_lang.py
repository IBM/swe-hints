#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Shared Java rules for the identity-selection baselines.

This module is the Java counterpart of the tree-sitter rules that
``identity_selection/defuse2*.py`` currently hard-code for Python.  It is
**purely additive**: no existing ``.py`` file is touched, and nothing here is
imported by the Python path, so ``results/`` stays bit-for-bit reproducible.

It supplies, in one place, everything a Java selection baseline needs:

  * the parser (``get_java_parser`` / ``parse``)
  * node-name tables for WRITE / READ context (``is_write_context`` /
    ``is_read_context``)
  * entity-type + entity-kind classification (``classify_entity_type`` /
    ``entity_kind_for``)
  * javadoc extraction (``javadoc_for`` / ``weak_semantics``)
  * modifiers / visibility (``modifiers_of`` / ``annotations_of`` /
    ``visibility_of`` / ``is_public``)
  * supertypes (``base_types``)
  * the ``_get_raise_string`` analogue (``get_raise_string``) plus the JUnit
    exception constructs (``get_expected_exception_types``)
  * the scope predicates that stand in for Python's module namespace
    (``is_at_compilation_unit_level`` / ``is_at_type_body_level``)
  * path -> fully-qualified-name (``path_to_fqn``) and the ``name#arity``
    catalogue key of ``src/lang/base.py`` CONTRACT 2 (``catalogue_key``)

===============================================================================
WHY JAVA CANNOT BE A LITERAL TRANSLITERATION OF THE PYTHON RULES
===============================================================================
Three grammar facts force deliberate, documented divergences.  Each one is
gated by a module-level switch so the strict transliteration stays runnable and
the choice is auditable rather than buried.

D-1  ``method_invocation`` name  (switch: ``COUNT_INVOCATION_NAME_AS_READ``)
     Python:  ``a.b()``  ->  ``call(function: attribute(object: a, attribute: b))``.
              ``is_read_context`` only follows ``attribute``'s *object*, so ``a``
              is READ and the method name ``b`` is **not**.  Python survives
              this because module-level functions are imported and called bare
              (``foo()`` -> ``call(function: identifier)``), which IS a read.
     Java:    there are no bare functions.  Every method is reached as
              ``obj.m()`` or ``Type.m()``, both of which parse as
              ``method_invocation(object: identifier, name: identifier)``.
              Transliterating Python would make the *method* half of
              ``code_write & test_read`` identically empty, i.e. the operator
              would return nothing for the single most common Java hint.
     Choice:  ``method_invocation``'s ``name`` field is a READ.

D-2  ``field_access`` field  (switch: ``COUNT_FIELD_ACCESS_AS_READ``)
     Same argument one level down: Java has no bare access to instance state,
     so ``svc.name`` is the only way a test can read a field the patch added.
     Python's matching construct (``self.name``) is likewise missed by the
     Python baseline -- that is a real, pre-existing Python blind spot, not
     something Java should inherit.
     Choice:  ``field_access``'s ``field`` is a READ (entity_type "attribute"),
     and its ``object`` is a READ (this half does mirror Python).

D-3  ``type_identifier``  (switch: ``COUNT_TYPE_USE_AS_READ``)
     Python identifiers are one node type; a class is read the same way a
     variable is.  Java splits them: a *declaration* name is ``identifier`` but
     every *use* of a type is ``type_identifier`` -- in ``new Foo()``,
     ``Foo x = ...``, ``extends Foo``, ``catch (Foo e)``, ``List<Foo>``,
     ``Foo.class``, ``(Foo) x``, ``throws Foo``.  A scanner that only visits
     ``identifier`` (the literal Python port) therefore never sees a class
     being used, and the *class* half of the operator is also identically
     empty.
     Choice:  every ``type_identifier`` is a READ with entity_type "class".
     This is safe precisely because ``type_identifier`` appears in type
     positions only, so no separate context table is needed.  ``var`` is
     excluded (Java 10 ``var`` parses as ``type_identifier``).

Consequence for cross-language comparison: Java READ sets are *structurally*
broader than Python's.  They are not broader by accident or by sloppiness --
they are broader by exactly the amount needed to make the same four sets
(code_read / code_write / test_read / test_write) mean the same thing.  Any
paper table that puts a Python row next to a Java row must carry this note.

===============================================================================
WHAT IS DELIBERATELY *NOT* DIVERGED (kept identical to the Python rules)
===============================================================================
  * formal parameters are neither READ nor WRITE
    (Python: ``parameters`` appears in no table, so ``def f(x)`` never
    registers ``x``; Java ``formal_parameter``'s ``name`` matches that).
  * the loop variable of a for-each is neither READ nor WRITE, while the
    iterated expression IS a READ
    (Python: ``for_statement`` reads only its ``right`` field).
  * a compound assignment (``+=``) makes its left side a READ, not a WRITE
    (Python: ``augmented_assignment`` appears in ``is_read_context`` only).
    A plain ``=`` makes the left side a WRITE.
  * the exception variable of a ``catch`` is neither
    (Python: ``except E as e`` -> ``except_clause``, in no table).

===============================================================================
ONE ASYMMETRY THAT IS AN IMPROVEMENT, NOT A MIRROR
===============================================================================
``src/identifier_extractor.py`` has a latent bug at line 373: it branches on
the node type ``annotated_assignment``, which tree-sitter-python never emits
(the real node is ``assignment`` with a ``type`` field), so Python's ``var_type``
is populated for 0 of 3220 variables.  That file is FROZEN and the bug is left
in place.  ``var_type_of`` below reads ``field_declaration``'s / 
``local_variable_declaration``'s ``type`` field, which tree-sitter-java *does*
emit, so the Java side populates ``var_type`` correctly.  Any table comparing
Python ``var_type`` coverage against Java's is comparing a bug against a
working implementation, not two languages.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Set

from tree_sitter_languages import get_parser


# ---------------------------------------------------------------------------
# Divergence switches (see D-1 / D-2 / D-3 in the module docstring)
# ---------------------------------------------------------------------------
# Flipping all three to False yields the literal transliteration of the Python
# rules.  It is kept runnable so the "what if we had not diverged" arm of the
# experiment can actually be produced; in practice it returns near-empty hints.

COUNT_INVOCATION_NAME_AS_READ = True   # D-1
COUNT_FIELD_ACCESS_AS_READ = True      # D-2
COUNT_TYPE_USE_AS_READ = True          # D-3


def set_strict_python_mirror(strict: bool) -> None:
    """Turn all three Java-specific divergences off (True) or on (False)."""
    global COUNT_INVOCATION_NAME_AS_READ, COUNT_FIELD_ACCESS_AS_READ
    global COUNT_TYPE_USE_AS_READ
    COUNT_INVOCATION_NAME_AS_READ = not strict
    COUNT_FIELD_ACCESS_AS_READ = not strict
    COUNT_TYPE_USE_AS_READ = not strict


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

JAVA_EXTENSIONS = (".java",)

_parser = None


def get_java_parser():
    """Cached tree-sitter Java parser.

    Requires tree-sitter==0.21.3 to match tree_sitter_languages 1.10.2; with
    tree_sitter 0.26 ``get_parser`` raises TypeError.  Use the repo venv.
    """
    global _parser
    if _parser is None:
        _parser = get_parser("java")
    return _parser


def parse(code: str):
    """Parse Java source, returning the tree-sitter tree (root type 'program')."""
    return get_java_parser().parse(code.encode("utf-8", errors="ignore"))


def is_java_path(path: str) -> bool:
    return path.endswith(JAVA_EXTENSIONS)


# ---------------------------------------------------------------------------
# Node-name tables
#
# Every name below was verified against tree_sitter_languages 1.10.2's Java
# grammar by dumping real parse trees; do not add speculative node names.
# ---------------------------------------------------------------------------

# Declarations that introduce a *type*.  All map to entity_type "class" per
# src/lang/base.py CONTRACT 1; the sub-kind lives in entity_kind.
TYPE_DECL_NODES = frozenset({
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
})

ENTITY_KIND_BY_NODE = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "compact_constructor_declaration": "constructor",
    "annotation_type_element_declaration": "annotation_element",
    "field_declaration": "field",
    "local_variable_declaration": "local",
    "enum_constant": "enum_constant",
}

# Declarations that introduce a *callable*.  entity_type "function".
CALLABLE_DECL_NODES = frozenset({
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
    "annotation_type_element_declaration",
})

# Declarations that introduce a *variable* via a `variable_declarator` child.
VARIABLE_DECL_NODES = frozenset({
    "field_declaration",
    "local_variable_declaration",
})

# Nodes that open a new scope; used by the scope predicates below.
SCOPE_BOUNDARY_NODES = TYPE_DECL_NODES | CALLABLE_DECL_NODES | frozenset({
    "lambda_expression",
    "static_initializer",
    "instance_initializer",
})

# Bodies of a type declaration.
TYPE_BODY_NODES = frozenset({
    "class_body", "interface_body", "enum_body", "enum_body_declarations",
    "annotation_type_body",
})

# Parent node types that make a contained identifier a READ outright.
# (Java analogue of defuse2's binary_operator/comparison_operator/... list.)
EXPRESSION_READ_PARENTS = frozenset({
    "binary_expression",
    "unary_expression",
    "ternary_expression",
    "parenthesized_expression",
    "instanceof_expression",
    "cast_expression",
    "update_expression",
    "array_access",
    "array_initializer",
    "dimensions_expr",
    "switch_expression",
    "switch_block_statement_group",
    "switch_rule",
    "switch_label",
    "lambda_expression",
    "condition",
    "assert_statement",
    "synchronized_statement",
    "throw_statement",
    "yield_statement",
    "explicit_constructor_invocation",
    "element_value_pair",
    "element_value_array_initializer",
    "resource",
    "template_expression",
})

# Statement parents that make a contained identifier a READ (Java analogue of
# defuse2's if_statement / elif_clause / while_statement / conditional list).
STATEMENT_READ_PARENTS = frozenset({
    "if_statement",
    "while_statement",
    "do_statement",
    "for_statement",
    "return_statement",
    "expression_statement",
    "labeled_statement",
})

# Where a string's text actually lives.  Java splits plain literals from text
# blocks; Python's single equivalent is "string_content".
STRING_FRAGMENT_NODES = frozenset({
    "string_fragment",
    "multiline_string_fragment",
})

# Identifier-bearing node types the scanner visits.  Python visits only
# "identifier"; Java must also visit "type_identifier" (see D-3).
IDENTIFIER_NODES = frozenset({"identifier", "type_identifier"})

# Java 10 local type inference: parses as a type_identifier but names no type.
NON_TYPE_TYPE_IDENTIFIERS = frozenset({"var"})

# Method names that assert on a thrown exception.  The closest Java analogue of
# Python's `with pytest.raises(...)` context manager.
JUNIT_THROWS_ASSERTIONS = frozenset({
    "assertThrows",
    "assertThrowsExactly",
    "expectThrows",
    "assertThatThrownBy",
    "assertThatExceptionOfType",
    "expectMessage",
    "expectCause",
    "hasMessage",
    "hasMessageContaining",
    "hasMessageStartingWith",
    "hasMessageEndingWith",
    "withMessage",
    "withMessageContaining",
})

# Source roots stripped by path_to_fqn before turning a path into a package.
JAVA_SOURCE_ROOTS = (
    "src/main/java/",
    "src/test/java/",
    "src/main/kotlin/",
    "src/test/kotlin/",
    "src/main/",
    "src/test/",
    "src/java/",
    "test/java/",
    "java/",
    "src/",
)

MODIFIER_KEYWORDS = frozenset({
    "public", "protected", "private", "abstract", "static", "final",
    "strictfp", "default", "synchronized", "native", "transient", "volatile",
    "sealed", "non-sealed",
})


# ---------------------------------------------------------------------------
# Generic node helpers (mirrors src/identifier_extractor.py's _text etc.)
# ---------------------------------------------------------------------------

def text(node) -> str:
    if node is None:
        return ""
    return node.text.decode("utf-8", errors="ignore").strip()


def node_contains(parent, child) -> bool:
    """Mirrors defuse2's _node_contains: identity or descendant."""
    if parent is None or child is None:
        return False
    if parent == child:
        return True
    for c in parent.children:
        if node_contains(c, child):
            return True
    return False


def first_child_of_type(node, *types):
    if node is None:
        return None
    for child in node.named_children:
        if child.type in types:
            return child
    return None


def children_of_type(node, *types) -> List:
    if node is None:
        return []
    return [c for c in node.named_children if c.type in types]


def descendants_of_type(node, *types) -> List:
    out: List = []

    def walk(n):
        if n.type in types:
            out.append(n)
        for c in n.named_children:
            walk(c)

    if node is not None:
        walk(node)
    return out


def decl_name(node) -> str:
    """Bare declared name of any declaration node."""
    if node is None:
        return ""
    if node.type in VARIABLE_DECL_NODES:
        declarator = node.child_by_field_name("declarator") or first_child_of_type(
            node, "variable_declarator"
        )
        return text(declarator.child_by_field_name("name")) if declarator else ""
    return text(node.child_by_field_name("name"))


# ---------------------------------------------------------------------------
# Scope predicates -- the Java stand-in for Python's module namespace
#
# Python's is_at_module_level walks parents looking for a 'module' node and
# bails on function_definition / class_definition.  Java has no module
# namespace: a compilation unit is a package declaration, imports, and one or
# more type declarations.  Nothing but a type can live at 'program' level, so a
# literal transliteration (is_at_compilation_unit_level) admits *only* type
# names and is useless as a WRITE/READ gate.  is_at_type_body_level is the
# working analogue: the body of the outermost type declaration is treated as
# "top level", so fields and methods qualify -- the same population Python's
# module level captures (module functions, module classes, module constants).
#
# Both are provided; defuse2_java.py, being the port of the *relaxed* variant,
# calls neither (see its docstring).
# ---------------------------------------------------------------------------

def is_at_compilation_unit_level(node) -> bool:
    """Literal transliteration of is_at_module_level ('program' <-> 'module').

    Walks parents and bails on any scope boundary, exactly as the Python
    original bails on function_definition / class_definition.  Note the shared
    consequence: passed a declaration's *name* identifier this is always False
    (the name's parent IS the boundary), so -- as in the former strict defuse2.py -- it
    must be passed the declaration NODE, not the name.  Even then, in Java it
    admits only top-level type declarations: no field and no method can sit
    directly under a compilation unit.  That is precisely why
    is_at_type_body_level exists.
    """
    if node is None:
        return False
    current = node.parent
    while current is not None:
        if current.type in SCOPE_BOUNDARY_NODES:
            return False
        if current.type == "program":
            return True
        current = current.parent
    return False


def is_at_type_body_level(node) -> bool:
    """Java analogue of is_at_module_or_class_level: 'top level' == type body.

    True when the node is inside at most one type declaration and inside no
    callable/lambda -- i.e. it is a field, a method/constructor signature, an
    enum constant, or the top-level type's own name.  Method *bodies* and
    nested types return False.
    """
    if node is None:
        return False
    current = node.parent
    inside_type = False
    while current is not None:
        if current.type == "program":
            return True
        if current.type in TYPE_DECL_NODES:
            if inside_type:
                return False  # already crossed one type boundary -- too deep
            inside_type = True
        elif current.type in CALLABLE_DECL_NODES or current.type in (
            "lambda_expression", "static_initializer", "instance_initializer"
        ):
            return False
        current = current.parent
    return False


# ---------------------------------------------------------------------------
# WRITE / READ context
# ---------------------------------------------------------------------------

def _is_named_child_of(node, parent, field: str) -> bool:
    return node == parent.child_by_field_name(field)


def is_write_context(node) -> bool:
    """True when the identifier is being *defined* or *assigned to*.

    Java analogue of defuse2's is_write_context.  Like the relaxed Python
    variant this carries no scope restriction: any nesting depth counts.
    """
    parent = node.parent
    if parent is None:
        return False
    ptype = parent.type

    # Callable and type declaration names -- Python's function_definition /
    # class_definition name field.
    if ptype in CALLABLE_DECL_NODES or ptype in TYPE_DECL_NODES:
        if _is_named_child_of(node, parent, "name"):
            return True

    # Variable declarators: fields, locals, spread params, resources.
    # Python's equivalent is `assignment` with an identifier on the left.
    if ptype == "variable_declarator":
        if _is_named_child_of(node, parent, "name"):
            return True

    # Enum constants are class-level constant definitions.
    if ptype == "enum_constant":
        if _is_named_child_of(node, parent, "name"):
            return True

    # Plain assignment only.  A compound assignment (+=, |=, ...) is a READ of
    # its left operand, mirroring Python's augmented_assignment handling.
    if ptype == "assignment_expression":
        operator = parent.child_by_field_name("operator")
        if operator is not None and operator.type == "=":
            left = parent.child_by_field_name("left")
            if left is not None and node_contains(left, node):
                return True

    return False


def is_read_context(node) -> bool:
    """True when the identifier is *used* at any scope depth.

    Java analogue of defuse2's is_read_context.  See D-1/D-2/D-3 in the module
    docstring for the three places this is intentionally broader than Python.
    """
    parent = node.parent
    if parent is None:
        return False
    ptype = parent.type

    # D-3: every type_identifier is a type *use*; the grammar never puts one in
    # a declaration-name position.
    if node.type == "type_identifier":
        if not COUNT_TYPE_USE_AS_READ:
            return False
        return text(node) not in NON_TYPE_TYPE_IDENTIFIERS

    # Calls.  Python: `call` -> function field.
    if ptype == "method_invocation":
        if _is_named_child_of(node, parent, "object"):
            return True          # mirrors Python's attribute-object read
        if _is_named_child_of(node, parent, "name"):
            return COUNT_INVOCATION_NAME_AS_READ      # D-1
        if _is_named_child_of(node, parent, "arguments"):
            return True

    if ptype == "object_creation_expression":
        return True

    # Assignment.  Python: assignment -> right, augmented_assignment -> both.
    if ptype == "assignment_expression":
        right = parent.child_by_field_name("right")
        if right is not None and node_contains(right, node):
            return True
        operator = parent.child_by_field_name("operator")
        if operator is not None and operator.type != "=":
            left = parent.child_by_field_name("left")
            if left is not None and node_contains(left, node):
                return True
        return False

    # Initialiser of a declarator -- the Java shape of `x = <expr>`.
    if ptype == "variable_declarator":
        return _is_named_child_of(node, parent, "value")

    # Argument positions.  Python: argument_list / keyword_argument.
    if ptype in ("argument_list", "annotation_argument_list"):
        return True

    # An annotation element's key names a parameter of the annotation type, not
    # an entity in the program; only its value is a read.
    if ptype == "element_value_pair":
        return not _is_named_child_of(node, parent, "key")

    if ptype in EXPRESSION_READ_PARENTS:
        return True

    # for-each: the iterated expression is a read, the loop variable is not
    # (mirrors Python's for_statement -> right).
    if ptype == "enhanced_for_statement":
        return _is_named_child_of(node, parent, "value")

    if ptype in STATEMENT_READ_PARENTS:
        return True

    # D-2: field access.  The object half mirrors Python; the field half does
    # not (Python misses `self.x`).
    if ptype == "field_access":
        obj = parent.child_by_field_name("object")
        if obj is not None and node_contains(obj, node):
            return True
        if _is_named_child_of(node, parent, "field"):
            return COUNT_FIELD_ACCESS_AS_READ
        return False

    # Annotations are Java's decorators; Python's `decorator` is an outright read.
    if ptype in ("annotation", "marker_annotation"):
        return True

    return False


# ---------------------------------------------------------------------------
# Entity classification
# ---------------------------------------------------------------------------

def classify_entity_type(node) -> str:
    """Map an identifier node to one of function | class | variable | attribute.

    src/lang/base.py CONTRACT 3: these four are the only legal typed-token
    entity types, and the downstream _ENTITY_GATE recognises only the first
    three for catalogue records.
    """
    if node.type == "type_identifier":
        return "class"

    parent = node.parent
    if parent is None:
        return "variable"
    ptype = parent.type

    if ptype in CALLABLE_DECL_NODES and _is_named_child_of(node, parent, "name"):
        return "function"
    if ptype in TYPE_DECL_NODES and _is_named_child_of(node, parent, "name"):
        return "class"
    if ptype == "method_invocation" and _is_named_child_of(node, parent, "name"):
        return "function"
    if ptype == "field_access" and _is_named_child_of(node, parent, "field"):
        return "attribute"
    if ptype == "enum_constant" and _is_named_child_of(node, parent, "name"):
        return "variable"
    # A Java annotation names an annotation *type*.  (Python's closest shape,
    # `decorator`, leaves the name typed "variable"; Java can do better because
    # the grammar guarantees the name resolves to a type.)
    if ptype in ("annotation", "marker_annotation") and _is_named_child_of(node, parent, "name"):
        return "class"
    return "variable"


def entity_kind_for(node) -> Optional[str]:
    """The optional entity_kind of src/lang/base.py CONTRACT 1.

    entity_type stays in {function, class, variable}; a Java interface / enum /
    record / annotation is entity_type="class" plus entity_kind="interface"|...
    Python never sets entity_kind, so exclude_none serialisation keeps existing
    Python output byte-identical.
    """
    return ENTITY_KIND_BY_NODE.get(node.type if node is not None else "")


# ---------------------------------------------------------------------------
# Javadoc
#
# Structurally different from Python: a Python docstring is the first *string
# statement inside* the body, a javadoc is a `block_comment` *preceding* the
# declaration (and preceding its annotations, which live in `modifiers`).
# ---------------------------------------------------------------------------

def javadoc_for(node, max_gap: int = 1) -> Optional[str]:
    """Return the cleaned javadoc immediately preceding a declaration node.

    max_gap is the number of blank lines tolerated between the end of the
    comment and the start of the declaration.  Only `/** ... */` counts; a
    plain `/* ... */` block comment is not documentation.
    """
    if node is None:
        return None
    prev = node.prev_named_sibling
    if prev is None or prev.type != "block_comment":
        return None
    raw = prev.text.decode("utf-8", errors="ignore")
    if not raw.startswith("/**"):
        return None
    if node.start_point[0] - prev.end_point[0] > max_gap:
        return None
    return _clean_javadoc(raw)


def _clean_javadoc(raw: str) -> Optional[str]:
    body = raw
    if body.startswith("/**"):
        body = body[3:]
    elif body.startswith("/*"):
        body = body[2:]
    if body.endswith("*/"):
        body = body[:-2]

    lines = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        lines.append(line)

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def javadoc_description(doc: Optional[str]) -> Optional[str]:
    """The free-text part of a javadoc, i.e. everything before the first @tag."""
    if not doc:
        return None
    out = []
    for line in doc.splitlines():
        if line.lstrip().startswith("@"):
            break
        out.append(line)
    result = "\n".join(out).strip()
    return result or None


def weak_semantics(doc: Optional[str]) -> Optional[str]:
    """First non-empty, non-tag line -- mirrors _weak_semantics in the extractor."""
    desc = javadoc_description(doc) or doc
    if not desc:
        return None
    for line in desc.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def strong_semantics(doc: Optional[str]) -> Optional[str]:
    """Full javadoc when it is more than one line -- mirrors the extractor."""
    if doc and len(doc.splitlines()) > 1:
        return doc
    return None


# ---------------------------------------------------------------------------
# Modifiers, visibility, supertypes, types
# ---------------------------------------------------------------------------

def _modifiers_node(node):
    return first_child_of_type(node, "modifiers")


def modifiers_of(node) -> List[str]:
    """Keyword modifiers (public/static/final/...) of a declaration, in order.

    Annotations live in the same `modifiers` node but are named children; they
    are returned by annotations_of instead.
    """
    mods = _modifiers_node(node)
    if mods is None:
        return []
    return [c.type for c in mods.children
            if not c.is_named and c.type in MODIFIER_KEYWORDS]


def annotations_of(node) -> List[str]:
    mods = _modifiers_node(node)
    if mods is None:
        return []
    return [text(c) for c in mods.named_children
            if c.type in ("annotation", "marker_annotation")]


def visibility_of(node) -> str:
    """public | protected | private | package-private (Java's default)."""
    mods = modifiers_of(node)
    for level in ("public", "protected", "private"):
        if level in mods:
            return level
    return "package-private"


def is_public(node) -> bool:
    return visibility_of(node) == "public"


def is_static(node) -> bool:
    return "static" in modifiers_of(node)


def base_types(node) -> List[str]:
    """Supertypes of a type declaration: extends + implements + permits.

    class C extends B implements I, J  -> ["B", "I", "J"]
    interface I extends J, K           -> ["J", "K"]
    """
    out: List[str] = []
    if node is None:
        return out
    superclass = node.child_by_field_name("superclass") or first_child_of_type(
        node, "superclass"
    )
    if superclass is not None:
        for c in superclass.named_children:
            out.append(text(c))
    for holder_type in ("super_interfaces", "extends_interfaces", "permits"):
        holder = first_child_of_type(node, holder_type)
        if holder is None:
            continue
        type_list = first_child_of_type(holder, "type_list") or holder
        for c in type_list.named_children:
            out.append(text(c))
    return [t for t in out if t]


def generics_of(node) -> List[str]:
    tp = first_child_of_type(node, "type_parameters")
    if tp is None:
        return []
    return [text(c) for c in tp.named_children if c.type == "type_parameter"]


def var_type_of(decl_node) -> Optional[str]:
    """Declared type of a field_declaration / local_variable_declaration.

    NOTE the asymmetry documented in the module docstring: the frozen Python
    extractor never populates var_type because it branches on a node type
    tree-sitter-python does not emit.  Java's `type` field is real, so this
    returns a value.
    """
    if decl_node is None:
        return None
    return text(decl_node.child_by_field_name("type")) or None


def var_value_of(decl_node) -> Optional[str]:
    declarator = decl_node.child_by_field_name("declarator") or first_child_of_type(
        decl_node, "variable_declarator"
    )
    if declarator is None:
        return None
    return text(declarator.child_by_field_name("value")) or None


# ---------------------------------------------------------------------------
# Arity and the CONTRACT 2 catalogue key
# ---------------------------------------------------------------------------

def arity_of(callable_node) -> int:
    """Declared parameter count.  A varargs parameter counts as one."""
    if callable_node is None:
        return 0
    params = callable_node.child_by_field_name("parameters")
    if params is None:
        params = first_child_of_type(callable_node, "formal_parameters")
    if params is None:
        return 0
    return len([c for c in params.named_children
                if c.type in ("formal_parameter", "spread_parameter", "receiver_parameter")])


def catalogue_key(name: str, node) -> str:
    """src/lang/base.py CONTRACT 2.

    Java callables are keyed "name#arity" because one class may declare
    doThing(String) and doThing(int); Java types and fields keep the bare name.
    The record's own `name` field always stays bare -- the discriminator lives
    only in the dict key, so rendered hints are unaffected.

    The four read/write sets and all seven usage operators stay on BARE names
    (CONTRACT 3): a call site cannot recover parameter types, so a richer key
    would make every intersection empty.
    """
    if node is not None and node.type in CALLABLE_DECL_NODES:
        return f"{name}#{arity_of(node)}"
    return name


# ---------------------------------------------------------------------------
# Exceptions: the _get_raise_string analogue
# ---------------------------------------------------------------------------

def get_raise_string(node) -> Optional[str]:
    """Java analogue of defuse2's _get_raise_string.

    Python walks raise_statement -> call -> argument_list -> string ->
    string_content, and separately handles `with pytest.raises(...)`.

    Java's two shapes are:
      throw new X("msg")   -> throw_statement -> object_creation_expression ->
                              argument_list -> string_literal -> string_fragment
      JUnit assertions     -> method_invocation named assertThrows /
                              expectMessage / hasMessageContaining / ... whose
                              argument_list carries the expected message.

    The position gate is the same as Python's: the first three levels must
    match exactly, after which the walk descends freely to the first string
    fragment (so `new X("a: " + b)` and `new X(String.format("...", y))` both
    yield their literal part, exactly as the Python version does).
    """
    if node is None:
        return None
    if node.type == "throw_statement":
        return _walk_to_fragment(
            node, 0, ["throw_statement", "object_creation_expression", "argument_list"]
        )
    if node.type == "method_invocation" and _is_junit_throws_assertion(node):
        return _walk_to_fragment(node, 0, ["method_invocation", "argument_list"])
    return None


def _is_junit_throws_assertion(node) -> bool:
    return text(node.child_by_field_name("name")) in JUNIT_THROWS_ASSERTIONS


def _walk_to_fragment(node, pos: int, prefix: Sequence[str]) -> Optional[str]:
    """Positional walk mirroring _get_raise_string's inner traverse()."""
    found = {"node": None}

    def traverse(n, p):
        if found["node"] is not None:
            return
        if p < len(prefix) and n.type != prefix[p]:
            return
        if n.type in STRING_FRAGMENT_NODES:
            found["node"] = n
            return
        for child in n.named_children:
            traverse(child, p + 1)

    traverse(node, pos)
    if found["node"] is None:
        return None
    return found["node"].text.decode("utf-8", errors="ignore")


def get_expected_exception_types(node) -> List[str]:
    """Exception *types* a node declares or asserts on.

    Java states exception types declaratively in three places Python has no
    equivalent for:
      throws IOException, SQLException      -> a `throws` clause on a method
      assertThrows(Foo.class, () -> ...)    -> JUnit 5
      @Test(expected = Foo.class)           -> JUnit 4

    Kept separate from get_raise_string because these carry a type and no
    message, so they cannot participate in the error-message text match that
    defuse2 uses to inject error entities into forward hints.
    """
    if node is None:
        return []
    out: List[str] = []

    if node.type in ("throws", "throws_clause"):
        out.extend(text(c) for c in node.named_children)

    elif node.type in CALLABLE_DECL_NODES:
        throws = first_child_of_type(node, "throws")
        if throws is not None:
            out.extend(text(c) for c in throws.named_children)

    elif node.type == "throw_statement":
        oce = first_child_of_type(node, "object_creation_expression")
        if oce is not None:
            out.append(text(oce.child_by_field_name("type")))
        else:
            ident = first_child_of_type(node, "identifier")
            if ident is not None:
                out.append(text(ident))

    elif node.type == "method_invocation" and _is_junit_throws_assertion(node):
        args = node.child_by_field_name("arguments")
        for lit in descendants_of_type(args, "class_literal"):
            ti = first_child_of_type(lit, "type_identifier", "scoped_type_identifier")
            if ti is not None:
                out.append(text(ti))

    elif node.type in ("annotation", "marker_annotation"):
        if text(node.child_by_field_name("name")) == "Test":
            args = node.child_by_field_name("arguments")
            for pair in descendants_of_type(args, "element_value_pair"):
                if text(pair.child_by_field_name("key")) != "expected":
                    continue
                value = pair.child_by_field_name("value")
                for lit in descendants_of_type(value, "class_literal"):
                    ti = first_child_of_type(lit, "type_identifier", "scoped_type_identifier")
                    if ti is not None:
                        out.append(text(ti))

    return [t for t in dict.fromkeys(out) if t]


def get_thrown_exception_values(node) -> List[str]:
    """All string literals passed to `throw new X(...)` within a subtree."""
    out: List[str] = []
    for th in descendants_of_type(node, "throw_statement"):
        msg = get_raise_string(th)
        if msg:
            out.append(msg)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# Imports and paths
# ---------------------------------------------------------------------------

def path_to_fqn(path: str) -> str:
    """Convert a Java file path to its fully-qualified type name.

    "src/main/java/com/x/Foo.java" -> "com.x.Foo"
    "core/src/test/java/a/BTest.java" -> "a.BTest"

    This is the Java stand-in for defuse2's _path_to_module.  It is a path
    heuristic, not a parse: a file whose directory layout disagrees with its
    `package` statement (rare, and illegal for public types) resolves wrongly.
    package_of_tree() below reads the real declaration when a parse is at hand.
    """
    name = path.replace("\\", "/")
    if name.endswith(".java"):
        name = name[: -len(".java")]
    for root in JAVA_SOURCE_ROOTS:
        idx = name.find(root)
        if idx != -1:
            name = name[idx + len(root):]
            break
    return name.replace("/", ".").strip(".")


def package_of_tree(root) -> Optional[str]:
    for child in root.named_children:
        if child.type == "package_declaration":
            for c in child.named_children:
                if c.type in ("scoped_identifier", "identifier"):
                    return text(c)
    return None


def import_target(import_node) -> Optional[str]:
    """The dotted path of an import_declaration, without any trailing `.*`."""
    if import_node is None or import_node.type != "import_declaration":
        return None
    for c in import_node.named_children:
        if c.type in ("scoped_identifier", "identifier"):
            return text(c)
    return None


def is_static_import(import_node) -> bool:
    return any(c.type == "static" or (not c.is_named and c.type == "static")
               for c in import_node.children)


def is_wildcard_import(import_node) -> bool:
    # The `*` of `import p.q.*;` parses as a NAMED node of type "asterisk",
    # not as an anonymous "*" token.  Verified against the 1.10.2 grammar.
    return any(c.type == "asterisk" for c in import_node.children)


def file_imports(root) -> List[str]:
    """File-level imports as source text -- the `imports` field of CONTRACT 1."""
    return [text(n) for n in root.named_children if n.type == "import_declaration"]


__all__ = [
    "COUNT_FIELD_ACCESS_AS_READ",
    "COUNT_INVOCATION_NAME_AS_READ",
    "COUNT_TYPE_USE_AS_READ",
    "CALLABLE_DECL_NODES",
    "ENTITY_KIND_BY_NODE",
    "EXPRESSION_READ_PARENTS",
    "IDENTIFIER_NODES",
    "JAVA_EXTENSIONS",
    "JUNIT_THROWS_ASSERTIONS",
    "STATEMENT_READ_PARENTS",
    "STRING_FRAGMENT_NODES",
    "TYPE_DECL_NODES",
    "VARIABLE_DECL_NODES",
    "annotations_of",
    "arity_of",
    "base_types",
    "catalogue_key",
    "children_of_type",
    "classify_entity_type",
    "decl_name",
    "descendants_of_type",
    "entity_kind_for",
    "file_imports",
    "first_child_of_type",
    "generics_of",
    "get_expected_exception_types",
    "get_java_parser",
    "get_raise_string",
    "get_thrown_exception_values",
    "import_target",
    "is_at_compilation_unit_level",
    "is_at_type_body_level",
    "is_java_path",
    "is_public",
    "is_read_context",
    "is_static",
    "is_static_import",
    "is_wildcard_import",
    "is_write_context",
    "javadoc_description",
    "javadoc_for",
    "modifiers_of",
    "node_contains",
    "package_of_tree",
    "parse",
    "path_to_fqn",
    "set_strict_python_mirror",
    "strong_semantics",
    "text",
    "var_type_of",
    "var_value_of",
    "visibility_of",
    "weak_semantics",
]
