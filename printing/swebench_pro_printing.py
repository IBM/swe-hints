#!/usr/bin/env python3
"""
Pretty-print instances from SWE-bench Pro.

Examples:
  # List instance ids
  python swebench_pro_printing.py --list-instances --limit 10

  # Print one key
  python swebench_pro_printing.py --instance sympy__sympy-20590 --key problem_statement

  # Print multiple keys
  python swebench_pro_printing.py --instance sympy__sympy-20590 --key instance_id problem_statement patch test_patch

  # Plain text output
  python swebench_pro_printing.py --instance sympy__sympy-20590 --key problem_statement --plain

  # Full instance views
  python swebench_pro_printing.py --instance sympy__sympy-20590 --style table
  python swebench_pro_printing.py --instance sympy__sympy-20590 --style json
"""

from typing import Dict as DictType
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

console = Console()

_dataset_cache = {}


def load_benchmark_dataset(benchmark: str = "swe-bench-pro", split: str = "test"):
    """
    Load a benchmark dataset with caching.

    Supported benchmark values:
      - swe-bench-pro
      - swebench-pro
      - swe_bench_pro
    """
    cache_key = f"{benchmark}_{split}"

    if cache_key in _dataset_cache:
        return _dataset_cache[cache_key]

    try:
        normalized = benchmark.lower()
        if normalized in {"swe-bench-pro", "swebench-pro", "swe_bench_pro"}:
            dataset = load_dataset("ScaleAI/SWE-bench_Pro", split=split)
        else:
            raise ValueError(f"Unknown benchmark: {benchmark}")

        _dataset_cache[cache_key] = dataset
        return dataset
    except Exception as e:
        console.print(f"[red]Error loading benchmark '{benchmark}': {str(e)}[/red]")
        sys.exit(1)


swebench_pro = load_benchmark_dataset("swe-bench-pro", "test")


def get_instance(instance_id: str, dataset=None) -> DictType | None:
    """Get an instance from the dataset."""
    if dataset is None:
        dataset = swebench_pro

    for instance in dataset:
        if instance["instance_id"] == instance_id:
            return instance
    return None


def print_patch(patch_content: str, title: str = "Patch"):
    """Display a patch with syntax highlighting for diff format."""
    if not patch_content:
        console.print(f"[yellow]{title}: Empty[/yellow]")
        return

    syntax = Syntax(
        patch_content,
        "diff",
        theme="monokai",
        line_numbers=True,
        word_wrap=False,
    )
    panel = Panel(
        syntax,
        title=f"[bold cyan]{title}[/bold cyan]",
        border_style="blue",
    )
    console.print(panel)


