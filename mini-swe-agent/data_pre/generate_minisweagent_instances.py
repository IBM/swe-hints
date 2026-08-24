#!/usr/bin/env python3
"""
Generate mini-SWE-agent instance JSONL file from HuggingFace SWE-bench Pro dataset.

This script loads the SWE-bench Pro dataset and generates a JSONL file containing
all instances formatted for use with mini-SWE-agent. Each instance includes the Docker
image name, problem statement, instance ID, base commit, and repo name.

mini-SWE-agent uses load_dataset() to ingest datasets, so the output is a JSONL file
that can be passed via --subset <path/to/instances.jsonl>.

Usage:
    python generate_minisweagent_instances.py --dockerhub_username <your-username>
    python generate_minisweagent_instances.py --dockerhub_username <your-username> --output_path custom_instances.jsonl

Running with mini-SWE-agent:
    mini-swe-agent swebench --subset path/to/instances.jsonl --split train
"""

import argparse
import json
import os
from pathlib import Path
from tqdm import tqdm
from datasets import load_dataset

# Import helper functions from the same directory
from image_uri import get_dockerhub_image_uri
from create_problem_statement import create_problem_statement
from create_hints import create_hints


NO_NEW_INTERFACES_MARKER = "No new interfaces are introduced"


def _format_section(header: str, data: list) -> str:
    """Format a single header + data list into a text block."""
    if not data:
        return ""
    lines = []
    if header:
        lines.append(header)
        lines.append("")
    for item in data:
        kind = item.get("type", "")
        name = item.get("name", "")
        if kind and name:
            lines.append(f"- **{kind}:** `{name}`")
        elif name:
            lines.append(f"- `{name}`")
    return "\n".join(lines)


def format_augmentation(augmentation: dict) -> str:
    """
    Format the augmentations dict into a hints string.

    Handles two formats:
      Flat:      { "header": "...", "data": [...] }
                 (e.g. swebench_pro_augmented.jsonl)
      Sectioned: { "forward": { "header": "...", "data": [...] },
                   "backward": { "header": "...", "data": [...] } }
                 (e.g. swebench_pro_augmented_comm-v3-enhanced-fb.jsonl)

    Returns "" if there is no non-empty data in any section.
    """
    if not augmentation:
        return ""

    # Flat format: has a top-level "data" key
    if "data" in augmentation:
        return _format_section(augmentation.get("header", ""), augmentation.get("data", []))

    # Sectioned format: values are dicts with their own header/data
    parts = []
    for section in augmentation.values():
        if not isinstance(section, dict):
            continue
        block = _format_section(section.get("header", ""), section.get("data", []))
        if block:
            parts.append(block)
    return "\n\n".join(parts)


def load_augmented_index(augmented_path: str) -> dict:
    """Load swebench_pro_augmented.jsonl into a dict keyed by instance_id."""
    index = {}
    path = Path(augmented_path)
    if not path.exists():
        raise FileNotFoundError(f"Augmented dataset not found: {augmented_path}")
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            index[row["instance_id"]] = row
    return index


def load_components_index(components_path: str) -> dict:
    """Load swebench_pro_with_components.jsonl into a dict keyed by instance_id.

    Returns a dict mapping instance_id ->
        {"new_components": {...}, "non_py_patch": "..."}
    """
    index = {}
    path = Path(components_path)
    if not path.exists():
        raise FileNotFoundError(f"Components dataset not found: {components_path}")
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            index[row["instance_id"]] = {
                "new_components": row.get("new_components", {}),
                "non_py_patch": row.get("non_py_patch", ""),
            }
    return index


