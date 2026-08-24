#!/usr/bin/env python3
"""
Generate LLM-reconstructed annotations (requirements or interface) for benchmark instances.

Supported datasets (any JSONL with the required fields):
  - SWE-bench Pro Python    : patch + test_patch + problem_statement
  - SWE Re-Bench leaderboard: patch + test_patch + problem_statement
  - FEA-Bench medium        : patch + test_patch
  - NoCode Bench Verified   : feature_patch + test_patch

Select the task with --task:

  requirements  Generate 4-8 bullet-point implementation requirements from the
                problem statement, gold patch, and test patch.
                Output field: requirements_generated (+ requirements_human when available)

  interface     Generate a structured public-API interface block from the problem
                statement, gold patch, test patch, and (optionally) Stage 1 AST diff
                and Stage 2 test contracts.
                Output field: interface_generated (+ interface_human when available)
                Extra flag:   --repos <dir>  path to local repo clones (enables Stage 1)

  both          Run requirements and interface in a single pass. Stage 1/2 are run
                once per instance; two LLM calls are made. All four fields are written
                to the same output row:
                  requirements_generated, requirements_human,
                  interface_generated,    interface_human

Output JSONL format (one row per instance):
    {
        "instance_id": "...",
        "repo": "...",
        "<task>_generated": "...",
        "<task>_human": "..."     # only present when input has it
    }
    For --task both, all four fields appear in the same row.

Usage:
    # Requirements only
    python swe_pro.py --task requirements --input /path/to/dataset.jsonl

    # Interface only (with local repo checkouts)
    python swe_pro.py --task interface --input /path/to/dataset.jsonl --repos repos/

    # Both in one pass (recommended — halves dataset loading time)
    python swe_pro.py --task both --input /path/to/dataset.jsonl --repos repos/ \\
        --output annotations_generated.jsonl

    # Limit to N instances (smoke-test)
    python swe_pro.py --task both --input /path/to/dataset.jsonl --limit 10

    # Single instance
    python swe_pro.py --task both --input /path/to/dataset.jsonl \\
        --instance_id instance_qutebrowser__qutebrowser-...

Environment variables:
  REQUIREMENTS_MODEL      Override the litellm model string
  REQUIREMENTS_API_BASE   Override the API base URL
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterator

import litellm
from tqdm import tqdm

# Stage 1 & 2 helpers for the interface task
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from extract_public_symbols import extract_public_symbols, repo_slug_to_dir
from extract_test_contracts import extract_test_contracts, format_contracts
from utils import get_impl_patch

litellm.drop_params = True

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

MODEL = os.environ.get("REQUIREMENTS_MODEL", "openai/YOUR_MODEL")
API_BASE = os.environ.get(
    "REQUIREMENTS_API_BASE",
    "YOUR_API_BASE",
)
EXTRA_BODY: dict = {}

# ---------------------------------------------------------------------------
# Shared: LLM call
# ---------------------------------------------------------------------------

def call_llm(messages: list[dict], retries: int = 3, backoff: float = 10.0) -> str:
    """Call the LLM and return the text of the first response message."""
    for attempt in range(retries):
        try:
            kwargs: dict = dict(
                model=MODEL,
                api_base=API_BASE,
                api_key="YOUR_API_KEY",
                temperature=1.0,
                messages=messages,
                reasoning_effort="high",
            )
            if EXTRA_BODY:
                kwargs["extra_body"] = EXTRA_BODY
            response = litellm.completion(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  [warn] LLM call failed ({exc}); retrying in {wait:.0f}s …")
                time.sleep(wait)
            else:
                raise
    return ""  # unreachable


# ---------------------------------------------------------------------------
# Shared: data loading & resume
# ---------------------------------------------------------------------------

def _iter_jsonl(path: str) -> Iterator[dict]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_instances(source: str) -> Iterator[dict]:
    if Path(source).exists():
        yield from _iter_jsonl(source)
    else:
        raise FileNotFoundError(f"Input not found: {source!r}")


def load_completed_ids(output_path: str) -> set[str]:
    done: set[str] = set()
    p = Path(output_path)
    if p.exists():
        with open(p) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["instance_id"])
                except Exception:
                    pass
    return done


# ===========================================================================
# TASK: requirements
# ===========================================================================

_REQ_FEW_SHOT_EXAMPLES = [
    {
        # instance_internetarchive__openlibrary-4a5d2a7d24c9e4c11d3069220c0685b736d5ecde
        "problem_statement": """\
