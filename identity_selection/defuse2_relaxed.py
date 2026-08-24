#!/usr/bin/env python3
"""
DefUse2 Relaxed — variant of defuse2.py with no scope restriction on WRITE/READ.

Differences from defuse2.py:
  - WRITE and READ are collected at ANY nesting depth (function bodies, nested
    classes, etc.), not just module-level or class-body-level.
  - is_at_module_level / is_at_module_or_class_level guards are removed from
    is_write_context, is_read_context, _extract_import, and get_all_identifiers_with_access.
  - Everything else (diff logic, forward/backward intersection, doc filter,
    import classification, new-file handling) is identical to defuse2.py.

Use this variant to evaluate whether the scope restriction helps or hurts.

Supported datasets (auto-detected from fields):
  - NoCode Bench Verified   : feature_patch + test_patch + doc_changes
  - FEA-Bench medium JSONL  : patch + test_patch
  - SWE Bench Pro Python    : patch + test_patch + problem_statement
  - SWE Re-Bench leaderboard: patch + test_patch + problem_statement

Note: For FEA-Bench, use FEA-Bench-v1.0-medium.jsonl (from get_dataset.py).
The raw HuggingFace dataset does not contain patch fields.

Usage:
    python identity_selection/defuse2_relaxed.py \\
        --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \\
        --output identity_selection/results_selection/defuse2_relaxed_sel/raw/ncbench_defuse2_relaxed.jsonl \\
        --repos  repos/doc2feat_repos

    python identity_selection/defuse2_relaxed.py \\
        --input  identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \\
        --output identity_selection/results_selection/defuse2_relaxed_sel/raw/feabench_defuse2_relaxed.jsonl \\
        --repos  repos/feabench_repos

    python identity_selection/defuse2_relaxed.py \\
        --input  identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \\
        --output identity_selection/results_selection/defuse2_relaxed_sel/raw/swebench_pro_defuse2_relaxed.jsonl \\
        --repos  repos/swe_pro_python_repos

    python identity_selection/defuse2_relaxed.py \\
        --input  identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \\
        --output identity_selection/results_selection/defuse2_relaxed_sel/raw/swerebench_defuse2_relaxed.jsonl \\
        --repos  repos/swerebench_repos \\
        --skip-errors
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

from tqdm import tqdm
from tree_sitter_languages import get_parser
from unidiff import PatchSet

from utils import load_jsonl, dump_jsonl, find_repo_dir, get_impl_patch, get_test_patch, get_doc_content

ts_parser = get_parser("python")

AUGMENTATION_HEADER_FORWARD = (
    "The following entities are defined in the implementation and used in tests "
    "(forward communication - new APIs/functions/classes):"
)
AUGMENTATION_HEADER_BACKWARD = (
    "The following entities are used in the implementation but defined in tests "
    "(backward communication - test fixtures/mocks):"
)


# ---------------------------------------------------------------------------
# Data structures
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
# Git helpers — mirrors augment_comm_v3_enhanced.py exactly
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
    """Return repo to a clean base commit. Mirrors augment_comm_v3_enhanced.py."""
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

    Uses shell=True / silent-on-error (mirrors augment.py's run_cmd style) so
    that patches which cannot apply at base_commit are silently skipped — the
    after-state will equal the before-state and no new entities will be reported
    for that file.
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
# AST helpers: READ / WRITE classification — mirrors augment_comm_v3_enhanced.py
# ---------------------------------------------------------------------------

def _node_contains(parent, child) -> bool:
    if parent == child:
        return True
    for c in parent.children:
        if _node_contains(c, child):
            return True
    return False


def is_at_module_level(node) -> bool:
    if node is None:
        return False
    current = node.parent
    while current is not None:
        if current.type in ["function_definition", "class_definition"]:
            return False
        if current.type == "module":
            return True
        current = current.parent
    return False


def is_at_module_or_class_level(node) -> bool:
    """True if node is at module level, or directly inside a class body (one level deep).

    This lets us capture class variables, class-level assignments, and method
    definitions inside a class, without descending into method bodies.
    """
    if node is None:
        return False
    current = node.parent
    inside_class = False
    while current is not None:
        if current.type == "module":
            return True
        if current.type == "class_definition":
            if inside_class:
                # Already passed one class boundary — too deep.
                return False
            inside_class = True
        elif current.type == "function_definition":
            # Inside a function body — not a class/module-level scope.
            return False
        current = current.parent
    return False


def is_write_context(node) -> bool:
    if node.parent is None:
        return False
    parent = node.parent
    parent_type = parent.type

    # Function/class name definitions — at any depth.
    if parent_type in ["function_definition", "class_definition"]:
        if node == parent.child_by_field_name("name"):
            return True

    # Variable assignments — at any depth.
    if parent_type == "assignment":
        left = parent.child_by_field_name("left")
        if left and _node_contains(left, node):
            return True

    return False


def is_read_context(node) -> bool:
    """True when the identifier is used (read) at any scope depth."""
    if node.parent is None:
        return False

    parent = node.parent
    parent_type = parent.type

    if parent_type == "call":
        func = parent.child_by_field_name("function")
        if func and _node_contains(func, node):
            return True

    if parent_type == "assignment":
        right = parent.child_by_field_name("right")
        if right and _node_contains(right, node):
            return True

    if parent_type == "augmented_assignment":
        right = parent.child_by_field_name("right")
        if right and _node_contains(right, node):
            return True
        left = parent.child_by_field_name("left")
        if left and _node_contains(left, node):
            return True

    if parent_type == "return_statement":
        return True

    if parent_type in ["binary_operator", "comparison_operator", "boolean_operator",
                       "unary_operator", "not_operator", "parenthesized_expression",
                       "list", "tuple", "set", "dictionary", "list_comprehension",
                       "dictionary_comprehension", "set_comprehension",
                       "generator_expression", "subscript", "slice"]:
        return True

    if parent_type in ["if_statement", "elif_clause", "while_statement",
                       "conditional_expression"]:
        return True

    if parent_type in ["argument_list", "keyword_argument"]:
        return True

    if parent_type == "for_statement":
        right = parent.child_by_field_name("right")
        if right and _node_contains(right, node):
            return True

    if parent_type == "attribute":
        obj = parent.child_by_field_name("object")
        if obj and _node_contains(obj, node):
            return True

    if parent_type == "decorator":
        return True

    return False


def _path_to_module(path: str) -> str:
    """Convert a file path to a dotted module name.

    "django/utils/helper.py"   → "django.utils.helper"
    "django/utils/__init__.py" → "django.utils"
    """
    name = path.replace("\\", "/")
    if name.endswith(".py"):
        name = name[:-3]
    name = name.replace("/", ".")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name


def _extract_import(
    stmt_node,
    local_modules: Set[str],
    file_path: str,
    results: List["Entity"],
) -> None:
    """
    Classify import names when the source module is in local_modules (i.e. a
    file touched by the current patch).

    Rules (mirrors identifier_usage.py):
      import X               → last component of X is WRITE
      import X as Z          → Z is WRITE
      from X import Y        → Y is WRITE
      from X import Y as Z   → Z is WRITE, Y is READ
    """
    def _text(n) -> str:
        return n.text.decode("utf-8", errors="ignore")

    nt = stmt_node.type

    if nt == "import_statement":
        for child in stmt_node.named_children:
            if child.type == "dotted_name":
                mod = _text(child)
                if mod in local_modules:
                    results.append(Entity(_text(child).split(".")[-1],
                                          AccessType.WRITE, "variable", file_path))
            elif child.type == "aliased_import":
                parts = list(child.named_children)
                if len(parts) == 2:
                    mod = _text(parts[0])
                    if mod in local_modules:
                        results.append(Entity(_text(parts[1]),
                                              AccessType.WRITE, "variable", file_path))

    elif nt == "import_from_statement":
        named = list(stmt_node.named_children)
        if not named:
            return
        mod = _text(named[0])
        if mod not in local_modules:
            return
        for child in named[1:]:
            if child.type == "dotted_name":
                results.append(Entity(_text(child).split(".")[-1],
                                      AccessType.WRITE, "variable", file_path))
            elif child.type == "aliased_import":
                parts = list(child.named_children)
                if len(parts) == 2:
                    # original name → READ, alias → WRITE
                    results.append(Entity(_text(parts[0]).split(".")[-1],
                                          AccessType.READ, "variable", file_path))
                    results.append(Entity(_text(parts[1]),
                                          AccessType.WRITE, "variable", file_path))


def _get_raise_string(node) -> Optional[str]:
    """Mirror augment_comm_v3_enhanced.py's _get_raise_string() exactly."""
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
            traverse(child, pos + 1)

    if node.type == "raise_statement":
        traverse(node, 0)
    elif node.type == "with_clause":
        node_text = node.text.decode("utf-8", errors="ignore")
        if "pytest.raises" in node_text:
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
        return string_node.text.decode("utf-8", errors="ignore")
    return None


