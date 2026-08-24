"""
Shared utilities for identity selection scripts.

Covers:
  - JSONL I/O
  - Repo directory resolution (handles owner/name, owner__name, name layouts)
  - Dataset adapter: extract (impl_patch, test_patch, doc_content) from any
    supported benchmark row
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# JSONL I/O
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dump_jsonl(rows: Iterable[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Repo directory resolution
# ---------------------------------------------------------------------------

def find_repo_dir(repo: str, repos_root: Path) -> Path:
    """
    Resolve a local repo checkout for a 'owner/name' (or bare 'name') string.

    Tries, in order:
      1. repos_root / name          — most common (SWE Pro, SWE Re-Bench, NoCode)
      2. repos_root / owner__name   — FEA-Bench testbed layout
      3. repos_root / owner / name  — nested layout

    Raises FileNotFoundError if none exist.
    """
    if "/" in repo:
        owner, name = repo.split("/", 1)
        for candidate in [
            repos_root / name,
            repos_root / f"{owner}__{name}",
            repos_root / owner / name,
        ]:
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            f"Cannot find local repo for '{repo}' under {repos_root}. "
            f"Tried: {repos_root / name}, "
            f"{repos_root / f'{owner}__{name}'}, "
            f"{repos_root / owner / name}"
        )
    if (repos_root / repo).exists():
        return repos_root / repo
    raise FileNotFoundError(
        f"Cannot find local repo for '{repo}' under {repos_root}"
    )


# ---------------------------------------------------------------------------
# Dataset adapter
# ---------------------------------------------------------------------------

def get_impl_patch(example: dict) -> str:
    """Return the implementation patch for any supported dataset."""
    # NoCode Bench Verified uses 'feature_patch'
    if "feature_patch" in example:
        return example.get("feature_patch", "") or ""
    # FEA-Bench medium / SWE Pro / SWE Re-Bench use 'patch'
    return example.get("patch", "") or ""


def get_test_patch(example: dict) -> str:
    """Return the test patch for any supported dataset."""
    return example.get("test_patch", "") or ""


def get_doc_content(example: dict) -> str:
    """
    Return the documentation text used to filter out entities already visible
    to the agent.

    - NoCode Bench Verified: joins the 'metadata' field of each doc_changes
      entry — the documentation files changed alongside the feature.
      (Original augment.py: '\n'.join([i['metadata'] for i in example['doc_changes']]))
    - FEA-Bench / SWE Pro / SWE Re-Bench: no doc_changes field — use
      problem_statement instead. This is the task description shown to the
      agent, so any identifier already named there should be filtered out.
    """
    if "doc_changes" in example:
        items = example.get("doc_changes") or []
        return "\n".join(str(item.get("metadata", "")) for item in items if isinstance(item, dict))

    # FEA-Bench: no problem_statement — use pr_title + pr_body from problem_info
    if "problem_info" in example:
        pi = example.get("problem_info") or {}
        return "\n".join(filter(None, [pi.get("pr_title", ""), pi.get("pr_body", "")]))

    return example.get("problem_statement", "") or ""