## Title: Incomplete Retrieval of Property Statement Values in Wikidata Entities.

### Description
Wikidata entities currently store property statements, but the code does not provide
a mechanism to access all the values associated with a specific property. As a result,
values may be difficult to retrieve, inconsistent, or unavailable when the property is
missing or when some statements are malformed.

### Expected Behavior
The entity model should expose a method that takes a property identifier and returns
the list of valid values contained in the statements, preserving order, skipping
invalid entries, and returning an empty list when no usable values exist.""",
        "patch": """\
diff --git a/openlibrary/core/wikidata.py b/openlibrary/core/wikidata.py
--- a/openlibrary/core/wikidata.py
+++ b/openlibrary/core/wikidata.py
+    def get_statement_values(self, property_id: str) -> list[str]:
+        if property_id not in self.statements:
+            return []
+        return [
+            statement["value"]["content"]
+            for statement in self.statements[property_id]
+            if "value" in statement and "content" in statement["value"]
+        ]""",
        "test_patch": """\
diff --git a/openlibrary/tests/core/test_wikidata.py b/openlibrary/tests/core/test_wikidata.py
+def test_get_statement_values() -> None:
+    entity.statements = {'P2038': [{'value': {'content': 'Chris-Wiggins'}}]}
+    assert entity.get_statement_values('P2038') == ['Chris-Wiggins']
+    entity.statements = {'P2038': [{'value': {'content': 'Value1'}}, {'value': {'content': 'Value2'}}]}
+    assert entity.get_statement_values('P2038') == ['Value1', 'Value2']
+    assert entity.get_statement_values('P9999') == []
+    entity.statements = {'P2038': [{'value': {'content': 'Valid'}}, {'wrong_key': {}}, {'value': {}}]}
+    assert entity.get_statement_values('P2038') == ['Valid']""",
        "requirements": """\
- The `WikidataEntity` class should provide a method named `get_statement_values` that takes a property identifier as input and returns a list of string values.
- The `get_statement_values` method should iterate over the statement objects of the requested property and collect the string in `value.content`, preserving the original order and skipping items missing the expected nested fields or with non-string/empty `content`.
- `get_statement_values` should return an empty list when the property is absent or when no valid values are present.
- The `statements` field in the `WikidataEntity` class should represent a mapping from property IDs to a list of structured statement objects, each of which may contain a nested value with content.""",
    },
    {
        # instance_qutebrowser__qutebrowser-c580ebf0801e5a3ecabc54f327498bb753c6d5f2
        "problem_statement": """\
## Title
Host blocking does not apply to subdomains when only the parent domain is listed

## Description
In the hosts-based blocking method, requests are only blocked if the exact request
hostname matches an entry in the blocked hosts set. Adding `example.com` to the
blocklist does not block `sub.example.com`.

## Expected behavior
Blocking a parent domain should block all of its subdomains unless explicitly whitelisted.""",
        "patch": """\
diff --git a/qutebrowser/utils/urlutils.py b/qutebrowser/utils/urlutils.py
+def widened_hostnames(hostname: str) -> Iterable[str]:
+    while hostname:
+        yield hostname
+        hostname = hostname.partition(".")[-1]""",
        "test_patch": """\
diff --git a/tests/unit/utils/test_urlutils.py b/tests/unit/utils/test_urlutils.py
+class TestWiden:
+    @pytest.mark.parametrize('hostname, expected', [
+        ('a.b.c', ['a.b.c', 'b.c', 'c']),
+        ('foobarbaz', ['foobarbaz']),
+        ('', []),
+        ('.c', ['.c', 'c']),
+        ('c.', ['c.']),
+        (None, []),
+    ])
+    def test_widen_hostnames(self, hostname, expected):
+        assert list(urlutils.widened_hostnames(hostname)) == expected""",
        "requirements": """\
- Respect the global/per-URL toggle: if content blocking is disabled for the current first-party URL, a request must not be blocked.
- Respect whitelist overrides first: if a request URL matches a whitelist rule, it must not be blocked regardless of any host or parent-domain matches.
- Treat a blocked registrable domain as covering all of its subdomains: if example.com is blocked, then example.com, sub.example.com, and a.b.example.com must all be blocked unless explicitly whitelisted.
- Determine blocking by checking the request host and each successive parent domain (left-stripping one label at a time) against both the runtime blocked set and the config-defined blocked set; the first match blocks the request.
- Define hostname widening semantics: for a multi-label hostname like a.b.c, the widening sequence is ["a.b.c", "b.c", "c"]; for a single-label hostname like foobarbaz, the sequence is ["foobarbaz"]; for an empty string, the sequence is empty.""",
    },
    {
        # instance_ansible__ansible-f327e65d11bb905ed9f15996024f857a95592629
        "problem_statement": """\
