#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Extract the **Java** subset of SWE-bench Multilingual to a local JSONL file.

Why this needs a heuristic
--------------------------
`SWE-bench/SWE-bench_Multilingual` covers 9 languages across 41 repos but ships
**no language column** — the schema is
`base_commit, created_at, eval_type, image, instance_id, log_parser, repo,
version, patch, test_patch, eval_script, problem_statement, hints_text,
FAIL_TO_PASS, PASS_TO_PASS`.  So "which rows are Java" has to be derived.

Two independent signals are computed and cross-checked:

  1. **Gold-patch extension** (authoritative here): the instance's `patch`
     touches at least one `*.java` file.  This is the rule that actually matters
     for the hints pipeline — `src/identifier_usage.py` diffs identifier
     sets across the gold patch, so an instance with no Java in `patch` yields
     nothing no matter what language the repo is nominally written in.
  2. **Build-tool log parser**: `log_parser` in {maven, gradle_custom, ant},
     i.e. the JVM test harnesses.

As of dataset revision 846e647 the two agree exactly: 43 instances over 6 repos
(lombok 17, lucene 9, gson 9, druid 5, javaparser 2, rxjava 1).  The script
reports any disagreement instead of silently preferring one signal, because a
future dataset revision could add a JVM language that is not Java (Kotlin,
Scala) — that would show up as "parser-only".

Output rows are the upstream rows verbatim plus one added field,
`repo_language: "java"`, so that `repos/build_java_repos.py` (and the
`--language` filter it inherits from `build_swe_pro_repos.py`) has something to
key on.

Usage
-----
    python helper_code/data_prepare/extract_swebench_multilingual_java.py \
        --output data/java/swebench_multilingual_java.jsonl

    # Preview only (no file written):
    python helper_code/data_prepare/extract_swebench_multilingual_java.py --dry-run

Then clone the repos it needs:
    python repos/build_java_repos.py --input data/java/swebench_multilingual_java.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from datasets import load_dataset

HF_DATASET = "SWE-bench/SWE-bench_Multilingual"
HF_SPLIT   = "test"

# JVM build harnesses used by the Java partition of this dataset.
JAVA_LOG_PARSERS = {
    "parse_log_maven",
    "parse_log_gradle_custom",
    "parse_log_ant",
}

# Fields every downstream consumer (src/identifier_usage.py, the agent
# runners, the eval harness) assumes are present and non-empty.
REQUIRED_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "patch",
    "test_patch",
    "problem_statement",
)

_DIFF_A = re.compile(r"^diff --git a/(\S+) b/\S+", re.M)


def patched_files(diff: str) -> list[str]:
    """Paths on the `a/` side of every file header in a unified diff."""
    return _DIFF_A.findall(diff or "")


def touches_java(diff: str) -> bool:
    return any(path.endswith(".java") for path in patched_files(diff))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download SWE-bench Multilingual and save the Java-only instances as JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/java/swebench_multilingual_java.jsonl"),
        help="Output JSONL path (default: data/java/swebench_multilingual_java.jsonl).",
    )
    parser.add_argument(
        "--split",
        default=HF_SPLIT,
        help=f"HuggingFace dataset split (default: {HF_SPLIT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats and sample instance IDs without writing any file.",
    )
    args = parser.parse_args()

    print(f"Loading {HF_DATASET} ({args.split} split) from HuggingFace ...")
    dataset = load_dataset(HF_DATASET, split=args.split)
    print(f"Total instances: {len(dataset)}")

    rows = [dict(inst) for inst in dataset]

    by_patch  = {r["instance_id"] for r in rows if touches_java(r.get("patch", ""))}
    by_parser = {r["instance_id"] for r in rows if r.get("log_parser") in JAVA_LOG_PARSERS}

    print(f"\nSignal 1 — gold patch touches *.java : {len(by_patch)}")
    print(f"Signal 2 — JVM log_parser            : {len(by_parser)}")
    if by_patch == by_parser:
        print("Signals agree exactly.")
    else:
        print("WARNING: signals disagree — inspect before trusting the output.")
        only_patch  = sorted(by_patch - by_parser)
        only_parser = sorted(by_parser - by_patch)
        if only_patch:
            print(f"  .java patch but non-JVM parser ({len(only_patch)}): {only_patch}")
        if only_parser:
            print(f"  JVM parser but no .java in patch ({len(only_parser)}): {only_parser}")
            print("  ^ likely another JVM language (Kotlin/Scala) — excluded.")

    java = [r for r in rows if r["instance_id"] in by_patch]
    for r in java:
        r["repo_language"] = "java"

    # ------------------------------------------------------------------
    # Field validation — refuse to ship rows the pipeline cannot consume.
    # ------------------------------------------------------------------
    bad: list[tuple[str, list[str]]] = []
    for r in java:
        missing = [f for f in REQUIRED_FIELDS if not str(r.get(f) or "").strip()]
        if missing:
            bad.append((r.get("instance_id", "<no id>"), missing))
    if bad:
        print(f"\nERROR: {len(bad)} instance(s) missing required fields:")
        for iid, missing in bad[:10]:
            print(f"  {iid}: {', '.join(missing)}")
        raise SystemExit(1)
    print(f"All {len(java)} instance(s) carry: {', '.join(REQUIRED_FIELDS)}")

    counts = Counter(r["repo"] for r in java)
    print(f"\nJava instances: {len(java)} across {len(counts)} repo(s)")
    for repo, n in counts.most_common():
        n_src  = sum(1 for r in java if r["repo"] == repo
                     for _ in [0] if touches_java(r["patch"]))
        n_test = sum(1 for r in java if r["repo"] == repo and touches_java(r["test_patch"]))
        print(f"  {repo:26s} {n:3d} instance(s)   "
              f"({n_src} with .java in patch, {n_test} with .java in test_patch)")

    if args.dry_run:
        print("\n[dry-run] Sample instance IDs:")
        for r in java[:5]:
            print(f"  {r['instance_id']}")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for r in java:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    print(f"\nSaved {len(java)} instances to {args.output}")
    print("\nNext step — clone the repos:")
    print(f"  python repos/build_java_repos.py --input {args.output}")


if __name__ == "__main__":
    main()
