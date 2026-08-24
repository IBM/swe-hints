# `src.identifier_usage_relaxed` + `src.identifier_information` + `src.enrich_semantics` — Benchmark Commands

Step 1 (identifier extraction), step 2 (taxonomy projection), and step 3 (LLM
semantic enrichment) for all five supported benchmarks.  Run from the **hints
repo root** with the virtual environment active:

```bash
cd hints_publish && source .venv/bin/activate
```

---

## Data files (from HuggingFace)

All four input JSONL files are downloaded by
[`identity_selection/data_selection/huggingface/download.py`](../identity_selection/data_selection/huggingface/download.py):

```bash
python identity_selection/data_selection/huggingface/download.py
```

FEA-Bench patches are **not** included in the HuggingFace release.
Fetch them first with
[`get_feabench_patches.py`](../identity_selection/data_selection/huggingface/get_feabench_patches.py)
(requires `GITHUB_TOKEN`):

```bash
python identity_selection/data_selection/huggingface/get_feabench_patches.py

export GITHUB_TOKEN="your_token_here"
python -m helper_code.fea_bench_data.get_dataset \
    --dataset identity_selection/data_selection/huggingface/fea_bench_lite_hf \
    --testbed repos/feabench_repos \
    --lite_ids helper_code/fea_bench_data/instances_lite.json \
    --medium_file identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --standard_dataset_path identity_selection/data_selection/huggingface/fea_bench_Standard \
    --oracle_dataset_path identity_selection/data_selection/huggingface/fea_bench_Oracle \
    --lite_standard_dataset_path identity_selection/data_selection/huggingface/fea_bench_Lite_Standard \
    --lite_oracle_dataset_path identity_selection/data_selection/huggingface/fea_bench_Lite_Oracle
```

---

## Repository layout

```
hints/
├── src/
│   ├── identifier_usage.py        # Step 1: extract identifier sets from patches
│   ├── identifier_information.py  # Step 2: look up & project to taxonomy level
│   └── enrich_semantics.py        # After step 2: LLM enrichment of semantics fields
├── repos/
│   └── swe_pro_python_repos/      # Cloned repos for diff-based extraction
│       ├── ansible/
│       ├── openlibrary/
│       └── qutebrowser/
├── results/                       # Output directory (created at runtime)
└── requirements.txt
```

---

## Setup

```bash
cd hints
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
```

Required packages: `pydantic`, `tree-sitter-languages`, `tree-sitter==0.21.3`,
`unidiff`, `datasets`, `rich`.

> **Note:** `tree-sitter` must be pinned to `0.21.3` to match `tree-sitter-languages 1.10.2`.
> ```bash
> uv pip install "tree-sitter==0.21.3"
> ```

---

## 1. SWE-bench Pro (Python, 266 instances)

**Input:** `identity_selection/data_selection/huggingface/swebench_pro_python.jsonl`
(fields: `repo`, `base_commit`, `patch`, `test_patch`)

**Repos:** `repos/swe_pro_python_repos/` — cloned as short names (`ansible`,
`openlibrary`, `qutebrowser`)

### Step 1 — extraction

```bash
python -m src.identifier_usage_relaxed \
    --input      identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --repos-dir  repos/swe_pro_python_repos \
    --output     results/swe_pro_proj/extracted_hints.jsonl \
    --skip-errors
```

### Step 2 — projection

```bash
python -m src.identifier_information   --usage   results/swe_pro_proj/extracted_hints.json --operator communication   --level    All   --output   results/swe_pro_proj/hints_communication_all.jsonl --skip-errors
```

### Step 2.5 — filter non-empty

```bash
python helper_code/filter_nonempty_identifiers.py \
    --input  results/swe_pro_proj/hints_communication_all.jsonl \
    --output results/swe_pro_proj/hints_communication_all_nonempty.jsonl
```

### Step 3 — LLM semantic enrichment

```bash
python -m src.enrich_semantics \
    --hints    results/swe_pro_proj/hints_communication_all_nonempty.jsonl \
    --source   identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```

### Step 4 — Interface & requirements retrieval  *(SWE-bench Pro only)*

Retrieves identifiers explicitly mentioned by name in the `interface` or
`requirements` fields of the dataset, using word-boundary matching over the
largest possible candidate set (`union | catalogue`).

Output schema is identical to `identifier_information.py` so the result flows
through the same filter → enrichment pipeline unchanged.

**Inputs:**
- `data/swebench_pro_python.jsonl` — the dataset (provides `interface` +
  `requirements`)