# Title: Collection Name Validation Accepts Python Keywords

## Description
The current validation system for Fully Qualified Collection Names (FQCN) in
ansible-galaxy incorrectly accepts collection names that contain Python reserved
keywords. Collection names like `def.collection` and `return.module` are accepted
when they should be rejected.""",
        "patch": """\
diff --git a/lib/ansible/utils/collection_loader/_collection_finder.py b/lib/ansible/utils/collection_loader/_collection_finder.py
+        if collection_name.count(u'.') != 1:
+            return False
+        return all(
+            not iskeyword(ns_or_name) and is_python_identifier(ns_or_name)
+            for ns_or_name in collection_name.split(u'.')
+        )""",
        "test_patch": """\
diff --git a/test/units/utils/collection_loader/test_collection_loader.py b/test/units/utils/collection_loader/test_collection_loader.py
+def test_fqcn_validation(fqcn, expected):
+    assert AnsibleCollectionRef.is_valid_collection_name(fqcn) is expected
+    # ('ns1.coll2', True), ('def.coll3', False), ('ns4.return', False)""",
        "requirements": """\
- The legacy helper functions `_is_py_id` and `_is_fqcn`, together with all related Python 2/3 compatibility code, should be removed in `dataclasses.py`.
- A new helper function `is_python_identifier` should be introduced to check whether a given string is a valid Python identifier.
- The method `is_valid_collection_name` must reject names where either `<namespace>` or `<name>` is a Python keyword, and both segments must be valid Python identifiers under language rules.
- The validity check must return a boolean (`True`/`False`) result indicating acceptance or rejection, rather than relying on exceptions.""",
    },
]

_REQ_SYSTEM_PROMPT = """\
You are a senior software engineer writing implementation requirements for code changes.

Given a GitHub issue (problem statement), the gold patch that resolves it, and the
test patch that verifies the fix, produce 4–8 concise bullet-point requirements that
precisely describe what a correct implementation MUST do.

Rules:
- Ground every requirement in what the patch actually changes — do not invent constraints
  that are not present in the diff.
- Use the test patch as evidence for exact expected behaviour: function names, return
  values, edge cases, and parameter semantics asserted by the tests must be reflected.
- Write requirements as implementation constraints, not issue restatements.
- Each bullet must be specific and testable.
- Mention concrete names (functions, classes, modules, flags) when the patch introduces them.
- Do NOT include a header line — start directly with the first bullet (`- ...`).
- Use plain Markdown bullets only (`- `). No numbered lists."""


def _build_req_few_shot() -> list[dict]:
    messages = [{"role": "system", "content": _REQ_SYSTEM_PROMPT}]
    for ex in _REQ_FEW_SHOT_EXAMPLES:
        user_content = (
            "## Problem statement\n"
            f"{ex['problem_statement'].strip()}\n\n"
            "## Gold patch\n"
            f"```diff\n{ex['patch'].strip()}\n```\n\n"
            "## Test patch\n"
            f"```diff\n{ex['test_patch'].strip()}\n```"
        )
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": ex["requirements"].strip()})
    return messages


_REQ_FEW_SHOT_MESSAGES = _build_req_few_shot()


def build_requirements_prompt(problem_statement: str, patch: str, test_patch: str) -> list[dict]:
    user_content = (
        "## Problem statement\n"
        f"{problem_statement.strip()}\n\n"
        "## Gold patch\n"
        f"```diff\n{patch.strip()}\n```\n\n"
        "## Test patch\n"
        f"```diff\n{test_patch.strip()}\n```"
    )
    return _REQ_FEW_SHOT_MESSAGES + [{"role": "user", "content": user_content}]


# ===========================================================================
# TASK: interface
# ===========================================================================

