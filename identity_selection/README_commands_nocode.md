# NoCode Identity Selection — Commands

All commands are run from the **hints repo root** (`hints_publish`).

```bash
cd /path/to/hints_publish && source .venv/bin/activate
```

---

## 1. NoCode Bench (Doc2Feat Verified)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `feature_patch` + `test_patch`).

```bash
python identity_selection/nocode.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output identity_selection/results_selection/nocode_sel/raw/ncbench_nocode.jsonl \
    --repos  repos/doc2feat_repos
```

---

## 2. FEA-Bench (Lite, 200 instances)

The HuggingFace dataset does not include patch fields by policy.
Patches must be fetched from GitHub first.

**Step 1 — Convert lite JSONL to HF Arrow format:**

```bash
python identity_selection/data_selection/huggingface/get_feabench_patches.py
```

**Step 2 — Fetch patches from GitHub (requires `GITHUB_TOKEN`):**

```bash
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

Step 2 is resumable — re-running skips instances already written to the output JSONL.

**Step 3 — Generate nocode hints:**

```bash
python identity_selection/nocode.py \
    --input  identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --output identity_selection/results_selection/nocode_sel/raw/feabench_nocode.jsonl \
    --repos  repos/feabench_repos
```

---

## 3. SWE-bench Pro (Python, 266 instances)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `patch` + `test_patch`).

```bash
python identity_selection/nocode.py \
    --input  identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/nocode_sel/raw/swebench_pro_nocode.jsonl \
    --repos  repos/swe_pro_python_repos
```

---

## 4. SWE Re-Bench Leaderboard (860 instances, test split)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `patch` + `test_patch`).

> **Note:** `download.py` uses the `test` split only (860 rows).  
> If `swe_rebench_leaderboard.jsonl` has 1720 rows it was downloaded with an older version — re-run `download.py` to fix it.

```bash
python identity_selection/nocode.py \
    --input  identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --output identity_selection/results_selection/nocode_sel/raw/swerebench_nocode.jsonl \
    --repos  repos/swerebench_repos
```

---

## Debugging a single instance

Add `--instance-id` to any command above to process just one instance:

```bash
python identity_selection/nocode.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output /tmp/test_nocode.jsonl \
    --repos  repos/doc2feat_repos \
    --instance-id psf__requests-5856
```
