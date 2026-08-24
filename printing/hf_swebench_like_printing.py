#!/usr/bin/env python3
"""
Generic printer for SWE-bench-like Hugging Face datasets.

Examples:
  python hf_swebench_like_printing.py --dataset ScaleAI/SWE-bench_Pro --list-keys
  python hf_swebench_like_printing.py --dataset ScaleAI/SWE-bench_Pro --list-instances --limit 10
  python hf_swebench_like_printing.py --dataset ScaleAI/SWE-bench_Pro -i sympy__sympy-20590 --show-patches
  python hf_swebench_like_printing.py --dataset ScaleAI/SWE-bench_Pro -i sympy__sympy-20590 -k problem_statement gold_patch test_patch
  python hf_swebench_like_printing.py --dataset ScaleAI/SWE-bench_Pro -i sympy__sympy-20590 -k problem_statement gold_patch --plain
  python hf_swebench_like_printing.py --dataset-path ../SWE-bench_Pro-os/results/swebench_pro_augmented_comm-v3-enhanced-fb.jsonl --list-keys
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from datasets import load_dataset
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

DEFAULT_DATASET = "ScaleAI/SWE-bench_Pro"
DEFAULT_SPLIT = "test"
DEFAULT_PATCH_KEYS = ["gold_patch", "patch", "test_patch", "feature_patch"]

console = Console()
_dataset_cache: dict[str, Any] = {}


def load_local_jsonl_dataset(file_path: str) -> list[dict[str, Any]]:
    resolved_path = Path(file_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = Path.cwd() / resolved_path

    if not resolved_path.exists():
        raise FileNotFoundError(f"Local dataset file not found: {resolved_path}")

    dataset: list[dict[str, Any]] = []
    with resolved_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} in '{resolved_path}': {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected JSON object on line {line_number} in '{resolved_path}', "
                    f"got {type(record).__name__}"
                )
            dataset.append(record)
    return dataset


def load_benchmark_dataset(dataset_name: str, split: str, dataset_path: str | None = None):
    cache_key = dataset_path if dataset_path else f"{dataset_name}:{split}"
    if cache_key in _dataset_cache:
        return _dataset_cache[cache_key]

    if dataset_path:
        dataset = load_local_jsonl_dataset(dataset_path)
    else:
        dataset = load_dataset(dataset_name, split=split)

    _dataset_cache[cache_key] = dataset
    return dataset


def get_instance(instance_id: str, dataset) -> dict[str, Any] | None:
    for item in dataset:
        record = dict(item)
        if record.get("instance_id") == instance_id:
            return record
    return None


def format_interface(interface_str: str) -> str:
    if not interface_str:
        return ""

    try:
        if interface_str.startswith('"') and interface_str.endswith('"'):
            interface_str = json.loads(interface_str)
    except (json.JSONDecodeError, ValueError):
        pass

    if isinstance(interface_str, str):
        if interface_str.startswith('"') and interface_str.endswith('"'):
            interface_str = interface_str[1:-1]

        formatted = interface_str.replace("\\n", "\n")
        formatted = formatted.replace("\\t", "\t")
        formatted = formatted.replace('\\"', '"')
        formatted = formatted.replace("\\\\", "\\")
        return formatted.strip()

    return str(interface_str).strip()


def print_patch(title: str, patch_content: str, plain: bool) -> None:
    if plain:
        print("=" * 100)
        print(title)
        print("=" * 100)
        print(patch_content if patch_content else "<empty>")
        print()
        return

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
    console.print(Panel(syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="blue"))


def print_value(title: str, value: Any, plain: bool) -> None:
    if plain:
        print("=" * 100)
        print(title)
        print("=" * 100)
        if isinstance(value, (dict, list)):
            print(json.dumps(value, indent=2, ensure_ascii=False))
        else:
            print(value)
        print()
        return

    if isinstance(value, str) and ("\n" in value or len(value) > 120):
        syntax = Syntax(value, "markdown", theme="monokai", line_numbers=False, word_wrap=True)
        console.print(Panel(syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="green"))
    elif isinstance(value, (dict, list)):
        syntax = Syntax(
            json.dumps(value, indent=2, ensure_ascii=False),
            "json",
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        console.print(Panel(syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="green"))
    else:
        console.print(f"[bold cyan]{title}:[/bold cyan] [green]{value}[/green]")


def print_keys(keys: list[str], plain: bool) -> None:
    if plain:
        print("Available keys:")
        for key in keys:
            print(f"- {key}")
        return

    table = Table(title="Available Keys", show_header=True, header_style="bold cyan")
    table.add_column("#", style="yellow", width=6)
    table.add_column("Key", style="green")
    for idx, key in enumerate(keys, 1):
        table.add_row(str(idx), key)
    console.print(table)


def print_header(args: argparse.Namespace, keys: list[str] | None = None) -> None:
    source = args.dataset_path if args.dataset_path else args.dataset
    split = "local" if args.dataset_path else args.split

    if args.plain:
        print("=" * 100)
        print("CONFIGURATION")
        print("=" * 100)
        print(f"Dataset: {source}")
        print(f"Split: {split}")
        if args.instance:
            print(f"Instance: {args.instance}")
        if keys:
            print(f"Keys: {', '.join(keys)}")
        print("=" * 100)
        print()
        return

    body = [f"[bold]Dataset:[/bold] {source}", f"[bold]Split:[/bold] {split}"]
    if args.instance:
        body.append(f"[bold]Instance:[/bold] {args.instance}")
    if keys:
        body.append(f"[bold]Keys:[/bold] {', '.join(keys)}")
    console.print(Panel("\n".join(body), title="[cyan]Configuration[/cyan]", border_style="cyan"))
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Print keys and patches from SWE-bench-like datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hugging Face dataset name")
    parser.add_argument("--split", "-s", default=DEFAULT_SPLIT, help="Dataset split")
    parser.add_argument("--dataset-path", help="Path to local JSONL dataset; overrides --dataset/--split")
    parser.add_argument("--instance", "-i", help="Instance ID to inspect")
    parser.add_argument("--key", "-k", nargs="+", help="Specific keys to print")
    parser.add_argument("--list-keys", action="store_true", help="Print dataset keys and exit")
    parser.add_argument("--list-instances", action="store_true", help="List instance IDs and exit")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for listing")
    parser.add_argument("--show-patches", action="store_true", help="Print detected patch keys")
    parser.add_argument("--patch-keys", nargs="+", default=DEFAULT_PATCH_KEYS, help="Patch-like keys to print")
    parser.add_argument("--plain", action="store_true", help="Use plain text output")
    parser.add_argument("--output", "-o", help="Write output to file; implies --plain")
    args = parser.parse_args()

    original_stdout = None
    if args.output:
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        original_stdout = sys.stdout
        sys.stdout = open(args.output, "w", encoding="utf-8")
        args.plain = True

    try:
        dataset = load_benchmark_dataset(args.dataset, args.split, args.dataset_path)
    except Exception as exc:
        print(f"Error loading dataset: {exc}", file=sys.stderr)
        sys.exit(1)

    sample = dict(dataset[0]) if len(dataset) > 0 else {}
    available_keys = list(sample.keys())

    if args.list_keys:
        print_header(args)
        print_keys(available_keys, plain=args.plain)
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
            print(f"Output written to: {args.output}")
        return

    if args.list_instances:
        print_header(args)
        instance_ids = [
            dict(item)["instance_id"]
            for item in dataset
            if "instance_id" in dict(item)
        ]
        if args.limit is not None:
            instance_ids = instance_ids[: args.limit]
        for idx, instance_id in enumerate(instance_ids, 1):
            if args.plain:
                print(f"{idx:4d}. {instance_id}")
            else:
                console.print(f"{idx:4d}. [green]{instance_id}[/green]")
        if original_stdout:
            sys.stdout.close()
            sys.stdout = original_stdout
            print(f"Output written to: {args.output}")
        return

    if not args.instance:
        parser.error("--instance is required unless using --list-keys or --list-instances")

    instance = get_instance(args.instance, dataset)
    if instance is None:
        print(f"Instance not found: {args.instance}", file=sys.stderr)
        sys.exit(1)

    requested_keys = list(args.key or [])
    if args.show_patches:
        for patch_key in args.patch_keys:
            if patch_key in instance and patch_key not in requested_keys:
                requested_keys.append(patch_key)

    if not requested_keys:
        requested_keys = available_keys

    print_header(args, requested_keys)

    for index, key in enumerate(requested_keys):
        if index > 0:
            if args.plain:
                print("-" * 100)
            else:
                console.print("\n" + "─" * 100 + "\n")

        if key not in instance:
            message = f"Key '{key}' not found. Available keys: {', '.join(available_keys)}"
            if args.plain:
                print(message)
            else:
                console.print(f"[red]{message}[/red]")
            continue

        value = instance[key]
        title = key.upper().replace("_", " ")

        if key == "interface" and isinstance(value, str):
            value = format_interface(value)

        if key in args.patch_keys and isinstance(value, str):
            print_patch(title, value, plain=args.plain)
        else:
            print_value(title, value, plain=args.plain)

    if original_stdout:
        sys.stdout.close()
        sys.stdout = original_stdout
        print(f"Output written to: {args.output}")


if __name__ == "__main__":
    main()

# Made with Bob