def get_all_identifiers_with_access(
    root,
    file_path: str = "",
    local_modules: Optional[Set[str]] = None,
) -> List[Entity]:
    """Extract all identifiers with READ/WRITE classification.

    local_modules: dotted module names for files touched by the current patch.
    Import statements whose source module is in local_modules are classified;
    all other import statements are skipped entirely.
    """
    if local_modules is None:
        local_modules = set()
    results = []

    def traverse(node):
        # Intercept import statements — consume them here, skip normal descent.
        if node.type in ("import_statement", "import_from_statement"):
            _extract_import(node, local_modules, file_path, results)
            return

        if node.type in ["raise_statement", "with_clause"]:
            raise_str = _get_raise_string(node)
            if raise_str is not None:
                results.append(Entity(
                    name=raise_str,
                    access_type=AccessType.WRITE,
                    entity_type="error_msg",
                    file_path=file_path,
                ))

        if node.type == "identifier":
            name = node.text.decode("utf-8", errors="ignore")

            entity_type = "variable"
            if node.parent and node.parent.type == "function_definition":
                if node == node.parent.child_by_field_name("name"):
                    entity_type = "function"
            elif node.parent and node.parent.type == "class_definition":
                if node == node.parent.child_by_field_name("name"):
                    entity_type = "class"
            elif node.parent and node.parent.type == "attribute":
                if node == node.parent.child_by_field_name("attribute"):
                    entity_type = "attribute"

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
    """Extract entities from Python code with read/write classification."""
    try:
        tree = ts_parser.parse(code.encode("utf-8", errors="ignore"))
        entities = get_all_identifiers_with_access(
            tree.root_node, file_path, local_modules=local_modules
        )
        return set(entities)
    except Exception:
        return set()


