#!/usr/bin/env python3
"""
Stage 2 of the interface reconstruction pipeline.

Parse the test_patch diff to extract exact contracts that the new tests assert:
  - Imported module paths + symbol names (highest confidence — explicit by name+path)
  - Direct calls / instantiations of new symbols (confirms test-visibility)
  - String literals used as command names or config keys in assertions

These contracts pin the two most failure-prone interface fields:
  * exact Python identifier  (prevents name hallucination)
  * canonical module path    (prevents import-path hallucination)

Output schema:
    {
        "imports": [                    # explicit import statements added by test
            {
                "module": str,          # e.g. "ansible.executor.play_iterator"
                "names":  [str],        # e.g. ["IteratingStates", "FailedStates"]
            }
        ],
        "called_names":  [str],         # identifiers directly called/instantiated
        "string_literals": [str],       # short string literals in assertions (routes, cmd names)
    }

Standalone usage:
    python helper_code/extract_test_contracts.py \\
        --instance_id instance_ansible__... \\
        --input swebench_pro.jsonl
"""

import argparse
import json
import re
import sys


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

# Added lines only (strip the leading '+', skip '+++' header lines)
def _added_lines(patch: str) -> list[str]:
    return [
        line[1:]  # strip leading '+'
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


# -- Import extraction -------------------------------------------------------

# Matches:  from some.module.path import Name1, Name2, Name3
_FROM_IMPORT_RE = re.compile(
    r"^from\s+([\w./]+)\s+import\s+(.+)$"
)
# Matches:  import some.module
_IMPORT_RE = re.compile(r"^import\s+([\w.]+)")


def _parse_imports(added: list[str]) -> list[dict]:
    """Return list of {module, names} from new import statements."""
    imports = []
    for line in added:
        line = line.strip()
        m = _FROM_IMPORT_RE.match(line)
        if m:
            module = m.group(1).replace("/", ".")  # handle relative path style
            names_raw = m.group(2)
            # Handle multi-line imports wrapped in parens — names may have trailing comma
            names = [
                n.strip().rstrip(",").strip("()")
                for n in re.split(r"[,\s]+", names_raw)
                if n.strip() and n.strip() not in ("(", ")", "\\", "as")
                and not n.strip().startswith("#")
                # skip 'as alias' tokens
                and not re.match(r"^[a-z]", n.strip())  # keep only PascalCase + UPPER + _prefixed
                or (n.strip() and re.match(r"^[A-Za-z_]", n.strip()))
            ]
            names = [n for n in names if re.match(r"^[A-Za-z_]\w*$", n)]
            if names:
                imports.append({"module": module, "names": names})
            continue

        m2 = _IMPORT_RE.match(line)
        if m2:
            imports.append({"module": m2.group(1), "names": []})

    return imports


# -- Called names extraction -------------------------------------------------

# Identifiers followed by '(' or '[' on added lines — likely calls/instantiations
_CALL_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*|[a-z_][a-z0-9_]*)\s*\(")
# Direct attribute access of imported modules: urlutils.widened_hostnames(
_ATTR_CALL_RE = re.compile(r"\b\w+\.([A-Za-z_]\w*)\s*\(")


def _parse_called_names(added: list[str]) -> list[str]:
    """Return unique names that are directly called/instantiated in new test lines."""
    seen: set[str] = set()
    names: list[str] = []

    # Skip test infrastructure names that are never interface entities
    _SKIP = {
        "assert", "print", "len", "list", "dict", "set", "str", "int", "float",
        "bool", "tuple", "range", "enumerate", "zip", "map", "filter",
        "isinstance", "hasattr", "getattr", "setattr", "open", "type",
        "pytest", "mock", "patch", "MagicMock", "Mock", "fixture",
        "parametrize", "raises", "approx", "caplog", "monkeypatch",
        "tmpdir", "tmp_path", "capsys", "capfd",
        # Python keywords that can appear before '(' in test code
        "while", "for", "if", "with", "return", "yield", "lambda", "not",
        "and", "or", "in", "is", "else", "elif", "try", "except",
    }

    for line in added:
        line = line.strip()
        if line.startswith(("#", "def ", "class ", "@")):
            continue
        for pat in (_CALL_RE, _ATTR_CALL_RE):
            for m in pat.finditer(line):
                name = m.group(1)
                if name not in _SKIP and name not in seen and len(name) > 2:
                    seen.add(name)
                    names.append(name)
    return names


# -- String literal extraction -----------------------------------------------

# Short string literals in assert lines — likely HTTP paths, command names, config keys
_ASSERT_STRING_RE = re.compile(r'assert\s+.*?["\']([^"\']{2,40})["\']')
_ROUTE_RE = re.compile(r'["\']/([\w/\-{}]+)["\']')


def _parse_string_contracts(added: list[str]) -> list[str]:
    """Return short string literals from assertion lines (routes, command names, keys)."""
    seen: set[str] = set()
    results: list[str] = []
    for line in added:
        for m in _ASSERT_STRING_RE.finditer(line):
            val = m.group(1)
            if val not in seen:
                seen.add(val)
                results.append(val)
        for m in _ROUTE_RE.finditer(line):
            val = "/" + m.group(1)
            if val not in seen:
                seen.add(val)
                results.append(val)
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_test_contracts(test_patch: str) -> dict:
    """
    Parse a test_patch diff and return all test-enforced contracts.

    Args:
        test_patch: raw unified diff string from the dataset's test_patch field

    Returns:
        {
            "imports":         [{module, names}],
            "called_names":    [str],
            "string_literals": [str],
        }
    """
    if not test_patch or not test_patch.strip():
        return {"imports": [], "called_names": [], "string_literals": []}

    added = _added_lines(test_patch)
    return {
        "imports":         _parse_imports(added),
        "called_names":    _parse_called_names(added),
        "string_literals": _parse_string_contracts(added),
    }


def format_contracts(contracts: dict) -> str:
    """
    Render test contracts as a human-readable block for the LLM prompt.

    Returns "" if no contracts were found.
    """
    parts = []

    if contracts.get("imports"):
        lines = ["Explicit imports added by tests:"]
        for imp in contracts["imports"]:
            if imp["names"]:
                lines.append(f"  from {imp['module']} import {', '.join(imp['names'])}")
            else:
                lines.append(f"  import {imp['module']}")
        parts.append("\n".join(lines))

    if contracts.get("called_names"):
        parts.append("Names directly called/instantiated in tests:\n  " +
                     ", ".join(contracts["called_names"]))

    if contracts.get("string_literals"):
        parts.append("String contracts (routes / command names / keys):\n  " +
                     ", ".join(f'"{s}"' for s in contracts["string_literals"]))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI for debugging
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Extract test contracts from test_patch (debug)")
    p.add_argument("--instance_id", required=True)
    p.add_argument("--input", default="swebench_pro.jsonl")
    args = p.parse_args()

    instance = None
    with open(args.input) as f:
        for line in f:
            row = json.loads(line)
            if row["instance_id"] == args.instance_id:
                instance = row
                break
    if not instance:
        sys.exit(f"Instance not found: {args.instance_id}")

    test_patch = instance.get("test_patch", "")
    contracts = extract_test_contracts(test_patch)

    print("=== Test Contracts ===\n")
    formatted = format_contracts(contracts)
    if formatted:
        print(formatted)
    else:
        print("(no contracts extracted)")
    print()
    print("=== Raw ===")
    print(json.dumps(contracts, indent=2))


if __name__ == "__main__":
    main()
