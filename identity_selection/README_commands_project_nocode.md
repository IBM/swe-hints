# NoCode Projection — Commands

All commands are run from the **repository root**.

```bash
cd /path/to/swe-hints && source .venv/bin/activate
```

Output goes to `projected_nocode/` under each selection folder.

---

## What this does

Given the `union_defuse_nocode/` files produced by each selector, the projection
applies a **uniform NoCode view**: every instance is reduced to just its
`{type, name}` entity list, regardless of which selector produced the file.

Two `augmentations` shapes are handled:
- **Flat** (`nocode` / `fea_brief`): `{header, data: [{type, name}]}`
- **Directional** (`defuse2`): `{forward: {data}, backward: {data}}`
  — both lists are merged into a single flat `data` list.

Output per instance (`projected_nocode/*.jsonl`):
```json
{
  "instance_id": "...",
  "repo": "...",
  "hints": {
    "header": "If completing this task requires creating new files, classes, fields, or error messages, you may consider using the following suggested entity names:",
    "data": [{"type": "function", "name": "..."}, ...]
  }
}
```

---

## 1. fea_brief_sel

```bash
python identity_selection/project_nocode.py \
    --input  identity_selection/results_selection/fea_brief_sel/union_defuse_nocode \
    --output identity_selection/results_selection/fea_brief_sel/projected_nocode
```

---

## 2. defuse2_sel

```bash
python identity_selection/project_nocode.py \
    --input  identity_selection/results_selection/defuse2_sel/union_defuse_nocode \
    --output identity_selection/results_selection/defuse2_sel/projected_nocode
```

---

## 3. nocode_sel

```bash
python identity_selection/project_nocode.py \
    --input  identity_selection/results_selection/nocode_sel/union_defuse_nocode \
    --output identity_selection/results_selection/nocode_sel/projected_nocode
```

---

## 4. defuse2_relaxed_sel

```bash
python identity_selection/project_nocode.py \
    --input  identity_selection/results_selection/defuse2_relaxed_sel/union_defuse_nocode \
    --output identity_selection/results_selection/defuse2_relaxed_sel/projected_nocode
```



---

## 5. swe_pro_sel (LLM NoCode Projection)

Project LLM-generated requirements and interface hints (`swe_pro_sel/union_defuse_nocode`) into NoCode `{type, name}` entity hints using [`project_swe_pro_nocode_llm.py`](project_swe_pro_nocode_llm.py):

### 1. feabench_swe_pro
```bash
python identity_selection/project_swe_pro_nocode_llm.py \
    --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/feabench_swe_pro.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/projected_nocode/feabench_swe_pro.jsonl
```

### 2. ncbench_swe_pro
```bash
python identity_selection/project_swe_pro_nocode_llm.py \
    --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/ncbench_swe_pro.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/projected_nocode/ncbench_swe_pro.jsonl
```

### 3. swebench_pro_official & swebench_pro_swe_pro
```bash
python identity_selection/project_swe_pro_nocode_llm.py \
    --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/swebench_pro_official.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/projected_nocode/swebench_pro_official.jsonl

python identity_selection/project_swe_pro_nocode_llm.py \
    --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/swebench_pro_swe_pro.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/projected_nocode/swebench_pro_swe_pro.jsonl
```

### 4. swerebench_swe_pro
```bash
python identity_selection/project_swe_pro_nocode_llm.py \
    --input  identity_selection/results_selection/swe_pro_sel/union_defuse_nocode/swerebench_swe_pro.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/projected_nocode/swerebench_swe_pro.jsonl
```
---

## Output files (already generated)

| Selector | File | Instances |
|---|---|---|
| `fea_brief_sel` | `feabench_fea_brief.jsonl` | 148 |
| `fea_brief_sel` | `ncbench_fea_brief.jsonl` | 31 |
| `fea_brief_sel` | `swebench_pro_fea_brief.jsonl` | 131 |
| `fea_brief_sel` | `swerebench_fea_brief.jsonl` | 26 |
| `defuse2_sel` | `feabench_defuse2.jsonl` | 148 |
| `defuse2_sel` | `ncbench_defuse2.jsonl` | 31 |
| `defuse2_sel` | `swebench_pro_defuse2.jsonl` | 131 |
| `defuse2_sel` | `swerebench_defuse2.jsonl` | 25 |
| `nocode_sel` | `feabench_nocode.jsonl` | 148 |
| `nocode_sel` | `ncbench_nocode.jsonl` | 31 |
| `nocode_sel` | `swebench_pro_nocode.jsonl` | 131 |
| `nocode_sel` | `swerebench_nocode.jsonl` | 26 |

---

## Step 2 — Generate mini-SWE-agent JSONL files

> **Not runnable from this repository.** Steps 2 and 2b call generators with
> `--selection_hints` / `--selection_base`, which no script here provides. To turn the
> `projected_nocode/` files from step 1 into agent instances, run
> `build_selection_enriched.py` and then `identity_projection/` (README.md in this folder,
> section 3).

Uses a `generate_minisweagent_instances.py` that takes `--selection_hints` (not in this repository)
with `--selection_hints` (projected_nocode) + `--selection_base` (union_defuse_nocode).

- **swerebench**: `image_name` is taken directly from the base row — no `--dockerhub_username` needed.
- **swebench_pro**: `image_name` is built as `<dockerhub_username>/<dockerhub_tag>` — `--dockerhub_username` is required.

