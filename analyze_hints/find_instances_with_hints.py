#!/usr/bin/env python3
"""
Find all Multi-SWE-bench instances that have non-empty hints.

Usage:
    python find_instances_with_hints.py
    python find_instances_with_hints.py --output instances_with_hints.txt
    python find_instances_with_hints.py --by-language
"""
import json
import argparse
from pathlib import Path
from collections import defaultdict

def load_jsonl(file_path):
    """Load instances from a JSONL file."""
    instances = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                instances.append(json.loads(line))
    return instances

def find_instances_with_hints(base_path="Multi-SWE-bench"):
    """
    Find all instances with non-empty hints across all languages and repositories.
    
    Returns:
        dict: Dictionary mapping language -> repo -> list of instance IDs with hints
    """
    base = Path(base_path)
    results = defaultdict(lambda: defaultdict(list))
    
    # Iterate through all language directories
    for lang_dir in sorted(base.iterdir()):
        if not lang_dir.is_dir() or lang_dir.name.startswith('.'):
            continue
        
        language = lang_dir.name
        
        # Iterate through all dataset files in the language directory
        for dataset_file in sorted(lang_dir.glob("*_dataset.jsonl")):
            repo_name = dataset_file.stem.replace("_dataset", "")
            
            # Load instances
            instances = load_jsonl(dataset_file)
            
            # Find instances with non-empty hints
            for instance in instances:
                hints = instance.get("hints", "")
                instance_id = instance.get("instance_id", "N/A")
                
                # Check if hints is non-empty (not empty string, not None, not empty dict/list)
                if hints and hints != "" and hints != {} and hints != []:
                    results[language][repo_name].append(instance_id)
    
    return results

def print_results(results, by_language=False, output_file=None):
    """Print the results in a formatted way."""
    total_count = 0
    output_lines = []
    
    if by_language:
        # Group by language
        output_lines.append("=" * 80)
        output_lines.append("INSTANCES WITH NON-EMPTY HINTS (GROUPED BY LANGUAGE)")
        output_lines.append("=" * 80)
        output_lines.append("")
        
        for language in sorted(results.keys()):
            lang_count = sum(len(instances) for instances in results[language].values())
            output_lines.append(f"\n{language.upper()} ({lang_count} instances with hints):")
            output_lines.append("-" * 80)
            
            for repo_name in sorted(results[language].keys()):
                instance_ids = results[language][repo_name]
                output_lines.append(f"\n  {repo_name} ({len(instance_ids)} instances):")
                for instance_id in sorted(instance_ids):
                    output_lines.append(f"    • {instance_id}")
                    total_count += 1
    else:
        # Flat list
        output_lines.append("=" * 80)
        output_lines.append("ALL INSTANCES WITH NON-EMPTY HINTS")
        output_lines.append("=" * 80)
        output_lines.append("")
        
        for language in sorted(results.keys()):
            for repo_name in sorted(results[language].keys()):
                for instance_id in sorted(results[language][repo_name]):
                    output_lines.append(instance_id)
                    total_count += 1
    
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append(f"TOTAL: {total_count} instances with non-empty hints")
    output_lines.append("=" * 80)
    
    # Output to file or stdout
    output_text = "\n".join(output_lines)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"Results written to: {output_file}")
        print(f"Total instances with hints: {total_count}")
    else:
        print(output_text)

def print_summary(results):
    """Print a summary of results."""
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total = 0
    for language in sorted(results.keys()):
        lang_total = sum(len(instances) for instances in results[language].values())
        total += lang_total
        print(f"{language.upper():15s}: {lang_total:4d} instances with hints")
        for repo_name in sorted(results[language].keys()):
            count = len(results[language][repo_name])
            print(f"  └─ {repo_name:40s}: {count:4d}")
    
    print("-" * 80)
    print(f"{'TOTAL':15s}: {total:4d} instances with hints")
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(
        description='Find Multi-SWE-bench instances with non-empty hints',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print all instances with hints (flat list)
  %(prog)s
  
  # Print grouped by language
  %(prog)s --by-language
  
  # Save to file
  %(prog)s --output instances_with_hints.txt
  
  # Show only summary
  %(prog)s --summary-only
  
  # Custom base path
  %(prog)s --base-path /path/to/Multi-SWE-bench
        """
    )
    
    parser.add_argument(
        '--base-path',
        type=str,
        default='Multi-SWE-bench',
        help='Base path to Multi-SWE-bench directory (default: Multi-SWE-bench)'
    )
    
    parser.add_argument(
        '--by-language',
        action='store_true',
        help='Group results by programming language'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Write output to file'
    )
    
    parser.add_argument(
        '--summary-only',
        action='store_true',
        help='Show only summary statistics'
    )
    
    args = parser.parse_args()
    
    print("Scanning Multi-SWE-bench for instances with hints...")
    results = find_instances_with_hints(args.base_path)
    
    if args.summary_only:
        print_summary(results)
    else:
        print_results(results, by_language=args.by_language, output_file=args.output)
        if not args.output:
            print_summary(results)

if __name__ == "__main__":
    main()

# Made with Bob
