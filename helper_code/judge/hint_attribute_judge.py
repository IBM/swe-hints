#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""LLM-as-judge for hint attributes: necessity, disclosure, behavioural guidance.

Scores each (instance, identifier, attribute) triple on three ordinal scales so a
per-attribute number can be averaged and reported.  Judge model defaults to
``openrouter/openai/gpt-5.6-luna``.

THREE SCALES
------------
N  necessity     0 redundant / 1 search-saving / 2 disambiguating / 3 load-bearing
D  disclosure    0 interface / 1 contract / 2 mechanism / 3 transcription
G  guidance      0 declarative / 1 orienting / 2 procedural / 3 prescriptive

    Hint Value Margin  HVM = N - max(D, G)     in [-3, +3]

`max` rather than a sum: a prescriptive hint is compromised whether or not it also
discloses, and D/G correlate enough that summing double-counts.

TWO CALLS PER ATTRIBUTE, NOT ONE
--------------------------------
Necessity is asked SOLUTION-BLIND (problem statement only).  Showing the gold
patch makes everything look derivable in hindsight, which would collapse the
scale.  Disclosure and guidance are asked SOLUTION-AWARE (gold + test patch),
because leakage is defined relative to the solution.

Both calls show ALL of the identifier's attributes and name ONE as the target.
Hiding the others would break necessity, which is conditional (whether `path`
matters depends on whether you already have `name`); judging all seven in one
call invites the model to rationalise the monotone ladder it expects.

MECHANICAL MEASUREMENTS
-----------------------
Some of what the judge is asked is measurable, and those columns are computed here
without an LLM so the judge can be checked against them.  On this corpus 128/128
hinted names appear in the test patch and 0/128 appear in any problem statement,
both consequences of the `communication` operator (it selects names written in the
implementation and read in tests).

The decisive one is `name_in_repo_at_base`: a git grep of the repository at
base_commit, which settles whether the agent could have found the name by reading.
An earlier proxy — "appears only in added lines of the gold patch" — was WRONG and
is kept only as `name_only_in_added_lines` for contrast: it measures new-to-this-
patch, not new-to-the-repository.  Validation caught this.  The proxy called
HTTPError, wapi, results, aggregate and purge "must invent"; the judge called them
SEARCH-SAVING; the repo grep found them in 60, 32, 296, 241 and 115 files
respectively.  The judge was right and the proxy was wrong.

Pass --repos-dir to enable the grep (needs the repository clones).

Usage
-----
    export JUDGE_API_KEY=$OPENROUTER_API_KEY
    python helper_code/judge/hint_attribute_judge.py \\
        --hints  results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \\
        --source identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \\
        --output results/judge/swe_pro_attr_judgments.jsonl \\
        --samples 3 --workers 8

    # validate the rubric on the attribute whose answer we already know
    python helper_code/judge/hint_attribute_judge.py ... --attributes name --samples 3
    # cheap smoke test, no API calls
    python helper_code/judge/hint_attribute_judge.py ... --dry-run --limit 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import litellm

# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------

MODEL = os.environ.get("JUDGE_MODEL", "openrouter/openai/gpt-5.6-luna")
API_KEY = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
API_BASE = os.environ.get("JUDGE_API_BASE", "")
# Reasoning effort. PIN IT AND REPORT IT: measured on weak_/strong_semantics, n=70,
# effort does NOT improve self-consistency (3-sample unanimity, low vs high:
# N 87/84%, D 90/89%, G 70/63%) but it DOES shift the guidance scale's calibration
# (mean G 0.91 at low, 1.20 at high). A ~0.3 shift on a 0-3 scale is large enough
# that G numbers are not comparable across effort settings, so this must be fixed
# for a whole study and stated in the paper. "medium" is the middle of the range
# that was tested; "low" measured marginally better and costs 0 reasoning tokens.
EFFORT = os.environ.get("JUDGE_REASONING_EFFORT", "medium")

ATTRIBUTES = ["name", "entity_type", "path", "is_new_file",
              "signature", "weak_semantics", "strong_semantics"]

