#!/usr/bin/env python3
"""
FEA-Brief identity selection — faithful port of get_dataset.py (FEA-Bench),
specifically the get_file_related_info() logic, brief variant (Python only,
no non_py_patch tracking).

Algorithm mirrors get_dataset.py exactly:
  - checkout_to_commit: 'git checkout --quiet <commit>'
  - apply_patch: writes 'patch.diff' into repo_dir, runs 'git apply patch.diff',
    removes the file
  - parse_namespaces: reads a file path from disk, uses Python ast module,
    visits FunctionDef and ClassDef (NOT AsyncFunctionDef), tracks nested
    namespace names as dotted paths (e.g. 'Coder.prepare_to_edit')
  - compare_namespaces: uses two temp file paths
  - handle_new_file: all namespaces in a new file are considered new
  - Cleanup: 'git reset --hard HEAD' + 'git clean -fdx'
  - Only Python files processed; non-Python files skipped entirely
  - No doc filtering (original get_dataset.py does not filter by problem_statement)

Always computes new_components on-the-fly from the repo — all four datasets
require --repos.

FEA-Bench: pass --feabench to load microsoft/FEA-Bench directly from
HuggingFace (requires the 'datasets' package).  The dataset only contains
'repo', 'pull_number', and 'base_commit' — no 'patch'.  When 'patch' is
absent it is fetched from the public GitHub PR diff URL
(https://patch-diff.githubusercontent.com/raw/{repo}/pull/{N}.diff),
which is exactly what get_dataset.py's GitHub API approach produces.
No token required.  The repos must already be cloned under --repos in the
short-name layout (e.g. repos/feabench_repos/django/).

Output: qualified names (e.g. 'Coder.prepare_to_edit') as produced by
parse_namespaces — full dotted path preserved.

Output format (mirrors get_dataset.py's new_components field):
    {
      "new_components": {
        "path/to/file.py": [
          {"type": "function"|"class", "name": "...dotted.name...",
           "lines": [start, end], "signature": "...", "doc": "..."},
          ...
        ]
      }
    }

Supported datasets (all require --repos):
  - NoCode Bench Verified   : feature_patch + doc_changes
  - FEA-Bench (HuggingFace) : repo + pull_number  (patch fetched from GitHub)
  - SWE Bench Pro Python    : patch
  - SWE Re-Bench leaderboard: patch

Usage:
    python identity_selection/fea_brief.py \\
        --input  /path/to/NoCode-bench/ncbench_verified_no_hint.jsonl \\
        --output results/ncbench_fea_brief.jsonl \\
        --repos  /path/to/NoCode-bench/repos

    python identity_selection/fea_brief.py \\
        --feabench \\
        --output identity_selection/data_selection/feabench_fea_brief.jsonl \\
        --repos  repos/feabench_repos  # loads directly from HuggingFace

    python identity_selection/fea_brief.py \\
        --input  /path/to/SWE-bench_Pro-os/swebench_pro.jsonl \\
        --output results/swebench_pro_fea_brief.jsonl \\
        --repos  /path/to/SWE-bench_Pro-os/repos

    python identity_selection/fea_brief.py \\
        --input  data/swerebench_2026.jsonl \\
        --output results/swerebench_fea_brief.jsonl \\
        --repos  repos/swerebench_repos
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional, Tuple

from tqdm import tqdm
from unidiff import PatchSet

from utils import load_jsonl, dump_jsonl, find_repo_dir, get_impl_patch

FEABENCH_HF_REPO = "microsoft/FEA-Bench"
FEABENCH_LITE_IDS_URL = (
    "https://raw.githubusercontent.com/microsoft/FEA-Bench/main/instances_lite.json"
)


def load_feabench_from_hf() -> list:
    """Load FEA-Bench instances directly from HuggingFace (microsoft/FEA-Bench)."""
    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("The 'datasets' package is required for --feabench. "
                 "Install it with: pip install datasets")
    ds = load_dataset(FEABENCH_HF_REPO, split="test")
    return [dict(row) for row in ds]


def load_lite_ids(lite_ids_path: Optional[str]) -> set:
    """
    Return the set of Lite instance IDs.
    If lite_ids_path is given, load from that local JSON file.
    Otherwise fetch from the FEA-Bench GitHub repo.
    """
    import json
    if lite_ids_path:
        with open(lite_ids_path, encoding="utf-8") as f:
            ids = json.load(f)
    else:
        print(f"Fetching Lite IDs from {FEABENCH_LITE_IDS_URL}…")
        req = urllib.request.Request(
            FEABENCH_LITE_IDS_URL, headers={"User-Agent": "fea-brief/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            ids = json.loads(resp.read().decode("utf-8"))
    return set(ids)


# Extensions that are never considered test files (mirrors collect_utils.py)
_NON_TEST_EXTS = {".json", ".png", "csv", ".txt", ".md", ".jpg", ".jpeg",
                  ".pkl", ".yml", ".yaml", ".toml"}
_TEST_WORDS = {"test", "tests", "e2e", "testing", "check"}


def fetch_patch_from_github(repo: str, pull_number: int) -> Tuple[str, str]:
    """
    Fetch the PR diff directly from GitHub's public diff URL — the same source
    used by get_dataset.py's GitHub API approach.  No token required.

    Splits into patch / test_patch exactly as get_dataset.py's extract_patches().

    Args:
        repo:        'owner/repo' string
        pull_number: PR number

    Returns:
        (patch, test_patch) — implementation diff and test diff as strings.
    """
    url = f"https://patch-diff.githubusercontent.com/raw/{repo}/pull/{pull_number}.diff"
    headers = {"User-Agent": "fea-brief/1.0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 5  # 5, 10, 20, 40, 80 s
                print(f"\n[RATE LIMIT] 429 on {repo}#{pull_number}, retrying in {wait}s…",
                      flush=True)
                time.sleep(wait)
            else:
                raise
    else:
        raise RuntimeError(f"Failed to fetch patch for {repo}#{pull_number} after 5 retries")

    patch_fix = ""
    patch_test = ""
    for hunk in PatchSet(raw):
        path = hunk.path
        if any(w in path for w in _TEST_WORDS) and not any(path.endswith(e) for e in _NON_TEST_EXTS):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch_fix, patch_test


# ---------------------------------------------------------------------------
# Git helpers — mirrors get_dataset.py exactly
# ---------------------------------------------------------------------------

def run_command(command, cwd=None, check=True):
    """Mirror get_dataset.py's run_command()."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}:")
        print("Standard Output:", e.stdout)
        print("Standard Error:", e.stderr)
        raise