### defuse2_relaxed — swebench_pro

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swebench_pro \
    --dockerhub_username jefzda \
    --selection_hints identity_selection/results_selection/defuse2_relaxed_sel/projected_nocode/swebench_pro_defuse2_relaxed.jsonl \
    --selection_base  identity_selection/results_selection/defuse2_relaxed_sel/union_defuse_nocode/swebench_pro_defuse2_relaxed.jsonl \
    --output_path     identity_selection/mini_swe/defuse2_relaxed/swebench_pro_defuse2.jsonl
```

### defuse2_relaxed — swerebench

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swerebench \
    --selection_hints identity_selection/results_selection/defuse2_relaxed_sel/projected_nocode/swerebench_defuse2_relaxed.jsonl \
    --selection_base  identity_selection/results_selection/defuse2_relaxed_sel/union_defuse_nocode/swerebench_defuse2_relaxed.jsonl \
    --output_path     identity_selection/mini_swe/defuse2_relaxed/swerebench_defuse2.jsonl
```

### fea_brief — swebench_pro

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swebench_pro \
    --dockerhub_username jefzda \
    --selection_hints identity_selection/results_selection/fea_brief_sel/projected_nocode/swebench_pro_fea_brief.jsonl \
    --selection_base  identity_selection/results_selection/fea_brief_sel/union_defuse_nocode/swebench_pro_fea_brief.jsonl \
    --output_path     identity_selection/mini_swe/fea_brief/swebench_pro_fea_brief.jsonl
```

### fea_brief — swerebench

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swerebench \
    --selection_hints identity_selection/results_selection/fea_brief_sel/projected_nocode/swerebench_fea_brief.jsonl \
    --selection_base  identity_selection/results_selection/fea_brief_sel/union_defuse_nocode/swerebench_fea_brief.jsonl \
    --output_path     identity_selection/mini_swe/fea_brief/swerebench_fea_brief.jsonl
```

### nocode — swebench_pro

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swebench_pro \
    --dockerhub_username jefzda \
    --selection_hints identity_selection/results_selection/nocode_sel/projected_nocode/swebench_pro_nocode.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/swebench_pro_nocode.jsonl \
    --output_path     identity_selection/mini_swe/nocode/swebench_pro_nocode.jsonl
```

### nocode — swerebench

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swerebench \
    --selection_hints identity_selection/results_selection/nocode_sel/projected_nocode/swerebench_nocode.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/swerebench_nocode.jsonl \
    --output_path     identity_selection/mini_swe/nocode/swerebench_nocode.jsonl
```

### swe_pro — swebench_pro

Uses `nocode_sel/union_defuse_nocode/swebench_pro_nocode.jsonl` as the base (full rows); the join restricts output to the `swe_pro_sel` instance subset.

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swebench_pro \
    --dockerhub_username jefzda \
    --selection_hints identity_selection/results_selection/swe_pro_sel/projected_nocode/swebench_pro_official.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/swebench_pro_nocode.jsonl \
    --output_path     identity_selection/mini_swe/swe_pro/swebench_pro_official.jsonl
```

### swe_pro — swerebench

```bash
python helper_code/generate_minisweagent_instances.py \
    --benchmark swerebench \
    --selection_hints identity_selection/results_selection/swe_pro_sel/projected_nocode/swerebench_swe_pro.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/swerebench_nocode.jsonl \
    --output_path     identity_selection/mini_swe/swe_pro/swerebench_swe_pro.jsonl
```

---

## Step 2b — Generate mini-SWE-agent JSONL files for ncbench (Doc2Feat-bench)

Uses [`helper_code/generate_doc2feat_instances.py`](../helper_code/generate_doc2feat_instances.py)
with `--selection_hints` (projected_nocode) + `--selection_base` (union_defuse_nocode).
No `--dockerhub_username` needed — ncbench has no Docker images.

> **Note:** `swe_pro_sel` uses `nocode_sel/union_defuse_nocode/ncbench_nocode.jsonl` as
> base because its own union file has no `problem_statement`.

### defuse2_relaxed — ncbench

```bash
python helper_code/generate_doc2feat_instances.py \
    --selection_hints identity_selection/results_selection/defuse2_relaxed_sel/projected_nocode/ncbench_defuse2_relaxed.jsonl \
    --selection_base  identity_selection/results_selection/defuse2_relaxed_sel/union_defuse_nocode/ncbench_defuse2_relaxed.jsonl \
    --output_path     identity_selection/mini_swe/defuse2_relaxed/ncbench_defuse2.jsonl
```

### fea_brief — ncbench

```bash
python helper_code/generate_doc2feat_instances.py \
    --selection_hints identity_selection/results_selection/fea_brief_sel/projected_nocode/ncbench_fea_brief.jsonl \
    --selection_base  identity_selection/results_selection/fea_brief_sel/union_defuse_nocode/ncbench_fea_brief.jsonl \
    --output_path     identity_selection/mini_swe/fea_brief/ncbench_fea_brief.jsonl
```

### nocode — ncbench

```bash
python helper_code/generate_doc2feat_instances.py \
    --selection_hints identity_selection/results_selection/nocode_sel/projected_nocode/ncbench_nocode.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/ncbench_nocode.jsonl \
    --output_path     identity_selection/mini_swe/nocode/ncbench_nocode.jsonl
```

### swe_pro — ncbench

```bash
python helper_code/generate_doc2feat_instances.py \
    --selection_hints identity_selection/results_selection/swe_pro_sel/projected_nocode/ncbench_swe_pro.jsonl \
    --selection_base  identity_selection/results_selection/nocode_sel/union_defuse_nocode/ncbench_nocode.jsonl \
    --output_path     identity_selection/mini_swe/swe_pro/ncbench_swe_pro.jsonl
```
