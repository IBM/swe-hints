# Selection Policies

The code in this directory decides **which** identifiers a hint reveals. It implements
DefUse and the selection policies of three published hint schemes, so they can be compared
under one fixed projection. Run all commands from the repository root, in the environment
from the root README's [Setup](../README.md#setup), with the variables (`BENCH`, `INPUT`,
`REPOS`, `OUT`) from its [Quick start](../README.md#quick-start-defuse-hints-for-your-own-benchmark).

| policy | script | selects |
|---|---|---|
| DefUse | `defuse2.py` | names the code patch defines and the tests use, or the tests define and the code uses; plus new `.py` files and the error messages the tests assert on; names in the issue text are dropped |
| Doc2Feat | `nocode.py` | new identifiers of the code patch (functions, classes, fields, error messages) whose name also appears among the test patch's new identifiers (after NoCode-bench's `augment.py`) |
| FEA-Bench (brief) | `fea_brief.py` | functions and classes the code patch adds, from an AST comparison of old and new files; no test filtering (after FEA-Bench's `get_dataset.py`) |
| SWE-bench Pro | `swe_pro.py` | requirements and an interface written by an LLM from the reference patch, approximating SWE-bench Pro's human annotators |

Each script has a Java version (`*_java.py`, shared rules in `java_lang.py`).

## 1. Get the data and the repositories

The input format and the four benchmarks' files are in
[src/README.md](../src/README.md#1-prepare-the-data); the clones in
[repos/README.md](../repos/README.md). Like the pipeline, every script here checks out
commits in `$REPOS`: run one at a time per `$REPOS`.

## 2. Run a policy

```bash
python identity_selection/defuse2.py  --input $INPUT --repos-dir $REPOS --output $OUT/${BENCH}_defuse2.jsonl  --skip-errors
python identity_selection/nocode.py   --input $INPUT --repos     $REPOS --output $OUT/${BENCH}_nocode.jsonl   --skip-errors
python identity_selection/fea_brief.py --input $INPUT --repos    $REPOS --output $OUT/${BENCH}_fea_brief.jsonl --skip-errors

export REQUIREMENTS_MODEL=openai/aws/claude-haiku-4-5    # any litellm model string
export REQUIREMENTS_API_BASE=https://...
export REQUIREMENTS_API_KEY=...
python identity_selection/swe_pro.py --task both --input $INPUT --repos $REPOS \
    --output $OUT/${BENCH}_swe_pro.jsonl --skip-errors
```

Each output row is the input row plus the selection (`augmentations` for `defuse2.py` and
`nocode.py`, `new_components` for `fea_brief.py`, `requirements_generated` and `interface_generated` for
`swe_pro.py`). The per-benchmark commands of the paper, with its file names, are in
`README_commands_defuse.md`, `README_commands_nocode.md`, `README_commands_fea_brief.md` and
`README_commands_swe_pro.md`.

**`defuse2.py` and the `src/` pipeline.** Both implement DefUse; the `src/` pipeline is its
`communication` operator ([src/README.md](../src/README.md#4-select-with-defuse-step-2)).

| | `src/` pipeline | `defuse2.py` |
|---|---|---|
| output per identifier | name, type, path, signature, location, docstring, ... | name and type |
| error messages the tests assert on | not selected | selected (on SWE-bench Pro, 7 extra names on 6 of 266 instances) |
| otherwise | the same selection | the same selection |

`validate_defuse2.py` compares the two on a benchmark:
`python identity_selection/validate_defuse2.py --src $OUT/hints_defuse.jsonl --defuse2 $OUT/${BENCH}_defuse2.jsonl`.

## 3. Turn a selection into mini-SWE-agent instances

A selection is a list of names per instance. Flatten it, take each name's attributes from
step 1's catalogue (`$OUT/extracted_hints.jsonl`, see
[src/README.md](../src/README.md#3-extract-the-identifiers-step-1)), and project it; the
result has the same shape as the pipeline's DefUse hints, so the same generators apply:

```bash
SEL=defuse2                               # $OUT/${BENCH}_${SEL}.jsonl: the output of step 2
P=declaration                             # any projection, see identity_projection/README.md
python identity_selection/project_nocode.py \
    -i $OUT/${BENCH}_${SEL}.jsonl -o $OUT/${BENCH}_${SEL}_names.jsonl
python identity_selection/build_selection_enriched.py --selection $OUT/${BENCH}_${SEL}_names.jsonl \
    --catalogue $OUT/extracted_hints.jsonl --output $OUT/${BENCH}_${SEL}_identifiers.jsonl
python identity_projection/project_enriched.py \
    -i $OUT/${BENCH}_${SEL}_identifiers.jsonl -o $OUT/${BENCH}_${SEL}_${P}_proj.jsonl -p $P
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${SEL}_${P}_proj.jsonl -s $INPUT \
    -b swerebench -p $P -o results/miniswe_${BENCH}/${BENCH}_${SEL}_${P}.jsonl
```

- `-b swerebench` is for inputs that carry `image_name`; see
  [identity_projection/README.md](../identity_projection/README.md#3-generate-mini-swe-agent-instances)
  for SWE-bench Pro, FEA-Bench and Doc2Feat-bench.
- `swe_pro.py` writes requirements text rather than names; flatten it with
  `project_swe_pro_nocode_llm.py` (an LLM call, same `REQUIREMENTS_*` variables) instead of
  `project_nocode.py`.
- Names the catalogue does not know keep only their name and type. For the `fea_brief` and
  `swe_pro` projections, first write the LLM descriptions on the identifiers file
  ([src/README.md](../src/README.md#5-write-the-llm-descriptions-step-3)).
- `nocode.py` and `nocode_java.py` list their names in an arbitrary order that changes from
  run to run (they iterate a Python set), so two runs give the same names in a different
  order.

## 4. Run the agent

See [mini-swe-agent/README.md](../mini-swe-agent/README.md).

## Java

The `*_java.py` scripts take the same arguments on Multi-SWE-bench Java
(`data/java/multi_swe_bench_java.jsonl`, `repos/multi_swe_java_repos`; see
[src/README.md](../src/README.md#java-multi-swe-bench)). Their outputs go straight to
`helper_code/data_prepare/generate_msb_instances.py`:

```bash
python identity_selection/nocode_java.py -i data/java/multi_swe_bench_java.jsonl \
    -r repos/multi_swe_java_repos -o results/java_msb_proj/nocode_java.jsonl --skip-errors
python helper_code/data_prepare/generate_msb_instances.py \
    --hints results/java_msb_proj/nocode_java.jsonl --source data/java/multi_swe_bench_java.jsonl \
    --projection declaration --catalogue results/java_msb_proj/extracted_hints.jsonl \
    --output results/miniswe_java/msb_nocode_java_declaration.jsonl
```

`--projection` is `name_only` or `declaration`; `--no-hints` writes the no-hint baseline.