def checkout_to_commit(repo_dir, commit_sha):
    """Mirror get_dataset.py's checkout_to_commit()."""
    run_command(["git", "checkout", "--quiet", commit_sha], cwd=repo_dir)


def apply_patch(repo_dir, patch_content):
    """Mirror get_dataset.py's apply_patch(), with fallbacks for apply failures."""
    patch_file = os.path.join(repo_dir, "patch.diff")
    with open(patch_file, "w") as f:
        f.write(patch_content)
    try:
        run_command(["git", "apply", "--whitespace=fix", "patch.diff"], cwd=repo_dir)
    except subprocess.CalledProcessError:
        # Fallback: 3-way merge (tolerates context mismatches)
        run_command(["git", "apply", "--3way", "--whitespace=fix", "patch.diff"], cwd=repo_dir)
    finally:
        if os.path.exists(patch_file):
            os.remove(patch_file)


# ---------------------------------------------------------------------------
# AST namespace extraction — mirrors get_dataset.py's parse_namespaces() exactly
# Note: only FunctionDef and ClassDef visited (no AsyncFunctionDef, matching original)
# ---------------------------------------------------------------------------

def remove_comments_and_whitespace(line):
    """Mirror get_dataset.py's remove_comments_and_whitespace()."""
    cleaned_line = re.sub(r"#.*", "", line)
    return cleaned_line.rstrip()


