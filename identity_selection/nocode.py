#!/usr/bin/env python3
"""
NoCode identity selection — faithful port of augment.py (NoCode-bench).

Algorithm mirrors augment.py exactly:
  - run_cmd uses shell=True, returns None on error (does not raise)
  - Git reset sequence: clean → reset --hard HEAD → checkout <commit>
  - Patch written to PATCH_FILE (absolute path next to this script),
    applied with 'git apply' (no --check)
  - Identifiers extracted flat: type is 'function', 'class', or 'field';
    error message strings extracted from raise / pytest.raises as 'error_msg'
  - New entities = those in after but not in before (type+name pair match)
  - Feature entities filtered by name intersection with test entities
  - New .py files from feature_patch added after filtering, encoded as
    SEPARATOR.join([path, 'file', path])
  - doc_content built from doc_changes[*]['metadata'] for NoCode Bench;
    falls back to problem_statement for other datasets (FEA-Bench, SWE Pro, SWE Re-Bench)
  - No repo cleanup after processing

Bug in original augment.py (construction/augmentation/augment.py):
  PATCH_FILE = './test.patch' is a relative path. When git apply runs with
  cwd=repo_dir, it resolves './test.patch' relative to the repo directory,
  not the directory augment.py was launched from. If those differ, git apply
  fails silently (rc=128, no exception), test_entities stays empty, and the
  test-name intersection filter drops all non-file entities. This explains
  why 4 scikit-learn instances in the HF dataset have empty augmentation data
  despite having valid new entities in both feature and test patches.
  Fix applied here: PATCH_FILE uses an absolute path via Path(__file__).parent.

Supported datasets (auto-detected from fields):
  - NoCode Bench Verified   : feature_patch + test_patch + doc_changes
  - FEA-Bench medium JSONL  : patch + test_patch
  - SWE Bench Pro Python    : patch + test_patch + problem_statement
  - SWE Re-Bench leaderboard: patch + test_patch + problem_statement

Note: For FEA-Bench, use FEA-Bench-v1.0-medium.jsonl (from get_dataset.py).
The raw HuggingFace dataset does not contain patch fields.

Usage (run from repo root):

    # NoCode Bench Verified
    source .venv/bin/activate
    python identity_selection/nocode.py \\
        --input  /path/to/NoCode-bench/ncbench_verified_no_hint.jsonl \\
        --output identity_selection/data_selection/ncbench_nocode.jsonl \\
        --repos  /path/to/NoCode-bench/repos

    # FEA-Bench
    python identity_selection/nocode.py \\
        --input  /path/to/FEA-Bench/feabench-data/FEA-Bench-v1.0-medium.jsonl \\
        --output identity_selection/data_selection/feabench_nocode.jsonl \\
        --repos  /path/to/FEA-Bench/feabench-data/testbed

    # SWE-bench Pro
    python identity_selection/nocode.py \\
        --input  /path/to/SWE-bench_Pro-os/swebench_pro.jsonl \\
        --output identity_selection/data_selection/swebench_pro_nocode.jsonl \\
        --repos  /path/to/SWE-bench_Pro-os/repos

    # SWE Re-Bench
    python identity_selection/nocode.py \\
        --input  data/swerebench_2026.jsonl \\
        --output identity_selection/data_selection/swerebench_nocode.jsonl \\
        --repos  repos/swerebench_repos

    # Single instance (for debugging)
    python identity_selection/nocode.py \\
        --input  /path/to/NoCode-bench/ncbench_verified_no_hint.jsonl \\
        --output /tmp/test_nocode.jsonl \\
        --repos  /path/to/NoCode-bench/repos \\
        --instance-id psf__requests-5856
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from tqdm import tqdm
from tree_sitter_languages import get_parser
from unidiff import PatchSet

from utils import load_jsonl, dump_jsonl, find_repo_dir, get_impl_patch, get_test_patch, get_doc_content

ts_parser = get_parser("python")

SEPARATOR = "\u2E80"
PATCH_FILE = str(Path(__file__).parent / "nocode_identity.patch")

AUGMENTATION_HEADER = (
    "If completing this task requires creating new files, classes, fields, "
    "or error messages, you may consider using the following suggested entity names:"
)


# ---------------------------------------------------------------------------
# Git helpers — mirrors augment.py's run_cmd (shell=True, returns None on error)
# ---------------------------------------------------------------------------

def run_cmd(command: str, cwd: Optional[str] = None) -> Optional[str]:
    """Run a shell command. Returns stdout string, or None on any error."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=cwd,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


