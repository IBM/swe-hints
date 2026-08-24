#!/usr/bin/env python3
"""
# Command line example for printing
python pretty_printing.py --instance pytest-dev__pytest-2794 --key instance_id augmentations problem_statement feature_patch test_patch

# Command line example for plain text printing
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement --plain
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement feature_patch -o ncbench_example/pytest-2794.txt
"""
from typing import Any, Dict as DictType  # Fixed import
from datasets import load_dataset
from rich.console import Console
from rich.syntax import Syntax
from rich.tree import Tree
from rich.panel import Panel
from rich.table import Table
import json
import argparse
import sys
import os
from pathlib import Path

console = Console()

# Global dataset cache
_dataset_cache = {}

def load_local_jsonl_dataset(file_path: str):
    """
    Load a local JSONL dataset into a list of dictionaries.

    Args:
        file_path: Path to a local .jsonl file

    Returns:
        List of parsed JSON objects
    """
    resolved_path = Path(file_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = Path.cwd() / resolved_path

    if not resolved_path.exists():
        raise FileNotFoundError(f"Local dataset file not found: {resolved_path}")

    dataset = []
    with resolved_path.open('r', encoding='utf-8') as f:
        for line_number, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON on line {line_number} in '{resolved_path}': {str(e)}"
                ) from e

            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected JSON object on line {line_number} in '{resolved_path}', "
                    f"got {type(record).__name__}"
                )

            dataset.append(record)

    return dataset


def load_benchmark_dataset(benchmark: str = 'nocode', split: str = 'test', dataset_path: str | None = None):
    """
    Load a benchmark dataset with caching.

    Args:
        benchmark: Benchmark name ('nocode', etc.)
        split: Dataset split ('test', 'train', 'validation')
        dataset_path: Optional local dataset path (.jsonl supported)

    Returns:
        Loaded dataset
    """
    cache_key = dataset_path if dataset_path else f"{benchmark}_{split}"

    if cache_key in _dataset_cache:
        return _dataset_cache[cache_key]

    try:
        if dataset_path:
            dataset = load_local_jsonl_dataset(dataset_path)
        elif benchmark.lower() == 'nocode':
            dataset = load_dataset('NoCode-bench/NoCode-bench_Verified', split=split)
        else:
            # Add more benchmarks here in the future
            raise ValueError(f"Unknown benchmark: {benchmark}")

        _dataset_cache[cache_key] = dataset
        return dataset
    except Exception as e:
        source = dataset_path if dataset_path else benchmark
        console.print(f"[red]Error loading dataset '{source}': {str(e)}[/red]")
        sys.exit(1)

# Default dataset for backward compatibility
ncbench_verified = load_benchmark_dataset('nocode', 'test')

def get_instance(instance_id: str, dataset=None) -> DictType | None:
    """
    Get an instance from the dataset.
    
    Args:
        instance_id: The instance identifier
        dataset: Optional dataset to search in (uses default if None)
    
    Returns:
        Instance dictionary or None if not found
    """
    if dataset is None:
        dataset = ncbench_verified
    
    for instance in dataset:
        if instance["instance_id"] == instance_id:
            return instance
    return None

def print_patch(patch_content: str, title: str = "Patch"):
    """Display a patch with syntax highlighting for diff format."""
    if not patch_content:
        console.print(f"[yellow]{title}: Empty[/yellow]")
        return
    
    # Use 'diff' lexer for patch syntax highlighting
    syntax = Syntax(
        patch_content,
        "diff",  # diff lexer highlights +/- lines
        theme="monokai",
        line_numbers=True,
        word_wrap=False  # Patches often have long lines
    )
    panel = Panel(
        syntax,
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="blue"
    )
    console.print(panel)

