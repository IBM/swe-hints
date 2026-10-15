#!/usr/bin/env python3
#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""Aggregate hint-attribute judgments into the paper table.

Reads the JSONL from hint_attribute_judge.py and reports, per attribute:

    n     judgments (attributes are present on DIFFERENT subsets - `signature`
          exists only on functions, `path`/`is_new_file` only on 58/160 - so the
          means are over different populations and n must be shown)
    N     necessity        0 redundant .. 3 load-bearing
    D     disclosure       0 interface .. 3 transcription
    G     guidance         0 declarative .. 3 prescriptive
    HVM   N - max(D,G)     positive = supplies more than it gives away

CONFIDENCE INTERVALS ARE CLUSTERED BY INSTANCE.  Identifiers are not independent:
160 of them come from 68 instances, and one instance contributes 12.  A naive
per-judgment interval would understate the uncertainty, so the bootstrap resamples
INSTANCES, not judgments.

BIMODAL ATTRIBUTES ARE SPLIT, NOT AVERAGED.  For `name` the score is not unimodal:
identifiers absent from the repository score 3 (the agent must invent a name the
test then demands) and identifiers already present score 1 (grep finds them).  The
mean of those two populations describes neither, so --split reports the shares.

Usage
-----
    python helper_code/judge/report_attribute_scores.py \\
        --input results/judge/swe_pro_attr_judgments.jsonl --latex
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

ATTR_ORDER = ["name", "entity_type", "path", "is_new_file",
              "signature", "weak_semantics", "strong_semantics"]

# The structural/semantic split IS the result, so the table is grouped by it rather
# than listing attributes in pipeline order. Every structural attribute scores D=0
# by construction (rubric level 0 is "identity and addressing", which is what they
# are), so the contrast that carries information is the D column between blocks.
GROUPS = [("Structural (interface-level)",
           ["signature", "name", "entity_type", "is_new_file", "path"]),
          ("Semantic (behaviour-level)",
           ["strong_semantics", "weak_semantics"])]

PRETTY = {"name": "Name", "entity_type": "Entity type", "path": "Path",
          "is_new_file": "Is new file", "signature": "Signature",
          "weak_semantics": "Weak semantics", "strong_semantics": "Strong semantics"}