def format_new_components(new_components: dict, with_doc: bool, non_py_patch: str = "") -> str:
    """
    Format new_components into a FEA-Bench-style definitions block for use as hints.

    Mirrors the original FEA-Bench pipeline (make_instructions.py):
      - detailed (with_doc=True):  signatures + docstrings (get_wrapped_definitions)
                                   + non-Python diffs (get_wrapped_doc_changes)
      - brief    (with_doc=False): signatures only, no docstrings, no non-Python diffs

    The non-Python diff block uses the exact same preamble and tag as the original
    get_wrapped_doc_changes():
        "To implement the new features mentioned above, some design in this
         repository need to be modified, as the modification in document files:
         <description changes>...</description changes>"

    Args:
        new_components: dict mapping file_path -> list of namespace dicts
                        (each dict has keys: type, name, signature, doc, lines)
        with_doc: if True emit docstrings and non-Python diffs (detailed);
                  if False omit them (brief)
        non_py_patch: raw diff string for non-Python file changes (used only
                      when with_doc=True)

    Returns:
        Formatted string, or "" when new_components is empty and no non-Python
        changes exist (for detailed mode).
    """
    parts = []

    for file_path, components in new_components.items():
        if not components:
            continue
        block = [f"[start of new definitions in {file_path}]"]
        for item in components:
            block.append(f"(definition of {item['name']}:)")
            block.append(item["signature"])
            if with_doc and item.get("doc"):
                block.append(f'"""{item["doc"]}"""')
        block.append(f"[end of new definitions in {file_path}]")
        parts.append("\n".join(block))

    if not parts and not (with_doc and non_py_patch):
        return ""

    result_parts = []

    if parts:
        definitions = "\n".join(parts)
        result_parts.append(
            "There are several new functions or classes that need to be implemented, "
            "using the definitions below:\n"
            "<definitions>\n"
            f"{definitions}\n"
            "</definitions>"
        )

    # Mirror get_wrapped_doc_changes() from the original FEA-Bench pipeline
    if with_doc and non_py_patch and non_py_patch.strip():
        result_parts.append(
            "To implement the new features mentioned above, some design in this "
            "repository need to be modified, as the modification in document files:\n"
            "<description changes>\n"
            f"{non_py_patch.strip()}\n"
            "</description changes>"
        )

    return "\n\n".join(result_parts)


# def create_hints(row):
#     """
#     Build the hints string from requirements and interface fields.

#     This is stored as a separate 'hints' key in the JSONL and rendered into
#     the dedicated <hints> section of swebench_pro_hints.yaml via {{hints}}.
#     The content of hints can be further customised later.

#     Args:
#         row: A dataset row dict containing 'requirements' and 'interface' fields

#     Returns:
#         str: Formatted hints string
#     """
#     return f"New interfaces introduced:\n{row['interface']}\n\nRequirements:\n{row['requirements']}"


