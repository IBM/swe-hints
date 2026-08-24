#!/usr/bin/env python3
"""
Stage 1 of the interface reconstruction pipeline.

Given a gold patch applied to a local repo checkout, extract every NEW or MOVED
public symbol and return a structured list suitable for feeding into the LLM
rendering stage.

Differs from add_new_components.py in three critical ways:
  1. Grouping: a new class is ONE entry; its public methods are listed under
     public_methods, not as separate top-level entries.
  2. Filtering: private symbols (_x, __x) are dropped unless passed in a
     force-include set.
  3. Extra detection: newly registered CLI commands (@cmdutils.register,
     argparse.ArgumentParser.add_argument), new config/setting keys.

Output schema per symbol:
    {
        "type":           "Function" | "Class" | "Method" | "Command" | "Config",
        "name":           str,           # exact Python identifier or command name
        "file_path":      str,           # repo-relative file path
        "signature":      str,           # raw def/class line(s)
        "docstring":      str,           # first docstring paragraph, or ""
        "class_context":  str,           # containing class name, or ""
        "public_methods": [              # only for type=="Class"
            {"name": str, "signature": str, "docstring": str}
        ],
        "command_name":   str,           # only for type=="Command", the CLI name
    }

Standalone usage (for inspection/debugging):
    python helper_code/extract_public_symbols.py \\
        --instance_id instance_qutebrowser__... \\
        --input swebench_pro.jsonl \\
        --repos repos/
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from unidiff import PatchSet


# ---------------------------------------------------------------------------
# Git helpers  (same as add_new_components.py)
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
    patch_file = repo_dir / "_tmp_patch.diff"
    patch_file.write_text(patch_content, encoding="utf-8")
    try:
        _run(["git", "apply", "_tmp_patch.diff"], cwd=repo_dir)
    finally:
        patch_file.unlink(missing_ok=True)


def _get_default_branch(repo_dir: Path) -> str:
    """Return the default branch name (main/master) of the repo."""
    result = _run(["git", "remote", "show", "origin"], cwd=repo_dir, check=False)
    for line in result.stdout.splitlines():
        if "HEAD branch:" in line:
            return line.split()[-1]
    return "main"


def reset_repo(repo_dir: Path, commit: str):
    """Clean up after patch extraction — return to default branch (not detached HEAD)."""
    _run(["git", "reset", "--hard", "HEAD"], cwd=repo_dir, check=False)
    _run(["git", "clean", "-fdx", "--quiet"], cwd=repo_dir, check=False)
    default_branch = _get_default_branch(repo_dir)
    result = _run(["git", "checkout", "--quiet", default_branch], cwd=repo_dir, check=False)
    if result.returncode != 0:
        # Branch may not exist locally yet — create it tracking origin
        _run(["git", "checkout", "-b", default_branch, f"origin/{default_branch}"],
             cwd=repo_dir, check=False)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _remove_comments(line: str) -> str:
    return re.sub(r"#.*", "", line).rstrip()


def _is_private(name: str) -> bool:
    """True for _x and __x names but NOT for dunders like __init__."""
    leaf = name.split(".")[-1]
    # __dunder__ methods are part of the public protocol — keep them
    if leaf.startswith("__") and leaf.endswith("__"):
        return False
    return leaf.startswith("_")


def _signature(source_lines: list[str], node: ast.AST) -> str:
    """Extract the def/class header line(s) up to the colon."""
    end_def = node.body[0].lineno - 1 if node.body else node.lineno  # type: ignore[attr-defined]
    sig_lines = source_lines[node.lineno - 1: end_def]  # type: ignore[attr-defined]
    return _remove_comments(" ".join(l.strip() for l in sig_lines))


def _first_para(docstring: str) -> str:
    """Return the first non-empty paragraph of a docstring."""
    if not docstring:
        return ""
    paras = re.split(r"\n\s*\n", docstring.strip())
    return paras[0].strip().replace("\n", " ")


class _PublicSymbolVisitor(ast.NodeVisitor):
    """
    Walk a module AST and collect:
      - module-level functions (non-private)
      - module-level classes (non-private), with their public methods
      - methods that are directly inside a class (one level deep)
    """

    def __init__(self, source: str):
        self._source_lines = source.splitlines()
        self._class_stack: list[str] = []
        self.symbols: list[dict] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        is_top_level = len(self._class_stack) == 0
        if is_top_level and not _is_private(node.name):
            # Collect class + its public methods as one grouped entry
            bases = [ast.unparse(b) for b in node.bases]
            entry: dict = {
                "type": "Class",
                "name": node.name,
                "signature": _signature(self._source_lines, node),
                "docstring": _first_para(ast.get_docstring(node) or ""),
                "class_context": "",
                "bases": bases,
                "public_methods": [],
            }
            # Collect public methods at this class level only
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not _is_private(child.name):
                        entry["public_methods"].append({
                            "name": child.name,
                            "signature": _signature(self._source_lines, child),
                            "docstring": _first_para(ast.get_docstring(child) or ""),
                        })
            self.symbols.append(entry)
            # Do NOT recurse deeper (we handled methods above)
        else:
            # Nested class — skip entirely
            pass

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Only care about module-level functions (not methods inside classes)
        if len(self._class_stack) == 0 and not _is_private(node.name):
            self.symbols.append({
                "type": "Function",
                "name": node.name,
                "signature": _signature(self._source_lines, node),
                "docstring": _first_para(ast.get_docstring(node) or ""),
                "class_context": "",
                "public_methods": [],
            })

    visit_AsyncFunctionDef = visit_FunctionDef


def _parse_public_symbols(source: str) -> list[dict]:
    """Return all public top-level symbols in a Python source string."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    v = _PublicSymbolVisitor(source)
    v.visit(tree)
    return v.symbols


