#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Clone (or update) all repos referenced by the SWE-bench Multilingual **Java** partition.

The Java partition is 6 repos / 43 instances — lombok, lucene, gson, druid,
javaparser, rxjava — and every instance pins a `base_commit`.  Step 1
(`src.identifier_usage`, and its Java sibling) checks the repo out at each
of those commits and diffs identifier sets across the gold patch, so the clones
need real history: no shallow clones, and every base_commit must be reachable
*before* a 43-instance run starts.

For each unique repo this script:
  1. Clones into <repos-dir>/<short-name>  (unshallows / fetches if already there)
  2. Verifies that every base_commit in the dataset resolves to a commit object

The resulting layout is what src/identifier_usage*.py expects — the directory name
is the repo slug tail (`instance["repo"].split("/")[-1]`):

    repos/java_repos/lombok
    repos/java_repos/lucene
    repos/java_repos/gson
    repos/java_repos/druid
    repos/java_repos/javaparser
    repos/java_repos/rxjava

Full clones are the default on purpose.  `--blobless` (git's --filter=blob:none)
downloads far less up front, but then every `git checkout <base_commit>` fetches
its blobs over the network — and step 1 does one checkout per instance.  Pay once
at clone time unless disk is genuinely tight.  Note that lucene and druid are
large (multi-GB with history); `--blobless` is a reasonable trade there if disk
is the binding constraint.

Language filtering
------------------
`SWE-bench/SWE-bench_Multilingual` has **no language column**, so when reading
straight from HuggingFace this script derives Java the same way
`helper_code/data_prepare/extract_swebench_multilingual_java.py` does: the gold
patch touches at least one `*.java` file.  A local JSONL produced by that script
carries `repo_language: "java"` and is filtered on that field instead.

Usage
-----
    # default: read the JSONL written by the extractor
    python repos/build_java_repos.py

    # straight from HuggingFace, no local JSONL needed
    python repos/build_java_repos.py --from-hf

    # show what would be cloned, without touching disk
    python repos/build_java_repos.py --dry-run

    # re-check an existing set without cloning anything
    python repos/build_java_repos.py --verify-only

    # for unreachable commits, try the SHAs and then refs/pull/* before giving up
    python repos/build_java_repos.py --fetch-missing

Then run step 1:
    python -m src.identifier_usage_java \\
        --input      data/java/swebench_multilingual_java.jsonl \\
        --repos-dir  repos/java_repos \\
        --output     results/java_proj/extracted_hints.jsonl \\
        --skip-errors
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HF_DATASET = "SWE-bench/SWE-bench_Multilingual"
HF_SPLIT   = "test"
DEFAULT_INPUT = Path("data/java/swebench_multilingual_java.jsonl")

_DIFF_A = re.compile(r"^diff --git a/(\S+) b/\S+", re.M)


def _git(args: list[str], cwd: Path | None = None, timeout: int | None = None):
    """Run a git command and hand back the CompletedProcess (never raises)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_shallow(repo_dir: Path) -> bool:
    return (repo_dir / ".git" / "shallow").exists()


def _dir_size(path: Path) -> str:
    proc = subprocess.run(["du", "-sh", str(path)], capture_output=True, text=True)
    return proc.stdout.split("\t")[0] if proc.returncode == 0 else "?"


def _touches_java(diff: str) -> bool:
    return any(p.endswith(".java") for p in _DIFF_A.findall(diff or ""))


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_repo_commits(args) -> dict[str, set[str]]:
    """Return {repo: {base_commit, ...}} for the Java partition."""
    if args.from_hf:
        try:
            from datasets import load_dataset
        except ImportError:
            sys.exit("ERROR: 'datasets' not installed.  Run: pip install datasets")
        print(f"Loading {HF_DATASET} ({args.split} split) from HuggingFace ...")
        rows = [dict(r) for r in load_dataset(HF_DATASET, split=args.split)]
        # No language column upstream — derive it from the gold patch.
        rows = [r for r in rows if _touches_java(r.get("patch", ""))]
    else:
        if not args.input.exists():
            sys.exit(
                f"ERROR: no such file: {args.input}\n"
                f"       Build it first:\n"
                f"         python helper_code/data_prepare/extract_swebench_multilingual_java.py\n"
                f"       or read the dataset directly with --from-hf."
            )
        rows = [
            json.loads(line)
            for line in args.input.open(encoding="utf-8")
            if line.strip()
        ]

    if args.language:
        keep = {lang.strip().lower() for lang in args.language.split(",")}
        # A JSONL that was already filtered may not carry repo_language at all;
        # only drop rows that explicitly disagree.
        rows = [
            r for r in rows
            if "repo_language" not in r
            or str(r.get("repo_language") or "").lower() in keep
        ]

    repo_commits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        repo_commits[row["repo"]].add(row["base_commit"])
    if not repo_commits:
        sys.exit("ERROR: no instances matched — check --input / --language / --from-hf.")
    return repo_commits


# ---------------------------------------------------------------------------
# Clone + verify
# ---------------------------------------------------------------------------

def clone(repo: str, repo_dir: Path, blobless: bool) -> str:
    """Clone `repo` into `repo_dir`, or refresh it if it is already there."""
    if (repo_dir / ".git").exists():
        if _is_shallow(repo_dir):
            proc = _git(["fetch", "--unshallow", "origin"], cwd=repo_dir, timeout=7200)
            return "unshallowed" if proc.returncode == 0 else f"FAILED: {proc.stderr.strip()[:200]}"
        proc = _git(["fetch", "--quiet", "origin"], cwd=repo_dir, timeout=7200)
        return "updated" if proc.returncode == 0 else f"FAILED: {proc.stderr.strip()[:200]}"

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["clone", "--quiet"]
    if blobless:
        # Full commit history, blobs fetched on demand.  See the module docstring.
        cmd.append("--filter=blob:none")
    cmd += [f"https://github.com/{repo}.git", str(repo_dir)]

    proc = _git(cmd, timeout=14400)
    if proc.returncode != 0:
        # Leave no half-clone behind for the next run to mistake for a good one.
        if repo_dir.exists() and not (repo_dir / ".git").exists():
            subprocess.run(["rm", "-rf", str(repo_dir)])
        return f"FAILED: {proc.stderr.strip()[:200]}"
    return "cloned"


def missing_commits(repo_dir: Path, commits: set[str]) -> list[str]:
    """Which of `commits` this checkout cannot resolve to a commit object."""
    return [
        sha for sha in sorted(commits)
        if _git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_dir).returncode != 0
    ]


def fetch_missing(repo_dir: Path, missing: list[str]) -> list[str]:
    """Try to recover commits a plain clone did not bring down.

    A base_commit can be absent for two reasons: it only ever lived on a pull-request
    head (a default clone fetches branches, not refs/pull/*), or it was orphaned by a
    force-push.  The first is recoverable, the second is not.
    """
    still = list(missing)

    # Cheapest first: ask for the individual SHAs.
    for sha in list(still):
        if _git(["fetch", "--quiet", "origin", sha], cwd=repo_dir, timeout=900).returncode == 0:
            if _git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_dir).returncode == 0:
                still.remove(sha)

    if still:
        # One bulk fetch of PR heads, then re-check whatever is left.
        _git(
            ["fetch", "--quiet", "origin", "+refs/pull/*/head:refs/remotes/origin/pr/*"],
            cwd=repo_dir,
            timeout=7200,
        )
        still = missing_commits(repo_dir, still)
    return still


def handle_repo(repo: str, commits: set[str], args) -> dict:
    repo_dir = args.repos_dir / repo.split("/")[-1]
    result = {"repo": repo, "dir": repo_dir, "commits": len(commits),
              "missing": [], "size": "-"}

    if args.verify_only:
        if not (repo_dir / ".git").exists():
            result["status"] = "NOT CLONED"
            return result
        result["status"] = "present"
    else:
        result["status"] = clone(repo, repo_dir, args.blobless)
        if result["status"].startswith("FAILED"):
            return result

    result["size"] = _dir_size(repo_dir)
    if args.no_verify:
        return result

    missing = missing_commits(repo_dir, commits)
    if missing and args.fetch_missing:
        missing = fetch_missing(repo_dir, missing)
        result["size"] = _dir_size(repo_dir)
    result["missing"] = missing
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone SWE-bench Multilingual (Java) repos for the Java hints pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"JSONL with repo + base_commit (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--from-hf",
        action="store_true",
        help=f"Ignore --input and read {HF_DATASET} from HuggingFace instead.",
    )
    parser.add_argument(
        "--split",
        default=HF_SPLIT,
        help=f"HuggingFace split, with --from-hf (default: {HF_SPLIT}).",
    )
    parser.add_argument(
        "--repos-dir", "-r",
        type=Path,
        default=Path("repos/java_repos"),
        help="Directory to clone repos into (default: repos/java_repos).",
    )
    parser.add_argument(
        "--language",
        default="java",
        help="repo_language filter, comma-separated; 'all' disables it (default: java).",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=6,
        help="Concurrent clones (default: 6 — the Java partition has 6 repos).",
    )
    parser.add_argument(
        "--blobless",
        action="store_true",
        help="Clone with --filter=blob:none: much smaller, but every checkout hits the network.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the base_commit reachability check.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check existing clones; clone nothing.",
    )
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="For unreachable commits, try fetching the SHAs and then refs/pull/*.",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Exit 0 even if some repos failed or have unreachable base_commits.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without touching disk.",
    )
    args = parser.parse_args()

    if args.language.strip().lower() == "all":
        args.language = ""

    repo_commits = load_repo_commits(args)
    total = sum(len(c) for c in repo_commits.values())
    print(f"\n{len(repo_commits)} repo(s), {total} distinct base_commit(s)\n")
    for repo, commits in sorted(repo_commits.items(), key=lambda kv: -len(kv[1])):
        repo_dir = args.repos_dir / repo.split("/")[-1]
        state = "exists" if repo_dir.exists() else "would clone"
        print(f"  {repo:34s} {len(commits):4d} commit(s)  [{state}]  -> {repo_dir}")
    if args.dry_run:
        return

    verb = "Verifying" if args.verify_only else "Cloning"
    print(f"\n{verb} with {args.workers} worker(s) ...\n")

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(handle_repo, repo, commits, args)
            for repo, commits in repo_commits.items()
        ]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results.append(res)
            note = f", {len(res['missing'])} MISSING" if res["missing"] else ""
            print(f"  {res['repo']:34s} {res['status']:16s} {res['size']:>7s}{note}", flush=True)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'repo':34s} {'status':16s} {'size':>7s}  commits  missing")
    print("-" * 78)
    failed = 0
    for res in sorted(results, key=lambda r: r["repo"]):
        print(f"{res['repo']:34s} {res['status']:16s} {res['size']:>7s} "
              f"{res['commits']:8d} {len(res['missing']):8d}")
        if res["status"].startswith(("FAILED", "NOT CLONED")) or res["missing"]:
            failed += 1

    for res in results:
        if res["missing"]:
            print(f"\nUnreachable base_commits in {res['repo']} ({len(res['missing'])}):")
            for sha in res["missing"][:10]:
                print(f"  {sha}")
            if len(res["missing"]) > 10:
                print(f"  ... and {len(res['missing']) - 10} more")
            if not args.fetch_missing:
                print("  Retry with --fetch-missing to pull the SHAs and refs/pull/* before giving up.")

    if failed:
        print(f"\n{failed} repo(s) need attention; step 1 will skip their instances "
              f"(run it with --skip-errors).")
        if not args.skip_errors:
            sys.exit(1)
    elif args.no_verify:
        print("\nAll repos present.  Base commits NOT checked (--no-verify).")
    else:
        print("\nAll repos ready and every base_commit is reachable.")

    print("\nNext step — run Step 1:")
    print("  python -m src.identifier_usage_java \\")
    print(f"      --input      {args.input if not args.from_hf else DEFAULT_INPUT} \\")
    print(f"      --repos-dir  {args.repos_dir} \\")
    print("      --output     results/java_proj/extracted_hints.jsonl \\")
    print("      --skip-errors")


if __name__ == "__main__":
    main()
