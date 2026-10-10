# Running DefUse on your own Python benchmark

This guide takes a repository-level Python coding benchmark of your own, selects
identifier hints for it with DefUse, and runs a coding agent with and without those
hints. The four benchmarks we studied, SWE-bench Pro, SWE-rebench, FEA-Bench and
Doc2Feat-bench, appear as worked examples; skip their subsections if you bring your own.
Section 0 is the whole path on one page.

## What DefUse selects

DefUse selects the identifiers that cross the boundary between a task's reference
patch and its tests. It is the **communication** set, the union of two directions:

- **forward**: names the code patch defines and the tests read
  (`code_write ∩ test_read`), such as a new function the hidden test calls;
- **backward**: names the tests define and the code reads
  (`code_read ∩ test_write`), such as a fixture.

```text
communication = forward ∪ backward = (code_write ∩ test_read) ∪ (code_read ∩ test_write)
```

New Python files the code patch creates are always added. Names the issue text already
mentions are then dropped. What remains are the identifiers the hidden tests depend on
and the agent cannot read from the task. Everything else the patch touches is left out.
In the code, DefUse is the `communication` operator of `src/identifier_information.py`.

This repository has two implementations. They select the same identifiers on
SWE-bench Pro, but their outputs differ:

| | `src/` pipeline (operator `communication`) | `identity_selection/defuse2_relaxed.py` |
|---|---|---|
| Output per identifier | name, type, path, signature, location, docstring, ... | name and type only |
| Projections available | all five (section 4) | names only |
| mini-swe-agent instances for | any benchmark (section 6) | SWE-bench Pro only |
| Use it when | you want hints at any level of detail | you only need the selected names |

Use the `src/` pipeline unless you specifically want the name list.

All commands run from the repository root unless a step says otherwise.

---

## 0. Quick start: your own benchmark

**What you need.**

| you need | what it is for | details |
|---|---|---|
| one JSON line per task: `instance_id`, `repo`, `base_commit`, `patch`, `test_patch`, `problem_statement` | selecting the hints | section 2 |
| read access to each task's Git repository, with full history | DefUse checks out `base_commit` and applies the patches | section 2.4 |
| one container image per task, with the repository at `base_commit` and its dependencies installed | running the agent | section 6.2 |
| a way to run each task's tests, such as lists of tests that must pass | scoring the agent's patches | section 6.6 |
| an LLM endpoint for the agent | running the agent | section 6.4 |

Hint selection needs only the first two rows. Most of the work for a new benchmark is
the input file and the container images; nothing in this repository is
benchmark-specific beyond them.

**The whole path.** Variables are set in section 1; each step names its section.

```bash
# --- in this repository ---------------------------------------------------------
python repos/build_swerebench_repos.py --input $INPUT --repos-dir $REPOS      # 2.4 clone repos

python -m src.identifier_usage_relaxed --input $INPUT --repos-dir $REPOS \
    --output $OUT/extracted_hints.jsonl --skip-errors                           # 3.1 step 1
python -m src.identifier_information --usage $OUT/extracted_hints.jsonl \
    --operator communication --level All \
    --output $OUT/hints_defuse.jsonl --skip-errors                              # 3.1 step 2
python helper_code/filter_nonempty_identifiers.py \
    --input $OUT/hints_defuse.jsonl --output $OUT/hints_defuse_nonempty.jsonl   # 3.1 step 3

P=declaration                                                                   # 4 projection
python identity_projection/project_enriched.py \
    -i $OUT/hints_defuse_nonempty.jsonl -o $OUT/${BENCH}_${P}_proj.jsonl -p $P
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl \
    -s $INPUT -b swerebench -p $P -o results/miniswe_${BENCH}/${BENCH}_${P}.jsonl   # 6.3
python -c "import json,sys; [print(json.dumps({**json.loads(l), 'hints': ''})) for l in open(sys.argv[1])]" \
    results/miniswe_${BENCH}/${BENCH}_${P}.jsonl > results/miniswe_${BENCH}/${BENCH}_empty.jsonl

# --- in your mini-swe-agent checkout, with this repository's overlay (6.1) -----
HINTS=/path/to/swe-hints            # this repository; BENCH and P as above
REPO_DIR=/testbed                   # 6.2: where your images keep the repository
sed "s#/testbed#${REPO_DIR}#g" src/minisweagent/config/benchmarks/swerebench_hints.yaml > mybench_hints.yaml

for V in $P empty; do                                                           # 6.5 run
  mini-extra swebench -c mybench_hints.yaml -c my_model.yaml \
      --subset $HINTS/results/miniswe_${BENCH}/${BENCH}_${V}.jsonl \
      --workers 8 --output ./output/${BENCH}_${V}
done
# 6.6: score ./output/${BENCH}_${V}/preds.json with your benchmark's tests
```