# The judge emits LABELS ONLY; the integer is derived here.  Asking for both
# produced contradictory pairs in validation (disclosure=2 labelled "INTERFACE",
# which is defined as 0), so the number is no longer the model's to choose.
N_MAP = {"REDUNDANT": 0, "SEARCH-SAVING": 1, "DISAMBIGUATING": 2, "LOAD-BEARING": 3}
D_MAP = {"INTERFACE": 0, "CONTRACT": 1, "MECHANISM": 2, "TRANSCRIPTION": 3}
G_MAP = {"DECLARATIVE": 0, "ORIENTING": 1, "PROCEDURAL": 2, "PRESCRIPTIVE": 3}


def _lab2int(label, mapping):
    if not isinstance(label, str):
        return None
    return mapping.get(label.strip().upper().replace("_", "-"))

_LOCK = threading.Lock()


def log(msg: str) -> None:
    with _LOCK:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Rubrics.  Anchors are drawn from real values in this corpus so the judge
# calibrates against cases it will actually see rather than against abstractions.
# ---------------------------------------------------------------------------

NECESSITY_RUBRIC = """\
Rate NECESSITY: could a competent engineer obtain this attribute's value WITHOUT
seeing the reference solution?

  0 REDUNDANT      - the value is stated in the problem statement itself.
  1 SEARCH-SAVING  - not stated, but an engineer with the repository at its current
                     commit would reach it through normal investigation (the entity
                     already exists; grep/reading finds it). The hint saves effort,
                     not information.
  2 DISAMBIGUATING - not stated and not already present, but strongly constrained by
                     repository convention (e.g. a new test file's location follows
                     an obvious existing layout). An engineer would likely guess it.
  3 LOAD-BEARING   - encodes a free choice the solution's author made that is not
                     recoverable from the problem statement or the existing codebase
                     (e.g. the name of a function that does not yet exist). Without
                     the hint an engineer would pick something else.

Judge ONLY the target attribute's value. Ignore whether the value seems important;
necessity is about RECOVERABILITY, not importance."""

DISCLOSURE_RUBRIC = """\
Rate DISCLOSURE: how much of the reference solution's CONTENT does this value carry?

  0 INTERFACE      - identity and addressing only: what it is called, where it lives,
                     how it is invoked. This is the line the benchmark itself
                     publishes to agents, so it is not leakage.
  1 CONTRACT       - observable behaviour: what it does, what its inputs and outputs
                     mean. A specification someone could implement many ways.
  2 MECHANISM      - how it does it: control flow, algorithm, ordering of operations,
                     or the names of specific helpers/APIs it calls internally.
  3 TRANSCRIPTION  - restates the solution closely enough that the code could be
                     transliterated from the text with little independent thought.

Example of 2: "overrides add_job to check the hostname against allowed hosts using
fnmatch patterns" - names the method and the matching library.
Example of 1: "A set of exact key names that should not be sanitized even if they
contain sensitive substrings" - states the contract without the mechanism."""

GUIDANCE_RUBRIC = """\
Rate BEHAVIOURAL GUIDANCE: how much does this value DIRECT the agent's actions, as
opposed to merely stating a fact it must act upon?

  0 DECLARATIVE    - states that something exists or what it is called. No action
                     is implied.
  1 ORIENTING      - narrows where to look or what to touch, without saying what to do.
  2 PROCEDURAL     - implies a sequence of steps or a specific approach to take.
  3 PRESCRIPTIVE   - reads as an instruction the agent can follow directly; the text
                     could substitute for a plan.

This is INDEPENDENT of disclosure. A line range discloses a lot (exactly where the
change goes) but guides nothing (it does not say what to do). An algorithm
description does both. Score them separately."""

SYSTEM = """\
You are an exacting research assistant evaluating hint quality for a software
engineering benchmark. You apply a rubric literally and consistently. You do not
reward values for being detailed or useful; you classify them by the stated
criteria only. You always answer with a single JSON object and nothing else."""