def _diff_public_symbols(old_source: Optional[str], new_source: str) -> list[dict]:
    """Return public symbols present in new_source but absent (by name) in old_source.

    Also detects new public methods/properties added to *existing* classes so
    that patches which only add methods (not whole new classes) are not missed.
    """
    old_syms = _parse_public_symbols(old_source or "")
    new_syms = _parse_public_symbols(new_source)

    old_top_names = {s["name"] for s in old_syms}

    # Build a map of existing class → set of method names before the patch
    old_class_methods: dict[str, set] = {
        s["name"]: {m["name"] for m in s.get("public_methods", [])}
        for s in old_syms
        if s["type"] == "Class"
    }

    results: list[dict] = []
    for sym in new_syms:
        if sym["name"] not in old_top_names:
            # Completely new top-level symbol
            results.append(sym)
        elif sym["type"] == "Class" and sym["name"] in old_class_methods:
            # Existing class — surface only genuinely new public methods
            old_meths = old_class_methods[sym["name"]]
            new_meths = [
                m for m in sym.get("public_methods", [])
                if m["name"] not in old_meths
            ]
            for m in new_meths:
                results.append({
                    "type": "Method",
                    "name": m["name"],
                    "signature": m["signature"],
                    "docstring": m["docstring"],
                    "class_context": sym["name"],
                    "file_path": sym.get("file_path", ""),
                    "public_methods": [],
                })
    return results


# ---------------------------------------------------------------------------
# Command / config detection via regex on diff hunks
# ---------------------------------------------------------------------------

