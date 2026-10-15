#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Java rich-entity extractor — the CONTRACT 1 counterpart of
``src/identifier_extractor.py``'s ``extract_rich_entities()``.

ADDITIVE ONLY.  Nothing here imports, patches or otherwise perturbs the Python
extraction path; ``src/identifier_extractor.py`` stays byte-identical and the
published Python results stay reproducible.

What is emitted
---------------
``extract_rich_entities(code, file_path, is_new_file=False)`` returns
``dict[catalogue_key, field_dict]`` where every field dict is a subset of
``IdentifierInformation``'s fields (plus the optional ``entity_kind``, which the
frozen model currently drops on ``model_validate`` — see NOTES).

  method_declaration / constructor_declaration      -> entity_type "function"
  compact_constructor_declaration                   -> entity_type "function"
  annotation_type_element_declaration               -> entity_type "function"
  class/interface/enum/record/annotation_type       -> entity_type "class"
                                                       + entity_kind
  field_declaration / enum_constant / record comp.  -> entity_type "variable"

Catalogue key (CONTRACT 2): Java callables are keyed ``f"{name}#{arity}"`` so
that ``doThing(String)`` and ``doThing(String, int)`` do not clobber each other;
types and fields keep the bare name.  The record's own ``name`` field is always
the bare name, so rendered hints are unaffected.  Because the four read/write
sets stay on bare names, ``catalogue_groups(catalogue)`` gives the consumer the
inverse index ``{bare name: [catalogue keys]}`` it needs to resolve a name from
a diff to 1..N records (measured: 230 overloaded bare names across the 43
SWE-bench-Multilingual Java instances, so this is load-bearing, not theoretical).

Module-level switches: ``INCLUDE_CONSTRUCTORS`` (default True — the brief asks
for constructor records; Python drops ``__init__``) and
``INCLUDE_PACKAGE_IN_IMPORTS`` (default False — the brief asks for
``import_declaration`` only).

Structural differences vs. the Python extractor (deliberate, documented)
-----------------------------------------------------------------------
* Java has no top-level function or variable: ``program``'s only declarations
  are ``package_declaration``, ``import_declaration`` and the five type
  declarations.  To keep the ``Func`` / ``Var`` taxonomy subtrees populated (and
  because a call site in a diff yields a bare method name that must resolve to
  *something* richer than ``{name, entity_type:"variable"}``), members are
  registered BOTH as top-level catalogue entries AND as ``cls_methods`` /
  ``cls_variables`` sub-records of their declaring type.  Set
  ``include_members=False`` to get the strict Python-shaped behaviour (types
  only).  Python's class methods are *not* top-level entries, so this is an
  asymmetry — see NOTES.
* Javadoc is a ``block_comment`` sibling PRECEDING the declaration, not a string
  statement inside the body, so semantics extraction is written fresh.