def _target_block(ident: dict, target: str) -> str:
    """The value under judgment, quoted in isolation.

    Validation showed the judge drifting to the ENTITY rather than the attribute
    value: asked about `name` = "wapi" it reasoned about "the WapiModule-based CRUD
    mechanism", which is a property of the thing named, not of the four-character
    string. Restating the value alone and saying so explicitly keeps the target fixed.
    """
    val = str(ident.get(target))
    if len(val) > 2000:
        val = val[:2000] + " …"
    return f"""## The value you are rating
attribute : `{target}`
value     : ```
{val}
```

You are rating THE TEXT ABOVE — not the entity it refers to, and not the other
attributes listed for context. Ask what this text, by itself, tells a reader."""


def _fmt_identifier(ident: dict, target: str) -> str:
    lines = []
    for a in ATTRIBUTES:
        v = ident.get(a)
        if v in (None, "", [], {}):
            continue
        mark = "  <<< TARGET" if a == target else ""
        val = str(v)
        if len(val) > 1200:
            val = val[:1200] + " …"
        lines.append(f"  {a}: {val}{mark}")
    return "\n".join(lines)


def build_necessity_prompt(inst: dict, ident: dict, target: str,
                           mech: dict | None = None) -> list[dict]:
    """Solution-blind: problem statement only, no patches.

    The repository fact is supplied rather than guessed. Validation showed the judge
    is perfect (13/13) when a name is genuinely absent from the tree but only 5/18
    when it is present - it has no way to grep, so "could an engineer find this by
    reading" was an unanswerable question. Handing it the measured file count turns
    recoverability from a guess into an interpretation, and keeps one rubric across
    attributes that do and do not have a mechanical equivalent.
    """
    repo_fact = ""
    if mech and "name_files_in_repo_at_base" in mech:
        n = mech["name_files_in_repo_at_base"]
        repo_fact = (f"\n## Measured repository fact\n"
                     f"The identifier `{ident.get('name')}` appears in {n} file(s) in this "
                     f"repository at the commit the agent starts from.\n"
                     + ("An engineer could therefore find it by searching the existing code.\n"
                        if n > 0 else
                        "It does not exist anywhere in the tree yet, so it cannot be found by "
                        "searching; any engineer would have to choose a name.\n"))
    user = f"""\
{NECESSITY_RUBRIC}
{repo_fact}

## Repository
{inst.get('repo', '')}

## Problem statement (this is ALL the agent is told)
{(inst.get('problem_statement') or '')[:6000]}

## The identifier, for context
{_fmt_identifier(ident, target)}

{_target_block(ident, target)}

## Your task
Rate NECESSITY.

Respond with exactly this JSON object:
{{"label": "<REDUNDANT|SEARCH-SAVING|DISAMBIGUATING|LOAD-BEARING>",
  "evidence": "<a short verbatim quote from the problem statement that justifies \
your rating, or the empty string if the statement says nothing relevant>",
  "rationale": "<one sentence>",
  "confidence": <0.0-1.0>}}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def build_leakage_prompt(inst: dict, ident: dict, target: str) -> list[dict]:
    """Solution-aware: gold patch + test patch visible."""
    user = f"""\
{DISCLOSURE_RUBRIC}

{GUIDANCE_RUBRIC}

## Problem statement
{(inst.get('problem_statement') or '')[:4000]}

## Reference solution (gold patch)
```diff
{(inst.get('patch') or '')[:14000]}
```

## Test patch (defines what must pass)
```diff
{(inst.get('test_patch') or '')[:6000]}
```

## The identifier, for context
{_fmt_identifier(ident, target)}

{_target_block(ident, target)}

## Your task
Rate DISCLOSURE and BEHAVIOURAL GUIDANCE for the value above, by comparing it
against the reference solution.

Respond with exactly this JSON object:
{{"disclosure_label": "<INTERFACE|CONTRACT|MECHANISM|TRANSCRIPTION>",
  "guidance_label": "<DECLARATIVE|ORIENTING|PROCEDURAL|PRESCRIPTIVE>",
  "evidence": "<the span of the target value that carries the most solution content, \
verbatim>",
  "rationale": "<one sentence>",
  "confidence": <0.0-1.0>}}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Mechanical measurements — no LLM.  These are facts, and they validate the judge.
