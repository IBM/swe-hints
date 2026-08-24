#!/usr/bin/env python3
"""
Statistics for the SWE-bench Pro Python dataset and its enriched identifier hints.

Covers:
  1. interface field — entry count, field coverage, Type value distribution
  2. requirements field — presence and length
  3. enriched identifiers — entity_type distribution, field coverage per type

Run from repo root:
    python identity_selection/swebench_pro_stats.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

SWE_PRO_SOURCE = Path(
    "identity_selection/data_selection/huggingface/swebench_pro_python.jsonl"
)
SWE_PRO_ENRICHED = Path(
    "results/swe_pro/hints_communication_all_nonempty_enriched.jsonl"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_interface_entries(iface: str) -> list[dict[str, str]]:
    """Split an interface string into per-entity blocks and extract fields."""
    entries = []
    blocks = re.split(r"(?=(?:^|\n)\s*[-*]?\s*Type\s*:)", iface)
    for block in blocks:
        block = block.strip()
        if not block or not re.search(r"\bType\s*:", block):
            continue
        entry: dict[str, str] = {}
        for field in ["Type", "Name", "Path", "Input", "Output", "Description", "Public API"]:
            m = re.search(rf"\b{field}\s*:\s*(.+)", block)
            if m:
                entry[field] = m.group(1).strip()
        entries.append(entry)
    return entries


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def pct(n: int, total: int) -> str:
    return f"{n} / {total} ({100 * n / total:.1f}%)" if total else f"{n} / {total}"


# ---------------------------------------------------------------------------
# 1. Source dataset — interface + requirements
# ---------------------------------------------------------------------------

def stats_source(path: Path) -> None:
    section("SOURCE: interface + requirements")

    instances = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    total = len(instances)
    print(f"Total instances: {total}")

    # requirements
    req_lengths = [len((d.get("requirements") or "").split()) for d in instances]
    has_req = sum(1 for x in req_lengths if x > 0)
    print(f"\nrequirements — present: {pct(has_req, total)}")
    if req_lengths:
        print(f"  word length  min={min(req_lengths)}  median={sorted(req_lengths)[total//2]}  max={max(req_lengths)}")

    # interface — instance-level presence
    iface_lengths = [len((d.get("interface") or "").split()) for d in instances]
    has_iface = sum(1 for x in iface_lengths if x > 0)
    print(f"\ninterface — present: {pct(has_iface, total)}")
    if iface_lengths:
        print(f"  word length  min={min(iface_lengths)}  median={sorted(iface_lengths)[total//2]}  max={max(iface_lengths)}")

    # interface — entry parsing
    all_entries: list[dict] = []
    entries_per_instance: Counter = Counter()
    type_ct: Counter = Counter()
    field_ct: Counter = Counter()

    for d in instances:
        entries = parse_interface_entries(d.get("interface") or "")
        entries_per_instance[len(entries)] += 1
        all_entries.extend(entries)
        for e in entries:
            for f in e:
                field_ct[f] += 1
            raw_type = e.get("Type", "")
            # Normalise: lowercase, collapse whitespace
            norm = re.sub(r"\s+", " ", raw_type).strip().lower()
            type_ct[norm] += 1

    n_entries = len(all_entries)
    zero = entries_per_instance.get(0, 0)
    print(f"\ninterface entries — total parsed: {n_entries}")
    print(f"  instances with 0 entries : {pct(zero, total)}")
    print(f"  instances with ≥1 entries: {pct(total - zero, total)}")

    print("\n  entries-per-instance distribution:")
    for n, ct in sorted(entries_per_instance.items()):
        print(f"    {n:3d} entries: {ct} instances")

    if n_entries:
        print(f"\n  field coverage across {n_entries} entries:")
        for field, ct in field_ct.most_common():
            print(f"    {field:<14}: {pct(ct, n_entries)}")

        print(f"\n  top Type values (normalised, across {n_entries} entries):")
        for val, ct in type_ct.most_common(20):
            print(f"    {ct:3d}  {repr(val)}")

    # issue_categories + issue_specificity distributions
    for key in ("issue_categories", "issue_specificity"):
        ct: Counter = Counter()
        for d in instances:
            raw = d.get(key) or []
            # field is stored as a JSON string in some rows — parse if needed
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = []
            for v in raw:
                ct[v] += 1
        print(f"\n{key} (multi-label, {total} instances):")
        for val, n in ct.most_common():
            print(f"    {n:3d}  {val}")


# ---------------------------------------------------------------------------
# 2. Enriched hints — identifier field coverage
# ---------------------------------------------------------------------------

def stats_enriched(path: Path) -> None:
    section("ENRICHED: identifier field coverage")

    if not path.exists():
        print(f"  File not found: {path}")
        return

    records = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    total_instances = len(records)
    all_identifiers = [ident for r in records for ident in r.get("identifiers", [])]
    total_ids = len(all_identifiers)

    print(f"Instances: {total_instances}")
    print(f"Total identifiers: {total_ids}")

    # Per entity_type
    by_type: dict[str, list[dict]] = {}
    for ident in all_identifiers:
        et = ident.get("entity_type", "unknown")
        by_type.setdefault(et, []).append(ident)

    print(f"\nentity_type distribution:")
    for et, ids in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {et:<12}: {pct(len(ids), total_ids)}")

    # Field coverage per entity_type
    for et, ids in sorted(by_type.items(), key=lambda x: -len(x[1])):
        n = len(ids)
        print(f"\n  [{et}] field coverage ({n} identifiers):")
        key_ct: Counter = Counter()
        for ident in ids:
            for k, v in ident.items():
                if v is not None and v != "" and v != [] and k not in ("name", "entity_type"):
                    key_ct[k] += 1
        for k, ct in key_ct.most_common():
            print(f"    {k:<25}: {pct(ct, n)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not SWE_PRO_SOURCE.exists():
        sys.exit(f"Source not found: {SWE_PRO_SOURCE}")

    stats_source(SWE_PRO_SOURCE)
    stats_enriched(SWE_PRO_ENRICHED)