The result is one agent run with Declaration hints and one without hints, on the same
tasks. The difference in resolve rate between the two is what the hints are worth.

---

## 1. Setup

```bash
git clone git@github.com:IBM/swe-hints.git && cd swe-hints
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt "tree-sitter==0.21.3"
pip install litellm tqdm        # only for the LLM descriptions (section 4)
```

The `tree-sitter==0.21.3` pin is required; `requirements.txt` carries it, and the
command repeats it for older checkouts. A newer version makes the parser fail with
`TypeError: __init__() takes exactly 1 argument`. The stack is tested on Python 3.12.

Set these once; every command below uses them:

```bash
BENCH=mybench                   # short name, used for output folders
INPUT=data/mybench.jsonl        # the benchmark, one JSON object per line (section 2)
REPOS=repos/${BENCH}_repos      # where the benchmark's repositories are cloned
OUT=results/${BENCH}_defuse     # outputs
mkdir -p data $OUT
```

---

## 2. Prepare the data

### 2.1 Input format

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
| `image_name` | optional | container image; copied into agent inputs (section 6) |

Only Python files in the two patches are analysed; everything else is ignored.
Without `problem_statement`, no names are dropped for being already visible.

### 2.2 Your own benchmark

Write the fields of section 2.1 from whatever your benchmark stores, in any way you
like; the pipeline reads only the JSONL. Check three things while you do:

- **`base_commit` must exist in the public history of `repo`**, so that a fresh clone
  can check it out.
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

### 2.3 Worked examples: the four benchmarks we studied

Skip this if you bring your own benchmark. One script downloads Doc2Feat Verified, SWE-bench Pro (Python instances), FEA-Bench
Lite and the SWE-rebench leaderboard (2026 partitions) into
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

FEA-Bench does not publish its patches. Rebuild them with FEA-Bench's own pipeline,
which needs a GitHub token:

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

Then use `fea_bench_lite_with_patches.jsonl` as `$INPUT`.

### 2.4 Clone the repositories

Both implementations check out `base_commit` and apply the patches, so every repository
must be a **full clone** (not shallow). This script reads `repo` from any input file and
clones `https://github.com/<repo>` with full history into `$REPOS/<name>`. On a re-run it
unshallows or fetches existing clones instead:

```bash
python repos/build_swerebench_repos.py --input $INPUT --repos-dir $REPOS --dry-run   # preview
python repos/build_swerebench_repos.py --input $INPUT --repos-dir $REPOS --skip-errors
```

When it finishes, the script suggests a next command using `src.identifier_usage`. Ignore
it and follow section 3.1, which uses `src.identifier_usage_relaxed`.

Things that go wrong here:

- **A base commit was force-pushed away.** GitHub often still serves it by hash:
  `git -C $REPOS/<name> fetch origin <base_commit>`. If that returns 404 the instance
  cannot be processed; `--skip-errors` in section 3 skips it.
- **The repository is private or not on GitHub.** The script only clones
  `https://github.com/<repo>`. Clone it yourself with full history into
  `$REPOS/<name>`, where `<name>` is the part of `repo` after the slash.
- **Two repositories share a name** under different owners. Clone both as
  `$REPOS/<owner>__<name>` and keep no plain `$REPOS/<name>` folder. The `src/` pipeline
  prefers the `<owner>__<name>` folder; `defuse2_relaxed.py` uses it only when no plain
  `<name>` folder exists.