_IFACE_FEW_SHOT_EXAMPLES = [
    {
        "problem_statement": """\
## Title
Host blocking does not apply to subdomains when only the parent domain is listed

## Description
Adding example.com to the blocklist does not block sub.example.com.""",
        "symbols": """\
- Type: Function, Name: `widened_hostnames`
  Path: qutebrowser/utils/urlutils.py
  Signature: def widened_hostnames(hostname: str) -> Iterable[str]:
  Docstring: A generator for widening string hostnames.""",
        "contracts": """\
Names directly called/instantiated in tests:
  widened_hostnames""",
        "patch": """\
diff --git a/qutebrowser/utils/urlutils.py b/qutebrowser/utils/urlutils.py
+def widened_hostnames(hostname: str) -> Iterable[str]:
+    \"\"\"A generator for widening string hostnames.
+
+    Ex: a.c.foo -> [a.c.foo, c.foo, foo]\"\"\"
+    while hostname:
+        yield hostname
+        hostname = hostname.partition(".")[-1]""",
        "test_patch": """\
diff --git a/tests/unit/utils/test_urlutils.py b/tests/unit/utils/test_urlutils.py
+class TestWiden:
+    @pytest.mark.parametrize('hostname, expected', [
+        ('a.b.c', ['a.b.c', 'b.c', 'c']),
+        ('foobarbaz', ['foobarbaz']),
+        ('', []),
+        (None, []),
+    ])
+    def test_widen_hostnames(self, hostname, expected):
+        assert list(urlutils.widened_hostnames(hostname)) == expected""",
        "interface": """\
Type: Function
Name: widened_hostnames
Path: qutebrowser/utils/urlutils.py
Input: hostname: str
Output: Iterable[str]
Description: Generates parent-domain variants of a hostname by successively removing the leftmost label.""",
    },
    {
        "problem_statement": """\
## Title
Changelog appears after all upgrades regardless of type

## Description
The application displays the changelog after any upgrade. A new `changelog_after_upgrade`
setting should control this, and a `VersionChange` enum should represent the upgrade type.""",
        "symbols": """\
- Type: Class, Name: `VersionChange`
  Path: qutebrowser/config/configfiles.py
  Signature: class VersionChange(enum.Enum):
  Public methods: `matches_filter`(filterstr: str) -> bool""",
        "contracts": """\
Names directly called/instantiated in tests:
  VersionChange, matches_filter, StateConfig

String contracts (routes / command names / keys):
  "unknown", "equal", "patch", "minor", "major"  """,
        "patch": """\
diff --git a/qutebrowser/config/configfiles.py b/qutebrowser/config/configfiles.py
+class VersionChange(enum.Enum):
+    unknown = enum.auto()
+    equal = enum.auto()
+    patch = enum.auto()
+    minor = enum.auto()
+    major = enum.auto()
+    def matches_filter(self, filterstr: str) -> bool:
+        allowed_values = {'major': [...], 'minor': [...], 'patch': [...], 'never': []}
+        return self in allowed_values[filterstr]""",
        "test_patch": """\
diff --git a/tests/unit/config/test_configfiles.py b/tests/unit/config/test_configfiles.py
+def test_qutebrowser_version_changed(state_writer, monkeypatch, old_version, new_version, expected):
+    state = configfiles.StateConfig()
+    assert state.qutebrowser_version_changed == expected
+def test_version_change_filter(value, filterstr, matches):
+    assert value.matches_filter(filterstr) == matches""",
        "interface": """\
Type: Class
Name: VersionChange
Path: qutebrowser/config/configfiles.py
Description: Represents the type of version change when comparing two versions of qutebrowser. This enum is used to determine whether a changelog should be displayed after an upgrade, based on user configuration.""",
    },
]

_IFACE_SYSTEM_PROMPT = """\
You are a senior engineer documenting public APIs for a software benchmark dataset.

Given a GitHub issue, new public symbols extracted from the gold patch (Stage 1),
test-enforced contracts (Stage 2), the full gold patch, and the full test patch,
produce a structured interface block in SWE-bench Pro format.

Rules:
- TRUST STAGE 1 ABOVE ALL ELSE. If Stage 1 reports "(none detected by static
  analysis)", that means no new public top-level symbols were added. Output
  exactly: No new interfaces are introduced
  Do NOT invent interfaces by reading the patch yourself in this case.
- Only produce entries for symbols that Stage 1 explicitly listed. Do not add
  symbols you see in the patch that are absent from Stage 1's output.
- NEVER document private symbols — any name starting with _ (single or double
  underscore) is private and must be omitted, even if it appears in the patch.
- NEVER document a symbol that already existed and was merely modified or moved;
  only truly new additions count.
- One entry per top-level public class or function.
- For classes, write a single entry describing the class; summarise public methods
  in a "Public API" line rather than listing them as separate entries.
- Use exact names and paths from the test patch when they are available — they
  take precedence over the static analysis results.
- For each entry include: Type, Name, Path, Input, Output (or Public API), Description.
- Do NOT include a preamble — start directly with the first entry."""