def print_instance(instance_id: str, style: str = "json", show_patches: bool = False):
    """
    Print instance with rich formatting.
    
    Args:
        style: "json" (syntax highlighted), "tree" (hierarchical), "table" (key-value pairs), "patches" (diff view)
        show_patches: If True, display feature_patch and test_patch separately after main content
    """
    instance = get_instance(instance_id)
    if not instance:
        console.print(f"[red]Instance '{instance_id}' not found[/red]")
        return
    
    if style == "json":
        # Syntax-highlighted JSON
        json_str = json.dumps(dict(instance), indent=2, default=str, ensure_ascii=False)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True, word_wrap=True)
        panel = Panel(syntax, title=f"[bold cyan]{instance_id}[/bold cyan]", border_style="blue")
        console.print(panel)
    
    elif style == "tree":
        # Hierarchical tree view
        tree = Tree(f"[bold magenta]{instance_id}[/bold magenta]")
        _add_to_tree(tree, dict(instance))
        console.print(tree)
    
    elif style == "table":
        # Key-value table
        table = Table(title=f"Instance: {instance_id}", show_header=True, header_style="bold cyan")
        table.add_column("Key", style="cyan", width=30)
        table.add_column("Type", style="yellow", width=15)
        table.add_column("Preview", style="green")
        
        for key, value in dict(instance).items():
            value_type = type(value).__name__
            
            # Special handling for patch fields
            if key in ["feature_patch", "test_patch"] and isinstance(value, str):
                line_count = value.count('\n')
                preview = f"Patch with {line_count} lines (use style='patches' to view)"
            elif isinstance(value, (list, dict)):
                preview = f"Size: {len(value)}"
            else:
                preview = str(value)[:80] + ("..." if len(str(value)) > 80 else "")
            
            table.add_row(key, value_type, preview)
        
        console.print(table)
    
    elif style == "patches":
        # Display patches with proper diff highlighting
        console.print(f"\n[bold magenta]Instance: {instance_id}[/bold magenta]\n")
        
        if "feature_patch" in instance and instance["feature_patch"]:
            print_patch(instance["feature_patch"], "Feature Patch")
            console.print()  # Add spacing
        
        if "test_patch" in instance and instance["test_patch"]:
            print_patch(instance["test_patch"], "Test Patch")
    
    # Optionally show patches after other styles
    if show_patches and style != "patches":
        console.print("\n" + "="*80 + "\n")
        if "feature_patch" in instance and instance["feature_patch"]:
            print_patch(instance["feature_patch"], "Feature Patch")
            console.print()
        if "test_patch" in instance and instance["test_patch"]:
            print_patch(instance["test_patch"], "Test Patch")

def print_instance_key(instance_id: str, key: str, dataset=None, plain: bool = False):
    """
    Print the content of a specific key from an instance with appropriate formatting.
    
    Args:
        instance_id: The instance identifier
        key: The key name to print (e.g., 'problem_statement', 'feature_patch', 'test_patch')
        dataset: Optional dataset to search in (uses default if None)
        plain: If True, output plain text without rich formatting
    
    Examples:
        print_instance_key('pytest-dev__pytest-2794', 'problem_statement')
        print_instance_key('pytest-dev__pytest-2794', 'feature_patch')
    """
    instance = get_instance(instance_id, dataset)
    if not instance:
        if plain:
            print(f"Error: Instance '{instance_id}' not found")
        else:
            console.print(f"[red]Instance '{instance_id}' not found[/red]")
        return
    
    if key not in instance:
        if plain:
            print(f"Error: Key '{key}' not found in instance '{instance_id}'")
            available_keys = list(dict(instance).keys())
            print(f"Available keys: {', '.join(available_keys)}")
        else:
            console.print(f"[red]Key '{key}' not found in instance '{instance_id}'[/red]")
            available_keys = list(dict(instance).keys())
            console.print(f"[yellow]Available keys: {', '.join(available_keys)}[/yellow]")
        return
    
    value = instance[key]
    
    if plain:
        # Plain text output
        print(f"\n{'=' * 80}")
        print(f"{key.upper().replace('_', ' ')}")
        print(f"{'=' * 80}")
        
        if isinstance(value, (dict, list)):
            print(json.dumps(value, indent=2, default=str, ensure_ascii=False))
        else:
            print(str(value))
        
        print(f"{'=' * 80}\n")
    else:
        # Rich formatted output
        # Special handling for patch fields - use the nice patch printing format
        if key in ["feature_patch", "test_patch"] and isinstance(value, str):
            print_patch(value, title=f"{key.replace('_', ' ').title()}")
        
        # Handle other string content with syntax highlighting
        elif isinstance(value, str):
            # Try to detect if it's code or markdown
            if len(value) > 100 or '\n' in value:
                # Long text - use panel with syntax highlighting
                syntax = Syntax(
                    value,
                    "markdown",  # Default to markdown for problem statements
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=True
                )
                panel = Panel(
                    syntax,
                    title=f"[bold cyan]{key}[/bold cyan]",
                    border_style="green"
                )
                console.print(panel)
            else:
                # Short text - simple display
                console.print(f"[bold cyan]{key}:[/bold cyan] [green]{value}[/green]")
        
        # Handle dictionaries and lists with JSON formatting
        elif isinstance(value, (dict, list)):
            json_str = json.dumps(value, indent=2, default=str, ensure_ascii=False)
            syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True, word_wrap=True)
            panel = Panel(
                syntax,
                title=f"[bold cyan]{key}[/bold cyan]",
                border_style="green"
            )
            console.print(panel)
        
        # Handle other types (numbers, booleans, etc.)
        else:
            console.print(f"[bold cyan]{key}:[/bold cyan] [green]{value}[/green]")

