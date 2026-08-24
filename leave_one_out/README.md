# Leave-One-Out (LOO) Experiment — v3

This directory contains the **v3** leave-one-out pipeline for measuring how much
removing an entire taxonomy **subgraph root** changes agent success.

> **What is v3 LOO importance?**
> For each root `r` and instance `i`, importance is
> `v(FULL_i) − v(LOO-r_i)`: the drop in resolve-rate when the entire subtree for
> `r` is withheld from an otherwise-complete hint set. Averaging over instances
> gives a per-root importance score.

---

## Files in this directory

Current v3-relevant contents of [`leave_one_out`](leave_one_out):

- [`taxonomy_game_v3.py`](leave_one_out/taxonomy_game_v3.py) — v3 taxonomy definitions and projection/rendering logic
- [`plan_loo_coalitions_v3.py`](leave_one_out/plan_loo_coalitions_v3.py) — plan NONE, FULL, and LOO-root coalitions
- [`generate_all_hints_v3.py`](leave_one_out/generate_all_hints_v3.py) — generate per-coalition agent input files
- [`run_loo_agent_v3.sh`](leave_one_out/run_loo_agent_v3.sh) — run the agent for v3 coalitions
- [`run_loo_eval_v3.sh`](leave_one_out/run_loo_eval_v3.sh) — evaluate v3 runs with SWE-bench Pro evaluation
- [`run_loo_eval_swerebench_v3.sh`](leave_one_out/run_loo_eval_swerebench_v3.sh) — evaluate v3 runs with SWErebench evaluation
- [`collect_loo_outcomes_v3.py`](leave_one_out/collect_loo_outcomes_v3.py) — collect outcomes and compute v3 importance
- [`inspect_loo_hints_v3.py`](leave_one_out/inspect_loo_hints_v3.py) — inspect rendered hints for v3 coalitions
- [`run_swerebench_all_hints.sh`](leave_one_out/run_swerebench_all_hints.sh) — all-hints baseline for SWErebench
- [`run_swerebench_no_hints.sh`](leave_one_out/run_swerebench_no_hints.sh) — no-hints baseline for SWErebench

Other files currently present but not part of the v3 workflow documentation:

- [`collect_loo_outcomes.py`](leave_one_out/collect_loo_outcomes.py)
- [`generate_all_hints.py`](leave_one_out/generate_all_hints.py)
- [`generate_baseline_jsonl.py`](leave_one_out/generate_baseline_jsonl.py)
- [`generate_feabench_inputs.py`](leave_one_out/generate_feabench_inputs.py)

---

## v3 LOO Design

Instead of leaving out a single row at a time, v3 leaves out an entire **subtree**
rooted at one of six nodes:

| Root | Subtree rows | Count |
|---|---|---|
| `File` | File, FileLoc, Import, NewFile, ModifiedFile | 5 |
| `Class` | Class, ClassName, SuperC, Generic, FuncPub, FuncPriv, LocParClass/Comp, WeakS/StrongSClass | 10 |
| `ClsFunc` | ClsFunc + all 14 class-function detail rows | 15 |
| `ClsVar` | ClsVar + all 6 class-variable detail rows | 7 |
| `Func` | Func + all 14 top-level function detail rows | 15 |
| `Var` | Var + all 6 top-level variable detail rows | 7 |

**Per-instance coalitions:**
- **NONE** — empty coalition, the no-hints baseline
- **FULL** — all active rows, the full-hints baseline
- **LOO-root** — FULL minus every row in a root's subtree

This gives `2 + |active_roots_i|` coalitions per instance.

**Importance:**
```
importance(root) = mean_i [ v(FULL_i) − v(LOO-root_i) ]
```

---

## v3 Taxonomy

[`taxonomy_game_v3.py`](leave_one_out/taxonomy_game_v3.py) makes [`File`](leave_one_out/taxonomy_game_v3.py) and [`Class`](leave_one_out/taxonomy_game_v3.py) top-level peers.
The LOO roots are:

- `File`
- `Class`
- `ClsFunc`
- `ClsVar`
- `Func`
- `Var`

Conceptually:

```
File
├── FileLoc → NewFile, ModifiedFile
├── Import
├── Func → ...
└── Var  → ...

Class
├── ClassName, SuperC, Generic, FuncPub → FuncPriv
├── LocParClass → LocCompClass
├── WeakSClass  → StrongSClass
├── ClsFunc → ...
└── ClsVar  → ...
```

---

## v3 Workflow

### 1. Plan coalitions

```bash
python leave_one_out/plan_loo_coalitions_v3.py \
    --hints leave_one_out/output/hints_helped_enriched.jsonl \
    --output-dir leave_one_out/runs/loo_helped_v3_r1
```

### 2. Generate agent inputs

```bash
python leave_one_out/generate_all_hints_v3.py \
    --hints leave_one_out/output/hints_helped_enriched.jsonl \
    --run-dir leave_one_out/runs/loo_helped_v3_r1
```

### 3. Run agent

```bash
bash leave_one_out/run_loo_agent_v3.sh loo_helped_v3_r1 20
```

### 4. Evaluate

For SWE-bench Pro style evaluation:

```bash
bash leave_one_out/run_loo_eval_v3.sh loo_helped_v3_r1
```

For SWErebench evaluation:

```bash
bash leave_one_out/run_loo_eval_swerebench_v3.sh loo_swerebench_v3_r1
```

### 5. Collect outcomes

```bash
python leave_one_out/collect_loo_outcomes_v3.py loo_helped_v3_r1
```


---

## Baseline Input Generation — No-Hints, All-Hints, and Name-Only

These three scripts produce flat mini-SWE-agent input JSONLs that serve as
baselines bracketing (and supplementing) the LOO experiment.  All commands
run from `PATH_TO/hints_publish`.

| Baseline | Script | Hints content |
|---|---|---|
| **No hints** | `generate_baseline_jsonl.py` | `hints: ""` — agent sees nothing |
| **All hints** | `generate_baseline_jsonl.py` | Full taxonomy rendered via `render_hint()` |
| **Name only** | `generate_nameonly_jsonl.py` | Bare identifier names, no path/signature/semantics |

---

### `generate_baseline_jsonl.py` — No-Hints and All-Hints

Generates both the NONE and FULL baselines in one pass.  The output stem
is derived from the hints filename unless overridden explicitly.

```bash
# SWErebench v2 — 300-instance subsample
python leave_one_out/generate_baseline_jsonl.py \
    --hints    results/swerebench_v2/hints_communication_all_nonempty_300_enriched.jsonl \
    --swebench data/swerebench_v2_python_all.jsonl \
    --all-hints-out leave_one_out/output/swerebench_v2_300_all_hints_v3.jsonl \
    --no-hints-out  leave_one_out/output/swerebench_v2_300_no_hints_v3.jsonl

# SWErebench (2025 + 2026 merged)
python leave_one_out/generate_baseline_jsonl.py \
    --hints    results/swerebench/hints_communication_all_nonempty_merged.jsonl \
    --swebench data/swerebench_2025.jsonl data/swerebench_2026.jsonl \
    --output-dir leave_one_out/output

# SWE-bench Pro
python leave_one_out/generate_baseline_jsonl.py \
    --hints    leave_one_out/output/hints_helped_enriched.jsonl \
    --swebench data/swebench_pro_python.jsonl \
    --output-dir leave_one_out/output
```

**Key flags**

| Flag | Description |
|---|---|
| `--hints` | Enriched hints JSONL (output of `enrich_semantics.py`) |
| `--swebench` | One or more SWE-bench source JSONLs (provides `image_name`, `problem_statement`, etc.) |
| `--output-dir` | Directory for auto-named outputs (`<stem>_all_hints_v3.jsonl` / `<stem>_no_hints_v3.jsonl`) |
| `--all-hints-out` | Explicit path for the all-hints output |
| `--no-hints-out` | Explicit path for the no-hints output |
| `--dockerhub` | DockerHub username for swe_pro image URI fallback (default: `jefzda`) |