# ---------------------------------------------------------------------------

def _grep_repo(repos_dir, repo: str, commit: str, name: str):
    """How many files at `commit` mention `name`. None if the repo is unavailable.

    This is the real recoverability test: if the name already occurs in the tree the
    agent is working on, it is findable by reading, whatever the gold patch does.
    """
    if not repos_dir or not name or "/" in name:
        return None
    d = Path(repos_dir) / repo.split("/")[-1]
    if not d.is_dir():
        return None
    try:
        r = subprocess.run(["git", "grep", "-l", "-w", name, commit],
                           cwd=d, capture_output=True, text=True, timeout=120)
        return len(r.stdout.strip().splitlines()) if r.returncode in (0, 1) else None
    except Exception:
        return None


def mechanical(inst: dict, ident: dict, repos_dir=None) -> dict:
    """Recoverability facts. Patch-derived, plus a repo grep when repos are present."""
    name = ident.get("name") or ""
    ps = inst.get("problem_statement") or ""
    tp = inst.get("test_patch") or ""
    gp = inst.get("patch") or ""
    out: dict = {}
    if name and "/" not in name:
        w = re.compile(r"\b" + re.escape(name) + r"\b")
        added = {l[1:] for l in gp.splitlines() if l.startswith("+") and not l.startswith("+++")}
        other = {l[1:] for l in gp.splitlines() if l.startswith("-") or (l and l[0] == " ")}
        out["name_in_problem_statement"] = bool(w.search(ps))
        out["name_in_test_patch"] = bool(w.search(tp))
        # Kept for contrast only - this is the proxy validation showed to be wrong.
        out["name_only_in_added_lines"] = (any(w.search(x) for x in added)
                                           and not any(w.search(x) for x in other))
        n_files = _grep_repo(repos_dir, inst.get("repo", ""), inst.get("base_commit", ""), name)
        if n_files is not None:
            out["name_files_in_repo_at_base"] = n_files
            out["name_in_repo_at_base"] = n_files > 0
    p = ident.get("path")
    if p:
        out["path_in_gold_patch"] = p in gp
        out["path_in_problem_statement"] = p in ps
    return out


# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _call(messages: list[dict], retries: int = 3) -> dict | None:
    """One judgment. Returns the parsed JSON plus `_meta` provenance.

    The envelope is recorded, not discarded: provider, finish_reason and token usage
    are what let a finished run be audited afterwards. Nine agent runs on this project
    were silently degraded by a provider returning empty completions, and it went
    unnoticed because nothing stored who served the call.
    """
    kwargs: dict = {"model": MODEL, "messages": messages, "temperature": 1.0,
                    "drop_params": True}
    if EFFORT:
        kwargs["reasoning_effort"] = EFFORT
    if API_KEY:
        kwargs["api_key"] = API_KEY
    if API_BASE:
        kwargs["api_base"] = API_BASE
    for attempt in range(retries):
        try:
            r = litellm.completion(**kwargs)
            ch = r.choices[0]
            txt = (ch.message.content or "").strip()
            raw = r.model_dump() if hasattr(r, "model_dump") else {}
            usage = raw.get("usage") or {}
            meta = {
                "provider": raw.get("provider") or getattr(r, "provider", None),
                "finish_reason": getattr(ch, "finish_reason", None),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"),
                "empty": not txt,
            }
            m = _JSON_RE.search(txt)
            if m:
                out = json.loads(m.group(0))
                out["_meta"] = meta
                return out
            # Parsed nothing: keep the evidence rather than silently retrying away.
            if attempt == retries - 1:
                return {"_error": "unparseable", "_meta": meta}
        except Exception as exc:
            if attempt == retries - 1:
                return {"_error": f"{type(exc).__name__}: {exc}"}
    return None


def _median_int(vals: list) -> int | None:
    v = [int(x) for x in vals if isinstance(x, (int, float))]
    return int(statistics.median(v)) if v else None