def generate_instances(dockerhub_username, dataset_split="test", python_only=False, skip_no_interface=False, plain_problem_statement=False, with_hints=False, requirements_only=False, interface_only=False, augmented_hints=None, components_hints_detailed=None, components_hints_brief=None):
    """
    Load SWE-bench Pro dataset and generate instance list.

    Args:
        dockerhub_username: Docker Hub username for image URI generation
        dataset_split: Which split of the dataset to use (default: 'test')
        python_only: If True, only include instances where repo_language == 'python'
        skip_no_interface: If True, skip instances whose interface field contains
                           "No new interfaces are introduced"
        plain_problem_statement: If True, use only the raw problem_statement field,
                                 omitting requirements and interface sections
        with_hints: If True, store requirements + interface as a separate 'hints'
                    field (for use with swebench_pro_hints.yaml) instead of
                    appending them to problem_statement
        requirements_only: If True, append only requirements to problem_statement,
                           omitting the interface section
        interface_only: If True, append only the interface field to problem_statement,
                        omitting requirements. The raw interface string is used as-is,
                        including "No new interfaces are introduced" when present.
        augmented_hints: Path to swebench_pro_augmented.jsonl. If provided, the
                         augmentation data is placed into the 'hints' field and
                         problem_statement is kept as plain issue text only.
        components_hints_detailed: Path to swebench_pro_with_components.jsonl. If
                         provided, new_components are formatted with docstrings
                         (FEA-Bench "detailed") and placed into the 'hints' field.
        components_hints_brief: Path to swebench_pro_with_components.jsonl. If
                         provided, new_components are formatted without docstrings
                         (FEA-Bench "brief") and placed into the 'hints' field.

    Returns:
        list: List of instance dictionaries formatted for JSONL output
    """
    print(f"Loading SWE-bench Pro dataset (split: {dataset_split})...")
    swebench_pro = load_dataset("ScaleAI/SWE-bench_Pro", split=dataset_split)

    aug_index = {}
    if augmented_hints:
        print(f"Loading augmentation data from {augmented_hints}...")
        aug_index = load_augmented_index(augmented_hints)

    components_index = {}
    components_with_doc = False
    if components_hints_detailed:
        print(f"Loading components (detailed) from {components_hints_detailed}...")
        components_index = load_components_index(components_hints_detailed)
        components_with_doc = True
    elif components_hints_brief:
        print(f"Loading components (brief) from {components_hints_brief}...")
        components_index = load_components_index(components_hints_brief)
        components_with_doc = False

    instances = []
    skipped_language = 0
    skipped_interface = 0
    print(f"Processing {len(swebench_pro)} instances...")

    for row in tqdm(swebench_pro):
        # Filter: Python only
        if python_only and row.get("repo_language", "").lower() != "python":
            skipped_language += 1
            continue

        # Filter: skip instances with no new interfaces
        if skip_no_interface and NO_NEW_INTERFACES_MARKER in row.get("interface", ""):
            skipped_interface += 1
            continue

        # Generate Docker Hub image URI
        instance_id = row["instance_id"]
        repo_name = row.get("repo", "")
        image_name = get_dockerhub_image_uri(instance_id, dockerhub_username, repo_name)

        # Build problem_statement and optional hints
        if components_index:
            # FEA-Bench components mode: plain problem_statement, new_components as hints
            # detailed (with_doc=True) or brief (with_doc=False) controlled by which flag was set
            problem_statement = row["problem_statement"]
            entry = components_index.get(instance_id, {})
            new_components = entry.get("new_components", {})
            non_py_patch = entry.get("non_py_patch", "")
            hints = format_new_components(new_components, with_doc=components_with_doc, non_py_patch=non_py_patch)
        elif augmented_hints:
            # Augmentation mode: raw issue as problem_statement, augmentation into hints
            problem_statement = row["problem_statement"]
            aug_row = aug_index.get(instance_id, {})
            hints = format_augmentation(aug_row.get("augmentations", {}))
        elif with_hints:
            # Separate mode: raw problem_statement + hints as its own field
            problem_statement = row["problem_statement"]
            hints = create_hints(row)
        elif plain_problem_statement:
            problem_statement = row["problem_statement"]
            hints = ""
        elif requirements_only:
            # problem_statement + requirements, no interface
            problem_statement = f"{row['problem_statement']}\n\nRequirements:\n{row['requirements']}"
            hints = ""
        elif interface_only:
            # problem_statement + raw interface string, no requirements
            # preserves "No new interfaces are introduced" as-is when present
            problem_statement = f"{row['problem_statement']}\n\nNew interfaces introduced:\n{row['interface']}"
            hints = ""
        else:
            # Baseline: requirements + interface appended into problem_statement
            problem_statement = create_problem_statement(row)
            hints = ""

        # Create instance dictionary matching the fields mini-SWE-agent reads:
        #   - image_name: used by get_swebench_docker_image_name() to pick the Docker image
        #   - problem_statement: passed as the task to agent.run()
        #   - hints: passed as hints= kwarg to agent.run() (used by swebench_pro_hints.yaml)
        #   - instance_id: used for output file naming and progress tracking
        #   - base_commit: informational, carried through for eval compatibility
        #   - repo: original repo field, kept for eval compatibility
        instance = {
            "image_name": image_name,
            "problem_statement": problem_statement,
            "hints": hints,
            "instance_id": instance_id,
            "base_commit": row["base_commit"],
            "repo": repo_name,
        }

        instances.append(instance)

    if python_only:
        print(f"  Skipped {skipped_language} non-Python instances (--python_only)")
    if skip_no_interface:
        print(f"  Skipped {skipped_interface} instances with no new interfaces (--skip_no_interface)")

    return instances


def write_jsonl(instances, output_path):
    """
    Write instances to JSONL file (one JSON object per line).

    mini-SWE-agent uses load_dataset() to load the file, which natively supports JSONL.

    Args:
        instances: List of instance dictionaries
        output_path: Path to output JSONL file
    """
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    print(f"Writing {len(instances)} instances to {output_path}...")
    with open(output_path, "w") as f:
        for instance in instances:
            f.write(json.dumps(instance, ensure_ascii=False) + "\n")

    print(f"✓ Successfully generated {output_path}")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate mini-SWE-agent instances from HuggingFace SWE-bench Pro dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate instances with default settings
  python generate_minisweagent_instances.py --dockerhub_username myusername

  # Generate instances with custom output path
  python generate_minisweagent_instances.py --dockerhub_username myusername --output_path custom_instances.jsonl

  # Use a different dataset split
  python generate_minisweagent_instances.py --dockerhub_username myusername --dataset_split dev

  # Python instances only, skipping those with no new interfaces
  python generate_minisweagent_instances.py --dockerhub_username myusername --python_only --skip_no_interface

  # Use only the raw problem statement (no requirements/interface sections)
  python generate_minisweagent_instances.py --dockerhub_username myusername --plain_problem_statement

  # Separate hints into their own field (for use with swebench_pro_hints.yaml)
  python generate_minisweagent_instances.py --dockerhub_username myusername --with_hints