def parse_interface_content(interface_text: str) -> list[dict]:
    """
    Parse interface text into structured components.
    
    Handles two formats:
    1. Format with Type:/Name:/Path: fields
    2. Format with bullet points (- Type:/- Function:) and Package: field
    """
    interfaces = []
    current_interface = {}
    current_key = None
    current_value = []
    preamble_lines = []
    in_preamble = True
    
    lines = interface_text.split('\n')
    
    for line in lines:
        stripped = line.strip()
        
        # Check if this line starts a new interface (bullet point format)
        if stripped.startswith('- Type:') or stripped.startswith('- Function:'):
            in_preamble = False
            # Save previous interface if exists
            if current_interface:
                if current_key and current_value:
                    current_interface[current_key] = ' '.join(current_value).strip()
                interfaces.append(current_interface)
            
            # Start new interface
            current_interface = {}
            current_key = 'type'
            if stripped.startswith('- Type:'):
                current_value = [stripped[7:].strip()]  # Remove "- Type:"
            else:  # - Function:
                current_value = [stripped[11:].strip()]  # Remove "- Function:"
            continue
        
        # Check if this is a key line (starts with known keys followed by colon)
        is_key_line = False
        new_key = None
        new_value = None
        
        if stripped.startswith('Type:') and not stripped.startswith('- Type:'):
            is_key_line = True
            new_key = 'type'
            new_value = stripped[5:].strip()
            in_preamble = False
            
            # If we encounter Type: and already have an interface, save it
            if current_interface:
                if current_key and current_value:
                    current_interface[current_key] = ' '.join(current_value).strip()
                interfaces.append(current_interface)
                current_interface = {}
                current_key = None
                current_value = []
                
        elif stripped.startswith('Name:'):
            is_key_line = True
            new_key = 'name'
            new_value = stripped[5:].strip()
            in_preamble = False
        elif stripped.startswith('Path:'):
            is_key_line = True
            new_key = 'path'
            new_value = stripped[5:].strip()
            in_preamble = False
        elif stripped.startswith('Package:'):
            is_key_line = True
            new_key = 'package'
            new_value = stripped[8:].strip()
            in_preamble = False
        elif stripped.startswith('Input:') or stripped.startswith('Inputs:'):
            is_key_line = True
            new_key = 'input'
            if stripped.startswith('Inputs:'):
                new_value = stripped[7:].strip()
            else:
                new_value = stripped[6:].strip()
            in_preamble = False
        elif stripped.startswith('Output:') or stripped.startswith('Outputs:'):
            is_key_line = True
            new_key = 'output'
            if stripped.startswith('Outputs:'):
                new_value = stripped[8:].strip()
            else:
                new_value = stripped[7:].strip()
            in_preamble = False
        elif stripped.startswith('Description:'):
            is_key_line = True
            new_key = 'description'
            new_value = stripped[12:].strip()
            in_preamble = False
        
        if is_key_line:
            # Save previous key-value if exists
            if current_key and current_value:
                current_interface[current_key] = ' '.join(current_value).strip()
            
            # Start new key-value
            current_key = new_key
            current_value = [new_value] if new_value else []
        elif stripped:
            # Continuation line (non-empty, non-key line)
            if in_preamble:
                preamble_lines.append(stripped)
            elif current_key:
                current_value.append(stripped)
        # Empty lines are ignored
    
    # Save the last key-value and interface
    if current_key and current_value:
        current_interface[current_key] = ' '.join(current_value).strip()
    if current_interface:
        interfaces.append(current_interface)
    
    # Add preamble as metadata if it exists
    if preamble_lines and interfaces:
        preamble_text = ' '.join(preamble_lines).strip()
        # Store preamble in first interface or as separate entry
        for interface in interfaces:
            interface['_preamble'] = preamble_text
            break  # Only add to first one
    
    return interfaces


