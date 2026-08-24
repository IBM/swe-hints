"""
Clone (or update) all repos referenced by the SWE-rebench-leaderboard 2026 splits.

For each unique repo found in the JSONL produced by extract_swerebench_2026.py,
this script:
  1. Clones the repo into <repos-dir>/<repo-name>  (skips if already present)
  2. Fetches all missing commits so every base_commit in the dataset is reachable

The resulting directory layout matches what src/identifier_usage.py expects:
  repos/swerebench_repos/<repo-name>/

Usage:
    python helper_code/build_swerebench_repos.py \\
        --input  data/swerebench_2026.jsonl \\
        --repos-dir repos/swerebench_repos

    # Skip repos that fail (e.g. private / moved) instead of stopping:
    python helper_code/build_swerebench_repos.py \\
        --input  data/swerebench_2026.jsonl \\
        --repos-dir repos/swerebench_repos \\
        --skip-errors

    # Dry-run: show which repos would be cloned without touching disk:
    python helper_code/build_swerebench_repos.py \\
        --input  data/swerebench_2026.jsonl \\
        --repos-dir repos/swerebench_repos \\
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    """Run a command, raising on failure with visible stderr."""
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _is_shallow(repo_dir: Path) -> bool:
    """Return True if the repo is a shallow clone."""
    return (repo_dir / ".git" / "shallow").exists()


def _unshallow(repo_dir: Path) -> None:
    """Convert a shallow clone to a full clone."""
    subprocess.run(
        ["git", "fetch", "--unshallow", "origin"],
        cwd=str(repo_dir),
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone / update repos for the SWE-rebench-leaderboard 2026 splits."
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="JSONL produced by extract_swerebench_2026.py (must have repo + base_commit).",
    )
    parser.add_argument(
        "--repos-dir", "-r",
        type=Path,
        default=Path("repos/swerebench_repos"),
        help="Directory to clone repos into (default: repos/swerebench_repos).",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="Continue past repos that fail to clone or fetch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without touching disk.",
    )
    args = parser.parse_args()

    # Load JSONL and collect: repo -> set of base_commits
    repo_commits: dict[str, set[str]] = defaultdict(set)
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            repo_commits[rec["repo"]].add(rec["base_commit"])

    print(f"Found {len(repo_commits)} unique repo(s) across "
          f"{sum(len(v) for v in repo_commits.values())} instance(s).\n")

    if args.dry_run:
        for repo, commits in sorted(repo_commits.items()):
            repo_name = repo.split("/")[-1]
            repo_dir  = args.repos_dir / repo_name
            status = "exists" if repo_dir.exists() else "would clone"
            print(f"  {repo:45s}  [{status}]  ({len(commits)} commit(s))")
        return

    args.repos_dir.mkdir(parents=True, exist_ok=True)

    n_ok = n_err = 0
    for repo, commits in sorted(repo_commits.items()):
        repo_name = repo.split("/")[-1]
        repo_dir  = args.repos_dir / repo_name
        clone_url = f"https://github.com/{repo}.git"

        try:
            if not repo_dir.exists():
                print(f"Cloning {repo} ...", flush=True)
                _run(["git", "clone", clone_url, str(repo_dir)])
            else:
                print(f"Updating {repo} ...", flush=True)
                if _is_shallow(repo_dir):
                    print(f"  Unshallowing {repo_dir} ...", flush=True)
                    _unshallow(repo_dir)
                else:
                    _run(["git", "fetch", "--quiet", "origin"], cwd=repo_dir)

            print(f"  OK  {repo_dir}  ({len(commits)} commit(s))")
            n_ok += 1
        except Exception as exc:
            print(f"  ERROR  {repo}: {exc}", file=sys.stderr)
            if not args.skip_errors:
                sys.exit(1)
            n_err += 1

    print(f"\nDone. {n_ok} repo(s) ready" + (f", {n_err} error(s) skipped" if n_err else "") + ".")
    print(f"\nNext step — run Step 1:")
    print(f"  python -m src.identifier_usage \\")
    print(f"    --input      {args.input} \\")
    print(f"    --repos-dir  {args.repos_dir} \\")
    print(f"    --output     results/swerebench/extracted_hints.jsonl \\")
    print(f"    --skip-errors")


if __name__ == "__main__":
    main()

# Made with Bob
