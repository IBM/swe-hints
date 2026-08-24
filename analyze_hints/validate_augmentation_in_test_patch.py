#!/usr/bin/env python3
"""
Validate Augmentation Entities in Test Patch

This script checks whether entity names from forward/backward augmentations
actually appear in the test_patch. Reports instances where entities are missing.

Works for both SWE-bench Pro (JSONL) and FEA-Bench (HuggingFace dataset).
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Set
from datasets import load_from_disk


def load_swebench_pro_jsonl(path: Path) -> List[dict]:
    """Load SWE-bench Pro JSONL file."""
    examples = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def load_feabench_dataset(path: Path, split: str = "test") -> List[dict]:
    """Load FEA-Bench HuggingFace dataset."""
    dataset_dict = load_from_disk(str(path))
    if split not in dataset_dict:
        raise ValueError(f"Split '{split}' not found. Available: {list(dataset_dict.keys())}")
    return list(dataset_dict[split])


def get_augmentation_names(augmentations: dict) -> Set[str]:
    """
    Extract all entity names from forward and backward augmentations.
    Skips entities with type "file".
    
    Args:
        augmentations: Dict with 'forward' and 'backward' keys
    
    Returns:
        Set of entity names (excluding file types)
    """
    names = set()
    
    # Get forward entity names
    forward = augmentations.get("forward", {})
    forward_data = forward.get("data", [])
    for entity in forward_data:
        if isinstance(entity, dict) and "name" in entity:
            # Skip file type entities
            if entity.get("type") != "file":
                names.add(entity["name"])
    
    # Get backward entity names
    backward = augmentations.get("backward", {})
    backward_data = backward.get("data", [])
    for entity in backward_data:
        if isinstance(entity, dict) and "name" in entity:
            # Skip file type entities
            if entity.get("type") != "file":
                names.add(entity["name"])
    
    return names


def check_names_in_test_patch(names: Set[str], test_patch: str) -> Dict[str, bool]:
    """
    Check which entity names appear in the test patch.
    
    Args:
        names: Set of entity names to check
        test_patch: The test patch content
    
    Returns:
        Dict mapping name -> whether it appears in test_patch
    """
    results = {}
    for name in names:
        # Check if name appears in test patch
        # Use word boundary check to avoid partial matches
        results[name] = name in test_patch
    return results


def validate_example(example: dict) -> Dict:
    """
    Validate a single example.
    
    Returns:
        Dict with validation results
    """
    instance_id = example.get("instance_id", "<unknown>")
    augmentations = example.get("augmentations", {})
    test_patch = example.get("test_patch", "")
    
    # Get all entity names from augmentations
    entity_names = get_augmentation_names(augmentations)
    
    if not entity_names:
        # No augmentations to validate
        return {
            "instance_id": instance_id,
            "has_augmentations": False,
            "missing_entities": [],
            "present_entities": [],
        }
    
    # Check which names appear in test patch
    name_presence = check_names_in_test_patch(entity_names, test_patch)
    
    missing = [name for name, present in name_presence.items() if not present]
    present = [name for name, present in name_presence.items() if present]
    
    return {
        "instance_id": instance_id,
        "has_augmentations": True,
        "total_entities": len(entity_names),
        "missing_entities": missing,
        "present_entities": present,
        "missing_count": len(missing),
        "present_count": len(present),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate that augmentation entity names appear in test patches"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input file/directory (JSONL for SWE-bench Pro, dataset dir for FEA-Bench)",
    )
    parser.add_argument(
        "--format",
        choices=["swebench-pro", "feabench"],
        required=True,
        help="Input format",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Dataset split for FEA-Bench (default: test)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file for detailed results (optional)",
    )
    parser.add_argument(
        "--print-missing-only",
        action="store_true",
        help="Only print instances with missing entities",
    )
    
    args = parser.parse_args()
    
    # Load examples
    print(f"Loading examples from {args.input}...")
    if args.format == "swebench-pro":
        examples = load_swebench_pro_jsonl(args.input)
    else:  # feabench
        examples = load_feabench_dataset(args.input, args.split)
    
    print(f"Loaded {len(examples)} examples")
    
    # Validate each example
    print("\nValidating augmentations...")
    results = []
    instances_with_missing = []
    
    for example in examples:
        result = validate_example(example)
        results.append(result)
        
        if result["has_augmentations"] and result["missing_count"] > 0:
            instances_with_missing.append(result["instance_id"])
    
    # Print summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    
    total_with_aug = sum(1 for r in results if r["has_augmentations"])
    total_with_missing = len(instances_with_missing)
    
    print(f"Total examples: {len(examples)}")
    print(f"Examples with augmentations: {total_with_aug}")
    print(f"Examples with missing entities: {total_with_missing}")
    
    if total_with_aug > 0:
        print(f"Percentage with missing: {100 * total_with_missing / total_with_aug:.1f}%")
    
    # Print detailed results
    if args.print_missing_only:
        print("\n" + "=" * 80)
        print("INSTANCES WITH MISSING ENTITIES")
        print("=" * 80)
        for result in results:
            if result["has_augmentations"] and result["missing_count"] > 0:
                print(f"\n{result['instance_id']}")
                print(f"  Missing ({result['missing_count']}): {', '.join(result['missing_entities'])}")
                print(f"  Present ({result['present_count']}): {', '.join(result['present_entities'])}")
    else:
        print("\n" + "=" * 80)
        print("ALL INSTANCES WITH AUGMENTATIONS")
        print("=" * 80)
        for result in results:
            if result["has_augmentations"]:
                status = "✗ HAS MISSING" if result["missing_count"] > 0 else "✓ ALL PRESENT"
                print(f"\n{result['instance_id']} - {status}")
                print(f"  Total entities: {result['total_entities']}")
                if result["missing_count"] > 0:
                    print(f"  Missing ({result['missing_count']}): {', '.join(result['missing_entities'])}")
                if result["present_count"] > 0:
                    print(f"  Present ({result['present_count']}): {', '.join(result['present_entities'])}")
    
    # Save detailed results if requested
    if args.output:
        print(f"\nSaving detailed results to {args.output}...")
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("Done!")
    
    # Print instance IDs with missing entities
    if instances_with_missing:
        print("\n" + "=" * 80)
        print("INSTANCE IDS WITH MISSING ENTITIES")
        print("=" * 80)
        for iid in instances_with_missing:
            print(iid)


if __name__ == "__main__":
    main()

# Made with Bob