def _format_symbols_for_prompt(symbols: list[dict]) -> str:
    if not symbols:
        return "(none detected by static analysis)"
    parts = []
    for s in symbols:
        lines = [f"- Type: {s['type']}, Name: `{s['name']}`"]
        if s.get("file_path"):
            lines.append(f"  Path: {s['file_path']}")
        if s.get("signature"):
            lines.append(f"  Signature: {s['signature']}")
        if s.get("docstring"):
            lines.append(f"  Docstring: {s['docstring']}")
        if s.get("bases"):
            lines.append(f"  Inherits: {', '.join(s['bases'])}")
        if s.get("class_context"):
            lines.append(f"  Class: {s['class_context']}")
        if s.get("public_methods"):
            meths = "; ".join(
                f"`{m['name']}`({m['signature'].split('(', 1)[-1].rstrip(':') if '(' in m['signature'] else ''})"
                for m in s["public_methods"]
            )
            lines.append(f"  Public methods: {meths}")
        parts.append("\n".join(lines))
    return "\n".join(parts)


def _build_iface_few_shot() -> list[dict]:
    messages = [{"role": "system", "content": _IFACE_SYSTEM_PROMPT}]
    for ex in _IFACE_FEW_SHOT_EXAMPLES:
        user_content = (
            "## Problem statement\n"
            f"{ex['problem_statement'].strip()}\n\n"
            "## New public symbols (Stage 1 — AST diff)\n"
            f"{ex['symbols'].strip()}\n\n"
            "## Test contracts (Stage 2)\n"
            f"{ex['contracts'].strip()}\n\n"
            "## Gold patch\n"
            f"```diff\n{ex['patch'].strip()}\n```\n\n"
            "## Test patch\n"
            f"```diff\n{ex['test_patch'].strip()}\n```"
        )
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": ex["interface"].strip()})
    return messages


_IFACE_FEW_SHOT_MESSAGES = _build_iface_few_shot()


def build_interface_prompt(
    problem_statement: str,
    symbols: list[dict],
    contracts: dict,
    patch: str,
    test_patch: str,
) -> list[dict]:
    sym_text = _format_symbols_for_prompt(symbols)
    contracts_text = format_contracts(contracts) or "(none)"
    user_content = (
        "## Problem statement\n"
        f"{problem_statement.strip()}\n\n"
        "## New public symbols (Stage 1 — AST diff)\n"
        f"{sym_text}\n\n"
        "## Test contracts (Stage 2)\n"
        f"{contracts_text}\n\n"
        "## Gold patch\n"
        f"```diff\n{patch.strip()}\n```\n\n"
        "## Test patch\n"
        f"```diff\n{test_patch.strip()}\n```"
    )
    return _IFACE_FEW_SHOT_MESSAGES + [{"role": "user", "content": user_content}]


# ===========================================================================
# Main pipeline
# ===========================================================================

def _get_repos_root(repos_dir: str | None, task: str) -> "Path | None":
    """Resolve Stage 1 repo root — only relevant for interface/both tasks."""
    if task == "requirements":
        return None
    if not repos_dir:
        print("  (Stage 1 disabled — no local repos)")
        return None
    repos_root = Path(repos_dir)
    if not repos_root.is_dir():
        print(f"Warning: --repos {repos_root} not found — Stage 1 will be skipped.")
        return None
    return repos_root