def parse_namespaces(file_path):
    """
    Mirror get_dataset.py's parse_namespaces() exactly.
    Takes a file path (string or Path), reads from disk.
    Returns list of namespace dicts with type, name, lines, signature, doc.
    """
    with open(file_path, "r", encoding="utf-8-sig") as file:
        source = file.read()

    tree = ast.parse(source, filename=str(file_path))
    namespaces = []

    class NamespaceVisitor(ast.NodeVisitor):
        def __init__(self):
            self.current_namespace = []
            self.namespace_stack = []

        def visit_FunctionDef(self, node):
            self._handle_namespace(node, "function")

        def visit_ClassDef(self, node):
            self._handle_namespace(node, "class")

        def _handle_namespace(self, node, type_):
            start_line = node.lineno
            end_line = self._find_end_line(node)
            end_def_line = self._find_definition_end_line(node)

            lines = source.splitlines()[start_line - 1:end_def_line]
            signature = " ".join(line.strip() for line in lines)
            signature = remove_comments_and_whitespace(signature)

            namespace = {
                "type": type_,
                "name": ".".join(self.current_namespace + [node.name]),
                "lines": (start_line, end_line),
                "signature": signature,
                "doc": ast.get_docstring(node) or "",
            }
            namespaces.append(namespace)

            self.namespace_stack.append(node.name)
            self.current_namespace.append(node.name)

            self.generic_visit(node)

            self.current_namespace.pop()
            self.namespace_stack.pop()

        def _find_end_line(self, node):
            max_line = node.lineno
            for child_node in ast.walk(node):
                if hasattr(child_node, "lineno"):
                    max_line = max(max_line, child_node.lineno)
            return max_line

        def _find_definition_end_line(self, node):
            if node.body:
                first_statement_line = node.body[0].lineno
                return first_statement_line - 1
            else:
                return node.lineno

    visitor = NamespaceVisitor()
    visitor.visit(tree)

    return namespaces


def compare_namespaces(old_file_path, new_file_path):
    """Mirror get_dataset.py's compare_namespaces() exactly."""
    old_namespaces = parse_namespaces(old_file_path) if old_file_path else []
    new_namespaces = parse_namespaces(new_file_path)

    old_namespaces_dict = {ns["name"]: ns for ns in old_namespaces}
    new_namespaces_dict = {ns["name"]: ns for ns in new_namespaces}

    added_namespaces = []
    for name, ns in new_namespaces_dict.items():
        if name not in old_namespaces_dict:
            added_namespaces.append(ns)

    return added_namespaces


def handle_new_file(file_path):
    """Handle the case where the file is entirely new. Mirrors get_dataset.py."""
    return parse_namespaces(file_path)


# ---------------------------------------------------------------------------
# On-the-fly new_components computation (for datasets without pre-computed field)
# Mirrors get_dataset.py's get_file_related_info(), brief variant (Python only)
# ---------------------------------------------------------------------------

def compute_new_components(repo_dir: str, patch_content: str,
                           base_commit_sha: str) -> Dict[str, list]:
    """
    Checkout repo at base_commit_sha, apply patch_content, AST-diff Python files.
    Returns new_components dict: {file_path: [namespace_dict, ...]}.
    Non-Python files are skipped (brief variant).
    Mirrors get_dataset.py's get_file_related_info() logic exactly.
    """
    testbed_dir = Path(repo_dir)

    # Always start clean — guards against dirty state from a previous failed run
    run_command(["git", "reset", "--hard", "HEAD"], cwd=repo_dir)
    run_command(["git", "clean", "-fdx"], cwd=repo_dir)

    checkout_to_commit(repo_dir, base_commit_sha)

    # Save original file contents before applying patch (Python files only)
    files = {}
    for hunk in PatchSet(patch_content):
        file_path = hunk.path
        if not file_path.endswith(".py"):
            continue
        full_file_path = testbed_dir / file_path
        if os.path.exists(full_file_path):
            files[file_path] = full_file_path.read_text(encoding="utf-8-sig")
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
                    old_file_path = Path(temp_dir) / "old.py"
                    new_file_path = Path(temp_dir) / "new.py"

                    old_file_path.write_text(original_content, encoding="utf-8")
                    new_file_path.write_text(new_full_file_path.read_text(encoding="utf-8-sig"))

                    added_namespaces = compare_namespaces(str(old_file_path), str(new_file_path))
            else:
                continue

            if added_namespaces:
                new_components[file_path].extend(added_namespaces)
    finally:
        # Always cleanup — mirrors get_dataset.py lines 315-316
        run_command(["git", "reset", "--hard", "HEAD"], cwd=repo_dir)
        run_command(["git", "clean", "-fdx"], cwd=repo_dir)

    return dict(new_components)


