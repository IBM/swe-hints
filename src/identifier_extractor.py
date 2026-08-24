"""
Identifier Extractor

Extracts rich IdentifierInformation fields from Python source using tree-sitter.
Called by identifier_usage.py during step 1 when the repo is checked out.

For each newly-introduced module-level function or class, extracts:
  - signature, input_names, input_types, input_spec, param_defaults
  - output_partial_type, output_complete_type
  - superclass, generics, public_methods, private_methods, class_variables
  - partial_location (start line), complete_location (start:end)
  - weak_semantics (first docstring line), strong_semantics (full docstring)
  - exception_types, exception_values
  - local_variables
  - imports (file-level)
  - path, is_new_file

For each newly-introduced module-level variable (assignment / annotated_assignment):
  - var_type (annotation if present), var_value (RHS text)
  - partial_location, complete_location
  - weak_semantics, strong_semantics (placeholders — to be filled by LLM)
  - imports (file-level)
  - path, is_new_file
"""

from __future__ import annotations

from typing import Optional

from tree_sitter_languages import get_parser

_ts_parser = get_parser("python")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(node) -> str:
    return node.text.decode("utf-8", errors="ignore").strip()


def _first_child_of_type(node, *types):
    for child in node.named_children:
        if child.type in types:
            return child
    return None


def _children_of_type(node, *types):
    return [c for c in node.named_children if c.type in types]


def _docstring(body_node) -> Optional[str]:
    """Extract docstring from a function/class body node."""
    if body_node is None:
        return None
    for child in body_node.named_children:
        if child.type == "expression_statement":
            for sub in child.named_children:
                if sub.type == "string":
                    raw = _text(sub)
                    # Strip quotes
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q) and len(raw) > 2 * len(q):
                            return raw[len(q):-len(q)].strip()
                    return raw.strip('"\'').strip()
        break  # docstring must be the first statement
    return None


def _weak_semantics(docstring: Optional[str]) -> Optional[str]:
    """First non-empty line of docstring."""
    if not docstring:
        return None
    for line in docstring.splitlines():
        line = line.strip()
        if line:
            return line
    return None


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------