def run(
    task: str,
    source: str,
    output_path: str,
    repos_dir: str | None = None,
    limit: int | None = None,
    instance_id: str | None = None,
    use_official: bool = False,
) -> None:
    done_ids = load_completed_ids(output_path)
    if done_ids:
        print(f"Resuming — {len(done_ids)} instances already done.")

    repos_root = _get_repos_root(repos_dir, task)

    try:
        instances = list(iter_instances(source))
    except Exception as exc:
        print(f"Failed to load instances: {exc}")
        return

    if instance_id:
        instances = [r for r in instances if r.get("instance_id") == instance_id]
        if not instances:
            print(f"No instance found with id {instance_id!r}")
            return

    instances = [r for r in instances if r.get("instance_id") not in done_ids]
    if limit is not None:
        instances = instances[:limit]

    print(f"Processing {len(instances)} instances (task={task}) …")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out_file = open(output_path, "a", buffering=1)
    n_ok = n_err = 0

    for row in tqdm(instances, unit="inst"):
        iid = row.get("instance_id", "")
        problem_statement = row.get("problem_statement", "")
        patch = get_impl_patch(row)
        test_patch = row.get("test_patch", "")

        if not patch:
            tqdm.write(f"  [skip] {iid} — missing patch")
            continue

        out_row: dict = {"instance_id": iid, "repo": row.get("repo", "")}

        # Stage 1 & 2 run once when needed (shared between interface and both)
        symbols: list[dict] = []
        contracts: dict = {}
        if task in ("interface", "both"):
            if repos_root:
                repo_str = row.get("repo", "")
                try:
                    repo_dir = repo_slug_to_dir(repo_str, repos_root)
                    symbols = extract_public_symbols(row, repo_dir)
                except FileNotFoundError as e:
                    tqdm.write(f"  [skip-stage1] {iid}: {e}")
                except Exception as e:
                    tqdm.write(f"  [warn-stage1] {iid}: {e}")
            contracts = extract_test_contracts(test_patch)

        # --- requirements ---
        if task in ("requirements", "both"):
            if use_official:
                req_gen = row.get("requirements", "")
                if not req_gen:
                    tqdm.write(f"  [warn] {iid} — no official requirements field")
            else:
                try:
                    req_gen = call_llm(build_requirements_prompt(problem_statement, patch, test_patch))
                    n_ok += 1
                except Exception as exc:
                    tqdm.write(f"  [error-req] {iid}: {exc}")
                    req_gen = ""
                    n_err += 1
            out_row["requirements_generated"] = req_gen

        # --- interface ---
        if task in ("interface", "both"):
            if use_official:
                iface_gen = row.get("interface", "")
                if not iface_gen:
                    tqdm.write(f"  [warn] {iid} — no official interface field")
            else:
                try:
                    iface_gen = call_llm(
                        build_interface_prompt(problem_statement, symbols, contracts, patch, test_patch)
                    )
                    n_ok += 1
                except Exception as exc:
                    tqdm.write(f"  [error-iface] {iid}: {exc}")
                    iface_gen = ""
                    n_err += 1
            out_row["interface_generated"] = iface_gen

        out_file.write(json.dumps(out_row, ensure_ascii=False) + "\n")

    out_file.close()
    print(f"\nDone. ok={n_ok}  errors={n_err}  output={output_path}")


# ===========================================================================
# CLI
# ===========================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate LLM annotations (requirements or interface) for benchmark instances",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--task",
        required=True,
        choices=["requirements", "interface", "both"],
        help="requirements, interface, or both in a single pass",
    )
    p.add_argument(
        "--input", "-i",
        required=True,
        type=Path,
        help="Path to input JSONL file (any supported benchmark)",
    )
    p.add_argument(
        "--output", "-o",
        default=None,
        help=(
            "Output JSONL path. Defaults to requirements_generated_with_tests.jsonl, "
            "interface_generated.jsonl, or annotations_generated.jsonl depending on "
            "--task. Supports resume."
        ),
    )
    p.add_argument(
        "--repos", "-r",
        default=None,
        help="(interface only) Path to local repo clones — enables Stage 1 AST diff",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N instances (useful for smoke-testing)",
    )
    p.add_argument(
        "--instance-id",
        default=None,
        help="Process a single instance by ID",
    )
    p.add_argument(
        "--skip-errors",
        action="store_true",
        help="Continue on failed instances instead of crashing",
    )
    p.add_argument(
        "--use-official",
        action="store_true",
        help=(
            "SWE-bench Pro only: copy the official `requirements` and `interface` "
            "fields from the dataset directly into the output instead of calling the LLM."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    defaults = {
        "requirements": "requirements_generated_with_tests.jsonl",
        "interface": "interface_generated.jsonl",
        "both": "annotations_generated.jsonl",
    }
    output = args.output or defaults[args.task]
    run(
        task=args.task,
        source=str(args.input),
        output_path=output,
        repos_dir=args.repos,
        limit=args.limit,
        instance_id=args.instance_id,
        use_official=args.use_official,
    )


if __name__ == "__main__":
    main()