# ---------------------------------------------------------------------------
# AST: flat identifier extraction — mirrors augment.py's get_all_identifers()
# ---------------------------------------------------------------------------

def _get_raise_string(node) -> Optional[str]:
    """Mirror augment.py's _get_raise_string() exactly."""
    if node.type not in ["raise_statement", "with_clause"]:
        return None

    string_node = None
    node_arrs = ["raise_statement", "call", "argument_list", "string", "string_content"]

    def traverse(node, pos):
        nonlocal string_node
        if pos <= 2 and node.type != node_arrs[pos]:
            return
        if node.type == node_arrs[-1]:
            string_node = node
            return
        for child in node.named_children:
            pos += 1
            traverse(child, pos)
            pos -= 1

    if node.type == "raise_statement":
        traverse(node, 0)
    elif "pytest.raises" in node.text.decode():
        call_nodes = []

        def get_call_nodes(root):
            for child in root.named_children:
                if child.type == "call":
                    call_nodes.append(child)
                else:
                    get_call_nodes(child)

        get_call_nodes(node)
        if call_nodes:
            traverse(call_nodes[0], 1)

    if string_node is not None:
        return string_node.text.decode()
    return None


def get_all_identifiers(root) -> List[dict]:
    """
    Mirror augment.py's get_all_identifers() exactly.
    Types: 'function', 'class', 'field', 'error_msg'.
    Note: original checks node.parent.type without None guard — preserved.
    """
    res = []

    def traverse(node):
        if node.type == "identifier":
            id_type = "field"
            if node.parent.type in ["function_definition", "class_definition"]:
                id_type = {
                    "function_definition": "function",
                    "class_definition": "class",
                }[node.parent.type]
            res.append({
                "name": node.text.decode(),
                "type": id_type,
            })

        if node.type in ["raise_statement", "with_clause"]:
            raise_str = _get_raise_string(node)
            if raise_str is not None:
                res.append({"name": raise_str, "type": "error_msg"})

        for child in node.named_children:
            traverse(child)

    traverse(root)
    return res


def parse_identifiers(code: str) -> List[dict]:
    root = ts_parser.parse(code.encode()).root_node
    return get_all_identifiers(root)


# ---------------------------------------------------------------------------
# Diff entity extraction — mirrors augment.py's get_diff_entities()
# ---------------------------------------------------------------------------

def get_diff_entities(impl_patch: str, test_patch: str,
                      base_commit: str, repo_dir: str,
                      patch_type: str = "feature") -> set:
    """
    Mirror augment.py's get_diff_entities() — uses shell=True run_cmd,
    3-step git reset, writes patch to PATCH_FILE in CWD.
    """
    def read_code(file_path):
        if not os.path.exists(file_path):
            return ""
        with open(file_path, "r") as f:
            return f.read()

    # Mirror augment.py reset sequence exactly
    run_cmd("git clean -fdx", repo_dir)
    run_cmd("git reset --hard HEAD", repo_dir)
    run_cmd(f"git checkout {base_commit}", repo_dir)

    patch_content = impl_patch if patch_type == "feature" else test_patch
    patch_set = PatchSet(patch_content)
    patched_files = [i for i in patch_set if i.path.endswith(".py")]

    diff_ids = {}
    for patched_file in patched_files:
        fpath = patched_file.path
        before_code = read_code(os.path.join(repo_dir, fpath))
        root = ts_parser.parse(before_code.encode()).root_node
        before_ids = get_all_identifiers(root)
        diff_ids[fpath] = {"before": before_ids}

    # Write patch to PATCH_FILE (CWD), apply with git apply (no --check)
    with open(PATCH_FILE, "w") as f:
        f.write(patch_content)
    run_cmd(f"git apply {PATCH_FILE}", repo_dir)

    for patched_file in patched_files:
        fpath = patched_file.path
        after_code = read_code(os.path.join(repo_dir, fpath))
        root = ts_parser.parse(after_code.encode()).root_node
        after_ids = get_all_identifiers(root)
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