- `results/swe_pro/extracted_hints.jsonl` — Step 1 output (provides `catalogue`
  + union sets)

```bash
# Step 4 — retrieval
python -m src.interface_retrieval \
    --dataset  data/swebench_pro_python.jsonl \
    --hints    results/swe_pro/extracted_hints.jsonl \
    --output   results/swe_pro/interface_retrieved_hints.jsonl

# Step 4.5 — filter non-empty
python helper_code/filter_nonempty_identifiers.py \
    --input  results/swe_pro/interface_retrieved_hints.jsonl \
    --output results/swe_pro/interface_retrieved_hints_nonempty.jsonl

# Step 5 — LLM semantic enrichment
python -m src.enrich_semantics \
    --hints    results/swe_pro/interface_retrieved_hints_nonempty.jsonl \
    --source   data/swebench_pro_python.jsonl \
    --output   results/swe_pro/interface_retrieved_hints_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```
---

## 2. Doc2Feat Verified (NoCode Bench)

**Input:** `identity_selection/data_selection/huggingface/doc2feat_verified.jsonl`
(HuggingFace copy; has `feature_patch`, `test_patch`, `doc_changes` — all needed
for correct extraction and doc-content filtering.)

**Repos:** `repos/doc2feat_repos/` — cloned as short names (e.g. `requests`,
`django`, `astropy`, …)

### Step 1 — extraction

```bash
python -m src.identifier_usage_relaxed \
    --input      identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --repos-dir  repos/doc2feat_repos \
    --output     results/doc2feat_proj/extracted_hints.jsonl \
    --skip-errors
```

### Step 2 — projection

```bash
python -m src.identifier_information \
    --usage    results/doc2feat_proj/extracted_hints.jsonl \
    --operator communication \
    --level    All \
    --output   results/doc2feat_proj/hints_communication_all.jsonl \
    --skip-errors
```

### Step 2.5 — filter non-empty

```bash
python helper_code/filter_nonempty_identifiers.py \
    --input  results/doc2feat_proj/hints_communication_all.jsonl \
    --output results/doc2feat_proj/hints_communication_all_nonempty.jsonl
```

### Step 3 — LLM semantic enrichment

```bash
python -m src.enrich_semantics \
    --hints    results/doc2feat_proj/hints_communication_all_nonempty.jsonl \
    --source   data/doc2feat_verified.jsonl \
    --output   results/doc2feat_proj/hints_communication_all_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```

---

## 3. SWE-Rebench Leaderboard (2026 partitions)

**Input:** `identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl`
(fields: `repo`, `base_commit`, `patch`, `test_patch`)

**Repos:** `repos/swerebench_repos/` — cloned as `org__name` slugs
(e.g. `a2a-python`, `actualpy`, …)

### Step 1 — extraction

There will be one error:
` SKIP chaoss__augur-3512: Step 1 error: CalledProcessError(128, ['git', 'checkout', '-q', 'c547710ec91e90626f475a492b93ef551f8979a7'])`

```bash
python -m src.identifier_usage_relaxed \
    --input      identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --repos-dir  repos/swerebench_repos \
    --output     results/swerebench_proj/extracted_hints.jsonl \
    --skip-errors
```

### Step 2 — projection

```bash
python -m src.identifier_information   --usage   results/swerebench_proj/extracted_hints.jsonl  --operator communication   --level    All   --output   results/swerebench_proj/hints_communication_all.jsonl --skip-errors
```

### Step 2.5 — filter non-empty

```bash
python helper_code/filter_nonempty_identifiers.py \
    --input  results/swerebench_proj/hints_communication_all.jsonl \
    --output results/swerebench_proj/hints_communication_all_nonempty.jsonl
```

### Step 3 — LLM semantic enrichment

```bash
python -m src.enrich_semantics \
    --hints    results/swerebench_proj/hints_communication_all_nonempty.jsonl \
    --source   identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --output   results/swerebench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```

---

## 4. FEA-Bench Lite (200 instances)

**Input:** `identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl`
(fields: `repo`, `base_commit`, `patch`, `test_patch` — populated by
`get_feabench_patches.py`)

**Repos:** `repos/feabench_repos/` — cloned as short names (e.g. `accelerate`,
`aider`, `astropy`, …)

### Step 1 — extraction

```bash
python -m src.identifier_usage_relaxed \
    --input      identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --repos-dir  repos/feabench_repos \
    --output     results/feabench_proj/extracted_hints.jsonl \
    --skip-errors
```

