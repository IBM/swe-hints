# Projections and Agent Instances

The code in this directory decides **how much** a hint reveals about each selected
identifier, and writes the mini-SWE-agent instances: each benchmark row with the rendered
hint added as a `hints` field. Run all commands from the repository root, in the environment
from the root README's [Setup](../README.md#setup), with the variables (`BENCH`, `INPUT`,
`OUT`) from its [Quick start](../README.md#quick-start-defuse-hints-for-your-own-benchmark). The input is the
DefUse result of [src/README.md](../src/README.md#4-select-with-defuse-step-2), or a
selection prepared as in [identity_selection/README.md](../identity_selection/README.md#3-turn-a-selection-into-mini-swe-agent-instances).

## 1. Choose a projection

| projection (`-p`) | name in the paper | shows per identifier | needs LLM descriptions |
|---|---|---|---|
| `nameonly` | Name Only | the name | no |
| `nocode` | Doc2Feat | name and kind, in Doc2Feat-bench's format | no |
| `declaration` | Declaration | name, kind, path, new-file flag and signature; class members nested under their class | no |
| `fea_brief` | Declaration+Doc | `declaration` plus a one-sentence description | yes |
| `swe_pro` | Pro | `fea_brief` plus a two-to-four sentence description of behaviour | yes |

`declaration` is the projection we recommend: it gives the interface the hidden tests depend
on, and no text describing how the solution works. For `fea_brief` and `swe_pro`, write the
LLM descriptions first ([src/README.md](../src/README.md#5-write-the-llm-descriptions-step-3))
and project the enriched file. The code also defines `semantics_only` and `declaration_v2`,
which are experimental.

## 2. Project

```bash
P=declaration        # nameonly | nocode | declaration | fea_brief | swe_pro
python identity_projection/project_enriched.py \
    -i $OUT/hints_defuse_nonempty.jsonl -o $OUT/${BENCH}_${P}_proj.jsonl -p $P
```

## 3. Generate mini-SWE-agent instances

| benchmark | generator | container image in each row |
|---|---|---|
| your own benchmark, SWE-rebench, any SWE-bench-style benchmark | `generate_instances.py -b swerebench` | the input row's `image_name` |
| SWE-bench Pro | `generate_instances.py -b swebench_pro -d jefzda` | `jefzda/sweap-images:<dockerhub_tag>` |
| FEA-Bench | `generate_instances.py -b feabench` | `feabench/sweb.eval.x86_64.<owner>_1776_<repo>-<n>:latest`, from `instance_id` |
| Doc2Feat-bench | `generate_doc2feat_instances.py` | none; the runner names it `ncbench_<instance_id>:latest` |
| Multi-SWE-bench Java | `generate_instances.py -b multi_swe_bench` | `mswebench/<org>_m_<repo>:pr-<number>` |

```bash
AGENT_IN=results/miniswe_${BENCH}/${BENCH}_${P}.jsonl

# Your own benchmark, or SWE-rebench: input rows carry image_name
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -b swerebench -p $P -o $AGENT_IN

# SWE-bench Pro: image built from dockerhub_tag
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -b swebench_pro -d jefzda -p $P -o $AGENT_IN

# FEA-Bench: the source is the dataset folder FEA-Bench builds (e.g. FEA-Bench-v1.0-Standard)
python identity_projection/generate_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl \
    -s /path/to/FEA-Bench-v1.0-Standard -b feabench -p $P -o $AGENT_IN

# Doc2Feat-bench
python identity_projection/generate_doc2feat_instances.py -H $OUT/${BENCH}_${P}_proj.jsonl -s $INPUT \
    -p $P -o $AGENT_IN
```

Each row has `instance_id`, `repo`, `problem_statement`, `hints`, `base_commit`, and
`image_name` (except for Doc2Feat-bench). For Doc2Feat-bench, the hint block the benchmark
already appends to `problem_statement` is removed first.

**The no-hint baseline.** Compare against the same instances with the hints removed. Copy
any projection's file and blank the field:

```bash
python -c "import json,sys; [print(json.dumps({**json.loads(l), 'hints': ''})) for l in open(sys.argv[1])]" \
    $AGENT_IN > results/miniswe_${BENCH}/${BENCH}_empty.jsonl
```

## 4. Run the agent

See [mini-swe-agent/README.md](../mini-swe-agent/README.md).

## What the agent sees

For a step-2 record with the identifiers `b_data` (a variable) and `prepare_multipart` (a
function in `lib/ansible/module_utils/urls.py`), the `hints` field reads:

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

The benchmark configs in `mini-swe-agent/` insert it into the prompt inside a `<hints>`
block, and leave the block out when `hints` is empty.

## Java (Multi-SWE-bench)

Project the Java DefUse result the same way, then generate with
`-b multi_swe_bench` and the Multi-SWE-bench source:

```bash
python identity_projection/project_enriched.py \
    -i results/java_msb_proj/hints_communication_all_nonempty.jsonl \
    -o results/java_msb_proj/msb_declaration_proj.jsonl -p declaration
python identity_projection/generate_instances.py -H results/java_msb_proj/msb_declaration_proj.jsonl \
    -s data/java/multi_swe_bench_java.jsonl -b multi_swe_bench -p declaration \
    -o results/miniswe_java/msb_declaration.jsonl
```

Selections from the `*_java.py` scripts go through
`helper_code/data_prepare/generate_msb_instances.py` instead
([identity_selection/README.md](../identity_selection/README.md#java)).
