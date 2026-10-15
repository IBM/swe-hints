# Running mini-SWE-agent with Hints

This folder is not runnable by itself. It is an overlay for the official
[mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent), tested on release `v2.4.6`:
benchmark configs whose prompt has a slot for the hints, runners that pass each instance's
`hints` field into it, and an optional backend that runs the containers in
[Daytona](https://www.daytona.io/) sandboxes instead of local Docker.

## 1. Set Up Environment

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

# Optional: Daytona sandboxes instead of local Docker (section 4)
cp $HINTS/mini-swe-agent/environments/__init__.py              src/minisweagent/environments/
cp $HINTS/mini-swe-agent/environments/extra/swerex_daytona.py  src/minisweagent/environments/extra/
pip install daytona-sdk
```

All later `mini-extra` commands run from this mini-swe-agent folder. The first `cp` also
installs `daytona.yaml`, which does nothing unless you pass it. The Daytona `__init__.py`
is v2.4.6's with one line added that registers `swerex_daytona`. The runners added by the
overlay are `mini-extra swebench` (SWE-bench-style benchmarks), `mini-extra doc2feat` and
`mini-extra multi-swe-bench` (Java).

## 2. Pick the benchmark template

Each benchmark config is a prompt template plus container settings. The template inserts
the instance's `hints` field into the prompt inside a `<hints>` block, and leaves the block
out when `hints` is empty. The instances themselves come from
[identity_projection/README.md](../identity_projection/README.md#3-generate-mini-swe-agent-instances),
or ready-made from [hints_to_release](../hints_to_release/README.md).

| benchmark | config (`-c`) | `mini-extra` command | repository inside the container |
|---|---|---|---|
| **your own benchmark** | `swerebench_hints.yaml`, or your copy (below) | `swebench` | `/testbed`, or set in your copy |
| SWE-bench Pro | `swebench_pro_hints.yaml` | `swebench` | `/app` |
| SWE-rebench, FEA-Bench, or any SWE-bench-style benchmark | `swerebench_hints.yaml` | `swebench` | `/testbed` |
| Doc2Feat-bench | `doc2feat.yaml` | `doc2feat` | `/root/<repo name>` |
| Multi-SWE-bench Java | `multi_swe_bench_hints.yaml` | `multi-swe-bench` | `/home/<repo name>`, set per instance by the runner |

**A template for your own benchmark.** Start from `swerebench_hints.yaml`:

- **Images.** Each task needs its own image, with the repository checked out at
  `base_commit` and its test dependencies installed. Put the image name in each input row's
  `image_name` field before generating instances. Images that SWE-bench's harness builds
  already have this shape.
- **Repository path.** The template assumes the repository is at `/testbed`, in its
  working directory and in the prompt text. Make your own copy with your path in both
  places, and pass the copy by path with `-c`:

  ```bash
  # in the mini-swe-agent checkout
  REPO_DIR=/workspace                 # where your images keep the repository
  sed "s#/testbed#${REPO_DIR}#g" src/minisweagent/config/benchmarks/swerebench_hints.yaml > mybench_hints.yaml
  ```
- **Setup before the agent starts.** If each container needs a command first, such as
  activating an environment, add it to the copy. It is rendered with the instance's fields,
  so it can use `{{instance_id}}` or `{{repo}}`:

  ```yaml
  run:
    env_startup_command: "source /opt/conda/bin/activate myenv"
  ```
- **Hint wording.** The `<hints>` block opens with "Consider the following hints, which are
  about entities and identifiers that you need:". Edit `instance_template` in the copy if
  you want different framing; keep it fixed across the runs you compare.

**Images for the paper's benchmarks.** SWE-bench Pro and SWE-rebench images are pulled by
name. Doc2Feat-bench images must be pulled and tagged locally first, with
`pull_instance_images.py` from the Doc2Feat-bench repository. FEA-Bench ships no
per-instance images: build them with FEA-Bench's own harness, under the names
`generate_instances.py -b feabench` writes.

## 3. Write a model config

The run merges the benchmark config with a model config; later `-c` files win. Write your
own model config, or start from the `rits_swebench_*.yaml` examples, which use
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

Set the provider's API key in your environment (for OpenRouter, `OPENROUTER_API_KEY`).

## 4. Run

```bash
cd /path/to/mini-swe-agent && source .venv/bin/activate

# Your own benchmark (SWE-rebench and FEA-Bench: -c swerebench_hints.yaml; SWE-bench Pro: -c swebench_pro_hints.yaml)
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

- **Config names.** A `-c` value is looked up first as a path, then among the installed
  configs, so your own template and model config can sit in the current folder.
- **Workers.** Every worker runs its own container; size `--workers` to your machine.
  SWE-bench Pro containers need up to 8 GiB each.
- **Containers.** Local Docker is the default. To run in Daytona sandboxes instead, install
  the Daytona files (section 1), `export DAYTONA_API_KEY=...`, and add `-c daytona.yaml` as
  the **last** `-c` so its `environment:` settings win. Each sandbox reserves 8 GiB, and a
  Daytona organization's default limit is 200 GiB in total, so keep `--workers` at 20 or
  below. The runners also accept `--environment-class singularity` (or `swerex_modal`).
- **Limits.** Each instance stops at 250 steps or $3, set in the benchmark config.
- **Outputs.** Patches go to `<output>/preds.json` (`preds.jsonl` for Doc2Feat-bench), and
  one trajectory per instance to `<output>/<instance_id>/`.
- **Re-runs resume.** Instances already in the predictions file are skipped, including ones
  that failed with an empty patch. Pass `--redo-existing` to run them again.

## 5. Evaluate

This repository contains no evaluation code. Score the predictions with each benchmark's
official evaluator:

| benchmark | official evaluator |
|---|---|
| SWE-bench Pro | [scaleapi/SWE-bench_Pro-os](https://github.com/scaleapi/SWE-bench_Pro-os), `swe_bench_pro_eval.py` |
| FEA-Bench | [microsoft/FEA-Bench](https://github.com/microsoft/FEA-Bench) |
| Multi-SWE-bench | [multi-swe-bench/multi-swe-bench](https://github.com/multi-swe-bench/multi-swe-bench) |
| NoCode-bench (Doc2Feat-bench), SWE-rebench, others | the evaluator their authors release |

Each evaluator documents its own input format. The agent's patches are in
`<output>/preds.json` (`preds.jsonl` for Doc2Feat-bench), keyed by instance:

```json
{"<instance_id>": {"instance_id": "<instance_id>", "model_name_or_path": "...", "model_patch": "diff --git ..."}}
```

SWE-bench Pro's `swe_bench_pro_eval.py`, for example, takes a JSON list of
`{"instance_id": ..., "patch": ..., "prefix": ...}` objects. An instance counts as resolved
only when all its fail-to-pass and pass-to-pass tests pass. Report rates over all generated
instances, counting unevaluated ones as unresolved.

If your benchmark has no evaluator of its own, score each patch like this:

1. Start the task's image.
2. Apply `model_patch` with `git apply`. A patch that does not apply counts as unresolved.
3. Apply the task's `test_patch`.
4. Run the tests the task requires: those the reference patch makes pass, and those that
   passed before and must keep passing.
5. Count the task as resolved only if all of them pass.

**Comparing conditions.** The hint effect is the difference between runs on the same tasks,
so keep everything else fixed: the same model, serving provider, template and step limit,
ideally on the same day. A single run is noisy. Two runs of one identical condition can
differ by several tasks, so repeat each condition and compare means.

## SWE-bench Pro instances with the benchmark's own hints

`data_pre/generate_minisweagent_instances.py` is adapted from the SWE-bench Pro harness's
[`generate_sweagent_instances.py`](https://github.com/scaleapi/SWE-bench_Pro-os/blob/main/helper_code/generate_sweagent_instances.py).
It writes SWE-bench Pro instances with the benchmark's own human-written `requirements` and
`interface`: `--with_hints` puts both in the `hints` field, `--requirements_only` or
`--interface_only` appends one of them to `problem_statement` instead, and without these
flags there are no hints. It imports `image_uri` and `create_problem_statement` from the harness's
`helper_code/` and `create_hints` from this repository's `helper_code/`, so put both on
`PYTHONPATH`. From this repository's root:

```bash
PYTHONPATH=/path/to/SWE-bench_Pro-os/helper_code:helper_code \
python mini-swe-agent/data_pre/generate_minisweagent_instances.py \
    --dockerhub_username jefzda --python_only --with_hints \
    --output_path results/miniswe_swe_pro/swe_pro_official_hints.jsonl
```

## Troubleshooting

| symptom | cause and fix |
|---|---|
| an agent run finishes instantly with every patch empty | no container runtime; check `docker ps`, or run in Daytona with `-c daytona.yaml` last (section 4) |
| the agent cannot find the repository or runs commands in the wrong folder | your images keep it outside `/testbed`; use a template copy (section 2) |
| `Error executing startup command` | your `env_startup_command` failed inside the container; run it by hand in the image |
| many instances end with `RepeatedFormatError` | the model returned empty responses; switch or pin the serving provider and rerun with `--redo-existing` |
| `Total memory limit exceeded` in Daytona | too many sandboxes at once; lower `--workers` (section 4) |

Debug one instance with `--filter <instance_id>` on a `mini-extra` run.