def print_interface(interface_text: str, title: str = "Interface", plain: bool = False):
    """Display interface with structured formatting."""
    # Store original text for display at the end
    original_text = interface_text
    
    if not interface_text or interface_text.strip() == "No new interfaces are introduced":
        if plain:
            print(f"\n{'=' * 80}")
            print(f"{title}")
            print(f"{'=' * 80}")
            print("No new interfaces are introduced")
            print(f"{'=' * 80}\n")
        else:
            console.print(f"[yellow]{title}: No new interfaces are introduced[/yellow]")
        return
    
    # Check if the interface text is JSON-encoded (starts and ends with quotes)
    if interface_text.startswith('"') and interface_text.endswith('"'):
        try:
            interface_text = json.loads(interface_text)
        except json.JSONDecodeError:
            pass  # If it fails, use the original text
    
    interfaces = parse_interface_content(interface_text)
    
    if plain:
        print(f"\n{'=' * 80}")
        print(f"{title.upper()}")
        print(f"{'=' * 80}\n")
        
        # Print preamble if exists
        if interfaces and '_preamble' in interfaces[0]:
            print(f"Preamble: {interfaces[0]['_preamble']}")
            print()
        
        for i, interface in enumerate(interfaces, 1):
            if i > 1:
                print("\n" + "-" * 80 + "\n")
            print(f"Interface #{i}:")
            print()
            for key in ['type', 'name', 'path', 'package', 'input', 'output', 'description']:
                if key in interface and not key.startswith('_'):
                    value = interface[key]
                    if key in ['path', 'package'] and ',' in value:
                        # Format multiple paths/packages
                        items = [p.strip() for p in value.split(',')]
                        print(f"  {key.upper()}:")
                        for item in items:
                            print(f"    - {item}")
                    else:
                        print(f"  {key.upper()}: {value}")
                    print()
        
        # Print raw original text
        print(f"\n{'=' * 80}")
        print("RAW ORIGINAL TEXT")
        print(f"{'=' * 80}")
        print(original_text)
        print(f"{'=' * 80}\n")
    else:
        # Rich formatted output
        # Print preamble if exists
        if interfaces and '_preamble' in interfaces[0]:
            preamble_panel = Panel(
                f"[italic]{interfaces[0]['_preamble']}[/italic]",
                title="[bold dim]Context[/bold dim]",
                border_style="dim",
                padding=(1, 2)
            )
            console.print(preamble_panel)
            console.print()
        
        for i, interface in enumerate(interfaces, 1):
            content_lines = []
            content_lines.append(f"[bold yellow]Interface #{i}[/bold yellow]\n")
            
            if 'type' in interface:
                content_lines.append(f"[bold cyan]Type:[/bold cyan] [green]{interface['type']}[/green]\n")
            if 'name' in interface:
                content_lines.append(f"[bold cyan]Name:[/bold cyan] [green]{interface['name']}[/green]\n")
            if 'path' in interface:
                # Split paths by comma for better readability
                paths = [p.strip() for p in interface['path'].split(',')]
                if len(paths) > 1:
                    content_lines.append(f"[bold cyan]Paths:[/bold cyan]")
                    for path in paths:
                        content_lines.append(f"  • [green]{path}[/green]")
                    content_lines.append("")
                else:
                    content_lines.append(f"[bold cyan]Path:[/bold cyan] [green]{interface['path']}[/green]\n")
            if 'package' in interface:
                content_lines.append(f"[bold cyan]Package:[/bold cyan] [green]{interface['package']}[/green]\n")
            if 'input' in interface:
                content_lines.append(f"[bold cyan]Input:[/bold cyan] [yellow]{interface['input']}[/yellow]\n")
            if 'output' in interface:
                content_lines.append(f"[bold cyan]Output:[/bold cyan] [yellow]{interface['output']}[/yellow]\n")
            if 'description' in interface:
                content_lines.append(f"[bold cyan]Description:[/bold cyan]\n  [white]{interface['description']}[/white]")
            
            panel = Panel(
                "\n".join(content_lines),
                title=f"[bold magenta]{title}[/bold magenta]" if i == 1 else "",
                border_style="magenta",
                padding=(1, 2)
            )
            console.print(panel)
            if i < len(interfaces):
                console.print()  # Add spacing between interfaces
        
        # Print raw original text
        console.print("\n")
        syntax = Syntax(
            original_text,
            "text",
            theme="monokai",
            line_numbers=False,
            word_wrap=True
        )
        panel = Panel(
            syntax,
            title="[bold dim]Raw Original Text[/bold dim]",
            border_style="dim",
            padding=(1, 2)
        )
        console.print(panel)


