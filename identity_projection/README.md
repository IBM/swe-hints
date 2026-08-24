# Identity Projection

Applies taxonomy projections to enriched identifier hints.

**Input:** `results/<bench>/hints_communication_all_nonempty_enriched.jsonl`  
**Script:** `identity_projection/project_enriched.py`  
**Output:** `identity_projection/results_projection/<proj>_proj/<bench>.jsonl`

---

## Projections

| Projection | Fields exposed per identifier |
|---|---|
| `nocode` | `name`, `entity_type` |
| `fea_brief` | `name`, `entity_type`, `path`, `is_new_file`, `signature`, `weak_semantics` |
| `swe_pro` | `name`, `entity_type`, `path`, `is_new_file`, `signature`, `weak_semantics`, `strong_semantics` |

For `fea_brief` and `swe_pro`, class identifiers also carry projected
`cls_methods` and `cls_variables` sub-records using the same field subset
(minus `path` / `is_new_file`, which are inherited from the parent class).

---

## Benchmarks

| Benchmark | Enriched input |
|---|---|
| `doc2feat` | `results/doc2feat_proj/hints_communication_all_nonempty_enriched.jsonl` |
| `feabench` | `results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl` |
| `swe_pro` | `results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl` |
| `swerebench` | `results/swerebench_proj/hints_communication_all_nonempty_enriched.jsonl` |

---

## Commands

Run from repo root with the virtual environment active:

```bash
cd /path/to/hints_publish && source .venv/bin/activate
```

### nocode projection

```bash
python identity_projection/project_enriched.py \
    --input   results/doc2feat_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/nocode_proj/doc2feat_nocode_proj.jsonl \
    --projection nocode

python identity_projection/project_enriched.py \
    --input   results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/nocode_proj/feabench_nocode_proj.jsonl \
    --projection nocode

python identity_projection/project_enriched.py \
    --input   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/nocode_proj/swe_pro_nocode_proj.jsonl \
    --projection nocode

python identity_projection/project_enriched.py \
    --input   results/swerebench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/nocode_proj/swerebench_nocode_proj.jsonl \
    --projection nocode
```

### fea_brief projection

```bash
python identity_projection/project_enriched.py \
    --input   results/doc2feat_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/fea_brief_proj/doc2feat_fea_brief_proj.jsonl \
    --projection fea_brief

python identity_projection/project_enriched.py \
    --input   results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/fea_brief_proj/feabench_fea_brief_proj.jsonl \
    --projection fea_brief

python identity_projection/project_enriched.py \
    --input   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/fea_brief_proj/swe_pro_fea_brief_proj.jsonl \
    --projection fea_brief

python identity_projection/project_enriched.py \
    --input   results/swerebench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/fea_brief_proj/swerebench_fea_brief_proj.jsonl \
    --projection fea_brief
```

### swe_pro projection

```bash
python identity_projection/project_enriched.py \
    --input   results/doc2feat_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/swe_pro_proj/doc2feat_swe_pro_proj.jsonl \
    --projection swe_pro

python identity_projection/project_enriched.py \
    --input   results/feabench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/swe_pro_proj/feabench_swe_pro_proj.jsonl \
    --projection swe_pro

python identity_projection/project_enriched.py \
    --input   results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/swe_pro_proj/swe_pro_swe_pro_proj.jsonl \
    --projection swe_pro

python identity_projection/project_enriched.py \
    --input   results/swerebench_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output  identity_projection/results_projection/swe_pro_proj/swerebench_swe_pro_proj.jsonl \
    --projection swe_pro
```

---

---

## Step 2 — Generate mini-SWE-agent instances

Uses [`identity_projection/generate_instances.py`](generate_instances.py).

- **swebench_pro**: `image_name` built from `dockerhub_tag` — `--dockerhub_username` required.
- **swerebench**: `image_name` taken directly from the source row.
- **doc2feat**: handled by `helper_code/generate_doc2feat_instances.py` — not covered here.

Output goes to `identity_projection/mini_swe/<proj>/<bench>_<proj>.jsonl`.

### nocode — swebench_pro

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/nocode_proj/swe_pro_nocode_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --benchmark  swebench_pro \
    --projection nocode \
    --dockerhub_username jefzda \
    --output     identity_projection/mini_swe/nocode/swe_pro_nocode.jsonl
```

### nocode — swerebench

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/nocode_proj/swerebench_nocode_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --benchmark  swerebench \
    --projection nocode \
    --output     identity_projection/mini_swe/nocode/swerebench_nocode.jsonl
```

### fea_brief — swebench_pro

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/fea_brief_proj/swe_pro_fea_brief_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --benchmark  swebench_pro \
    --projection fea_brief \
    --dockerhub_username jefzda \
    --output     identity_projection/mini_swe/fea_brief/swe_pro_fea_brief.jsonl
```

### fea_brief — swerebench

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/fea_brief_proj/swerebench_fea_brief_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --benchmark  swerebench \
    --projection fea_brief \
    --output     identity_projection/mini_swe/fea_brief/swerebench_fea_brief.jsonl
```

### swe_pro — swebench_pro

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/swe_pro_proj/swe_pro_swe_pro_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --benchmark  swebench_pro \
    --projection swe_pro \
    --dockerhub_username jefzda \
    --output     identity_projection/mini_swe/swe_pro/swe_pro_swe_pro.jsonl
```

### swe_pro — swerebench

```bash
python identity_projection/generate_instances.py \
    --hints      identity_projection/results_projection/swe_pro_proj/swerebench_swe_pro_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --benchmark  swerebench \
    --projection swe_pro \
    --output     identity_projection/mini_swe/swe_pro/swerebench_swe_pro.jsonl
```

---

## Step 2b — Generate mini-SWE-agent instances for Doc2Feat-bench

Uses [`identity_projection/generate_doc2feat_instances.py`](generate_doc2feat_instances.py).
No `--dockerhub_username` or `image_name` — doc2feat has no Docker images.
The baked-in augmentation block is stripped from `problem_statement` automatically.

### nocode — doc2feat

```bash
python identity_projection/generate_doc2feat_instances.py \
    --hints      identity_projection/results_projection/nocode_proj/doc2feat_nocode_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --projection nocode \
    --output     identity_projection/mini_swe/nocode/doc2feat_nocode.jsonl
```

### fea_brief — doc2feat

```bash
python identity_projection/generate_doc2feat_instances.py \
    --hints      identity_projection/results_projection/fea_brief_proj/doc2feat_fea_brief_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --projection fea_brief \
    --output     identity_projection/mini_swe/fea_brief/doc2feat_fea_brief.jsonl
```

### swe_pro — doc2feat

```bash
python identity_projection/generate_doc2feat_instances.py \
    --hints      identity_projection/results_projection/swe_pro_proj/doc2feat_swe_pro_proj.jsonl \
    --source     identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --projection swe_pro \
    --output     identity_projection/mini_swe/swe_pro/doc2feat_swe_pro.jsonl
```

---

## Debugging a single instance

Add `--instance-id` to any command:

```bash
python identity_projection/project_enriched.py \
    --input      results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --output     /tmp/debug.jsonl \
    --projection swe_pro \
    --instance-id "instance_ansible__ansible-395e5e20fab9cad517243372fa3c3c5d9e09ab2a-v7eee2454f617569fd6889f2211f75bc02a35f9f8"
```
