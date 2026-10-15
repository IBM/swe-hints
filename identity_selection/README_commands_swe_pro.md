# SWE-Pro Annotation Pipeline — Commands

All commands are run from the **repository root**.

```bash
cd /path/to/swe-hints && source .venv/bin/activate
```

Output goes to `identity_selection/results_selection/swe_pro_sel/raw/`.

The pipeline supports three tasks via `--task`:

| Task | What it generates | Default output filename |
|---|---|---|
| `requirements` | 4–8 bullet implementation requirements | `requirements_generated_with_tests.jsonl` |
| `interface` | Structured public-API interface block | `interface_generated.jsonl` |
| `both` | Both in a single pass (recommended) | `annotations_generated.jsonl` |

---

## 1. NoCode Bench (Doc2Feat Verified)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `feature_patch` + `test_patch`).

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/ncbench_swe_pro.jsonl \
    --repos repos/doc2feat_repos
```

---

## 2. FEA-Bench (Lite, 200 instances)

The HuggingFace dataset does not include patch fields by policy.
Patches must be fetched from GitHub first — see `README_commands.md` steps 1 & 2.

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/feabench_swe_pro.jsonl \
    --repos repos/feabench_repos
```

---

## 3. SWE-bench Pro (Python, 266 instances)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `patch` + `test_patch`).

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swebench_pro_swe_pro.jsonl \
    --repos repos/swe_pro_python_repos
```

The dataset ships with official human-written annotations. Use `--use-official` to copy
them directly into the output (no LLM calls, instant):

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swebench_pro_official.jsonl \
    --use-official
```

> `--use-official` reads the `requirements` and `interface` fields already present in
> `swebench_pro_python.jsonl` and writes them to `requirements_generated` /
> `interface_generated` without calling the LLM. `--repos` is not needed.
> For any other dataset that lacks these fields the value will be `""` and a warning is printed.

---

## 4. SWE Re-Bench Leaderboard (860 instances, test split)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `patch` + `test_patch`).

> **Note:** `download.py` uses the `test` split only (860 rows).
> If `swe_rebench_leaderboard.jsonl` has 1720 rows it was downloaded with an older version — re-run `download.py` to fix it.

### First-time only — fetch dangling commits

**`tobymao/sqlglot`** — 6 commits dropped by force-push, still fetchable from GitHub:

```bash
cd repos/swerebench_repos/sqlglot && git fetch origin \
  696150dcb3337e328290434debbb28055233b2f8 \
  f5b5b9338eb92b7aa2c9b4c92c6138c2c05e1c40 \
  194850a52497300a8f1d47f2306b67cdd11ffab6 \
  74b4e7c311e9d4ff39ce2e4d91940eced96aa32f \
  2607a3ad44f039a076626abafb5340e70aa2e18b \
  bb4eda1beb68b92de9ab014a63c67797a07df2fa
cd /path/to/swe-hints
```

**`chaoss/augur`** — 1 commit permanently deleted from GitHub (HTTP 404). Cannot be recovered.
Will be skipped by `--skip-errors`:

| Instance ID | Base commit | Status |
|---|---|---|
| `chaoss__augur-3512` | `c547710ec91e90626f475a492b93ef551f8979a7` | ❌ permanently lost |

### Generate annotations

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swerebench_swe_pro.jsonl \
    --repos repos/swerebench_repos \
    --skip-errors
```

---

## Running a single task

Use `--task requirements` or `--task interface` instead of `--task both`:

```bash
# Requirements only
python identity_selection/swe_pro.py \
    --task  requirements \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swebench_pro_requirements.jsonl

# Interface only (Stage 1 AST diff requires --repos)
python identity_selection/swe_pro.py \
    --task  interface \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swebench_pro_interface.jsonl \
    --repos repos/swe_pro_python_repos
```

> **Note:** `--repos` is optional. If omitted, Stage 1 (AST diff of public symbols) is
> skipped and the interface prompt falls back to the patch alone.

---

## Debugging a single instance

Add `--instance-id` to any command above to process just one instance:

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output /tmp/test_swe_pro.jsonl \
    --repos repos/doc2feat_repos \
    --instance-id psf__requests-5856
```

---

## Smoke-test (first N instances)

Use `--limit` to stop after N instances:

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output /tmp/test_swe_pro_10.jsonl \
    --repos repos/swe_pro_python_repos \
    --limit 10
```

---

## Resume

All tasks support **resume** — if the output file already exists, completed instance IDs are
loaded from it and skipped automatically. Simply re-run the same command.

---

## Error handling

Add `--skip-errors` to continue past failed instances. LLM errors are already retried
3 times with exponential back-off; `--skip-errors` covers infrastructure errors (missing
repo, bad patch, etc.) and writes a `.errors.jsonl` sidecar:

```bash
python identity_selection/swe_pro.py \
    --task  both \
    --input identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/swe_pro_sel/raw/swebench_pro_swe_pro.jsonl \
    --repos repos/swe_pro_python_repos \
    --skip-errors
```