def print_requirements(requirements_text: str, title: str = "Requirements", plain: bool = False):
    """Display requirements with better formatting."""
    # Store original text for display at the end
    original_text = requirements_text
    
    if not requirements_text:
        if plain:
            print(f"\n{'=' * 80}")
            print(f"{title}")
            print(f"{'=' * 80}")
            print("No requirements specified")
            print(f"{'=' * 80}\n")
        else:
            console.print(f"[yellow]{title}: No requirements specified[/yellow]")
        return
    
    # Check if the requirements text is JSON-encoded (starts and ends with quotes)
    if requirements_text.startswith('"') and requirements_text.endswith('"'):
        try:
            requirements_text = json.loads(requirements_text)
        except json.JSONDecodeError:
            pass  # If it fails, use the original text
    
    if plain:
        print(f"\n{'=' * 80}")
        print(f"{title.upper()}")
        print(f"{'=' * 80}")
        print(requirements_text)
        print(f"\n{'=' * 80}")
        print("RAW ORIGINAL TEXT")
        print(f"{'=' * 80}")
        print(original_text)
        print(f"{'=' * 80}\n")
    else:
        # Try to parse as requirements.txt format
        lines = requirements_text.strip().split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                formatted_lines.append(f"[dim]{line}[/dim]")
            elif '==' in line or '>=' in line or '<=' in line or '~=' in line:
                # Package with version
                parts = line.split('==') if '==' in line else line.split('>=') if '>=' in line else line.split('<=') if '<=' in line else line.split('~=')
                if len(parts) == 2:
                    formatted_lines.append(f"[cyan]{parts[0]}[/cyan][yellow]=={parts[1]}[/yellow]")
                else:
                    formatted_lines.append(f"[cyan]{line}[/cyan]")
            else:
                formatted_lines.append(f"[cyan]{line}[/cyan]")
        
        panel = Panel(
            "\n".join(formatted_lines),
            title=f"[bold cyan]{title}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(panel)
        
        # Print raw original text
        console.print("\n")
        syntax = Syntax(
            original_text,
            "text",
            theme="monokai",
            line_numbers=False,
            word_wrap=True
        )
        panel = Panel(
            syntax,
            title="[bold dim]Raw Original Text[/bold dim]",
            border_style="dim",
            padding=(1, 2)
        )
        console.print(panel)


def print_instance(instance_id: str, style: str = "json", show_patches: bool = False, dataset=None):
    """
    Print instance with rich formatting.

    style:
      - json
      - tree
      - table
      - patches
    """
    instance = get_instance(instance_id, dataset)
    if not instance:
        console.print(f"[red]Instance '{instance_id}' not found[/red]")
        return

    patch_like_keys = [k for k in ["patch", "test_patch", "gold_patch"] if k in instance]

    if style == "json":
        json_str = json.dumps(dict(instance), indent=2, default=str, ensure_ascii=False)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True, word_wrap=True)
        panel = Panel(syntax, title=f"[bold cyan]{instance_id}[/bold cyan]", border_style="blue")
        console.print(panel)

    elif style == "tree":
        tree = Tree(f"[bold magenta]{instance_id}[/bold magenta]")
        _add_to_tree(tree, dict(instance))
        console.print(tree)

    elif style == "table":
        table = Table(title=f"Instance: {instance_id}", show_header=True, header_style="bold cyan")
        table.add_column("Key", style="cyan", width=30)
        table.add_column("Type", style="yellow", width=15)
        table.add_column("Preview", style="green")

        for key, value in dict(instance).items():
            value_type = type(value).__name__

            if key in patch_like_keys and isinstance(value, str):
                line_count = value.count("\n") + (1 if value else 0)
                preview = f"Patch with {line_count} lines (use style='patches' to view)"
            elif isinstance(value, (list, dict)):
                preview = f"Size: {len(value)}"
            else:
                text = str(value)
                preview = text[:80] + ("..." if len(text) > 80 else "")

            table.add_row(key, value_type, preview)

        console.print(table)

    elif style == "patches":
        console.print(f"\n[bold magenta]Instance: {instance_id}[/bold magenta]\n")
        for key in patch_like_keys:
            if instance.get(key):
                print_patch(instance[key], key.replace("_", " ").title())
                console.print()

    if show_patches and style != "patches":
        console.print("\n" + "=" * 80 + "\n")
        for key in patch_like_keys:
            if instance.get(key):
                print_patch(instance[key], key.replace("_", " ").title())
                console.print()


def print_instance_key(instance_id: str, key: str, dataset=None, plain: bool = False):
    """Print one key from an instance."""
    instance = get_instance(instance_id, dataset)
    if not instance:
        if plain:
            print(f"Error: Instance '{instance_id}' not found")
        else:
            console.print(f"[red]Instance '{instance_id}' not found[/red]")
        return

    if key not in instance:
        available_keys = list(dict(instance).keys())
        if plain:
            print(f"Error: Key '{key}' not found in instance '{instance_id}'")
            print(f"Available keys: {', '.join(available_keys)}")
        else:
            console.print(f"[red]Key '{key}' not found in instance '{instance_id}'[/red]")
            console.print(f"[yellow]Available keys: {', '.join(available_keys)}[/yellow]")
        return

    value = instance[key]

    # Special handling for interface key
    if key == "interface" and isinstance(value, str):
        print_interface(value, title="Interface", plain=plain)
        return
    
    # Special handling for requirements key
    if key == "requirements" and isinstance(value, str):
        print_requirements(value, title="Requirements", plain=plain)
        return

    if plain:
        print(f"\n{'=' * 80}")
        print(f"{key.upper().replace('_', ' ')}")
        print(f"{'=' * 80}")
        if isinstance(value, (dict, list)):
            print(json.dumps(value, indent=2, default=str, ensure_ascii=False))
        else:
            print(str(value))
        print(f"{'=' * 80}\n")
        return

    if key in {"patch", "test_patch", "gold_patch"} and isinstance(value, str):
        print_patch(value, title=key.replace("_", " ").title())
    elif isinstance(value, str):
        if len(value) > 100 or "\n" in value:
            syntax = Syntax(
                value,
                "markdown",
                theme="monokai",
                line_numbers=False,
                word_wrap=True,
            )
            panel = Panel(
                syntax,
                title=f"[bold cyan]{key}[/bold cyan]",
                border_style="green",
            )
            console.print(panel)
        else:
            console.print(f"[bold cyan]{key}:[/bold cyan] [green]{value}[/green]")
    elif isinstance(value, (dict, list)):
        json_str = json.dumps(value, indent=2, default=str, ensure_ascii=False)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True, word_wrap=True)
        panel = Panel(
            syntax,
            title=f"[bold cyan]{key}[/bold cyan]",
            border_style="green",
        )
        console.print(panel)
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
        text = str(data)
        text = text[:100] + ("..." if len(text) > 100 else "")
        parent.add(f"[green]{text}[/green]")