Running with mini-SWE-agent (batch):
  mini-swe-agent swebench \\
    --subset path/to/instances.jsonl \\
    --split train \\
    --output output_dir/

Running with mini-SWE-agent (single instance):
  mini-swe-agent swebench-single \\
    --subset path/to/instances.jsonl \\
    --split train \\
    --instance <instance_id>
        """,
    )

    parser.add_argument(
        "--dockerhub_username",
        required=True,
        help="Docker Hub username for generating image URIs (required)",
    )

    parser.add_argument(
        "--output_path",
        default="mini-swe-agent/data/instances.jsonl",
        help="Output path for the generated JSONL file (default: mini-swe-agent/data/instances.jsonl)",
    )

    parser.add_argument(
        "--dataset_split",
        default="test",
        help="Which split of the dataset to use (default: test)",
    )

    parser.add_argument(
        "--python_only",
        action="store_true",
        default=False,
        help="Only include instances where repo_language is 'python'",
    )

    parser.add_argument(
        "--skip_no_interface",
        action="store_true",
        default=False,
        help="Skip instances whose interface field contains 'No new interfaces are introduced'",
    )

    parser.add_argument(
        "--plain_problem_statement",
        action="store_true",
        default=False,
        help="Use only the raw problem_statement field, omitting requirements and interface sections",
    )

    parser.add_argument(
        "--with_hints",
        action="store_true",
        default=False,
        help="Store requirements + interface as a separate 'hints' field instead of appending to "
             "problem_statement. Use with --config swebench_pro_hints.yaml in mini-swe-agent.",
    )

    parser.add_argument(
        "--requirements_only",
        action="store_true",
        default=False,
        help="Append only the requirements section to problem_statement, omitting the interface section",
    )

    parser.add_argument(
        "--interface_only",
        action="store_true",
        default=False,
        help="Append only the raw interface field to problem_statement, omitting requirements. "
             "Preserves 'No new interfaces are introduced' as-is when present.",
    )

    parser.add_argument(
        "--augmented_hints",
        default=None,
        help="Path to swebench_pro_augmented.jsonl. Puts augmentation data into the 'hints' field "
             "and uses plain problem_statement. Use with --config swebench_pro_hints.yaml.",
    )

    parser.add_argument(
        "--components_hints_detailed",
        default=None,
        help="Path to swebench_pro_with_components.jsonl. Formats new_components as FEA-Bench "
             "'detailed' hints (signature + docstring) placed into the 'hints' field. "
             "Use with --config swebench_pro_hints.yaml.",
    )

    parser.add_argument(
        "--components_hints_brief",
        default=None,
        help="Path to swebench_pro_with_components.jsonl. Formats new_components as FEA-Bench "
             "'brief' hints (signature only, no docstring) placed into the 'hints' field. "
             "Use with --config swebench_pro_hints.yaml.",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Generate instances
    instances = generate_instances(
        args.dockerhub_username,
        args.dataset_split,
        python_only=args.python_only,
        skip_no_interface=args.skip_no_interface,
        plain_problem_statement=args.plain_problem_statement,
        with_hints=args.with_hints,
        requirements_only=args.requirements_only,
        interface_only=args.interface_only,
        augmented_hints=args.augmented_hints,
        components_hints_detailed=args.components_hints_detailed,
        components_hints_brief=args.components_hints_brief,
    )

    # Write to JSONL file
    write_jsonl(instances, args.output_path)

    print(f"\n✓ Done! Generated {len(instances)} instances.")
    print(f"  Output: {args.output_path}")
    print(f"\nYou can now use this file with mini-SWE-agent (batch):")
    print(f"  mini-swe-agent swebench \\")
    print(f"    --subset {args.output_path} \\")
    print(f"    --split train \\")
    print(f"    --output output_dir/")


if __name__ == "__main__":
    main()