def _add_to_tree(parent, data, max_items: int = 10):
    """Helper to build tree recursively."""
    if isinstance(data, dict):
        for i, (key, value) in enumerate(data.items()):
            if i >= max_items:
                parent.add(f"[dim]... {len(data) - max_items} more items[/dim]")
                break
            branch = parent.add(f"[cyan]{key}[/cyan]")
            _add_to_tree(branch, value, max_items)
    elif isinstance(data, (list, tuple)):
        for i, item in enumerate(data[:max_items]):
            branch = parent.add(f"[yellow][{i}][/yellow]")
            _add_to_tree(branch, item, max_items)
        if len(data) > max_items:
            parent.add(f"[dim]... {len(data) - max_items} more items[/dim]")
    else:
        text = str(data)[:100] + ("..." if len(str(data)) > 100 else "")
        parent.add(f"[green]{text}[/green]")


def print_multiple_keys(instance_id: str, keys: list[str], dataset=None, separator: bool = True, plain: bool = False):
    """
    Print multiple keys from an instance with optional separation.
    
    Args:
        instance_id: The instance identifier
        keys: List of keys to print
        dataset: Optional dataset to search in
        separator: Whether to add visual separation between outputs
        plain: If True, output plain text without rich formatting
    """
    for i, key in enumerate(keys):
        if i > 0 and separator:
            if plain:
                print("\n" + "=" * 80 + "\n")
            else:
                console.print("\n" + "─" * 80 + "\n")
        try:
            print_instance_key(instance_id, key, dataset, plain=plain)
        except Exception as e:
            if plain:
                print(f"Error printing key '{key}': {str(e)}")
            else:
                console.print(f"[red]Error printing key '{key}': {str(e)}[/red]")


def print_plain_header(benchmark: str, split: str, instance_id: str, keys: list[str]):
    """Print a plain text header suitable for file output."""
    print("=" * 80)
    print("CONFIGURATION")
    print("=" * 80)
    print(f"Benchmark: {benchmark}")
    print(f"Split: {split}")
    print(f"Instance: {instance_id}")
    print(f"Keys: {', '.join(keys)}")
    print("=" * 80)
    print()