---

## 3. Run DefUse

> Both implementations **check out commits and reset the clones in `$REPOS`**. Run one
> job at a time per `$REPOS`. To run in parallel, give each job its own copy:
> `git clone --shared $REPOS/<name> <other_dir>/<name>`.

### 3.1 The `src/` pipeline (recommended)

```bash
# Step 1: for every instance, which names each patch reads and writes,
#         plus a catalogue of everything known about each name
python -m src.identifier_usage_relaxed --input $INPUT --repos-dir $REPOS \
    --output $OUT/extracted_hints.jsonl --skip-errors

# Step 2: apply DefUse (operator `communication`) and attach each name's attributes
python -m src.identifier_information --usage $OUT/extracted_hints.jsonl \
    --operator communication --level All \
    --output $OUT/hints_defuse.jsonl --skip-errors

# Step 3: drop instances where DefUse selects nothing
python helper_code/filter_nonempty_identifiers.py \
    --input $OUT/hints_defuse.jsonl --output $OUT/hints_defuse_nonempty.jsonl
```

Step 1 takes one to two seconds per instance. Expect a sizeable share of instances to
come out empty in step 3: DefUse selects nothing when the tests use no new name. On
SWE-bench Pro, 68 of the 266 Python instances are non-empty.

`$OUT/hints_defuse_nonempty.jsonl` is the DefUse result. Section 4 projects it, and
section 6 turns the projection into agent runs.

### 3.2 `identity_selection/defuse2_relaxed.py`

```bash
python identity_selection/defuse2_relaxed.py --input $INPUT --repos-dir $REPOS \
    --output $OUT/${BENCH}_defuse2_relaxed.jsonl --skip-errors
```

Failed instances go to `$OUT/${BENCH}_defuse2_relaxed.jsonl.errors.jsonl`.

Section 6.3 turns this output into mini-swe-agent instances, for SWE-bench Pro only.
For other benchmarks, use section 3.1.

---

## 4. Choose a projection

A **projection** decides how much to show about each selected identifier:

| projection | shows per identifier | needs LLM descriptions |
|---|---|---|
| `nameonly` | the name | no |
| `nocode` | name and type, in Doc2Feat-bench's format | no |
| `declaration` | name, type, path, new-file flag and signature; class members nested under their class | no |
| `fea_brief` | `declaration` plus a one-sentence description | yes |
| `swe_pro` | `fea_brief` plus a two-to-four sentence description | yes |

`declaration` is the projection we recommend. It gives the interface the hidden tests
depend on, and no text describing how the solution works. The code also defines
`declaration_v2` and `semantics_only`, which are experimental.

```bash
P=declaration        # nameonly | nocode | declaration | fea_brief | swe_pro
python identity_projection/project_enriched.py \
    -i $OUT/hints_defuse_nonempty.jsonl -o $OUT/${BENCH}_${P}_proj.jsonl -p $P
```

### LLM descriptions, for `fea_brief` and `swe_pro`

Step 2 fills the two description fields from **the reference patch's own docstrings**
whenever the new code has one; on SWE-bench Pro that is 47 of 160 identifiers. Showing
those to an agent hands it the solution author's documentation. Always run this step
before projecting to `fea_brief` or `swe_pro`; it overwrites them with LLM-written text:

```bash
export ENRICH_MODEL=openai/aws/claude-haiku-4-5   # any litellm model string
export ENRICH_API_BASE=https://...
export ENRICH_API_KEY=...
python -m src.enrich_semantics --hints $OUT/hints_defuse_nonempty.jsonl --source $INPUT \
    --output $OUT/hints_defuse_nonempty_enriched.jsonl --skip-errors
```

Then run `project_enriched.py` on `$OUT/hints_defuse_nonempty_enriched.jsonl`. The step
is resumable. `--dry-run --limit 5` builds the prompts without calling the model. The
other three projections never show the description fields, so they need no enrichment.

---

## 5. Output formats

**Step 1** (`extracted_hints.jsonl`):