def _extract_function(node, file_path: str, is_new_file: bool) -> dict:
    """Extract all IdentifierInformation fields from a function_definition node."""
    name = _text(node.child_by_field_name("name"))
    params_node = node.child_by_field_name("parameters")
    ret_node = node.child_by_field_name("return_type")  # after ->
    body_node = node.child_by_field_name("body")

    # --- Location ---
    start_line = node.start_point[0] + 1  # 1-based
    end_line   = node.end_point[0] + 1
    partial_location  = f"{file_path}:{start_line}"
    complete_location = f"{file_path}:{start_line}-{end_line}"

    # --- Docstring / semantics ---
    docstring = _docstring(body_node)
    weak_s  = _weak_semantics(docstring)
    strong_s = docstring if docstring and len(docstring.splitlines()) > 1 else None

    # --- Signature ---
    signature = None
    input_names: list[str] = []
    input_types: list[str] = []
    param_defaults: list[str] = []

    if params_node:
        sig_parts: list[str] = []
        for param in params_node.named_children:
            ptype = param.type
            if ptype == "identifier":
                pname = _text(param)
                sig_parts.append(pname)
                input_names.append(pname)
            elif ptype == "typed_parameter":
                pname_node = param.child_by_field_name("name") or _first_child_of_type(param, "identifier")
                ptype_node = param.child_by_field_name("type")
                pname = _text(pname_node) if pname_node else ""
                ptype_str = _text(ptype_node) if ptype_node else ""
                sig_parts.append(f"{pname}: {ptype_str}" if ptype_str else pname)
                if pname:
                    input_names.append(pname)
                if ptype_str:
                    input_types.append(f"{pname}: {ptype_str}")
            elif ptype == "default_parameter":
                pname_node = param.child_by_field_name("name")
                pval_node  = param.child_by_field_name("value")
                pname = _text(pname_node) if pname_node else ""
                pval  = _text(pval_node)  if pval_node  else ""
                sig_parts.append(f"{pname}={pval}")
                if pname:
                    input_names.append(pname)
                if pval:
                    param_defaults.append(f"{pname}={pval}")
            elif ptype == "typed_default_parameter":
                pname_node = param.child_by_field_name("name")
                ptype_node = param.child_by_field_name("type")
                pval_node  = param.child_by_field_name("value")
                pname = _text(pname_node) if pname_node else ""
                ptype_str = _text(ptype_node) if ptype_node else ""
                pval  = _text(pval_node)  if pval_node  else ""
                part = pname
                if ptype_str: part += f": {ptype_str}"
                if pval:      part += f" = {pval}"
                sig_parts.append(part)
                if pname:
                    input_names.append(pname)
                if ptype_str:
                    input_types.append(f"{pname}: {ptype_str}")
                if pval:
                    param_defaults.append(f"{pname}={pval}")
            elif ptype in ("list_splat_pattern", "dictionary_splat_pattern"):
                inner = _first_child_of_type(param, "identifier")
                prefix = "*" if ptype == "list_splat_pattern" else "**"
                pname = (prefix + _text(inner)) if inner else _text(param)
                sig_parts.append(pname)
                input_names.append(pname)
            else:
                sig_parts.append(_text(param))

        ret_str = _text(ret_node) if ret_node else ""
        param_str = ", ".join(sig_parts)
        signature = f"{name}({param_str})" + (f" -> {ret_str}" if ret_str else "")

    # Input spec: "name: type, name2: type2" or just names
    if input_types:
        input_spec = ", ".join(input_types)
    elif input_names:
        input_spec = ", ".join(n for n in input_names if n not in ("self", "cls"))
    else:
        input_spec = None

    # Output types
    output_partial_type = output_complete_type = None
    if ret_node:
        ret_str = _text(ret_node)
        output_partial_type = ret_str.split("[")[0].strip()  # e.g. "list" from "list[str]"
        output_complete_type = ret_str

    # --- Exception types/values ---
    exception_types: list[str] = []
    exception_values: list[str] = []

    def _scan_raises(n):
        if n.type == "raise_statement":
            for child in n.named_children:
                if child.type == "call":
                    func = child.child_by_field_name("function")
                    if func:
                        exception_types.append(_text(func))
                    args = child.child_by_field_name("arguments")
                    if args:
                        for arg in args.named_children:
                            if arg.type in ("string", "concatenated_string"):
                                val = _text(arg).strip('"\'')
                                if val:
                                    exception_values.append(val)
                elif child.type == "identifier":
                    exception_types.append(_text(child))
        for c in n.named_children:
            _scan_raises(c)

    if body_node:
        _scan_raises(body_node)

    # --- Local variables (assignments in function body, excl. self.x) ---
    local_variables: list[str] = []

    def _scan_locals(n, depth=0):
        if depth > 0 and n.type in ("function_definition", "class_definition"):
            return  # don't descend into nested defs
        if n.type == "assignment":
            left = n.child_by_field_name("left")
            if left and left.type == "identifier":
                lname = _text(left)
                if lname not in ("self", "cls") and lname not in local_variables:
                    local_variables.append(lname)
        for c in n.named_children:
            _scan_locals(c, depth + 1)

    if body_node:
        _scan_locals(body_node)

    return {
        "name": name,
        "entity_type": "function",
        "path": file_path,
        "is_new_file": is_new_file,
        "partial_location": partial_location,
        "complete_location": complete_location,
        "weak_semantics": weak_s,
        "strong_semantics": strong_s,
        "signature": signature,
        "input_spec": input_spec or None,
        "input_names": ", ".join(n for n in input_names if n not in ("self", "cls")) or None,
        "input_types": ", ".join(input_types) or None,
        "output_partial_type": output_partial_type,
        "output_complete_type": output_complete_type,
        "local_variables": ", ".join(local_variables) or None,
        "exception_types": ", ".join(dict.fromkeys(exception_types)) or None,
        "exception_values": ", ".join(dict.fromkeys(exception_values)) or None,
        "param_defaults": ", ".join(param_defaults) or None,
    }


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