def print_multiple_keys(instance_id: str, keys: list[str], dataset=None, separator: bool = True, plain: bool = False):
    """Print multiple keys from an instance."""
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
    parser = argparse.ArgumentParser(
        description="Pretty print SWE-bench Pro instances with rich formatting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list-instances --limit 10
  %(prog)s --instance sympy__sympy-20590 --key problem_statement
  %(prog)s --instance sympy__sympy-20590 --key instance_id problem_statement patch test_patch
  %(prog)s --instance sympy__sympy-20590 --style table
  %(prog)s --instance sympy__sympy-20590 --style patches
        """,
    )

    parser.add_argument(
        "--benchmark", "-b",
        type=str,
        default="swe-bench-pro",
        help="Benchmark name (default: swe-bench-pro)",
    )
    parser.add_argument(
        "--split", "-s",
        type=str,
        default="test",
        help="Dataset split (default: test)",
    )
    parser.add_argument(
        "--instance", "-i",
        type=str,
        help="Instance ID to print",
    )
    parser.add_argument(
        "--key", "-k",
        type=str,
        nargs="+",
        help="Key(s) to print",
    )
    parser.add_argument(
        "--list-instances", "-l",
        action="store_true",
        help="List all available instance IDs in the benchmark",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of instances to list",
    )
    parser.add_argument(
        "--no-separator",
        action="store_true",
        help="Disable visual separators between multiple keys",
    )
    parser.add_argument(
        "--style",
        type=str,
        choices=["json", "tree", "table", "patches"],
        help="Display style for full instance",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Output plain text without rich formatting",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Write output to file instead of stdout",
    )

    args = parser.parse_args()

    original_stdout = None
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                print(f"Error: Could not create directory '{output_dir}': {str(e)}")
                sys.exit(1)

        try:
            original_stdout = sys.stdout
            sys.stdout = open(args.output, "w", encoding="utf-8")
            args.plain = True
        except Exception as e:
            print(f"Error: Could not open file '{args.output}': {str(e)}")
            sys.exit(1)

    try:
        dataset = load_benchmark_dataset(args.benchmark, args.split)
    except Exception as e:
        if args.plain:
            print(f"Error: Failed to load benchmark: {str(e)}")
        else:
            console.print(f"[red]Failed to load benchmark: {str(e)}[/red]")
        sys.exit(1)

    if args.list_instances:
        if args.plain:
            print(f"Available instances in {args.benchmark} ({args.split} split):\n")
        else:
            console.print(f"[bold cyan]Available instances in {args.benchmark} ({args.split} split):[/bold cyan]\n")

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

        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        return

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

    if args.style:
        print_instance(args.instance, style=args.style, dataset=dataset)
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
        return

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

    if args.plain:
        print_plain_header(args.benchmark, args.split, args.instance, args.key)
    else:
        console.print(Panel(
            f"[bold]Benchmark:[/bold] {args.benchmark}\n"
            f"[bold]Split:[/bold] {args.split}\n"
            f"[bold]Instance:[/bold] {args.instance}\n"
            f"[bold]Keys:[/bold] {', '.join(args.key)}",
            title="[cyan]Configuration[/cyan]",
            border_style="cyan"
        ))
        console.print()

    print_multiple_keys(
        args.instance,
        args.key,
        dataset=dataset,
        separator=not args.no_separator,
        plain=args.plain,
    )

    if original_stdout:
        sys.stdout.close()
        sys.stdout = original_stdout
        print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()