def main():
    """
    Main entry point with command-line argument support.
    
    Examples:
        # Print single key
        python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement
        
        # Print multiple keys
        python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch
        
        # Use different benchmark
        python pretty_printing.py --benchmark nocode --instance pytest-dev__pytest-2794 --key problem_statement
        
        # List available instances
        python pretty_printing.py --list-instances
    """
    parser = argparse.ArgumentParser(
        description='Pretty print benchmark instances with rich formatting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print single key
  %(prog)s --instance pytest-dev__pytest-2794 --key problem_statement
  
  # Print multiple keys
  %(prog)s --instance pytest-dev__pytest-2794 --key problem_statement feature_patch
  
  # Use different benchmark (future support)
  %(prog)s --benchmark nocode --instance pytest-dev__pytest-2794 --key problem_statement
  
  # List all instances
  %(prog)s --list-instances
  
  # List instances with limit
  %(prog)s --list-instances --limit 10
        """
    )
    
    parser.add_argument(
        '--benchmark', '-b',
        type=str,
        default='nocode',
        help='Benchmark name (default: nocode). Future: swe-bench, etc.'
    )
    
    parser.add_argument(
        '--split', '-s',
        type=str,
        default='test',
        choices=['test', 'train', 'validation'],
        help='Dataset split (default: test)'
    )
    
    parser.add_argument(
        '--instance', '-i',
        type=str,
        help='Instance ID to print (e.g., pytest-dev__pytest-2794)'
    )
    
    parser.add_argument(
        '--key', '-k',
        type=str,
        nargs='+',
        help='Key(s) to print (e.g., problem_statement feature_patch test_patch)'
    )
    
    parser.add_argument(
        '--list-instances', '-l',
        action='store_true',
        help='List all available instance IDs in the benchmark'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of instances to list (use with --list-instances)'
    )
    
    parser.add_argument(
        '--no-separator',
        action='store_true',
        help='Disable visual separators between multiple keys'
    )
    
    parser.add_argument(
        '--style',
        type=str,
        choices=['json', 'tree', 'table', 'patches'],
        help='Display style for full instance (alternative to --key)'
    )

    parser.add_argument(
        '--dataset-path',
        type=str,
        help='Path to a local dataset file (.jsonl supported). Overrides --benchmark/--split loading.'
    )
    
    parser.add_argument(
        '--plain',
        action='store_true',
        help='Output plain text without rich formatting (suitable for copying to files)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Write output to file instead of stdout'
    )
    
    args = parser.parse_args()
    
    # Redirect output to file if specified
    original_stdout = None
    if args.output:
        # Create directory if it doesn't exist
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                print(f"Error: Could not create directory '{output_dir}': {str(e)}")
                sys.exit(1)
        
        try:
            original_stdout = sys.stdout
            sys.stdout = open(args.output, 'w', encoding='utf-8')
            args.plain = True  # Force plain text when writing to file
        except Exception as e:
            print(f"Error: Could not open file '{args.output}': {str(e)}")
            sys.exit(1)
    
    # Load the specified benchmark dataset
    try:
        dataset = load_benchmark_dataset(args.benchmark, args.split, args.dataset_path)
    except Exception as e:
        if args.plain:
            print(f"Error: Failed to load dataset: {str(e)}")
        else:
            console.print(f"[red]Failed to load dataset: {str(e)}[/red]")
        sys.exit(1)
    
    # Handle list instances
    if args.list_instances:
        if args.plain:
            source_label = args.dataset_path if args.dataset_path else f"{args.benchmark} ({args.split} split)"
            print(f"Available instances in {source_label}:\n")
        else:
            source_label = args.dataset_path if args.dataset_path else f"{args.benchmark} ({args.split} split)"
            console.print(f"[bold cyan]Available instances in {source_label}:[/bold cyan]\n")
        
        instance_ids = [inst["instance_id"] for inst in dataset]
        
        if args.limit:
            instance_ids = instance_ids[:args.limit]
            if args.plain:
                print(f"Showing first {args.limit} of {len(dataset)} instances\n")
            else:
                console.print(f"[yellow]Showing first {args.limit} of {len(dataset)} instances[/yellow]\n")
        
        for idx, inst_id in enumerate(instance_ids, 1):
            if args.plain:
                print(f"{idx:4d}. {inst_id}")
            else:
                console.print(f"{idx:4d}. [green]{inst_id}[/green]")
        
        if args.limit and len(dataset) > args.limit:
            if args.plain:
                print(f"\n... and {len(dataset) - args.limit} more instances")
            else:
                console.print(f"\n[dim]... and {len(dataset) - args.limit} more instances[/dim]")
        
        # Close output file if needed
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        return
    
    # Validate required arguments
    if not args.instance:
        if args.plain:
            print("Error: --instance is required (or use --list-instances)")
        else:
            console.print("[red]Error: --instance is required (or use --list-instances)[/red]")
        parser.print_help()
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        sys.exit(1)
    
    # Handle style-based printing (full instance)
    if args.style:
        if args.plain:
            print("Warning: --plain mode not supported with --style, using rich formatting")
        print_instance(args.instance, style=args.style)
        # Close output file if needed
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        return
    
    # Handle key-based printing
    if not args.key:
        if args.plain:
            print("Error: --key is required (or use --style for full instance)")
        else:
            console.print("[red]Error: --key is required (or use --style for full instance)[/red]")
        parser.print_help()
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        sys.exit(1)
    
    # Print header
    if args.plain:
        print_plain_header(
            args.dataset_path if args.dataset_path else args.benchmark,
            args.split if not args.dataset_path else "local",
            args.instance,
            args.key
        )
    else:
        dataset_label = args.dataset_path if args.dataset_path else args.benchmark
        split_label = args.split if not args.dataset_path else "local"
        console.print(Panel(
            f"[bold]Benchmark:[/bold] {dataset_label}\n"
            f"[bold]Split:[/bold] {split_label}\n"
            f"[bold]Instance:[/bold] {args.instance}\n"
            f"[bold]Keys:[/bold] {', '.join(args.key)}",
            title="[cyan]Configuration[/cyan]",
            border_style="cyan"
        ))
        console.print()
    
    # Print the requested keys
    print_multiple_keys(
        args.instance,
        args.key,
        dataset=dataset,
        separator=not args.no_separator,
        plain=args.plain
    )
    
    # Close output file if needed
    if original_stdout:
        sys.stdout.close()
        sys.stdout = original_stdout
        print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()

# Usage examples (for reference):
# instance_id = 'pytest-dev__pytest-2794'
# print_instance(instance_id, style="table")   # Quick overview (shows patch line counts)
# print_instance(instance_id, style="tree")    # Hierarchical structure
# print_instance(instance_id, style="json")    # Full details with syntax highlighting
# print_instance(instance_id, style="patches") # View patches with diff highlighting
# print_instance(instance_id, style="table", show_patches=True)  # Table + patches