def _extract_class(node, file_path: str, is_new_file: bool) -> dict:
    """Extract all IdentifierInformation fields from a class_definition node."""
    name = _text(node.child_by_field_name("name"))
    body_node = node.child_by_field_name("body")

    # --- Location ---
    start_line = node.start_point[0] + 1
    end_line   = node.end_point[0] + 1
    partial_location  = f"{file_path}:{start_line}"
    complete_location = f"{file_path}:{start_line}-{end_line}"

    # --- Docstring ---
    docstring = _docstring(body_node)
    weak_s  = _weak_semantics(docstring)
    strong_s = docstring if docstring and len(docstring.splitlines()) > 1 else None

    # --- Superclass / generics ---
    superclasses: list[str] = []
    generics_list: list[str] = []

    # argument_list in class def holds bases
    arg_node = _first_child_of_type(node, "argument_list")
    if arg_node:
        for base in arg_node.named_children:
            if base.type == "identifier":
                superclasses.append(_text(base))
            elif base.type == "subscript":
                # Generic[T] or Protocol[T]
                generics_list.append(_text(base))
            else:
                superclasses.append(_text(base))

    # type_parameter node (PEP 695 syntax)
    type_params = _first_child_of_type(node, "type_parameter")
    if type_params:
        generics_list.append(_text(type_params))

    # --- Methods (rich sub-records) and class variables (rich sub-records) ---
    public_methods: list[str] = []    # kept as name-only lists for FuncPub/FuncPriv nodes
    private_methods: list[str] = []
    cls_methods: list[dict] = []      # rich per-method dicts for ClsFunc nodes
    cls_variables: list[dict] = []    # rich per-variable dicts for ClsVar nodes

    if body_node:
        for child in body_node.named_children:
            if child.type in ("function_definition", "decorated_definition"):
                func_node = child if child.type == "function_definition" else \
                            _first_child_of_type(child, "function_definition")
                if func_node:
                    mname_node = func_node.child_by_field_name("name")
                    if mname_node:
                        mname = _text(mname_node)
                        if mname.startswith("__") and mname.endswith("__"):
                            pass  # skip dunder in both lists
                        elif mname.startswith("_"):
                            private_methods.append(mname)
                        else:
                            public_methods.append(mname)
                    # Always extract rich info for all non-dunder methods
                    if mname_node:
                        mname = _text(mname_node)
                        if not (mname.startswith("__") and mname.endswith("__")):
                            rich = _extract_function(func_node, file_path, is_new_file)
                            cls_methods.append(rich)
            elif child.type in ("assignment", "annotated_assignment",
                                "expression_statement"):
                # Unwrap expression_statement if needed
                target = child
                if child.type == "expression_statement":
                    inner = _first_child_of_type(
                        child, "assignment", "annotated_assignment"
                    )
                    if inner:
                        target = inner
                    else:
                        continue
                rich_var = _extract_variable(target, file_path, is_new_file)
                if rich_var is not None:
                    cls_variables.append(rich_var)

    return {
        "name": name,
        "entity_type": "class",
        "path": file_path,
        "is_new_file": is_new_file,
        "partial_location": partial_location,
        "complete_location": complete_location,
        "weak_semantics": weak_s,
        "strong_semantics": strong_s,
        "superclass": ", ".join(superclasses) or None,
        "generics": ", ".join(generics_list) or None,
        "public_methods":  ", ".join(public_methods)  or None,
        "private_methods": ", ".join(private_methods) or None,
        "cls_methods":   cls_methods   or None,
        "cls_variables": cls_variables or None,
    }


# ---------------------------------------------------------------------------
# Variable extraction
# ---------------------------------------------------------------------------

