# DefUse2 Identity Selection — Commands

All commands are run from the **hints repo root** (`hints_publish`).

```bash
cd /path/to/hints_publish && source .venv/bin/activate
```

---

## 1. NoCode Bench (Doc2Feat Verified)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `feature_patch` + `test_patch`).

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output identity_selection/results_selection/defuse2_sel/raw/ncbench_defuse2.jsonl \
    --repos  repos/doc2feat_repos
```

---

## 2. FEA-Bench (Lite, 200 instances)

The HuggingFace dataset does not include patch fields by policy.
Patches must be fetched from GitHub first — see `README_commands.md` steps 1 & 2.

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/fea_bench_lite_with_patches.jsonl \
    --output identity_selection/results_selection/defuse2_sel/raw/feabench_defuse2.jsonl \
    --repos  repos/feabench_repos
```

---

## 3. SWE-bench Pro (Python, 266 instances)

Input is the HuggingFace JSONL downloaded by `download.py` (already has `patch` + `test_patch`).

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/defuse2_sel/raw/swebench_pro_defuse2.jsonl \
    --repos  repos/swe_pro_python_repos
```

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
cd /path/to/hints_publish
```

**`chaoss/augur`** — 1 commit permanently deleted from GitHub (HTTP 404). Cannot be recovered.
Will be skipped by `--skip-errors`:

| Instance ID | Base commit | Status |
|---|---|---|
| `chaoss__augur-3512` | `c547710ec91e90626f475a492b93ef551f8979a7` | ❌ permanently lost |

### Generate hints

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/swe_rebench_leaderboard.jsonl \
    --output identity_selection/results_selection/defuse2_sel/raw/swerebench_defuse2.jsonl \
    --repos  repos/swerebench_repos \
    --skip-errors
```

---

## Debugging a single instance

Add `--instance-id` to any command above to process just one instance:

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/doc2feat_verified.jsonl \
    --output /tmp/test_defuse2.jsonl \
    --repos  repos/doc2feat_repos \
    --instance-id psf__requests-5856
```

---

## Error handling

Add `--skip-errors` to continue past failed instances and write a `.errors.jsonl` sidecar file:

```bash
python identity_selection/defuse2.py \
    --input  identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output identity_selection/results_selection/defuse2_sel/raw/swebench_pro_defuse2.jsonl \
    --repos  repos/swe_pro_python_repos \
    --skip-errors
```