### Step 2 — projection

```bash
python -m src.identifier_information   --usage   results/feabench_proj/extracted_hints.jsonl --operator communication   --level    All   --output   results/feabench_proj/hints_communication_all.jsonl --skip-errors
```

### Step 2.5 — filter non-empty

```bash
python helper_code/filter_nonempty_identifiers.py \
    --input  results/feabench_proj/hints_communication_all.jsonl \
    --output results/feabench_proj/hints_communication_all_nonempty.jsonl
```

### Step 3 — LLM semantic enrichment

```bash
python -m src.enrich_semantics \
    --hints    results/feabench_proj/hints_communication_all_nonempty.jsonl \
    --source   identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --output   results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```

---

## 5. SWE-Rebench V2 (Python)

**Input:** `data/swerebench_v2_python_all.jsonl`
(fields: `repo`, `base_commit`, `patch`, `test_patch`, `problem_statement`)

**Repos:** `repos/swerebench_v2_repos/` — cloned as `org__name` slugs

### Step 1 — extraction

```bash
python -m src.identifier_usage_relaxed \
    --input      data/swerebench_v2_python_all.jsonl \
    --repos-dir  repos/swerebench_v2_repos \
    --output     results/swerebench_v2/extracted_hints.jsonl \
    --skip-errors
```

### Step 2 — projection

```bash
python -m src.identifier_information \
    --usage      results/swerebench_v2/extracted_hints.jsonl \
    --operator   communication \
    --level      All \
    --dataset    data/swerebench_v2_python_all.jsonl \
    --drop-uncatalogued \
    --output     results/swerebench_v2/extracted_hints_proj.jsonl \
    --skip-errors
```

### Step 2.5 — filter non-empty

```bash
python helper_code/filter_nonempty_identifiers.py \
    --input  results/swerebench_v2/hints_communication_all.jsonl \
    --output results/swerebench_v2/hints_communication_all_nonempty.jsonl
```

### Step 3 — LLM semantic enrichment

```bash
python -m src.enrich_semantics \
    --hints    results/swerebench_v2/hints_communication_all_nonempty.jsonl \
    --source   data/swerebench_v2_python_all.jsonl \
    --output   results/swerebench_v2/hints_communication_all_nonempty_enriched.jsonl \
    --workers  4 \
    --skip-errors
```

---

## Debugging a single instance

Add `--instance-id` to any command above to process just one instance:

```bash
# Step 1
python -m src.identifier_usage_relaxed \
    --input      identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --repos-dir  repos/swe_pro_python_repos \
    --output     /tmp/debug_usage.jsonl \
    --instance-id "ansible__ansible-12345"

# Step 2
python -m src.identifier_information \
    --usage      /tmp/debug_usage.jsonl \
    --operator   communication \
    --level      All \
    --dataset    identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --drop-uncatalogued \
    --output     /tmp/debug_proj.jsonl \
    --instance-id "ansible__ansible-12345"
```

---

## Step 1 output format

One JSON line per instance:

```json
{
  "instance_id": "ansible__ansible-12345",
  "code_read":  ["BaseRole", "TaskInclude"],
  "code_write": ["RoleInclude", "load_data"],
  "test_read":  ["RoleInclude", "load_data"],
  "test_write": ["test_load"],
  "catalogue":  { "RoleInclude": { "entity_type": "class", ... } }
}
```

## Step 3 output format

Same schema as step 2, with `weak_semantics` and `strong_semantics` always
populated (overwriting any existing values, including docstring-derived ones).
LLM calls are made per identifier using focused patch context.

Environment variables for the LLM endpoint:

```bash
export ENRICH_MODEL="openai/aws/claude-haiku-4-5"   # default
export ENRICH_API_BASE="https://your-litellm-endpoint"
export ENRICH_API_KEY="your-key"
```

The script is **resumable** — re-running appends only instances not already
present in the output file.

## Step 2 output format

One JSON line per instance:

```json
{
  "instance_id": "ansible__ansible-12345",
  "operator": "communication",
  "level": "All",
  "identifiers": [
    { "name": "RoleInclude", "entity_type": "class", "weak_semantics": "...", ... },
    { "name": "load_data",   "entity_type": "function", "signature": "...", ... }
  ]
}
```

Errors (when `--skip-errors` is set) are written as:

```json
{ "instance_id": "...", "error": "FileNotFoundError(...)" }
```