# ---------------------------------------------------------------------------
# Core per-instance logic
# ---------------------------------------------------------------------------

def process_instance(example: dict, repos_root: Path) -> dict:
    repo        = example.get("repo", "")
    base_commit = example["base_commit"]
    repo_dir    = str(find_repo_dir(repo, repos_root))

    # FEA-Bench HuggingFace rows have no 'patch' — fetch from GitHub PR diff URL.
    if not example.get("patch") and not example.get("feature_patch"):
        pull_number = example["pull_number"]
        patch, _test_patch = fetch_patch_from_github(repo, pull_number)
        example = {**example, "patch": patch, "test_patch": _test_patch}

    impl_patch  = get_impl_patch(example)

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
        description="FEA-Brief identity selection — AST-diff new function/class hints."
    )
    ap.add_argument("--input",  "-i", type=Path, default=None,
                    help="Input JSONL. NoCode Bench: ncbench_verified_no_hint.jsonl; "
                         "SWE Pro / SWE Re-Bench: the raw dataset JSONL. "
                         "Omit when using --feabench.")
    ap.add_argument("--feabench", action="store_true",
                    help="Load FEA-Bench directly from HuggingFace "
                         f"({FEABENCH_HF_REPO}) instead of a local JSONL.")
    ap.add_argument("--lite", action="store_true",
                    help="Only process the Lite subset of FEA-Bench (186 instances). "
                         "Fetches the Lite ID list from GitHub unless --lite-ids is given.")
    ap.add_argument("--lite-ids", type=str, default=None,
                    help="Path to a local instances_lite.json (list of instance IDs). "
                         "Only used with --lite. Defaults to fetching from GitHub.")
    ap.add_argument("--output", "-o", type=Path, required=True,
                    help="Output JSONL with augmentations field added.")
    ap.add_argument("--repos",  "-r", type=Path, required=True,
                    help="Directory containing cloned repos.")
    ap.add_argument("--skip-errors", action="store_true",
                    help="Skip failed instances instead of crashing.")
    ap.add_argument("--instance-id", type=str, default=None,
                    help="Process a single instance_id (for debugging).")
    args = ap.parse_args()

    if not args.feabench and args.input is None:
        ap.error("--input is required unless --feabench is specified.")
    if args.feabench and args.input is not None:
        ap.error("--input and --feabench are mutually exclusive.")
    if args.lite and not args.feabench:
        ap.error("--lite only applies when using --feabench.")
    if not args.repos.is_dir():
        sys.exit(f"Repos directory not found: {args.repos}")

    if args.feabench:
        print(f"Loading FEA-Bench from HuggingFace ({FEABENCH_HF_REPO})…")
        examples = load_feabench_from_hf()
    else:
        if not args.input.exists():
            sys.exit(f"Input not found: {args.input}")
        examples = load_jsonl(args.input)

    if args.lite:
        lite_ids = load_lite_ids(args.lite_ids)
        before = len(examples)
        examples = [e for e in examples if e.get("instance_id") in lite_ids]
        print(f"Filtered to Lite subset: {len(examples)}/{before} instances.")

    if args.instance_id:
        examples = [e for e in examples if e.get("instance_id") == args.instance_id]
        if not examples:
            sys.exit(f"No instance with id={args.instance_id!r}")

    output_rows = []
    errors = []

    for ex in tqdm(examples, desc="FEA-Brief"):
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