* ``param_defaults`` is structurally empty in Java and is always None.
* ``var_type`` IS populated (from ``field_declaration``'s ``type`` field).  The
  Python path never populates it (a latent, frozen bug) — see NOTES.
* v1 does NOT recurse into nested type declarations, symmetric with the Python
  extractor which never descends into a nested ``class_definition``.

NOTES (asymmetries a reader must know about)
--------------------------------------------
1. ``var_type``: 0/3220 on the Python goldens because
   ``identifier_extractor.py:373`` branches on ``annotated_assignment``, a node
   type tree-sitter-python never emits.  That file is FROZEN and was not
   touched.  Java populates ``var_type`` on ~100% of fields, so ``VarType`` /
   ``ClsVarType`` fire for Java and have never fired for Python.
2. ``entity_kind`` is not (yet) a field on the frozen ``IdentifierInformation``
   model, so ``model_validate`` silently drops it (pydantic's default
   ``extra="ignore"``, verified).  Emitting it is forward-compatible and costs
   nothing today.
3. Field/enum-constant records carry weak/strong semantics from their javadoc;
   the Python extractor hardcodes None for variables.
"""

from __future__ import annotations

import re
import sys
from typing import Optional

from tree_sitter_languages import get_parser

try:  # normal import path: `python -m ...` / `import src.lang.java_extractor`
    from src.lang import registry
except ImportError:  # pragma: no cover - direct `python src/lang/java_extractor.py`
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    from src.lang import registry


# ---------------------------------------------------------------------------
# Parser (memoised: get_parser("java") builds a fresh Parser on every call)
# ---------------------------------------------------------------------------

_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        _PARSER = get_parser("java")
    return _PARSER


# ---------------------------------------------------------------------------
# Node-type tables (all verified against tree_sitter_languages 1.10.2)
# ---------------------------------------------------------------------------

TYPE_DECLS = (
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
)

_KIND_OF_DECL = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}

METHOD_DECLS = (
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
    "annotation_type_element_declaration",
)

_BODY_TYPES = ("class_body", "interface_body", "enum_body", "annotation_type_body",
               "enum_body_declarations")

# Scopes a local-variable scan must not descend into (the Java analogue of the
# Python scanner refusing to descend into a nested def/class).
_LOCAL_SCAN_STOP = ("lambda_expression",) + METHOD_DECLS + TYPE_DECLS + _BODY_TYPES

# Constructors are the Java analogue of Python's `__init__`, which the Python
# extractor drops from cls_methods and from the public/private name lists.  The
# implementation brief asks for constructor records explicitly, so they are kept
# (catalogue entry + cls_methods + name lists); flip this to False for strict
# Python-shaped parity.
INCLUDE_CONSTRUCTORS = True

# Set True to prefix `imports` with the file's `package ...;` declaration.
# The plan doc asks for it, the implementation brief asks for import_declaration
# only; the brief wins and this is the one-line switch.
INCLUDE_PACKAGE_IN_IMPORTS = False

_MODIFIER_KEYWORDS = frozenset({
    "public", "protected", "private", "abstract", "static", "final", "strictfp",
    "default", "synchronized", "native", "transient", "volatile", "sealed",
    "non-sealed",
})


# ---------------------------------------------------------------------------
# Small helpers (mirroring identifier_extractor.py's _text / _first_child_of_type)
# ---------------------------------------------------------------------------

def _text(node) -> str:
    if node is None:
        return ""
    return node.text.decode("utf-8", errors="ignore").strip()


def _first_child_of_type(node, *types):
    if node is None:
        return None
    for child in node.named_children:
        if child.type in types:
            return child
    return None


def _children_of_type(node, *types):
    if node is None:
        return []
    return [c for c in node.named_children if c.type in types]


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _join(parts) -> Optional[str]:
    """", "-join, de-duplicated, order preserving; None when empty."""
    parts = [p for p in parts if p]
    return ", ".join(dict.fromkeys(parts)) or None


def _location(node, file_path: str) -> tuple[str, str]:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    return f"{file_path}:{start_line}", f"{file_path}:{start_line}-{end_line}"


def _modifier_keywords(node) -> set[str]:
    """Modifier keywords of a declaration.

    They are ANONYMOUS children of the `modifiers` node (annotations are the
    named ones), so a substring test on the text would wrongly match e.g.
    `@SuppressWarnings("public")`.
    """
    mods = _first_child_of_type(node, "modifiers")
    if mods is None:
        return set()
    return {c.type for c in mods.children if c.type in _MODIFIER_KEYWORDS}


def _split_java_type(raw: str) -> tuple[Optional[str], Optional[str]]:
    """("Map", "Map<String, List<T>>");  "String[]" -> ("String[]", "String[]")."""
    complete = _norm_ws(raw)
    if not complete:
        return None, None
    if "<" not in complete:
        return complete, complete
    base = complete.split("<", 1)[0].strip()
    trailing = re.search(r"((?:\s*\[\s*\])+)\s*$", complete)
    if trailing:
        base += "[]" * trailing.group(1).count("[")
    return (base or complete), complete


# ---------------------------------------------------------------------------
# Javadoc  ->  weak_semantics / strong_semantics
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(
    r"</?(?:p|br|li|ul|ol|pre|b|i|em|strong|code|tt|blockquote|h[1-6])\s*/?>",
    re.IGNORECASE,
)
_INLINE_TAG_RE = re.compile(r"\{@(?:link|linkplain|code|literal|value)\s+([^}]*)\}")
_MAX_JAVADOC_GAP_LINES = 2   # blank lines tolerated between javadoc and decl


def _javadoc_node(decl):
    """The `/** ... */` block_comment immediately preceding `decl`, if any."""
    sib = decl.prev_named_sibling
    while sib is not None and sib.type == "line_comment":
        sib = sib.prev_named_sibling
    if sib is None or sib.type != "block_comment":
        return None
    if not _text(sib).startswith("/**"):
        return None  # a license header / plain block comment is not a doc comment
    if decl.start_point[0] - sib.end_point[0] > _MAX_JAVADOC_GAP_LINES:
        return None
    return sib


def _clean_javadoc(raw: str) -> str:
    """Strip the comment delimiters, the leading `*` gutter and javadoc markup."""
    body = raw
    if body.startswith("/**"):
        body = body[3:]
    elif body.startswith("/*"):
        body = body[2:]
    if body.endswith("*/"):
        body = body[:-2]
    lines: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        lines.append(line)
    text = "\n".join(lines)
    text = _INLINE_TAG_RE.sub(lambda m: m.group(1).strip(), text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _description_part(cleaned: str) -> str:
    """Everything before the first block tag line (@param / @return / @throws)."""
    out: list[str] = []
    for line in cleaned.splitlines():
        if line.lstrip().startswith("@"):
            break
        out.append(line)
    return "\n".join(out).strip()


def _first_paragraph(desc: str) -> str:
    """Javadoc's summary never runs past the first paragraph."""
    out: list[str] = []
    for line in desc.splitlines():
        if not line.strip():
            if out:
                break
            continue
        out.append(line)
    return "\n".join(out)


def _first_sentence(cleaned: str) -> Optional[str]:
    desc = _description_part(cleaned) or cleaned
    desc = _first_paragraph(desc) or desc
    if not desc:
        return None
    flat = _norm_ws(desc)
    if not flat:
        return None
    m = re.search(r"\.(?:\s|$)", flat)
    if m:
        return flat[: m.start() + 1].strip()
    # No sentence terminator: fall back to the first non-empty line (Python's rule)
    for line in desc.splitlines():
        line = line.strip()
        if line:
            return line
    return flat


def _semantics(decl) -> tuple[Optional[str], Optional[str]]:
    node = _javadoc_node(decl)
    if node is None:
        return None, None
    cleaned = _clean_javadoc(_text(node))
    if not cleaned:
        return None, None
    weak = _first_sentence(cleaned)
    strong = cleaned if (weak is None or len(cleaned) > len(weak)) else None
    return weak, strong


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def _param_nodes(params_node) -> list:
    if params_node is None:
        return []
    return [c for c in params_node.named_children
            if c.type in ("formal_parameter", "spread_parameter", "receiver_parameter")]


def _param_name_type(param) -> tuple[str, str]:
    """(name, type) for formal_parameter / spread_parameter / receiver_parameter."""
    if param.type == "spread_parameter":
        # No `name` field; the name lives in a variable_declarator child.
        decl = _first_child_of_type(param, "variable_declarator")
        name = _text(decl.child_by_field_name("name")) if decl is not None else ""
        tnode = None
        for c in param.named_children:
            if c.type not in ("modifiers", "variable_declarator"):
                tnode = c
                break
        return name, (_norm_ws(_text(tnode)) + "..." if tnode is not None else "")
    name = _text(param.child_by_field_name("name"))
    tnode = param.child_by_field_name("type")
    return name, _norm_ws(_text(tnode)) if tnode is not None else ""


def _is_receiver(param, pname: str) -> bool:
    """A receiver is `receiver_parameter`, OR — grammar quirk, verified — a
    `formal_parameter` named `this` when the receiver carries a type annotation
    (`void f(@Tag Foo this)`).  `this` is reserved, so the name test is safe.
    """
    return param.type == "receiver_parameter" or pname == "this"


def _arity(node) -> int:
    """Call-site arity: an explicit receiver (`void f(Foo this, int i)`) is not
    an argument — `o.f(i)` passes one.  Java's receiver is the structural
    analogue of Python's `self`, which the Python extractor also drops from
    input_names / input_spec."""
    return len([p for p in _param_nodes(node.child_by_field_name("parameters"))
                if not _is_receiver(p, _param_name_type(p)[0])])


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

def _string_value(node) -> Optional[str]:
    """Text of a string_literal / text_block with its delimiters removed."""
    raw = _text(node)
    if node.type == "text_block":
        return raw.strip('"').strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return re.sub(r'\\(["\\\\\'])', r"\1", raw[1:-1])
    return raw or None


def _string_fragments(node) -> list[str]:
    """String literals inside an expression (Java's `"a " + x + " b"` is the
    structural analogue of Python's `concatenated_string`, which the Python
    extractor already handles)."""
    out: list[str] = []
    if node.type in ("string_literal", "text_block"):
        v = _string_value(node)
        if v:
            out.append(v)
        return out
    if node.type in ("binary_expression", "parenthesized_expression"):
        for c in node.named_children:
            out.extend(_string_fragments(c))
    return out


def _scan_throws(decl, body_node) -> tuple[list[str], list[str]]:
    """(exception_types, exception_values).

    Types come from the declarative `throws` clause AND from `throw new X(...)`
    in the body; values from string literals passed to those constructors.
    """
    types: list[str] = []
    values: list[str] = []

    throws_clause = _first_child_of_type(decl, "throws")
    if throws_clause is not None:
        for t in throws_clause.named_children:
            txt = _norm_ws(_text(t))
            if txt:
                types.append(txt)

    def _scan(n):
        if n.type == "throw_statement":
            for child in n.named_children:
                if child.type == "object_creation_expression":
                    tnode = child.child_by_field_name("type")
                    if tnode is None:
                        tnode = _first_child_of_type(
                            child, "type_identifier", "scoped_type_identifier",
                            "generic_type")
                    if tnode is not None:
                        types.append(_norm_ws(_text(tnode)))
                    args = child.child_by_field_name("arguments")
                    if args is not None:
                        for arg in args.named_children:
                            frags = _string_fragments(arg)
                            if frags:
                                values.append(_norm_ws(" ".join(frags)))
                elif child.type in ("identifier", "field_access"):
                    # mirrors the Python extractor's `raise e` handling
                    types.append(_text(child))
        for c in n.named_children:
            _scan(c)

    if body_node is not None:
        _scan(body_node)
    return types, values


# ---------------------------------------------------------------------------
# Local variables
# ---------------------------------------------------------------------------

def _scan_locals(body_node) -> list[str]:
    """Names declared by `local_variable_declaration`, a try-with-resources
    `resource`, or an enhanced `for (T x : ...)`.

    Does not descend into lambda bodies, anonymous-class bodies or nested
    type/method declarations — symmetric with the Python scanner's refusal to
    descend into a nested def/class.
    """
    names: list[str] = []

    def _walk(n, depth=0):
        if depth > 0 and n.type in _LOCAL_SCAN_STOP:
            return
        if n.type in ("local_variable_declaration", "resource"):
            declarators = _children_of_type(n, "variable_declarator")
            if declarators:
                for d in declarators:
                    nm = _text(d.child_by_field_name("name"))
                    if nm and nm not in names:
                        names.append(nm)
            else:  # `resource` carries the name directly
                nm = _text(n.child_by_field_name("name"))
                if nm and nm not in names:
                    names.append(nm)
        elif n.type == "enhanced_for_statement":
            nm = _text(n.child_by_field_name("name"))
            if nm and nm not in names:
                names.append(nm)
        for c in n.named_children:
            _walk(c, depth + 1)

    if body_node is not None:
        _walk(body_node)
    return names


# ---------------------------------------------------------------------------
# Method / constructor extraction  ->  entity_type "function"
# ---------------------------------------------------------------------------

def _extract_method(node, file_path: str, is_new_file: bool) -> dict:
    """CONTRACT-1 function record for a method/constructor/annotation element."""
    name = _text(node.child_by_field_name("name"))
    params_node = node.child_by_field_name("parameters")
    body_node = node.child_by_field_name("body")
    partial_location, complete_location = _location(node, file_path)
    weak_s, strong_s = _semantics(node)

    # --- Signature / inputs -------------------------------------------------
    sig_parts: list[str] = []
    input_names: list[str] = []
    input_types: list[str] = []
    for param in _param_nodes(params_node):
        pname, ptype = _param_name_type(param)
        if ptype and pname:
            sig_parts.append(f"{ptype} {pname}")
        else:
            sig_parts.append(_norm_ws(_text(param)))
        # The receiver stays in the signature (Python keeps `self` there too)
        # but is not an input and not part of the arity.
        if pname and not _is_receiver(param, pname):
            input_names.append(pname)
            if ptype:
                input_types.append(f"{pname}: {ptype}")

    # A generic method's own <T> has no taxonomy row of its own (Generic is
    # class-scope), so it rides on the signature, which is where it belongs.
    tp_node = node.child_by_field_name("type_parameters")
    generics_str = _norm_ws(_text(tp_node)) if tp_node is not None else ""

    if node.type == "annotation_type_element_declaration":
        signature = f"{name}{generics_str}()"
    else:
        signature = f"{name}{generics_str}({', '.join(sig_parts)})"

    # --- Return type --------------------------------------------------------
    output_partial_type = output_complete_type = None
    if node.type not in ("constructor_declaration", "compact_constructor_declaration"):
        ret_node = node.child_by_field_name("type")
        if ret_node is not None:
            output_partial_type, output_complete_type = _split_java_type(_text(ret_node))
            if output_complete_type:
                signature += f" -> {output_complete_type}"

    input_spec = ", ".join(input_types) or ", ".join(input_names) or None

    exception_types, exception_values = _scan_throws(node, body_node)
    local_variables = _scan_locals(body_node)

    record = {
        "name": name,
        "entity_type": "function",
        "path": file_path,
        "is_new_file": is_new_file,
        "partial_location": partial_location,
        "complete_location": complete_location,
        "weak_semantics": weak_s,
        "strong_semantics": strong_s,
        "signature": signature,
        "input_spec": input_spec,
        "input_names": ", ".join(input_names) or None,
        "input_types": ", ".join(input_types) or None,
        "output_partial_type": output_partial_type,
        "output_complete_type": output_complete_type,
        "local_variables": ", ".join(local_variables) or None,
        "exception_types": _join(exception_types),
        "exception_values": _join(exception_values),
        # Java has no default parameter values — structurally always None.
        "param_defaults": None,
    }
    if node.type in ("constructor_declaration", "compact_constructor_declaration"):
        record["entity_kind"] = "constructor"
    elif node.type == "annotation_type_element_declaration":
        record["entity_kind"] = "annotation_element"
    return record


def _is_public(node, owner_kind: Optional[str]) -> bool:
    """Java has real modifiers, unlike Python's leading-underscore convention.

    Interface / annotation members are implicitly public unless declared private.
    """
    mods = _modifier_keywords(node)
    if "public" in mods:
        return True
    if mods & {"private", "protected"}:
        return False
    if owner_kind in ("interface", "annotation"):
        return True
    return False  # package-private counts as non-public


# ---------------------------------------------------------------------------
# Field / enum-constant / record-component extraction  ->  entity_type "variable"
# ---------------------------------------------------------------------------

def _variable_record(name, file_path, is_new_file, node, var_type, var_value,
                     weak_s=None, strong_s=None, entity_kind=None) -> dict:
    partial_location, complete_location = _location(node, file_path)
    rec = {
        "name": name,
        "entity_type": "variable",
        "path": file_path,
        "is_new_file": is_new_file,
        "partial_location": partial_location,
        "complete_location": complete_location,
        "var_type": var_type or None,
        "var_value": var_value or None,
        "weak_semantics": weak_s,
        "strong_semantics": strong_s,
    }
    if entity_kind:
        rec["entity_kind"] = entity_kind
    return rec


def _extract_fields(node, file_path: str, is_new_file: bool) -> list[dict]:
    """One `field_declaration` can declare N variables: `int COUNT = 3, OTHER = 4;`"""
    type_node = node.child_by_field_name("type")
    var_type = _norm_ws(_text(type_node)) if type_node is not None else None
    weak_s, strong_s = _semantics(node)
    out: list[dict] = []
    for decl in _children_of_type(node, "variable_declarator"):
        name = _text(decl.child_by_field_name("name"))
        if not name:
            continue
        value_node = decl.child_by_field_name("value")
        vtype = var_type
        # `int a[]` — dimensions live on the declarator, not the type.
        if _first_child_of_type(decl, "dimensions") is not None and vtype:
            vtype = vtype + "[]"
        out.append(_variable_record(
            name, file_path, is_new_file, decl, vtype,
            _norm_ws(_text(value_node)) if value_node is not None else None,
            weak_s, strong_s))
    return out


def _extract_enum_constants(body_node, enum_name: str, file_path: str,
                            is_new_file: bool) -> list[dict]:
    out: list[dict] = []
    for const in _children_of_type(body_node, "enum_constant"):
        name = _text(const.child_by_field_name("name"))
        if not name:
            continue
        args = const.child_by_field_name("arguments")
        weak_s, strong_s = _semantics(const)
        out.append(_variable_record(
            name, file_path, is_new_file, const, enum_name,
            _norm_ws(_text(args)) if args is not None else None,
            weak_s, strong_s, entity_kind="enum_constant"))
    return out


def _extract_record_components(params_node, file_path: str,
                               is_new_file: bool) -> list[dict]:
    out: list[dict] = []
    for param in _param_nodes(params_node):
        pname, ptype = _param_name_type(param)
        if not pname:
            continue
        out.append(_variable_record(pname, file_path, is_new_file, param,
                                    ptype, None, entity_kind="record_component"))
    return out


# ---------------------------------------------------------------------------
# Type declaration extraction  ->  entity_type "class" (+ entity_kind)
# ---------------------------------------------------------------------------

def _bases(node) -> Optional[str]:
    """`extends` + `implements`, folded into one `superclass` string.

    `superclass` and `super_interfaces` are reachable by field name on a class,
    but an interface's `extends J, K` is an `extends_interfaces` NODE with no
    field name at all — hence the node-type lookups.
    """
    bases: list[str] = []
    sc = _first_child_of_type(node, "superclass")
    if sc is not None:
        for c in sc.named_children:
            bases.append(_norm_ws(_text(c)))
    # `permits` is deliberately NOT folded in: a permitted subclass is not a
    # supertype of this declaration.
    for holder_type in ("super_interfaces", "extends_interfaces"):
        holder = _first_child_of_type(node, holder_type)
        if holder is None:
            continue
        tl = _first_child_of_type(holder, "type_list") or holder
        for c in tl.named_children:
            bases.append(_norm_ws(_text(c)))
    return _join(bases)


def _body_of(node):
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    return _first_child_of_type(node, *_BODY_TYPES)


def _member_nodes(body_node) -> list:
    """Direct members, transparently unwrapping `enum_body_declarations`."""
    if body_node is None:
        return []
    out: list = []
    for child in body_node.named_children:
        if child.type == "enum_body_declarations":
            out.extend(child.named_children)
        else:
            out.append(child)
    return out


def _extract_type_decl(node, file_path: str, is_new_file: bool) -> tuple[dict, list[tuple[str, dict]]]:
    """Returns (class record, [(catalogue_key, member record), ...])."""
    kind = _KIND_OF_DECL[node.type]
    name = _text(node.child_by_field_name("name"))
    body_node = _body_of(node)
    partial_location, complete_location = _location(node, file_path)
    weak_s, strong_s = _semantics(node)

    tp_node = node.child_by_field_name("type_parameters") or \
        _first_child_of_type(node, "type_parameters")
    generics = _norm_ws(_text(tp_node)) if tp_node is not None else None

    public_methods: list[str] = []
    private_methods: list[str] = []
    cls_methods: list[dict] = []
    cls_variables: list[dict] = []
    members: list[tuple[str, dict]] = []

    # A record's components are its fields.
    if node.type == "record_declaration":
        for rec in _extract_record_components(
                node.child_by_field_name("parameters"), file_path, is_new_file):
            cls_variables.append(rec)
            members.append((rec["name"], rec))

    if node.type == "enum_declaration" and body_node is not None:
        for rec in _extract_enum_constants(body_node, name, file_path, is_new_file):
            cls_variables.append(rec)
            members.append((rec["name"], rec))

    for child in _member_nodes(body_node):
        if child.type in METHOD_DECLS:
            if not INCLUDE_CONSTRUCTORS and child.type in (
                    "constructor_declaration", "compact_constructor_declaration"):
                continue
            mname = _text(child.child_by_field_name("name"))
            if not mname:
                continue
            if _is_public(child, kind):
                public_methods.append(mname)
            else:
                private_methods.append(mname)
            rich = _extract_method(child, file_path, is_new_file)
            cls_methods.append(rich)
            members.append((f"{mname}#{_arity(child)}", rich))
        elif child.type == "field_declaration":
            for rec in _extract_fields(child, file_path, is_new_file):
                cls_variables.append(rec)
                members.append((rec["name"], rec))
        # static_initializer / nested type declarations are intentionally
        # skipped (see module docstring, "structural differences").

    record = {
        "name": name,
        "entity_type": "class",
        "entity_kind": kind,
        "path": file_path,
        "is_new_file": is_new_file,
        "partial_location": partial_location,
        "complete_location": complete_location,
        "weak_semantics": weak_s,
        "strong_semantics": strong_s,
        "superclass": _bases(node),
        "generics": generics,
        "public_methods": _join(public_methods),
        "private_methods": _join(private_methods),
        "cls_methods": cls_methods or None,
        "cls_variables": cls_variables or None,
    }
    return record, members


# ---------------------------------------------------------------------------
# File-level imports
# ---------------------------------------------------------------------------

def _extract_imports(root) -> list[str]:
    imports: list[str] = []
    if INCLUDE_PACKAGE_IN_IMPORTS:
        for node in root.named_children:
            if node.type == "package_declaration":
                imports.append(_norm_ws(_text(node)).rstrip(";"))
                break
    for node in root.named_children:
        if node.type == "import_declaration":
            # the node's text carries its own ';'; drop it so the "; "-join
            # reads like the Python extractor's import list
            imports.append(_norm_ws(_text(node)).rstrip(";"))
    return imports


# ---------------------------------------------------------------------------
# Catalogue key (CONTRACT 2)
# ---------------------------------------------------------------------------

def catalogue_key(info: dict, arity: Optional[int] = None) -> str:
    """`name#arity` for Java callables, bare `name` for types and fields."""
    name = info.get("name") or ""
    if info.get("entity_type") != "function":
        return name
    if arity is None:
        raw = info.get("input_names")
        arity = len([p for p in raw.split(",") if p.strip()]) if raw else 0
    return f"{name}#{arity}"


def catalogue_groups(catalogue: dict) -> dict[str, list[str]]:
    """Inverse index {bare name: [catalogue keys]} for the four read/write sets.

    Those sets are keyed on BARE names (CONTRACT 3) — a call site cannot recover
    parameter types — so a consumer holding the name "doThing" needs this to
    reach the records "doThing#1" and "doThing#3".  Emit it as a sidecar next to
    the catalogue for language != python; Python's catalogue is already keyed by
    bare name and needs no groups.
    """
    groups: dict[str, list[str]] = {}
    for key, info in catalogue.items():
        name = (info or {}).get("name") or key.split("#", 1)[0]
        groups.setdefault(name, []).append(key)
    return groups


def _put(result: dict, key: str, info: dict) -> None:
    """Insert, but never let a member clobber a type declaration's entry."""
    prev = result.get(key)
    if prev is not None and prev.get("entity_type") == "class" \
            and info.get("entity_type") != "class":
        return
    result[key] = info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_rich_entities(
    code: str,
    file_path: str,
    is_new_file: bool = False,
    *,
    include_members: bool = True,
) -> dict[str, dict]:
    """Parse Java `code` and return {catalogue_key: IdentifierInformation fields}.

    Keys: bare name for types/fields, `name#arity` for methods/constructors.
    Set include_members=False for the strict Python shape (type records only,
    with their members still present as cls_methods / cls_variables).
    """
    try:
        source = code.encode("utf-8", errors="ignore") if isinstance(code, str) else code
        tree = _parser().parse(source)
    except Exception:
        return {}

    root = tree.root_node
    imports_str = "; ".join(_extract_imports(root)) or None

    result: dict[str, dict] = {}
    for node in root.named_children:
        if node.type not in TYPE_DECLS:
            continue
        record, members = _extract_type_decl(node, file_path, is_new_file)
        if not record["name"]:
            continue
        top = dict(record)
        top["imports"] = imports_str
        _put(result, record["name"], top)
        if include_members:
            for key, member in members:
                member_top = dict(member)
                member_top["imports"] = imports_str
                _put(result, key, member_top)
    return result


def extract_entities(code: str, local_modules: Optional[set] = None):
    """CONTRACT 3 read/write scanner — lives in src/lang/java_usage.py."""
    from src.lang import java_usage  # local import: separate owner, avoids a cycle
    return java_usage.extract_entities(code, local_modules)


def parse(code):
    source = code.encode("utf-8", errors="ignore") if isinstance(code, str) else code
    return _parser().parse(source)


def path_to_module(path: str) -> str:
    """"src/main/java/com/foo/Bar.java" -> "com.foo.Bar" (Maven/Gradle layout)."""
    name = path.replace("\\", "/")
    if name.endswith(".java"):
        name = name[: -len(".java")]
    parts = [p for p in name.split("/") if p and p != "."]
    for root_marker in (("src", "main", "java"), ("src", "test", "java"),
                        ("src", "main", "kotlin"), ("src", "java"), ("src",)):
        n = len(root_marker)
        if len(parts) > n and tuple(parts[:n]) == root_marker:
            parts = parts[n:]
            break
    else:
        for i, part in enumerate(parts):
            if part == "java" and i + 1 < len(parts):
                parts = parts[i + 1:]
                break
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Adapter object (LanguageAdapter Protocol) + registration
# ---------------------------------------------------------------------------

class JavaAdapter:
    """Satisfies src/lang/base.py's LanguageAdapter Protocol."""

    name = "java"
    extensions = (".java",)

    parse = staticmethod(parse)
    catalogue_groups = staticmethod(catalogue_groups)
    extract_rich_entities = staticmethod(extract_rich_entities)
    extract_entities = staticmethod(extract_entities)
    path_to_module = staticmethod(path_to_module)
    catalogue_key = staticmethod(catalogue_key)


adapter = JavaAdapter()
registry.register(adapter)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import json
    for arg in sys.argv[1:]:
        with open(arg, "r", encoding="utf-8", errors="ignore") as fh:
            entities = extract_rich_entities(fh.read(), arg)
        print(json.dumps(entities, indent=2, default=str))
