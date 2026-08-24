#!/usr/bin/env python3
"""
Analyze augmentation data structure in NoCode-bench dataset.

This script examines the 'augmentations' field in the dataset to identify:
- All unique keys present in augmentation data items
- Frequency of each key across all instances
- Examples of different key combinations
- Statistics about the data structure
"""

from datasets import load_dataset
from collections import defaultdict, Counter
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
import json

console = Console()


def analyze_augmentation_keys(dataset):
    """
    Analyze the keys present in augmentation data across all instances.
    
    Returns:
        dict: Analysis results including key frequencies, combinations, and examples
    """
    all_keys = set()
    key_frequency = Counter()
    key_combinations = defaultdict(list)
    instances_with_augmentations = 0
    total_augmentation_items = 0
    
    # Track examples for each key combination
    combination_examples = {}
    
    # Track type field values
    type_values = Counter()
    type_examples = {}
    
    for instance in dataset:
        instance_id = instance.get("instance_id", "unknown")
        augmentations = instance.get("augmentations", {})
        
        if not augmentations:
            continue
            
        data = augmentations.get("data", [])
        
        if not data:
            continue
            
        instances_with_augmentations += 1
        
        for item in data:
            if not isinstance(item, dict):
                continue
                
            total_augmentation_items += 1
            item_keys = tuple(sorted(item.keys()))
            
            # Track all unique keys
            all_keys.update(item.keys())
            
            # Count frequency of each key
            for key in item.keys():
                key_frequency[key] += 1
            
            # Track key combinations
            key_combinations[item_keys].append(instance_id)
            
            # Store example for this combination (first occurrence)
            if item_keys not in combination_examples:
                combination_examples[item_keys] = {
                    'instance_id': instance_id,
                    'data': item
                }
            
            # Track type field values
            if 'type' in item:
                type_value = item['type']
                type_values[type_value] += 1
                
                # Store example for this type (first occurrence)
                if type_value not in type_examples:
                    type_examples[type_value] = {
                        'instance_id': instance_id,
                        'data': item
                    }
    
    return {
        'all_keys': sorted(all_keys),
        'key_frequency': key_frequency,
        'key_combinations': dict(key_combinations),
        'combination_examples': combination_examples,
        'type_values': type_values,
        'type_examples': type_examples,
        'instances_with_augmentations': instances_with_augmentations,
        'total_augmentation_items': total_augmentation_items,
        'total_instances': len(dataset)
    }


def print_type_analysis(analysis):
    """Print analysis of 'type' field values."""
    if 'type_values' not in analysis or not analysis['type_values']:
        console.print("[yellow]No 'type' field found in augmentation data[/yellow]\n")
        return
    
    console.print(Panel(
        f"[bold]Unique Type Values:[/bold] {len(analysis['type_values'])}\n"
        f"[bold]Total Items with Type:[/bold] {sum(analysis['type_values'].values())}",
        title="[cyan]Type Field Analysis[/cyan]",
        border_style="cyan"
    ))
    console.print()
    
    # Type frequency table
    table = Table(title="Type Values Distribution", show_header=True, header_style="bold magenta")
    table.add_column("Type Value", style="cyan", width=40)
    table.add_column("Count", style="yellow", justify="right")
    table.add_column("Percentage", style="green", justify="right")
    
    total_with_type = sum(analysis['type_values'].values())
    for type_value, count in analysis['type_values'].most_common():
        percentage = (count / total_with_type * 100) if total_with_type > 0 else 0
        table.add_row(str(type_value), str(count), f"{percentage:.1f}%")
    
    console.print(table)
    console.print()
    
    # Show examples for each type
    console.print("[bold cyan]Examples for Each Type:[/bold cyan]\n")
    for idx, (type_value, example_info) in enumerate(sorted(analysis['type_examples'].items()), 1):
        console.print(f"[bold yellow]{idx}. Type: {type_value}[/bold yellow]")
        console.print(f"   Instance: [green]{example_info['instance_id']}[/green]")
        console.print(f"   Example data:")
        
        example_json = json.dumps(example_info['data'], indent=4, default=str, ensure_ascii=False)
        for line in example_json.split('\n'):
            console.print(f"     [dim]{line}[/dim]")
        console.print()


def print_analysis_summary(analysis):
    """Print a summary of the analysis results."""
    
    # Summary statistics
    console.print(Panel(
        f"[bold]Total Instances:[/bold] {analysis['total_instances']}\n"
        f"[bold]Instances with Augmentations:[/bold] {analysis['instances_with_augmentations']}\n"
        f"[bold]Total Augmentation Items:[/bold] {analysis['total_augmentation_items']}\n"
        f"[bold]Unique Keys Found:[/bold] {len(analysis['all_keys'])}",
        title="[cyan]Analysis Summary[/cyan]",
        border_style="cyan"
    ))
    console.print()
    
    # All unique keys
    console.print("[bold cyan]All Unique Keys in Augmentation Data:[/bold cyan]")
    for key in analysis['all_keys']:
        freq = analysis['key_frequency'][key]
        percentage = (freq / analysis['total_augmentation_items'] * 100) if analysis['total_augmentation_items'] > 0 else 0
        console.print(f"  • [green]{key}[/green]: {freq} occurrences ({percentage:.1f}%)")
    console.print()
    
    # Key frequency table
    table = Table(title="Key Frequency Distribution", show_header=True, header_style="bold magenta")
    table.add_column("Key", style="cyan", width=30)
    table.add_column("Count", style="yellow", justify="right")
    table.add_column("Percentage", style="green", justify="right")
    
    for key, count in analysis['key_frequency'].most_common():
        percentage = (count / analysis['total_augmentation_items'] * 100) if analysis['total_augmentation_items'] > 0 else 0
        table.add_row(key, str(count), f"{percentage:.1f}%")
    
    console.print(table)
    console.print()
    
    # Key combinations
    console.print(f"[bold cyan]Key Combinations Found:[/bold cyan] {len(analysis['key_combinations'])} unique combinations\n")
    
    for idx, (keys, instance_ids) in enumerate(sorted(analysis['key_combinations'].items(), key=lambda x: len(x[1]), reverse=True), 1):
        console.print(f"[bold yellow]Combination {idx}:[/bold yellow] ({len(instance_ids)} instances)")
        console.print(f"  Keys: [green]{', '.join(keys)}[/green]")
        console.print(f"  Example instances: {', '.join(instance_ids[:3])}")
        if len(instance_ids) > 3:
            console.print(f"  ... and {len(instance_ids) - 3} more")
        
        # Show example data
        if keys in analysis['combination_examples']:
            example = analysis['combination_examples'][keys]
            console.print(f"  [dim]Example from {example['instance_id']}:[/dim]")
            example_json = json.dumps(example['data'], indent=4, default=str, ensure_ascii=False)
            # Indent the JSON
            for line in example_json.split('\n'):
                console.print(f"    [dim]{line}[/dim]")
        console.print()