def judge_one(inst: dict, ident: dict, target: str, samples: int, dry: bool,
              repos_dir=None) -> dict:
    rec = {"instance_id": inst["instance_id"], "identifier": ident.get("name"),
           "entity_type": ident.get("entity_type"), "attribute": target,
           "value": str(ident.get(target))[:400], "mechanical": mechanical(inst, ident, repos_dir)}
    if dry:
        rec["_prompts"] = {"necessity": build_necessity_prompt(inst, ident, target, rec["mechanical"])[-1]["content"],
                           "leakage": build_leakage_prompt(inst, ident, target)[-1]["content"]}
        return rec

    nec, dis, gui, raw = [], [], [], []
    for _ in range(samples):
        a = _call(build_necessity_prompt(inst, ident, target, rec["mechanical"]))
        b = _call(build_leakage_prompt(inst, ident, target))
        raw.append({"necessity": a, "leakage": b})
        v = _lab2int((a or {}).get("label"), N_MAP)
        if v is not None:
            nec.append(v)
        v = _lab2int((b or {}).get("disclosure_label"), D_MAP)
        if v is not None:
            dis.append(v)
        v = _lab2int((b or {}).get("guidance_label"), G_MAP)
        if v is not None:
            gui.append(v)

    N, D, G = _median_int(nec), _median_int(dis), _median_int(gui)
    rec.update({
        "N": N, "D": D, "G": G,
        "HVM": (N - max(D, G)) if None not in (N, D, G) else None,
        "samples": {"N": nec, "D": dis, "G": gui},
        "agreement": {k: (len(set(v)) == 1 if v else None)
                      for k, v in (("N", nec), ("D", dis), ("G", gui))},
        "raw": raw,
    })
    return rec


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hints", type=Path, required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--attributes", nargs="*", default=ATTRIBUTES)
    ap.add_argument("--samples", type=int, default=3, help="LLM samples per judgment; median wins.")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="First N instances.")
    ap.add_argument("--repos-dir", type=Path, default=None,
                    help="Clones dir (e.g. repos/swe_pro_python_repos). Enables the "
                         "git-grep-at-base-commit recoverability check.")
    ap.add_argument("--redo", action="store_true",
                    help="Ignore existing output and re-judge everything (costs money).")
    ap.add_argument("--dry-run", action="store_true", help="Build prompts, make no API calls.")
    args = ap.parse_args()

    src = {}
    with args.source.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                src[r["instance_id"]] = r

    rows = [json.loads(l) for l in args.hints.open(encoding="utf-8") if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    jobs = []
    for r in rows:
        inst = src.get(r["instance_id"])
        if inst is None:
            continue
        inst = {**inst, "instance_id": r["instance_id"]}
        for ident in r.get("identifiers", []):
            for a in args.attributes:
                if ident.get(a) not in (None, "", [], {}):
                    jobs.append((inst, ident, a))

    # Resume: a full sweep is thousands of paid calls, so never redo completed work.
    done_keys = set()
    if args.output.exists() and not args.redo:
        with args.output.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done_keys.add((r["instance_id"], r.get("identifier"), r["attribute"]))
                except Exception:
                    pass
    if done_keys:
        before = len(jobs)
        jobs = [j for j in jobs
                if (j[0]["instance_id"], j[1].get("name"), j[2]) not in done_keys]
        log(f"resume: {len(done_keys)} judgments already present, {before - len(jobs)} skipped")

    log(f"judgments: {len(jobs)}  (attributes={args.attributes}, samples={args.samples})")
    log(f"model: {MODEL}  reasoning_effort={EFFORT or 'provider default'}"
        + ("   [DRY RUN]" if args.dry_run else ""))
    if not args.dry_run and not API_KEY:
        sys.exit("No API key: set JUDGE_API_KEY or OPENROUTER_API_KEY.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    mode = "w" if (args.redo or not args.output.exists()) else "a"
    with args.output.open(mode, encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(judge_one, i, d, a, args.samples, args.dry_run,
                                args.repos_dir)
                    for i, d, a in jobs]
            for fut in as_completed(futs):
                rec = fut.result()
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                done += 1
                if done % 25 == 0 or done == len(jobs):
                    log(f"  {done}/{len(jobs)}")

    log(f"wrote {args.output}")


if __name__ == "__main__":
    main()