def _extract_variable(node, file_path: str, is_new_file: bool) -> Optional[dict]:
    """
    Extract IdentifierInformation fields from a module-level assignment or
    annotated_assignment node.

    Returns None if the LHS is not a simple identifier (e.g. tuple unpacking,
    attribute assignment) since those don't map to a single catalogue entry.
    """
    if node.type == "assignment":
        left  = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or left.type != "identifier":
            return None
        name      = _text(left)
        var_type  = None
        var_value = _text(right) if right else None

    elif node.type == "annotated_assignment":
        # LHS is always the first named child for annotated_assignment
        left       = _first_child_of_type(node, "identifier")
        type_node  = node.child_by_field_name("type")
        value_node = node.child_by_field_name("value")
        if left is None:
            return None
        name      = _text(left)
        var_type  = _text(type_node)  if type_node  else None
        var_value = _text(value_node) if value_node else None

    else:
        return None

    start_line        = node.start_point[0] + 1
    end_line          = node.end_point[0]   + 1
    partial_location  = f"{file_path}:{start_line}"
    complete_location = f"{file_path}:{start_line}-{end_line}"

    return {
        "name":               name,
        "entity_type":        "variable",
        "path":               file_path,
        "is_new_file":        is_new_file,
        "partial_location":   partial_location,
        "complete_location":  complete_location,
        "var_type":           var_type,
        "var_value":          var_value,
        # Placeholders — weak/strong semantics to be generated by LLM
        "weak_semantics":     None,
        "strong_semantics":   None,
    }


# ---------------------------------------------------------------------------
# File-level imports
# ---------------------------------------------------------------------------

def _extract_imports(tree_root) -> list[str]:
    imports: list[str] = []
    for node in tree_root.named_children:
        if node.type in ("import_statement", "import_from_statement"):
            imports.append(_text(node))
    return imports


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_rich_entities(
    code: str,
    file_path: str,
    is_new_file: bool = False,
) -> dict[str, dict]:
    """
    Parse `code` and return a dict mapping identifier name -> raw field dict
    for every module-level function and class defined in it.

    The returned dicts are ready to be passed to
    IdentifierInformation.model_validate().
    """
    try:
        tree = _ts_parser.parse(code.encode("utf-8", errors="ignore"))
    except Exception:
        return {}

    root = tree.root_node
    imports = _extract_imports(root)
    imports_str = "; ".join(imports) if imports else None

    result: dict[str, dict] = {}

    def _process_nodes(nodes) -> None:
        for node in nodes:
            # Unwrap expression_statement — module-level assignments are wrapped in it
            target = node
            if node.type == "expression_statement":
                inner = _first_child_of_type(node, "assignment", "annotated_assignment")
                if inner:
                    target = inner
                else:
                    continue

            # Handle decorators wrapping a def/class
            if target.type == "decorated_definition":
                inner = _first_child_of_type(node, "function_definition", "class_definition")
                if inner:
                    target = inner
                else:
                    continue

            if target.type == "function_definition":
                info = _extract_function(target, file_path, is_new_file)
                info["imports"] = imports_str
                result[info["name"]] = info

            elif target.type == "class_definition":
                info = _extract_class(target, file_path, is_new_file)
                info["imports"] = imports_str
                result[info["name"]] = info

            elif target.type in ("assignment", "annotated_assignment"):
                info = _extract_variable(target, file_path, is_new_file)
                if info is not None:
                    info["imports"] = imports_str
                    result[info["name"]] = info

            elif target.type in (
                "try_statement", "if_statement", "with_statement",
                "block", "except_clause", "else_clause", "elif_clause",
                "finally_clause",
            ):
                # Recurse into blocks that commonly wrap module-level assignments,
                # e.g. try/except for optional imports, if TYPE_CHECKING blocks.
                _process_nodes(target.named_children)

    _process_nodes(root.named_children)
    return result


# Made with Bob