```json
{"instance_id": "...", "code_read": [...], "code_write": ["b_data", "body", ...],
 "test_read": [...], "test_write": [...], "catalogue": {"prepare_multipart": {...}}}
```

**Step 2** (`hints_defuse.jsonl`), one entry per selected identifier, empty fields
omitted:

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

Names the catalogue does not know, such as local variables, come out as just a name
and `"entity_type": "variable"`.

**`defuse2_relaxed.py`**: your input row plus

```json
"augmentations": {
  "forward":  {"header": "The following entities are defined in the implementation and used in tests ...",
               "data": [{"type": "class", "name": "FailedStates"}, {"type": "class", "name": "IteratingStates"}]},
  "backward": {"header": "The following entities are used in the implementation but defined in tests ...",
               "data": []}}
```

**Rendered hints**, the text the agent sees, for the step 2 example above:

```text
nameonly:
If completing this task requires creating new files, classes, fields, or error messages, you may consider using the following suggested entity names:

- `b_data`
- `prepare_multipart`

declaration:
### `b_data` (variable)

### `prepare_multipart` (function) — `lib/ansible/module_utils/urls.py`
Signature: `prepare_multipart(fields)`
```

---

## 6. Run mini-swe-agent with the hints

### 6.1 Install mini-swe-agent with this repository's overlay

The `mini-swe-agent/` folder of this repository is not runnable by itself. It is an
overlay for the official [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent),
tested on release `v2.4.6`: benchmark configs whose prompt has a slot for the hints,
and runners that pass each instance's `hints` field into it.

```bash
HINTS=/path/to/swe-hints                     # this repository
git clone https://github.com/SWE-agent/mini-swe-agent.git && cd mini-swe-agent
git checkout v2.4.6
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .

cp $HINTS/mini-swe-agent/config/*.yaml               src/minisweagent/config/benchmarks/
cp $HINTS/mini-swe-agent/run/benchmarks/*.py         src/minisweagent/run/benchmarks/
cp $HINTS/mini-swe-agent/run/utilities/mini_extra.py src/minisweagent/run/utilities/
cp -r $HINTS/mini-swe-agent/model_registry_cost .
cp $HINTS/mini-swe-agent/rits_swebench_*.yaml .      # model config examples
```

All later `mini-extra` commands run from this mini-swe-agent folder.

### 6.2 Pick the benchmark template

Each benchmark config is a prompt template plus container settings. The template inserts
the instance's `hints` field into the prompt inside a `<hints>` block, and leaves the
block out when `hints` is empty.

| benchmark | instance generator | config (`-c`) | `mini-extra` command | container image | repo inside container |
|---|---|---|---|---|---|
| **your own benchmark** | `generate_instances.py -b swerebench` | `swerebench_hints.yaml`, or your copy (below) | `swebench` | the input row's `image_name` | `/testbed`, or set in your copy |
| SWE-bench Pro | `generate_instances.py -b swebench_pro -d jefzda` | `swebench_pro_hints.yaml` | `swebench` | `docker.io/jefzda/sweap-images:<dockerhub_tag>` | `/app` |
| SWE-rebench, or any SWE-bench-style benchmark | `generate_instances.py -b swerebench` | `swerebench_hints.yaml` | `swebench` | the input row's `image_name` | `/testbed` |
| Doc2Feat-bench | `generate_doc2feat_instances.py` | `doc2feat.yaml` | `doc2feat` | `ncbench_<instance_id>:latest` | `/root/<repo name>` |

**A template for your own benchmark.** Start from `swerebench_hints.yaml`:

- **Images.** Each task needs its own image, with the repository checked out at
  `base_commit` and its test dependencies installed. Put the image name in each input
  row's `image_name` field before generating instances (section 6.3). Images that
  SWE-bench's harness builds already have this shape.
- **Repository path.** The template assumes the repository is at `/testbed`, in its
  working directory and in the prompt text. Make your own copy with your path in both
  places, and pass the copy by path with `-c`:

  ```bash
  # in the mini-swe-agent checkout
  REPO_DIR=/workspace                 # where your images keep the repository
  sed "s#/testbed#${REPO_DIR}#g" src/minisweagent/config/benchmarks/swerebench_hints.yaml > mybench_hints.yaml
  ```