def filter_entities_by_access(entities: Set[Entity], access_type: AccessType) -> Set[Entity]:
    return {e for e in entities if e.access_type == access_type}


def entities_to_dict(entities: Set[Entity]) -> List[Dict[str, str]]:
    """Convert Entity objects to dict format.

    Deduplicates by name only — file_path is internal bookkeeping and the hint
    consumer only sees the name.  Prefers 'function'/'class' entity_type over
    'variable' when the same name appears from multiple files/contexts.
    """
    key_to_entity: Dict[str, Entity] = {}
    for entity in entities:
        key = entity.name
        if key not in key_to_entity:
            key_to_entity[key] = entity
        else:
            existing = key_to_entity[key]
            if (entity.entity_type in ["function", "class"]
                    and existing.entity_type not in ["function", "class"]):
                key_to_entity[key] = entity

    result = []
    for entity in key_to_entity.values():
        result.append({"type": entity.entity_type, "name": entity.name})

    result.sort(key=lambda x: x["name"])
    return result


# ---------------------------------------------------------------------------
# Diff entity extraction — mirrors augment_comm_v3_enhanced.py's
# get_diff_entities_with_access()
# ---------------------------------------------------------------------------

def python_files_from_patch(patch_content: str):
    if not patch_content.strip():
        return []
    patch_set = PatchSet(patch_content)
    return [patched_file for patched_file in patch_set if patched_file.path.endswith(".py")]


def get_diff_entities_with_access(example: dict, repo_dir: Path,
                                   patch_type: str) -> Set[Entity]:
    """
    Compute entities introduced by either impl_patch or test_patch with READ/WRITE info.
    Mirrors augment_comm_v3_enhanced.py's get_diff_entities_with_access() exactly.
    """
    base_commit = example["base_commit"]
    patch_content = get_impl_patch(example) if patch_type == "feature" else get_test_patch(example)

    reset_repo(repo_dir, base_commit)

    patched_files = python_files_from_patch(patch_content)

    patch_set = PatchSet(patch_content) if patch_content.strip() else PatchSet("")
    new_files = [f for f in patch_set.added_files if f.path.endswith(".py")]

    # Dotted module names for every .py file touched by this patch.
    # Used to gate import classification — only imports from these modules count.
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
# Core per-instance logic — mirrors augment_comm_v3_enhanced.py's
# get_communication_hints() and add_augmentations()
# ---------------------------------------------------------------------------

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
        description="Generate communication-based augmentation hints (DefUse2)"
    )
    argp.add_argument("--input",  "-i", type=Path, required=True,
                      help="Input JSONL. NoCode Bench: ncbench_verified_no_hint.jsonl; "
                           "FEA-Bench: FEA-Bench-v1.0-medium.jsonl (from get_dataset.py); "
                           "SWE Pro / SWE Re-Bench: the raw dataset JSONL.")
    argp.add_argument("--output", "-o", type=Path, required=True,
                      help="Output JSONL path.")
    argp.add_argument("--repos-dir", "-r", type=Path, required=True,
                      help="Directory containing cloned repos.")
    argp.add_argument("--skip-errors", action="store_true",
                      help="Continue on failed instances and write an .errors.jsonl file.")
    argp.add_argument("--instance-id", type=str, default=None,
                      help="Optional single instance_id for debugging.")

    args = argp.parse_args()

    main(
        input_path=args.input,
        output_path=args.output,
        repos_dir=args.repos_dir,
        skip_errors=args.skip_errors,
        instance_id=args.instance_id,
    )
