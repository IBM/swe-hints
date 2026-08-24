#!/usr/bin/env python3
"""
Print debug3_identifiers.jsonl alongside the SWE-bench Pro
requirements and interface fields for the same instances.

Usage
-----
    python helper_code/print_debug3.py

    # single instance
    python helper_code/print_debug3.py --instance-id <id>

    # control verbosity
    python helper_code/print_debug3.py --no-catalogue
    python helper_code/print_debug3.py --no-swebench
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

IDENTIFIERS_JSONL = Path("results/debug3_identifiers.jsonl")
SWEBENCH_JSONL    = Path("data/swebench_pro_python.jsonl")

SEP  = "=" * 90
SEP2 = "-" * 60

def _wrap(text: str, indent: int = 4, width: int = 88) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=width, initial_indent=prefix,
                         subsequent_indent=prefix)


def _fmt_interface(raw: str) -> str:
    """Unescape \\n in the interface string."""
    if not raw:
        return "(empty)"
    return raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').strip()


def print_instance(
    iid: str,
    id_rec: dict,
    sw_rec: dict | None,
    *,
    show_catalogue: bool = True,
    show_swebench: bool = True,
) -> None:
    print(SEP)
    print(f"INSTANCE  {iid}")
    print(SEP)

    # ------------------------------------------------------------------ #
    # Step 1 output: identifier sets
    # ------------------------------------------------------------------ #
    print("\n[ IDENTIFIER SETS ]")
    print(f"  code_write ({len(id_rec['code_write'])}): {id_rec['code_write']}")
    print(f"  code_read  ({len(id_rec['code_read'])}):  {id_rec['code_read']}")
    print(f"  test_write ({len(id_rec['test_write'])}): {id_rec['test_write']}")
    print(f"  test_read  ({len(id_rec['test_read'])}):  {id_rec['test_read']}")

    # ------------------------------------------------------------------ #
    # Catalogue
    # ------------------------------------------------------------------ #
    catalogue: dict = id_rec.get("catalogue", {})
    print(f"\n[ CATALOGUE ]  ({len(catalogue)} entries)")
    if catalogue and show_catalogue:
        for name, info in catalogue.items():
            etype  = info.get("entity_type", "?")
            path   = info.get("path", "")
            loc    = info.get("complete_location", info.get("partial_location", ""))
            print(f"\n  ── {name}  [{etype}]  {path}:{loc}")
            fields_to_show = [
                ("superclass",           "superclass      "),
                ("weak_semantics",       "weak semantics  "),
                ("strong_semantics",     "strong semantics"),
                ("signature",            "signature       "),
                ("input_names",          "input names     "),
                ("input_types",          "input types     "),
                ("output_partial_type",  "output partial  "),
                ("output_complete_type", "output complete "),
                ("public_methods",       "public methods  "),
                ("private_methods",      "private methods "),
                ("class_variables",      "class vars      "),
                ("local_variables",      "local vars      "),
                ("exception_types",      "except types    "),
                ("exception_values",     "except values   "),
                ("param_defaults",       "param defaults  "),
                ("imports",              "imports         "),
            ]
            for field, label in fields_to_show:
                val = info.get(field)
                if val:
                    print(f"     {label}: {val}")
    elif not catalogue:
        print("  (none)")

    # ------------------------------------------------------------------ #
    # SWE-bench Pro: requirements + interface
    # ------------------------------------------------------------------ #
    if show_swebench:
        if sw_rec is None:
            print("\n[ SWE-BENCH PRO ]  (not found in dataset)")
        else:
            print(f"\n[ REQUIREMENTS ]")
            req = sw_rec.get("requirements", "") or ""
            if req:
                # requirements is sometimes JSON-escaped
                try:
                    req = json.loads(f'"{req}"') if req.startswith('"') else req
                except Exception:
                    pass
                req = req.replace("\\n", "\n").strip()
                for line in req.splitlines():
                    print(f"    {line}")
            else:
                print("    (empty)")

            print(f"\n[ INTERFACE ]")
            iface = sw_rec.get("interface", "") or ""
            print(_fmt_interface(iface))

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print step-1 identifier data + SWE-bench Pro requirements/interface."
    )
    parser.add_argument("--identifiers", type=Path, default=IDENTIFIERS_JSONL,
                        help=f"Step 1 JSONL (default: {IDENTIFIERS_JSONL})")
    parser.add_argument("--swebench",    type=Path, default=SWEBENCH_JSONL,
                        help=f"SWE-bench Pro JSONL (default: {SWEBENCH_JSONL})")
    parser.add_argument("--instance-id", type=str, default=None,
                        help="Only print this instance.")
    parser.add_argument("--no-catalogue", action="store_true",
                        help="Hide the catalogue section.")
    parser.add_argument("--no-swebench", action="store_true",
                        help="Hide the requirements/interface section.")
    args = parser.parse_args()

    # Load identifier records
    id_records: dict[str, dict] = {}
    with open(args.identifiers, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                id_records[rec["instance_id"]] = rec

    # Load SWE-bench Pro records (indexed by instance_id)
    sw_records: dict[str, dict] = {}
    if args.swebench.exists():
        with open(args.swebench, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    sw_records[rec["instance_id"]] = rec

    # Filter if requested
    iids = list(id_records.keys())
    if args.instance_id:
        if args.instance_id not in id_records:
            print(f"instance_id {args.instance_id!r} not found.")
            return
        iids = [args.instance_id]

    for iid in iids:
        print_instance(
            iid,
            id_records[iid],
            sw_records.get(iid),
            show_catalogue=not args.no_catalogue,
            show_swebench=not args.no_swebench,
        )


if __name__ == "__main__":
    main()

# Made with Bob