def get_new_entities(example: dict, repos_dir: Path) -> set:
    """Mirror augment.py's get_new_entities() exactly."""
    repo_name = example["repo"].split("/")[-1]
    repo_dir = str(repos_dir / repo_name)

    impl_patch = get_impl_patch(example)
    test_patch = get_test_patch(example)
    base_commit = example["base_commit"]

    # New .py files from implementation patch
    feature_patch_set = PatchSet(impl_patch)
    new_files_entities = [
        {"name": i.path, "type": "file"}
        for i in feature_patch_set.added_files
        if i.path.endswith(".py")
    ]

    feature_entities = get_diff_entities(impl_patch, test_patch, base_commit, repo_dir, "feature")
    test_entities    = get_diff_entities(impl_patch, test_patch, base_commit, repo_dir, "test")

    # Filter feature entities by name intersection with test entities
    test_entities_names = {i.split(SEPARATOR)[-1] for i in test_entities}
    new_ids_filter_by_test = [
        i for i in feature_entities
        if i.split(SEPARATOR)[-1] in test_entities_names
    ]

    # Add new files after filtering (mirrors augment.py line 161)
    new_ids_filter_by_test += [
        SEPARATOR.join([i["name"], i["type"], i["name"]])
        for i in new_files_entities
    ]

    # Filter out entities already in doc content
    doc_content = get_doc_content(example)
    new_entities = set()
    for i in new_ids_filter_by_test:
        if i.split(SEPARATOR)[-1] not in doc_content:
            new_entities.add(i)

    return new_entities


def process_instance(example: dict, repos_dir: Path) -> dict:
    entities = get_new_entities(example, repos_dir)
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
        description="NoCode identity selection — test-filtered new entity hints."
    )
    ap.add_argument("--input",  "-i", type=Path, required=True,
                    help="Input JSONL. NoCode Bench: ncbench_verified_no_hint.jsonl; "
                         "FEA-Bench: FEA-Bench-v1.0-medium.jsonl (from get_dataset.py); "
                         "SWE Pro / SWE Re-Bench: the raw dataset JSONL.")
    ap.add_argument("--output", "-o", type=Path, required=True,
                    help="Output JSONL with augmentations field added.")
    ap.add_argument("--repos",  "-r", type=Path, required=True,
                    help="Directory containing cloned repos.")
    ap.add_argument("--skip-errors", action="store_true",
                    help="Skip failed instances instead of crashing.")
    ap.add_argument("--instance-id", type=str, default=None,
                    help="Process a single instance_id (for debugging).")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"Input not found: {args.input}")
    if not args.repos.is_dir():
        sys.exit(f"Repos directory not found: {args.repos}")

    examples = load_jsonl(args.input)
    if args.instance_id:
        examples = [e for e in examples if e.get("instance_id") == args.instance_id]
        if not examples:
            sys.exit(f"No instance with id={args.instance_id!r}")

    output_rows = []
    errors = []

    for ex in tqdm(examples, desc="NoCode"):
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
        print(f"Wrote {len(errors)} errors → {err_path}")

    # Clean up temp patch file if present
    try:
        os.remove(PATCH_FILE)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