- **Setup before the agent starts.** If each container needs a command first, such
  as activating an environment, add it to the copy. It is rendered with the instance's
  fields, so it can use `{{instance_id}}` or `{{repo}}`:

  ```yaml
  run:
    env_startup_command: "source /opt/conda/bin/activate myenv"
  ```
- **Hint wording.** The `<hints>` block opens with "Consider the following hints, which
  are about entities and identifiers that you need:". Edit `instance_template` in the
  copy if you want different framing; keep it fixed across the runs you compare.
- **Doc2Feat-bench images** must be pulled and tagged locally first, with
  `pull_instance_images.py` from the Doc2Feat-bench repository.
- **FEA-Bench** ships no per-instance images. Build them with FEA-Bench's own harness
  and add `image_name` to the input rows.

### 6.3 Generate the mini-swe-agent instances

Run from this repository, on the projection from section 4. Following contains some examples of generate instances, essentially keeps all the structure same except adding a key:value in jsonline file called "hints".

```bash
P=declaration
AGENT_IN=results/miniswe_${BENCH}/${BENCH}_${P}.jsonl

# Your own benchmark, or SWE-rebench: input rows carry image_name
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -b swerebench -p $P -o $AGENT_IN

# SWE-bench Pro: image built from dockerhub_tag
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -b swebench_pro -d jefzda -p $P -o $AGENT_IN

# Doc2Feat-bench
python identity_projection/generate_doc2feat_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -p $P -o $AGENT_IN
```

Each row has `instance_id`, `repo`, `base_commit`, `problem_statement`, `hints`, and
`image_name` except for Doc2Feat-bench.

**The no-hint baseline.** Compare against the same instances with the hints removed.
Copy any projection's file and blank the field:

```bash
python -c "import json,sys; [print(json.dumps({**json.loads(l), 'hints': ''})) for l in open(sys.argv[1])]" \
    $AGENT_IN > results/miniswe_${BENCH}/${BENCH}_empty.jsonl
```

**Name lists from `defuse2_relaxed.py`** (section 3.2) have their own generator.

For instance, for SWE-bench Pro only:

```bash
python mini-swe-agent/data_pre/generate_minisweagent_instances.py \
    --dockerhub_username jefzda --python_only \
    --augmented_hints $OUT/${BENCH}_defuse2_relaxed.jsonl \
    --output_path results/miniswe_${BENCH}/${BENCH}_defuse_names.jsonl
```

### 6.4 Write a model config

The run merges the benchmark config with a model config; later `-c` files win. Write
your own model config, or start from the `rits_swebench_*.yaml` examples, which use
`litellm_textbased` with an `api_base` and `api_key`. An OpenRouter example:

```yaml
# my_model.yaml
model:
  model_class: "openrouter_textbased"
  model_name: "deepseek/deepseek-v4-flash"
  cost_tracking: "ignore_errors"
  action_regex: "```bash\\s*\\n(.*?)\\n```"
  model_kwargs:
    temperature: 1.0
    top_p: 1.0
    reasoning:
      effort: "max"
```

Set corresponding api key in your environment.

### 6.5 Run

```bash
cd /path/to/mini-swe-agent && source .venv/bin/activate

# Your own benchmark (SWE-rebench: -c swerebench_hints.yaml; SWE-bench Pro: -c swebench_pro_hints.yaml)
mini-extra swebench \
    -c mybench_hints.yaml \
    -c my_model.yaml \
    --subset $HINTS/results/miniswe_${BENCH}/${BENCH}_${P}.jsonl \
    --workers 8 \
    --output ./output/${BENCH}_${P}

# Doc2Feat-bench
mini-extra doc2feat \
    -c doc2feat.yaml \
    -c my_model.yaml \
    --subset $HINTS/results/miniswe_${BENCH}/${BENCH}_${P}.jsonl \
    --workers 8 \
    --output ./output/${BENCH}_${P}
```