# Patterns for CLI command registration (Python frameworks)
_CMD_PATTERNS = [
    # qutebrowser @cmdutils.register / @cmd.register
    re.compile(r'^\+\s*@(?:\w+\.)*register\b.*\n(?:^\+.*\n)*?^\+\s*(?:async )?def\s+(\w+)', re.MULTILINE),
    # argparse subparsers
    re.compile(r'^\+.*add_parser\s*\(\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    # click @cli.command / @app.command
    re.compile(r'^\+\s*@(?:\w+\.)command\s*\(\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
]

# Config / setting key patterns
_CFG_PATTERNS = [
    # ansible config DOCUMENTATION string keys
    re.compile(r'^\+\s+([a-z][a-z0-9_]+)\s*:\s*$', re.MULTILINE),
]


def _extract_command_names(patch_content: str) -> list[str]:
    """Find CLI command names newly registered in the patch."""
    names = []
    for pat in _CMD_PATTERNS:
        for m in pat.finditer(patch_content):
            name = m.group(1).replace("_", "-")  # Python func → CLI name convention
            if name not in names:
                names.append(name)
    return names


# ---------------------------------------------------------------------------
# Per-instance extraction (public API of this module)
# ---------------------------------------------------------------------------

def extract_public_symbols(instance: dict, repo_dir: Path) -> list[dict]:
    """
    Main entry point. Returns list of public symbol dicts for this instance.

    If nothing is found (no public surface change), returns [].
    """
    patch_content = instance.get("patch", "")
    base_commit = instance["base_commit"]

    if not patch_content.strip():
        return []

    checkout(repo_dir, base_commit)

    # Collect old source for each Python file touched by the patch
    old_sources: dict[str, Optional[str]] = {}
    try:
        patch_set = PatchSet(patch_content)
    except Exception:
        reset_repo(repo_dir, base_commit)
        return []

    for hunk in patch_set:
        fpath = hunk.path
        if not fpath.endswith(".py"):
            continue
        full = repo_dir / fpath
        old_sources[fpath] = full.read_text(encoding="utf-8", errors="replace") if full.is_file() else None

    # Apply gold patch
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
        for sym in _diff_public_symbols(old_src, new_src):
            sym["file_path"] = fpath
            symbols.append(sym)

    # Detect newly registered commands from diff text
    for cmd_name in _extract_command_names(patch_content):
        # Avoid duplicating if already captured by AST (function name match)
        existing_names = {s["name"].replace("_", "-") for s in symbols}
        if cmd_name not in existing_names:
            symbols.append({
                "type": "Command",
                "name": cmd_name,
                "signature": "",
                "docstring": "",
                "class_context": "",
                "public_methods": [],
                "command_name": cmd_name,
                "file_path": "",
            })

    reset_repo(repo_dir, base_commit)
    return symbols


# ---------------------------------------------------------------------------
# Repo path resolution (same convention as add_new_components.py)
# ---------------------------------------------------------------------------

def repo_slug_to_dir(repo: str, repos_root: Path) -> Path:
    owner, name = repo.split("/", 1)
    for candidate in [repos_root / f"{owner}__{name}", repos_root / name]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Cannot find local repo for '{repo}' under {repos_root}."
    )


# ---------------------------------------------------------------------------
# CLI for debugging
# ---------------------------------------------------------------------------

def _format_symbol(sym: dict) -> str:
    lines = [f"Type: {sym['type']}"]
    lines.append(f"Name: {sym['name']}")
    if sym.get("file_path"):
        lines.append(f"Path: {sym['file_path']}")
    if sym.get("signature"):
        lines.append(f"Signature: {sym['signature']}")
    if sym.get("docstring"):
        lines.append(f"Docstring: {sym['docstring']}")
    if sym.get("bases"):
        lines.append(f"Bases: {', '.join(sym['bases'])}")
    if sym.get("public_methods"):
        methods = ", ".join(m["name"] for m in sym["public_methods"])
        lines.append(f"Public methods: {methods}")
    return "\n  ".join(lines)


def main():
    p = argparse.ArgumentParser(description="Extract public symbols from a gold patch (debug)")
    p.add_argument("--instance_id", required=True)
    p.add_argument("--input", default="swebench_pro.jsonl")
    p.add_argument("--repos", default="repos/")
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

    repo_dir = repo_slug_to_dir(instance["repo"], Path(args.repos))
    symbols = extract_public_symbols(instance, repo_dir)

    print(f"Found {len(symbols)} public symbol(s):\n")
    for i, sym in enumerate(symbols, 1):
        print(f"[{i}] {_format_symbol(sym)}")
        print()


if __name__ == "__main__":
    main()