def print_detailed_examples(analysis, limit=5):
    """Print detailed examples of augmentation data."""
    console.print(Panel(
        f"Showing up to {limit} examples of augmentation data structures",
        title="[cyan]Detailed Examples[/cyan]",
        border_style="cyan"
    ))
    console.print()
    
    shown = 0
    for keys, example_info in list(analysis['combination_examples'].items())[:limit]:
        shown += 1
        console.print(f"[bold yellow]Example {shown}:[/bold yellow]")
        console.print(f"  Instance: [green]{example_info['instance_id']}[/green]")
        console.print(f"  Keys: [cyan]{', '.join(keys)}[/cyan]")
        console.print(f"  Data:")
        
        example_json = json.dumps(example_info['data'], indent=4, default=str, ensure_ascii=False)
        for line in example_json.split('\n'):
            console.print(f"    {line}")
        console.print()


def export_analysis_to_file(analysis, filename="augmentation_analysis.json"):
    """Export analysis results to a JSON file."""
    # Convert Counter to dict for JSON serialization
    export_data = {
        'all_keys': analysis['all_keys'],
        'key_frequency': dict(analysis['key_frequency']),
        'key_combinations': {
            str(k): v for k, v in analysis['key_combinations'].items()
        },
        'combination_examples': {
            str(k): v for k, v in analysis['combination_examples'].items()
        },
        'type_values': dict(analysis.get('type_values', {})),
        'type_examples': {
            str(k): v for k, v in analysis.get('type_examples', {}).items()
        },
        'statistics': {
            'total_instances': analysis['total_instances'],
            'instances_with_augmentations': analysis['instances_with_augmentations'],
            'total_augmentation_items': analysis['total_augmentation_items'],
            'unique_keys': len(analysis['all_keys']),
            'unique_combinations': len(analysis['key_combinations']),
            'unique_type_values': len(analysis.get('type_values', {}))
        }
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    console.print(f"[green]✓[/green] Analysis exported to: [cyan]{filename}[/cyan]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Analyze augmentation data structure in NoCode-bench dataset',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--benchmark', '-b',
        type=str,
        default='nocode-verified',
        help='Benchmark name (default: nocode-verified)'
    )
    
    parser.add_argument(
        '--split', '-s',
        type=str,
        default='test',
        choices=['test', 'train', 'validation'],
        help='Dataset split (default: test)'
    )
    
    parser.add_argument(
        '--examples', '-e',
        type=int,
        default=5,
        help='Number of detailed examples to show (default: 5)'
    )
    
    parser.add_argument(
        '--export', '-o',
        type=str,
        help='Export analysis to JSON file'
    )
    
    parser.add_argument(
        '--instance', '-i',
        type=str,
        help='Analyze specific instance only'
    )
    
    args = parser.parse_args()
    
    # Load dataset
    console.print(f"[cyan]Loading {args.benchmark} dataset ({args.split} split)...[/cyan]")
    
    if args.benchmark.lower() == 'nocode-verified':
        dataset = load_dataset('NoCode-bench/NoCode-bench_Verified', split=args.split)
    elif args.benchmark.lower() == 'nocode-full':
        dataset = load_dataset('NoCode-bench/NoCode-bench_Full', split=args.split)
    else:
        console.print(f"[red]Unknown benchmark: {args.benchmark}[/red]")
        console.print(f"[yellow]Available benchmarks: nocode-verified, nocode-full[/yellow]")
        return
    
    console.print(f"[green]✓[/green] Loaded {len(dataset)} instances\n")
    
    # Filter to specific instance if requested
    if args.instance:
        dataset = [inst for inst in dataset if inst.get('instance_id') == args.instance]
        if not dataset:
            console.print(f"[red]Instance '{args.instance}' not found[/red]")
            return
        console.print(f"[yellow]Analyzing single instance: {args.instance}[/yellow]\n")
    
    # Analyze
    console.print("[cyan]Analyzing augmentation data...[/cyan]\n")
    analysis = analyze_augmentation_keys(dataset)
    
    # Print results
    print_analysis_summary(analysis)
    
    # Print type analysis
    print_type_analysis(analysis)
    
    if args.examples > 0:
        print_detailed_examples(analysis, limit=args.examples)
    
    # Export if requested
    if args.export:
        export_analysis_to_file(analysis, args.export)


if __name__ == "__main__":
    main()

# Made with Bob
