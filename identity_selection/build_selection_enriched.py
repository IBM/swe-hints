#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Bridge the SELECTION axis onto the PROJECTION axis.

A selection policy (defuse2.py, nocode.py, fea_brief.py, swe_pro.py) outputs only
{type, name} per identifier once project_nocode.py (or, for swe_pro.py,
project_swe_pro_nocode_llm.py) has flattened it.  The projections need the
structural facts (entity_type, path, is_new_file, signature, ...), which live in
the step-1 catalogue (python -m src.identifier_usage -> extracted_hints.jsonl).

This script joins a selection's identifier NAMES against that catalogue and emits
records in the shape identity_projection/project_enriched.py expects:

    {"instance_id": ..., "identifiers": [ {catalogue fields}, ... ]}

Names with no catalogue entry keep what the selection knew about them (name +
entity_type derived from the selection's own "type" field), so a selection never
loses identifiers just because the AST had nothing to say.

From there every selection takes the same route to mini-SWE-agent instances as the
src/ pipeline: project_enriched.py, then generate_instances.py (or
generate_doc2feat_instances.py).

Usage:
    python identity_selection/build_selection_enriched.py \
        --selection identity_selection/results_selection/nocode_sel/projected_nocode/swebench_pro_nocode.jsonl \
        --catalogue results/swe_pro_proj/extracted_hints.jsonl \
        --output    identity_selection/results_selection/nocode_sel/enriched/swebench_pro_nocode.jsonl

Written by Bastian Lipka for the paper's selection comparison (Table 2 inputs).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The selection axis labels identifiers with its own vocabulary ("field",
# "function", "class", "error_message"); the projection axis and the
# downstream _ENTITY_GATE use the four-value catalogue vocabulary.
_TYPE_MAP = {
    "field": "variable",
    "variable": "variable",
    "function": "function",
    "method": "function",
    "class": "class",
    "error_message": "variable",
}


def load_catalogue(path: Path) -> dict[str, dict[str, dict]]:
    """instance_id -> {identifier name -> catalogue entry}."""
    index: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            index[rec["instance_id"]] = rec.get("catalogue") or {}
    return index


def selection_identifiers(record: dict) -> list[dict]:
    """Pull the flat {type, name} list out of a projected_nocode record."""
    hints = record.get("hints") or {}
    data = hints.get("data")
    if isinstance(data, list):
        return data
    return []


def build(selection: Path, catalogue: Path, output: Path) -> None:
    cat = load_catalogue(catalogue)
    output.parent.mkdir(parents=True, exist_ok=True)

    n_rec = n_ident = n_hit = 0
    with selection.open(encoding="utf-8") as fh_in, output.open("w", encoding="utf-8") as fh_out:
        for line in fh_in:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            iid = rec["instance_id"]
            per_instance = cat.get(iid, {})

            identifiers: list[dict] = []
            seen: set[str] = set()
            for entry in selection_identifiers(rec):
                name = entry.get("name")
                if not name or name in seen:
                    continue
                seen.add(name)
                n_ident += 1

                hit = per_instance.get(name)
                if hit:
                    n_hit += 1
                    ident = dict(hit)
                    # The catalogue is authoritative for entity_type; fall back
                    # to the selection's own label when it has none.
                    if not ident.get("entity_type"):
                        ident["entity_type"] = _TYPE_MAP.get(entry.get("type", ""), "variable")
                else:
                    ident = {
                        "name": name,
                        "entity_type": _TYPE_MAP.get(entry.get("type", ""), "variable"),
                    }
                identifiers.append(ident)

            fh_out.write(json.dumps({"instance_id": iid, "identifiers": identifiers},
                                    ensure_ascii=False) + "\n")
            n_rec += 1

    pct = (100.0 * n_hit / n_ident) if n_ident else 0.0
    print(f"  {selection.name}: {n_rec} records, {n_ident} identifiers, "
          f"{n_hit} catalogue hits ({pct:.1f} %) -> {output}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selection", type=Path, required=True,
                    help="A selection arm's projected_nocode JSONL.")
    ap.add_argument("--catalogue", type=Path, required=True,
                    help="Step-1 extracted_hints.jsonl carrying the per-instance catalogue.")
    ap.add_argument("--output", type=Path, required=True,
                    help="Output JSONL in project_enriched.py input shape.")
    args = ap.parse_args()

    if not args.selection.exists():
        sys.exit(f"Selection not found: {args.selection}")
    if not args.catalogue.exists():
        sys.exit(f"Catalogue not found: {args.catalogue}")

    build(args.selection, args.catalogue, args.output)


if __name__ == "__main__":
    main()
