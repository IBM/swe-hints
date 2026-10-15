# The Hint Pipeline

The code in this directory turns a benchmark's tasks into DefUse hints, with the attributes
of every selected identifier. Run all commands from the repository root, in the environment
from the root README's [Setup](../README.md#setup), with the variables (`BENCH`, `INPUT`,
`REPOS`, `OUT`) from its [Quick start](../README.md#quick-start-defuse-hints-for-your-own-benchmark).

| step | module | output |
|---|---|---|
| 1. extract | `identifier_usage.py` (uses `identifier_extractor.py`) | which names each patch reads and writes, plus a catalogue of everything known about each name |
| 2. select | `identifier_information.py` | the DefUse identifiers with their attributes |
| 3. describe | `enrich_semantics.py` | LLM-written descriptions, only needed by the `fea_brief` and `swe_pro` projections |

## 1. Prepare the data

### Input format

One JSON object per line, one line per task instance:

| field | required | meaning |
|---|---|---|
| `instance_id` | yes | unique id |
| `repo` | yes | GitHub `owner/name`, e.g. `ansible/ansible` |
| `base_commit` | yes | commit the task starts from |
| `patch` | yes | reference solution, unified diff, **without test files** (`feature_patch` is accepted instead) |
| `test_patch` | yes | test changes, unified diff |
| `problem_statement` | recommended | issue text; names it already mentions are dropped, and it becomes the agent's task |
| `doc_changes` | optional | Doc2Feat only; replaces `problem_statement` for that filter |
| `image_name` | optional | container image; copied into the agent's instances |

Only Python files in the two patches are analysed; everything else is ignored. Without
`problem_statement`, no names are dropped for being already visible.

### Your own benchmark

Write those fields from whatever your benchmark stores; the pipeline reads only the JSONL.
Check three things while you do:

- **`base_commit` must exist in the public history of `repo`**, so that a fresh clone can
  check it out.
- **`patch` must apply cleanly** to `base_commit` with `git apply`, and so must
  `test_patch` on top of it. Step 1 applies both.
- **`instance_id` must be unique.** Every later file is joined on it.

If your benchmark is a HuggingFace dataset, map its columns:

```python
import json
from datasets import load_dataset

ds = load_dataset("ORG/BENCHMARK", split="test")
COLUMNS = {                      # pipeline field -> the dataset's column name
    "instance_id": "instance_id",
    "repo": "repo",
    "base_commit": "base_commit",
    "patch": "patch",
    "test_patch": "test_patch",
    "problem_statement": "problem_statement",
}
with open("data/mybench.jsonl", "w") as f:
    for row in ds:
        f.write(json.dumps({field: row[col] for field, col in COLUMNS.items()}) + "\n")
```

Keep only Python tasks. If the benchmark has a language column, filter on it; SWE-bench
Pro, for example, has `repo_language`.

**If your benchmark ships one combined diff** with code and tests together, split it by
file path. This heuristic recovers SWE-bench Pro's own code/test split on 263 of 266
instances; the three misses are CI files the pipeline ignores anyway:

```python
import re
from unidiff import PatchSet

TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")

def split_patch(diff: str) -> tuple[str, str]:
    """Split one unified diff into (code_patch, test_patch) by file path."""
    code, test = [], []
    for pf in PatchSet(diff):
        path = pf.target_file[2:] if pf.target_file != "/dev/null" else pf.source_file[2:]
        (test if TEST_PATH.search(path) else code).append(str(pf))
    return "".join(code), "".join(test)
```

Adjust `TEST_PATH` if the benchmark's repositories keep tests somewhere unusual.

### The four benchmarks in the paper

One script downloads Doc2Feat Verified, SWE-bench Pro (Python instances), FEA-Bench Lite
and the SWE-rebench leaderboard (2026 partitions) into
`identity_selection/data_selection/huggingface/`:

```bash
python identity_selection/data_selection/huggingface/download.py
```

| benchmark | file written | note |
|---|---|---|
| Doc2Feat Verified | `doc2feat_verified.jsonl` | ready to use |
| SWE-bench Pro | `swebench_pro_python.jsonl` | ready to use |
| SWE-rebench | `swe_rebench_leaderboard.jsonl` | ready to use |
| FEA-Bench Lite | `fea_bench_lite.jsonl` | **has no patches**; see below |

FEA-Bench does not publish its patches. Rebuild them with FEA-Bench's own pipeline, which
needs a GitHub token:

```bash
export GITHUB_TOKEN=...
python repos/build_feabench_repos.py --repos-dir repos/feabench_repos
python identity_selection/data_selection/huggingface/get_feabench_patches.py
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

Then use `fea_bench_lite_with_patches.jsonl` as `$INPUT`. The values used for each
benchmark:

| benchmark | `INPUT` (under `identity_selection/data_selection/huggingface/`) | `REPOS` | `OUT` |
|---|---|---|---|
| SWE-bench Pro | `swebench_pro_python.jsonl` | `repos/swe_pro_python_repos` | `results/swe_pro_proj` |
| Doc2Feat-bench | `doc2feat_verified.jsonl` | `repos/doc2feat_repos` | `results/doc2feat_proj` |
| SWE-rebench | `swe_rebench_leaderboard.jsonl` | `repos/swerebench_repos` | `results/swerebench_proj` |
| FEA-Bench | `fea_bench_lite_with_patches.jsonl` | `repos/feabench_repos` | `results/feabench_proj` |

On SWE-rebench one instance fails in step 1 because its base commit is gone
(`chaoss__augur-3512`); `--skip-errors` skips it.

## 2. Clone the repositories

Every task's repository must be cloned with full history into `$REPOS`; see
[repos/README.md](../repos/README.md).

> Steps 1 and 2 of the next sections and the selection scripts **check out commits and
> reset the clones in `$REPOS`**. Run one job at a time per `$REPOS`. To run in parallel,
> give each job its own copy: `git clone --shared $REPOS/<name> <other_dir>/<name>`.

## 3. Extract the identifiers (step 1)

For every instance: which names each patch reads and writes, and a catalogue of everything
known about each name (kind, path, signature, docstring, ...). WRITE and READ are collected
at any nesting depth.

```bash
python -m src.identifier_usage --input $INPUT --repos-dir $REPOS \
    --output $OUT/extracted_hints.jsonl --skip-errors
```

Step 1 takes one to two seconds per instance.

## 4. Select with DefUse (step 2)

Apply DefUse (operator `communication`), attach each name's attributes, then drop instances
where DefUse selects nothing:

```bash
python -m src.identifier_information --usage $OUT/extracted_hints.jsonl \
    --operator communication --level All \
    --output $OUT/hints_defuse.jsonl --skip-errors
python helper_code/filter_nonempty_identifiers.py \
    --input $OUT/hints_defuse.jsonl --output $OUT/hints_defuse_nonempty.jsonl
```

Expect a sizeable share of instances to come out empty: DefUse selects nothing when the
tests use no new name. On SWE-bench Pro, 68 of the 266 Python instances are non-empty.
`$OUT/hints_defuse_nonempty.jsonl` is the DefUse result.

### Operators

`--operator` chooses the selection from step 1's four sets; DefUse is `communication`.

| operator | formula | meaning |
|---|---|---|
| `forward` | `code_write ∩ test_read` | new APIs defined in code, used in tests |
| `backward` | `code_read ∩ test_write` | test fixtures used in code |
| `communication` | `(code_write ∩ test_read) ∪ (code_read ∩ test_write)` | DefUse: forward ∪ backward |
| `intersection` | `(code_read ∪ code_write) ∩ (test_read ∪ test_write)` | any shared identifier |
| `code_only` | `code_read ∪ code_write` | everything the code patch touches |
| `test_only` | `test_read ∪ test_write` | everything the test patch touches |
| `union` | all four sets | everything from both patches |

`--level` chooses which attributes step 2 keeps; `All` keeps every one, and the projections
of [identity_projection/README.md](../identity_projection/README.md) decide what the agent
sees.

## 5. Write the LLM descriptions (step 3)

Only for the `fea_brief` and `swe_pro` projections. Step 2 fills the two description fields
(`weak_semantics`, `strong_semantics`) from **the reference patch's own docstrings**
whenever the new code has one; on SWE-bench Pro that is 47 of 160 identifiers. Showing
those to an agent hands it the solution author's documentation. This step overwrites them
with LLM-written text:

```bash
export ENRICH_MODEL=openai/aws/claude-haiku-4-5   # any litellm model string
export ENRICH_API_BASE=https://...
export ENRICH_API_KEY=...
python -m src.enrich_semantics --hints $OUT/hints_defuse_nonempty.jsonl --source $INPUT \
    --output $OUT/hints_defuse_nonempty_enriched.jsonl --skip-errors --workers 4
```

The step is resumable. `--workers N` enriches N instances at a time (default 1); the output
rows then come in completion order, which nothing downstream depends on.
`--dry-run --limit 5` builds the prompts without calling the model. The paper used Claude
Haiku 4.5. LLM output differs between runs, so the descriptions cannot be regenerated byte
for byte; the paper's hints are in [hints_to_release](../hints_to_release/README.md).

## 6. Next steps

- Project the hints and generate mini-SWE-agent instances:
  [identity_projection/README.md](../identity_projection/README.md).
- Compare DefUse with other selection policies:
  [identity_selection/README.md](../identity_selection/README.md).

## Output formats

**Step 1** (`extracted_hints.jsonl`):

```json
{"instance_id": "...", "code_read": [...], "code_write": ["b_data", "body", ...],
 "test_read": [...], "test_write": [...], "catalogue": {"prepare_multipart": {...}}}
```

New files are stored in `code_write` as paths (they contain a `/`) and are added to every
operator that includes the code patch.

**Step 2** (`hints_defuse.jsonl`), one entry per selected identifier, empty fields omitted:

```json
{"instance_id": "instance_ansible__ansible-b748edea...", "operator": "communication", "level": "All",
 "identifiers": [
   {"name": "b_data", "entity_type": "variable"},
   {"name": "prepare_multipart", "entity_type": "function",
    "path": "lib/ansible/module_utils/urls.py", "is_new_file": false,
    "signature": "prepare_multipart(fields)",
    "complete_location": "lib/ansible/module_utils/urls.py:1399-1509",
    "weak_semantics": "Takes a mapping, and prepares a multipart/form-data body",
    "strong_semantics": "...", "exception_types": "TypeError, ValueError"}]}
```

Names the catalogue does not know, such as local variables, come out as just a name and
`"entity_type": "variable"`.

## Java (Multi-SWE-bench)

The same steps, with a Java step 1. Put Multi-SWE-bench's Java instance files (one JSONL per
repository) in `data/java/multi_swe_raw/`, then:

```bash
python helper_code/data_prepare/extract_multi_swe_bench_java.py \
    --raw-dir data/java/multi_swe_raw --output data/java/multi_swe_bench_java.jsonl
python repos/build_java_repos.py --input data/java/multi_swe_bench_java.jsonl \
    --repos-dir repos/multi_swe_java_repos
python -m src.identifier_usage_java --input data/java/multi_swe_bench_java.jsonl \
    --repos-dir repos/multi_swe_java_repos \
    --output results/java_msb_proj/extracted_hints.jsonl --skip-errors
```

Step 2 is the same command as for Python, on `results/java_msb_proj/extracted_hints.jsonl`.
Java has no module-level functions, so the extractor registers every member twice, once at
top level and once under its class; and `entity_kind` (interface, enum, record, annotation)
is not kept by step 2, so every Java type renders as a class.

## Troubleshooting

| symptom | cause and fix |
|---|---|
| `TypeError: __init__() takes exactly 1 argument` | wrong tree-sitter; reinstall with `pip install -r requirements.txt` (or `requirements-lock.txt`), which pins `tree-sitter==0.21.3` |
| `Repo not found: repos/.../<name>` | clone missing or named differently; see [repos/README.md](../repos/README.md) |
| `CalledProcessError(128, ['git', 'checkout', ...])` | base commit not in the clone; fetch it by hash ([repos/README.md](../repos/README.md)) |
| every instance empty after step 2 | `test_patch` empty or folded into `patch`; split it (section 1) |
| step 1 errors with `git apply` failing | the patch does not apply at `base_commit`; check the patch and commit in your input |
| a clone left on a detached commit or with changes | a run was interrupted; `git -C $REPOS/<name> reset --hard && git -C $REPOS/<name> clean -fdx` |

Debug one instance by adding `--instance-id <id>` to any command in sections 3 to 5.