- **Config names.** A `-c` value is looked up first as a path, then among the
  installed configs, so your own template and model config can sit in the current
  folder.
- **Workers.** Every worker runs its own container; size `--workers` to your machine.
  SWE-bench Pro containers need up to 8 GiB each.
- **Containers.** Docker is the default. To use another backend the runners support,
  add `--environment-class singularity` (or `swerex_modal`).
- **Limits.** Each instance stops at 250 steps or $3, set in the benchmark config.
- **Outputs.** Patches go to `<output>/preds.json` (`preds.jsonl` for Doc2Feat-bench),
  and one trajectory per instance to `<output>/<instance_id>/`.
- **Re-runs resume.** Instances already in the predictions file are skipped, including
  ones that failed with an empty patch. Pass `--redo-existing` to run them again.

### 6.6 Evaluate

Score the predictions with each benchmark's official evaluator. 

For instance, for SWE-bench Pro,
first convert them with this repository's patch gatherer, then run
`swe_bench_pro_eval.py` from the
[SWE-bench Pro harness](https://github.com/scaleapi/SWE-bench_Pro-os):

```bash
python $HINTS/mini-swe-agent/eval/gather_patches.py \
    --directory ./output/${BENCH}_${P} --prefix ${BENCH}_${P} \
    --output ./output/${BENCH}_${P}_patches.json --mini
```

An instance counts as resolved only when all its fail-to-pass and pass-to-pass tests
pass. Report rates over all generated instances, counting unevaluated ones as unresolved.

**Your own benchmark.** The agent's patches are in `<output>/preds.json`, keyed by
instance:

```json
{"<instance_id>": {"instance_id": "<instance_id>", "model_name_or_path": "...", "model_patch": "diff --git ..."}}
```

If your benchmark has no evaluator of its own, score each patch like this:

1. Start the task's image.
2. Apply `model_patch` with `git apply`. A patch that does not apply counts as unresolved.
3. Apply the task's `test_patch`.
4. Run the tests the task requires: those the reference patch makes pass, and those
   that passed before and must keep passing.
5. Count the task as resolved only if all of them pass.

**Comparing conditions.** The hint effect is the difference between runs on the same
tasks, so keep everything else fixed: the same model, serving provider, template and
step limit, ideally on the same day. A single run is noisy. Two runs of one identical
condition can differ by several tasks, so repeat each condition and compare means.

---

## 7. Troubleshooting

| symptom | cause and fix |
|---|---|
| `TypeError: __init__() takes exactly 1 argument` | wrong tree-sitter; `pip install "tree-sitter==0.21.3"` |
| `Repo not found: repos/.../<name>` | clone missing or named differently; see section 2.4 |
| `CalledProcessError(128, ['git', 'checkout', ...])` | base commit not in the clone; fetch it by hash (section 2.4) |
| every instance empty after step 3 | `test_patch` empty or folded into `patch`; split it (section 2.2) |
| step 1 errors with `git apply` failing | the patch does not apply at `base_commit`; check the patch and commit in your input (section 2.2) |
| a clone left on a detached commit or with changes | a run was interrupted; `git -C $REPOS/<name> reset --hard && git -C $REPOS/<name> clean -fdx` |
| `enrich_semantics: unrecognized arguments: --workers` | this script has no `--workers`; drop the flag (older docs show it) |
| `argument --projection/-p: invalid choice` | the projection is not in `project_enriched.py` or the generator; see section 4 |
| an agent run finishes instantly with every patch empty | no container runtime; check `docker ps`, or pass `--environment-class` (section 6.5) |
| the agent cannot find the repository or runs commands in the wrong folder | your images keep it outside `/testbed`; use a template copy (section 6.2) |
| `Error executing startup command` | your `env_startup_command` failed inside the container; run it by hand in the image |
| many instances end with `RepeatedFormatError` | the model returned empty responses; pin the provider (section 6.4) and rerun with `--redo-existing` |

Debug one instance by adding `--instance-id <id>` to any command in sections 3 and 4,
or `--filter <instance_id>` to a `mini-extra` run.
