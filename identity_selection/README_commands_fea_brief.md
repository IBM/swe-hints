# FEA-Brief Identity Selection — Commands

All commands are run from the **hints repo root** (`hints_publish`).

```bash
cd /path/to/hints_publish && source .venv/bin/activate
```

---

## 1. NoCode Bench (Doc2Feat Verified)

Input already has `feature_patch` + `test_patch` — no extra setup needed.

```bash
python identity_selection/fea_brief.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output identity_selection/results_selection/fea_brief_sel/raw/ncbench_fea_brief.jsonl \
    --repos  repos/doc2feat_repos \
    --skip-errors
```

---

## 2. FEA-Bench (Lite, ~186 instances)

Loads directly from HuggingFace and fetches patches from GitHub.
Requires a **read-only** `GITHUB_TOKEN` (classic or fine-grained, no extra scopes needed —
unauthenticated limit is 60 req/hour which is exhausted quickly across 186+ instances).

### First-time only — fetch dangling sqlglot commits

14 `tobymao/sqlglot` base-commits were dropped by a force-push and won't be
fetched by a normal `git fetch`. Fetch them once by SHA:

```bash
cd repos/feabench_repos/sqlglot && git fetch origin \
  c371ac055a7546d8215d3a2acc0d1a64f43a07f1 \
  d6bac3e54c6445c52daa04015b1b2e4a6933e682 \
  eae3c5165c16b61c7b524a55776bdb1127005c7d \
  f920014709c2d3ccb7ec18fb622ecd6b6ee0afcd \
  f5bfd67341518d0ecb1c3693e0b41ed5c1cf0596 \
  dbb1ddef53e76ee51a1cf6a24a1de854a69c6093 \
  7f40ddd9b41f3dabdcbc3105cf5f06faacd82d75 \
  22a16848d80a2fa6d310f99d21f7d81f90eb9440 \
  fcc05c9daa31c7a51474ec9c72ceafd682359f90 \
  38e2e19ac3e20224dc07128994a47340aa56e635 \
  2655d7c11d677cf47f33ac62fbfb86f4117ffd75 \
  6992c1855f343a5d0120a3b4c993d8c406dd29ba \
  6e4c0ef48ab0db1a336d634273dab35de17c80bc \
  f5f3f84c7343151c5f48da60e8c15df41aadb33a
cd /path/to/hints_publish
```

### Generate hints

```bash
export GITHUB_TOKEN="your_read_only_token"

python identity_selection/fea_brief.py \
    --feabench \
    --lite \
    --lite-ids /path/to/FEA-Bench/instances_lite.json \
    --output identity_selection/results_selection/fea_brief_sel/raw/feabench_fea_brief.jsonl \
    --repos  repos/feabench_repos \
    --skip-errors
```

---

## 3. SWE-bench Pro (Python, 266 instances)

Input already has `patch` + `test_patch` — no extra setup needed.

```bash
python identity_selection/fea_brief.py \
    --input  identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/fea_brief_sel/raw/swebench_pro_fea_brief.jsonl \
    --repos  repos/swe_pro_python_repos \
    --skip-errors
```

---

## 4. SWE Re-Bench Leaderboard (860 instances, test split)

Input already has `patch` + `test_patch` — no extra setup needed.

> **Note:** `download.py` uses the `test` split only (860 rows).
> If `swe_rebench_leaderboard.jsonl` has 1720 rows it was downloaded with an older version — re-run `download.py` to fix it.

### First-time only — fetch dangling commits

All repos were checked upfront with `git cat-file -e` against the full dataset.
Results:

**`tobymao/sqlglot`** — 6 commits dropped by force-push, still fetchable from GitHub:

| Instance ID | Base commit |
|---|---|
| `tobymao__sqlglot-5189` | `696150dcb3337e328290434debbb28055233b2f8` |
| `tobymao__sqlglot-5256` | `f5b5b9338eb92b7aa2c9b4c92c6138c2c05e1c40` |
| `tobymao__sqlglot-5352` | `194850a52497300a8f1d47f2306b67cdd11ffab6` |
| `tobymao__sqlglot-6174` | `74b4e7c311e9d4ff39ce2e4d91940eced96aa32f` |
| `tobymao__sqlglot-6346` | `2607a3ad44f039a076626abafb5340e70aa2e18b` |
| `tobymao__sqlglot-6413` | `bb4eda1beb68b92de9ab014a63c67797a07df2fa` |

```bash
cd repos/swerebench_repos/sqlglot && git fetch origin \
  696150dcb3337e328290434debbb28055233b2f8 \
  f5b5b9338eb92b7aa2c9b4c92c6138c2c05e1c40 \
  194850a52497300a8f1d47f2306b67cdd11ffab6 \
  74b4e7c311e9d4ff39ce2e4d91940eced96aa32f \
  2607a3ad44f039a076626abafb5340e70aa2e18b \
  bb4eda1beb68b92de9ab014a63c67797a07df2fa
cd /path/to/hints_publish
```

**`chaoss/augur`** — 1 commit permanently deleted from GitHub (HTTP 404). Cannot be recovered.
Will be skipped by `--skip-errors`:

| Instance ID | Base commit | Status |
|---|---|---|
| `chaoss__augur-3512` | `c547710ec91e90626f475a492b93ef551f8979a7` | ❌ permanently lost |

### Generate hints

```bash
python identity_selection/fea_brief.py \
    --input  identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --output identity_selection/results_selection/fea_brief_sel/raw/swerebench_fea_brief.jsonl \
    --repos  repos/swerebench_repos \
    --skip-errors
```

---

## Comparing FEA-Bench output against the Standard dataset

```bash
python helper_code/compare_feabench_hints.py \
    --ours     identity_selection/results_selection/fea_brief_sel/raw/feabench_fea_brief.jsonl \
    --standard /path/to/FEA-Bench/feabench-data/FEA-Bench-v1.0-Lite-Standard
```

---

## Debugging a single instance

Add `--instance-id` to any command above to process just one instance:

```bash
python identity_selection/fea_brief.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output /tmp/test_fea_brief.jsonl \
    --repos  repos/doc2feat_repos \
    --instance-id psf__requests-5856
```
