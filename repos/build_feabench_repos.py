"""
Clone (or update) all repos referenced by the FEA-Bench HuggingFace dataset.

Reads unique repos from microsoft/FEA-Bench, then for each:
  1. Clones into <repos-dir>/<short-name>  (skips if already present)
  2. Fetches to ensure every base_commit is reachable

The resulting layout matches what src/identifier_usage.py expects:
    repos_dir/<short-name>/    e.g. repos/feabench_repos/aider

Usage
-----
    python helper_code/build_feabench_repos.py \\
        --repos-dir repos/feabench_repos

    # Skip repos that fail instead of stopping:
    python helper_code/build_feabench_repos.py \\
        --repos-dir repos/feabench_repos \\
        --skip-errors

    # Dry-run: show what would be cloned without touching disk:
    python helper_code/build_feabench_repos.py \\
        --repos-dir repos/feabench_repos \\
        --dry-run

After running this script, point src/identifier_usage.py at the result:
    python -m src.identifier_usage \\
        --input      <your-feabench-instances.jsonl> \\
        --repos-dir  repos/feabench_repos \\
        --output     results/feabench/usage.jsonl \\
        --skip-errors
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _is_shallow(repo_dir: Path) -> bool:
    return (repo_dir / ".git" / "shallow").exists()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone FEA-Bench repos for src/identifier_usage.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--repos-dir", "-r",
        type=Path,
        default=Path("repos/feabench_repos"),
        help="Directory to clone repos into (default: repos/feabench_repos).",
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

    # ------------------------------------------------------------------
    # 1. Load unique repos + commits from HuggingFace
    # ------------------------------------------------------------------
    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("ERROR: 'datasets' package not installed.  Run: pip install datasets")

    print("Loading microsoft/FEA-Bench from HuggingFace ...")
    hf_ds = load_dataset("microsoft/FEA-Bench", split="test")

    # repo -> set of base_commits
    repo_commits: dict[str, set[str]] = defaultdict(set)
    for row in hf_ds:
        repo_commits[row["repo"]].add(row["base_commit"])

    print(f"Found {len(repo_commits)} unique repo(s) across {len(hf_ds)} instance(s).\n")

    if args.dry_run:
        for repo in sorted(repo_commits):
            short = repo.split("/")[-1]
            repo_dir = args.repos_dir / short
            status = "exists" if repo_dir.exists() else "would clone"
            print(f"  {repo:55s}  [{status}]  ({len(repo_commits[repo])} commit(s))")
        return

    # ------------------------------------------------------------------
    # 2. Clone / update each repo
    # ------------------------------------------------------------------
    args.repos_dir.mkdir(parents=True, exist_ok=True)

    n_ok = n_err = 0
    for repo in sorted(repo_commits):
        short = repo.split("/")[-1]
        repo_dir = args.repos_dir / short
        clone_url = f"https://github.com/{repo}.git"
        commits = repo_commits[repo]

        try:
            if not repo_dir.exists():
                print(f"Cloning {repo} ...", flush=True)
                _run(["git", "clone", clone_url, str(repo_dir)])
            else:
                print(f"Updating {repo} ...", flush=True)
                if _is_shallow(repo_dir):
                    _run(["git", "fetch", "--unshallow", "origin"], cwd=repo_dir)
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
    print(f"      --input      <your-feabench-instances.jsonl> \\")
    print(f"      --repos-dir  {args.repos_dir} \\")
    print(f"      --output     results/feabench/usage.jsonl \\")
    print(f"      --skip-errors")


if __name__ == "__main__":
    main()

# Made with Bob
