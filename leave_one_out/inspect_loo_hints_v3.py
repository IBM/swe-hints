"""
inspect_loo_hints_v3.py
=======================
Inspect the rendered hints for every coalition in a v3 LOO run.

For each instance, shows:
  - The NONE coalition  (should be empty)
  - The FULL coalition  (all active rows)
  - Each LOO-<root> coalition (FULL minus that root's subtree)

This lets you verify that:
  1. NONE produces no hints.
  2. FULL produces the complete hint text.
  3. Each LOO coalition is missing exactly the rows from the named subtree.

Usage
-----
    # All 33 instances, brief mode (row diffs only):
    python leave_one_out/inspect_loo_hints_v3.py

    # One specific instance:
    python leave_one_out/inspect_loo_hints_v3.py \
        --instance-id instance_ansible__ansible-489156378c...

    # Full rendered hint text for every coalition:
    python leave_one_out/inspect_loo_hints_v3.py --full-text

    # Only show LOO coalitions for a specific root:
    python leave_one_out/inspect_loo_hints_v3.py --root Func

    # Custom run directory or hints file:
    python leave_one_out/inspect_loo_hints_v3.py \
        --run-dir  leave_one_out/runs/loo_helped_v3_r1 \
        --hints    leave_one_out/output/hints_helped_enriched.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    available_rows,
    render_hint,
    subtree_rows,
)

DIVIDER   = "=" * 80
SUBDIV    = "-" * 60


def load_hints(path: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                index[rec["instance_id"]] = rec
    return index


def load_audit(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def fmt_rows(rows: list[str] | frozenset[str], width: int = 70) -> str:
    """Pretty-print a sorted row list, wrapping at `width` chars."""
    items = sorted(rows)
    if not items:
        return "(none)"
    lines, cur = [], ""
    for item in items:
        seg = (", " if cur else "") + item
        if len(cur) + len(seg) > width:
            lines.append(cur)
            cur = item
        else:
            cur += seg
    if cur:
        lines.append(cur)
    indent = "  "
    return ("\n" + indent).join(lines)


def inspect_instance(
    audit_rec: dict,
    hint_rec: dict,
    manifest: dict,
    full_text: bool,
    filter_root: str | None,
) -> None:
    iid          = audit_rec["instance_id"]
    active       = frozenset(audit_rec["active_rows"])
    active_roots = audit_rec["active_roots"]
    none_cid     = audit_rec["none_cid"]
    full_cid     = audit_rec["full_cid"]
    loo_cids     = audit_rec["loo_cids"]  # root -> cid

    print(DIVIDER)
    print(f"INSTANCE : {iid}")
    print(f"Active rows ({len(active)}): {fmt_rows(active)}")
    print(f"Active roots ({len(active_roots)}): {active_roots}")

    # ── NONE ─────────────────────────────────────────────────────────────────
    if filter_root is None:
        print(f"\n{'·'*4} NONE  (cid: {none_cid})")
        none_rows = frozenset(manifest[none_cid]["rows"])
        assert none_rows == frozenset(), f"NONE coalition should be empty, got {none_rows}"
        none_hint = render_hint(hint_rec, frozenset())
        if none_hint:
            print(f"  ⚠ WARN: NONE rendered non-empty hints!")
            print(f"  {none_hint[:200]}")
        else:
            print("  ✓ Empty (no hints) — correct.")

    # ── FULL ─────────────────────────────────────────────────────────────────
    if filter_root is None:
        print(f"\n{'·'*4} FULL  (cid: {full_cid})")
        full_rows = frozenset(manifest[full_cid]["rows"])
        missing_from_full = active - full_rows
        extra_in_full     = full_rows - active
        if missing_from_full:
            print(f"  ⚠ WARN: FULL is missing active rows: {sorted(missing_from_full)}")
        elif extra_in_full:
            print(f"  ⚠ WARN: FULL has extra rows not in active: {sorted(extra_in_full)}")
        else:
            print(f"  ✓ Contains all {len(full_rows)} active rows — correct.")
        if full_text:
            full_hint = render_hint(hint_rec, full_rows)
            print(f"  --- hint text ({len(full_hint)} chars) ---")
            print(full_hint)
            print(f"  --- end ---")
        else:
            full_hint = render_hint(hint_rec, full_rows)
            print(f"  Hint text: {len(full_hint)} chars")

    # ── LOO coalitions ────────────────────────────────────────────────────────
    for root in LOO_SUBGRAPH_ROOTS:
        if filter_root and root != filter_root:
            continue
        if root not in loo_cids:
            if not filter_root:
                print(f"\n{'·'*4} LOO-{root}  (root not active — no coalition)")
            continue

        cid  = loo_cids[root]
        rows = frozenset(manifest[cid]["rows"])

        expected_removed = active & subtree_rows(root)
        expected_kept    = active - subtree_rows(root)

        print(f"\n{'·'*4} LOO-{root}  (cid: {cid})")
        print(f"  Expected to REMOVE ({len(expected_removed)} rows from {root} subtree):")
        print(f"    {fmt_rows(expected_removed)}")
        print(f"  Expected to KEEP   ({len(expected_kept)} rows):")
        print(f"    {fmt_rows(expected_kept)}")

        # Verify
        actually_removed = active - rows
        actually_kept    = rows

        wrong_removed = actually_removed - expected_removed
        missed_remove = expected_removed - actually_removed
        wrong_kept    = actually_kept - expected_kept

        if missed_remove:
            print(f"  ✗ ERROR: should have removed but didn't: {sorted(missed_remove)}")
        if wrong_removed:
            print(f"  ✗ ERROR: removed rows that shouldn't be removed: {sorted(wrong_removed)}")
        if wrong_kept:
            print(f"  ✗ ERROR: coalition contains unexpected rows: {sorted(wrong_kept)}")
        if not (missed_remove or wrong_removed or wrong_kept):
            print(f"  ✓ Coalition rows are correct.")

        loo_hint = render_hint(hint_rec, rows)
        if full_text:
            print(f"  --- hint text ({len(loo_hint)} chars) ---")
            print(loo_hint if loo_hint else "(empty)")
            print(f"  --- end ---")
        else:
            print(f"  Hint text: {len(loo_hint)} chars")
            if loo_hint:
                # Show just the first line as a sanity preview
                first_line = loo_hint.split("\n")[0]
                print(f"  Preview : {first_line[:100]}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect rendered hints for every v3 LOO coalition.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--run-dir", type=Path,
        default=Path("leave_one_out/runs/loo_helped_v3_r1"),
        help="Run directory (default: leave_one_out/runs/loo_helped_v3_r1)",
    )
    parser.add_argument(
        "--hints", type=Path,
        default=Path("leave_one_out/output/hints_helped_enriched.jsonl"),
        help="Enriched hints JSONL (default: leave_one_out/output/hints_helped_enriched.jsonl)",
    )
    parser.add_argument(
        "--instance-id", type=str, default=None,
        help="Inspect a single instance only.",
    )
    parser.add_argument(
        "--root", type=str, default=None,
        choices=list(LOO_SUBGRAPH_ROOTS),
        help="Only show LOO coalitions for this root (e.g. --root Func).",
    )
    parser.add_argument(
        "--full-text", action="store_true",
        help="Print the full rendered hint text for every coalition.",
    )
    args = parser.parse_args()

    # ── Load artefacts ────────────────────────────────────────────────────────
    audit_path    = args.run_dir / "instance_audit.jsonl"
    manifest_path = args.run_dir / "coalition_manifest.json"

    for p in (audit_path, manifest_path, args.hints):
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            sys.exit(1)

    manifest  = json.loads(manifest_path.read_text())
    audit     = load_audit(audit_path)
    hints_idx = load_hints(args.hints)

    if args.instance_id:
        audit = [r for r in audit if r["instance_id"] == args.instance_id]
        if not audit:
            print(f"ERROR: instance_id {args.instance_id!r} not found in audit.",
                  file=sys.stderr)
            sys.exit(1)

    # ── Summary header ────────────────────────────────────────────────────────
    from collections import Counter
    type_counts = Counter(v["coalition_type"] for v in manifest.values())
    print(f"Run       : {args.run_dir.name}")
    print(f"Instances : {len(audit)}")
    print(f"Coalition counts: " +
          "  ".join(f"{t}={n}" for t, n in sorted(type_counts.items())))
    print(f"Subtree sizes:")
    for root in LOO_SUBGRAPH_ROOTS:
        print(f"  {root:8s}: {len(subtree_rows(root)):2d} rows")
    print()

    # ── Per-instance inspection ───────────────────────────────────────────────
    errors = 0
    for audit_rec in audit:
        iid = audit_rec["instance_id"]
        hint_rec = hints_idx.get(iid)
        if hint_rec is None:
            print(f"WARNING: {iid} not in hints file — skipping.", file=sys.stderr)
            continue

        inspect_instance(audit_rec, hint_rec, manifest,
                         full_text=args.full_text,
                         filter_root=args.root)

    print(DIVIDER)
    if errors == 0:
        print("All coalitions verified ✓")
    else:
        print(f"⚠  {errors} error(s) found.")


if __name__ == "__main__":
    main()

# Made with Bob