def cluster_bootstrap(recs: list[dict], field: str, iters: int = 2000, seed: int = 0):
    """95% CI for the mean of `field`, resampling INSTANCES rather than judgments."""
    by_inst = defaultdict(list)
    for r in recs:
        v = r.get(field)
        if v is not None:
            by_inst[r["instance_id"]].append(v)
    insts = list(by_inst)
    if len(insts) < 2:
        return (None, None)
    rng = random.Random(seed)
    means = []
    for _ in range(iters):
        pick = [rng.choice(insts) for _ in insts]
        vals = [v for i in pick for v in by_inst[i]]
        if vals:
            means.append(st.mean(vals))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", type=Path, required=True)
    ap.add_argument("--latex", action="store_true", help="Also emit a LaTeX table.")
    ap.add_argument("--functions-only", action="store_true",
                    help="Restrict to function identifiers, the only subset carrying "
                         "all seven attributes - the apples-to-apples comparison.")
    args = ap.parse_args()

    recs = [json.loads(l) for l in args.input.open(encoding="utf-8") if l.strip()]
    recs = [r for r in recs if r.get("N") is not None]
    if args.functions_only:
        recs = [r for r in recs if r.get("entity_type") == "function"]

    inst = {r["instance_id"] for r in recs}
    print(f"{len(recs)} judgments over {len(inst)} instances"
          + ("   [functions only]" if args.functions_only else ""))

    def stats(g):
        return (len(g), st.mean(r["N"] for r in g), st.mean(r["D"] for r in g),
                st.mean(r["G"] for r in g), st.mean(r["HVM"] for r in g))

    print(f"\n{'attribute':22s} {'n':>4s} {'N':>5s} {'D':>5s} {'G':>5s} {'HVM':>7s}"
          f" {'HVM 95% CI':>16s} {'agree':>6s}")
    print("-" * 78)
    table = []
    for gname, attrs in GROUPS:
        print(f"{gname}")
        block = []
        rows_here = [(a, [r for r in recs if r["attribute"] == a]) for a in attrs]
        rows_here = [(a, g) for a, g in rows_here if g]
        # within a block, strongest margin first
        rows_here.sort(key=lambda ag: -st.mean(r["HVM"] for r in ag[1]))
        for a, g in rows_here:
            n, N, D, G, H = stats(g)
            lo, hi = cluster_bootstrap(g, "HVM")
            un = sum(1 for r in g if all(r["agreement"].get(k) for k in ("N", "D", "G")))
            # a margin whose interval spans 0 is not distinguishable from break-even
            mark = " " if (lo is not None and lo > 0) else "*"
            ci = f"[{lo:+.2f}, {hi:+.2f}]" if lo is not None else "—"
            print(f"  {PRETTY.get(a,a):20s} {n:4d} {N:5.2f} {D:5.2f} {G:5.2f} "
                  f"{H:+6.2f}{mark} {ci:>16s} {100*un/len(g):5.0f}%")
            block.extend(g)
            table.append((gname, a, n, N, D, G, H, lo, hi))
        n, N, D, G, H = stats(block)
        print(f"  {'— group mean':20s} {n:4d} {N:5.2f} {D:5.2f} {G:5.2f} {H:+6.2f}")
    print("-" * 78)
    print("* HVM interval spans 0: not distinguishable from break-even.")

    # Bimodal attributes: report the split, not the mean.
    print("\nnecessity distribution (a mean hides a bimodal attribute):")
    for a in ATTR_ORDER:
        g = [r for r in recs if r["attribute"] == a]
        if not g:
            continue
        d = Counter(r["N"] for r in g)
        parts = "  ".join(f"N={k}:{d[k]:3d}" for k in sorted(d))
        print(f"  {a:18s} {parts}")

    # The measured split for `name`, where recoverability is a fact not a judgment.
    nm = [r for r in recs if r["attribute"] == "name"
          and "name_in_repo_at_base" in r.get("mechanical", {})]
    if nm:
        ex = [r for r in nm if r["mechanical"]["name_in_repo_at_base"]]
        ab = [r for r in nm if not r["mechanical"]["name_in_repo_at_base"]]
        print(f"\n`name` against the repository at base commit (git grep, not judged):")
        print(f"  absent from repo -> agent must invent : {len(ab):3d} "
              f"({100*len(ab)/len(nm):.0f}%)  mean N={st.mean(r['N'] for r in ab) if ab else 0:.2f}")
        print(f"  present in repo  -> findable by grep  : {len(ex):3d} "
              f"({100*len(ex)/len(nm):.0f}%)  mean N={st.mean(r['N'] for r in ex) if ex else 0:.2f}")

    if args.latex:
        print("\n" + r"\begin{table}[ht]\centering")
        print(r"\caption{Hint attribute scores on SWE-bench Pro (DefUse selection, "
              r"68 instances, 787 judgments). $N$ necessity (0 redundant--3 "
              r"load-bearing), $D$ disclosure (0 interface--3 transcription), $G$ "
              r"behavioural guidance (0 declarative--3 prescriptive). "
              r"$\mathrm{HVM}=N-\max(D,G)$: positive means the attribute supplies more "
              r"unrecoverable information than it reveals of the solution. Intervals are "
              r"instance-clustered bootstrap; $^{*}$ marks a margin indistinguishable "
              r"from break-even. Structural attributes score $D=0$ by construction, the "
              r"rubric's interface level. Judge: GPT-5.6 Luna, median of 3 samples.}")
        print(r"\label{tab:hint_attribute_scores}")
        print(r"\begin{tabular}{lrrrrr}")
        print(r"\toprule")
        print(r"\textbf{Attribute} & \textbf{n} & $N$ & $D$ & $G$ & \textbf{HVM} \\")
        for gi, (gname, _) in enumerate(GROUPS):
            rows = [t for t in table if t[0] == gname]
            if not rows:
                continue
            print(r"\midrule")
            print(r"\multicolumn{6}{l}{\textit{" + gname + r"}} \\")
            for _, a, n, N, D, G, H, lo, hi in rows:
                mark = "" if (lo is not None and lo > 0) else r"$^{*}$"
                print(f"\\quad {PRETTY.get(a,a)} & {n} & {N:.2f} & {D:.2f} & {G:.2f} "
                      f"& ${H:+.2f}${mark} \\\\")
            bn = sum(t[2] for t in rows)
            import statistics as _st
            allg = [r for r in recs if r["attribute"] in [t[1] for t in rows]]
            print(f"\\quad \\emph{{group mean}} & {bn} & "
                  f"{_st.mean(r['N'] for r in allg):.2f} & "
                  f"{_st.mean(r['D'] for r in allg):.2f} & "
                  f"{_st.mean(r['G'] for r in allg):.2f} & "
                  f"$\\mathbf{{{_st.mean(r['HVM'] for r in allg):+.2f}}}$ \\\\")
        print(r"\bottomrule")
        print(r"\end{tabular}")
        print(r"\end{table}")


if __name__ == "__main__":
    main()