---

### `generate_nameonly_jsonl.py` — Name-Only Hints

Exposes only the bare identifier names — no path, signature, semantics,
imports, or location.  Files are reduced to their filename stem
(e.g. `http.py`, not `src/websockets/http.py`).  All names are listed
alphabetically under a single `## Identifier Hints:` header.

```bash
# SWErebench v2 — 300-instance subsample
python leave_one_out/generate_nameonly_jsonl.py \
    --hints    results/swerebench_v2/hints_communication_all_nonempty_300_enriched.jsonl \
    --swebench data/swerebench_v2_python_all.jsonl \
    --output   leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl

# SWErebench (2025 + 2026 merged)
python leave_one_out/generate_nameonly_jsonl.py \
    --hints    results/swerebench/hints_communication_all_nonempty_merged.jsonl \
    --swebench data/swerebench_2025.jsonl data/swerebench_2026.jsonl \
    --output   leave_one_out/output/swerebench_name_only_v3.jsonl
```

**Key flags**

| Flag | Description |
|---|---|
| `--hints` | Enriched hints JSONL |
| `--swebench` | One or more SWE-bench source JSONLs |
| `--output` | Output JSONL path |
| `--dockerhub` | DockerHub username for swe_pro image URI fallback (default: `jefzda`) |

**Example output** for a single instance:

```
## Identifier Hints:
- UnknownCommitMessageStyle
- changelog
- check_token
- current_commit_parser
- footer
- generate_changelog
- logs.py
- markdown_changelog
- parser_angular.py
- text
```

---

### Running the agent on baselines

After generating the input JSONLs, run `mini-extra` from `/PATH/TO/mini-swe-agent`:

```bash
cd /PATH/TO/mini-swe-agent
source .venv/bin/activate

# No hints
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_ds.yaml \
    --subset  /PATH/TO/hints_publish/leave_one_out/output/swerebench_v2_300_no_hints_v3.jsonl \
    --workers 30 \
    --output  ./loo/swerebench_v2_300_no_hints

# All hints
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_ds.yaml \
    --subset  /PATH/TO/hints_publish/leave_one_out/output/swerebench_v2_300_all_hints_v3.jsonl \
    --workers 30 \
    --output  ./loo/swerebench_v2_300_all_hints

# Name only
mini-extra swebench \
    -c swerebench_hints.yaml \
    -c rits_swebench_ds.yaml \
    --subset  /PATH/TO/hints_publish/leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl \
    --workers 30 \
    --output  ./loo/swerebench_v2_300_name_only
```

> **Pre-pull Docker images** before running to avoid per-instance pull timeouts:
>
> ```bash
> python3 -c "
> import json
> ids = set()
> with open('results/swerebench_v2/hints_communication_all_nonempty_300_enriched.jsonl') as f:
>     for line in f: ids.add(json.loads(line)['instance_id'])
> with open('data/swerebench_v2_python_all.jsonl') as f:
>     for line in f:
>         rec = json.loads(line)
>         if rec['instance_id'] in ids: print(rec['image_name'])
> " | sort -u | xargs -P 32 -I{} docker pull {}
> ```

---

### Inspecting hint content

Use `helper_code/print_hints.py` to inspect any of the generated JSONLs:

```bash
# Browse all instances
python helper_code/print_hints.py \
    --input leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl | less

# Single instance
python helper_code/print_hints.py \
    --input leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl \
    --instance-id relekang__python-semantic-release-21

# Compare name-only vs all-hints side by side
python helper_code/print_hints.py \
    --input   leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl \
    --compare leave_one_out/output/swerebench_v2_300_all_hints_v3.jsonl \
    --limit 5 | less
```
