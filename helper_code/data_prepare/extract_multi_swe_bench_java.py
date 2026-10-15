#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Normalise ByteDance-Seed/Multi-SWE-bench (Java) into the schema this pipeline expects.

Multi-SWE-bench is NOT SWE-bench-shaped.  Field mapping applied here:

    org + repo            -> repo               ("google" + "gson" -> "google/gson")
    base.sha              -> base_commit
    title + body          -> problem_statement  (blank-line joined)
    fix_patch             -> patch
    test_patch            -> test_patch         (unchanged)
    f2p_tests (dict)      -> FAIL_TO_PASS       (sorted keys; falls back to
                                                 n2p_tests then fixed_tests, which is
                                                 where several repos actually put it)
    p2p_tests (dict)      -> PASS_TO_PASS       (sorted keys)
    -                     -> repo_language = "java"

`hints` is RENAMED to `msb_hints`.  Multi-SWE-bench ships its own natural-language
hint string, and the downstream mini-SWE-agent input schema uses `hints` for the
hint text WE generate — leaving it in place would silently pre-fill every prompt
with someone else's hints.

The bulky per-run test logs (`run_result`, `test_patch_result`, `fix_patch_result`)
are dropped by default: they are ~90% of the file size (elastic__logstash is 12 MB
for 38 rows) and nothing in this pipeline reads them.  Keep them with --keep-logs.

Usage
-----
    python helper_code/data_prepare/extract_multi_swe_bench_java.py \
        --raw-dir data/java/multi_swe_raw \
        --output  data/java/multi_swe_bench_java.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_DROP_BY_DEFAULT = ("run_result", "test_patch_result", "fix_patch_result")


def _tests(row: dict, *fields: str) -> list[str]:
    """First non-empty dict among `fields`, as sorted keys."""
    for f in fields:
        v = row.get(f)
        if isinstance(v, dict) and v:
            return sorted(v)
        if isinstance(v, list) and v:
            return sorted(v)
    return []


def normalise(row: dict, keep_logs: bool = False) -> dict:
    org, repo = row.get("org", ""), row.get("repo", "")
    base = row.get("base") or {}

    title = (row.get("title") or "").strip()
    body = (row.get("body") or "").strip()
    problem = "\n\n".join(p for p in (title, body) if p)

    out = {
        "instance_id": row.get("instance_id") or f"{org}__{repo}-{row.get('number')}",
        "repo": f"{org}/{repo}" if org else repo,
        "repo_language": "java",
        "base_commit": base.get("sha", ""),
        "patch": row.get("fix_patch", ""),
        "test_patch": row.get("test_patch", ""),
        "problem_statement": problem,
        # f2p lives in different fields depending on the repo; take the first populated.
        "FAIL_TO_PASS": _tests(row, "f2p_tests", "n2p_tests", "fixed_tests"),
        "PASS_TO_PASS": _tests(row, "p2p_tests", "s2p_tests"),
        # Multi-SWE-bench's own hint string — renamed so it cannot collide with ours.
        "msb_hints": row.get("hints", ""),
        "number": row.get("number"),
        "resolved_issues": row.get("resolved_issues"),
    }
    if keep_logs:
        for f in _DROP_BY_DEFAULT:
            out[f] = row.get(f)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=Path("data/java/multi_swe_raw"),
                    help="Directory of downloaded <org>__<repo>.jsonl files.")
    ap.add_argument("--output", "-o", type=Path,
                    default=Path("data/java/multi_swe_bench_java.jsonl"))
    ap.add_argument("--keep-logs", action="store_true",
                    help="Retain run_result/test_patch_result/fix_patch_result.")
    ap.add_argument("--require-patches", action="store_true",
                    help="Drop rows missing patch, test_patch, base_commit or problem_statement.")
    args = ap.parse_args()

    files = sorted(args.raw_dir.glob("*.jsonl"))
    if not files:
        raise SystemExit(f"No .jsonl under {args.raw_dir}")

    rows, dropped = [], 0
    for f in files:
        for line in f.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = normalise(json.loads(line), keep_logs=args.keep_logs)
            if args.require_patches and not all(
                rec[k] for k in ("patch", "test_patch", "base_commit", "problem_statement")
            ):
                dropped += 1
                continue
            rows.append(rec)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} instances to {args.output}"
          + (f" ({dropped} dropped)" if dropped else ""))
    print(f"  size: {args.output.stat().st_size // 1024} KB")
    for repo, n in sorted(Counter(r["repo"] for r in rows).items(), key=lambda kv: -kv[1]):
        print(f"    {repo:44s} {n:4d}")
    for field in ("patch", "test_patch", "base_commit", "problem_statement", "FAIL_TO_PASS"):
        n = sum(1 for r in rows if r[field])
        print(f"  non-empty {field:20s} {n}/{len(rows)}")


if __name__ == "__main__":
    main()
