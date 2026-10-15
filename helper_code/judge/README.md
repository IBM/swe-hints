# LLM Judge of Hint Attributes

The code in this directory scores what each attribute of a hint (name, kind, path, new-file
flag, signature, and the two LLM-written descriptions) does for an agent, with an LLM judge.
Each (instance, identifier, attribute) is scored on three ordinal scales:

| scale | question | 0 | 3 |
|---|---|---|---|
| N, necessity | could the agent not recover it from the task alone? | redundant | load-bearing |
| D, disclosure | how much of the solution does it reveal? | interface | transcription |
| G, guidance | how far does it direct the agent's actions? | declarative | prescriptive |

The **hint value margin** is `HVM = N - max(D, G)`: positive when an attribute supplies more
than it gives away. Necessity is asked without the solution (problem statement only);
disclosure and guidance are asked with the reference and test patches. Run all commands
from the repository root, in the environment from the root README's
[Setup](../../README.md#setup).

## 1. Set Up Environment

The judge calls an LLM through litellm, which that environment includes. The paper used
GPT 5.6 Luna with medium reasoning effort, through OpenRouter:

```bash
export JUDGE_API_KEY=...                                  # defaults to $OPENROUTER_API_KEY
export JUDGE_MODEL=openrouter/openai/gpt-5.6-luna         # the default
export JUDGE_REASONING_EFFORT=medium                      # the default
# export JUDGE_API_BASE=https://...                       # for a non-OpenRouter endpoint
```

## 2. Judge

The input is the enriched DefUse result of
[src/README.md](../../src/README.md#5-write-the-llm-descriptions-step-3) and the benchmark
file. For the paper's SWE-bench Pro setting:

```bash
python helper_code/judge/hint_attribute_judge.py \
    --hints  results/swe_pro_proj/hints_communication_all_nonempty_enriched.jsonl \
    --source identity_selection/data_selection/huggingface/swebench_pro_python.jsonl \
    --output results/judge/swe_pro_attr_judgments.jsonl \
    --samples 3 --workers 8
```

- `--samples 3` asks each question three times and keeps the median.
- `--dry-run --limit 2` builds the prompts without calling the model.
- `--attributes name` judges one attribute only.
- `--repos-dir repos/swe_pro_python_repos` adds a measured column: whether the hinted name
  already exists in the repository at `base_commit` (a `git grep`), against which the
  judge's necessity score for `name` can be checked.
- The run is resumable; `--redo` starts over.

## 3. Aggregate

```bash
python helper_code/judge/report_attribute_scores.py --input results/judge/swe_pro_attr_judgments.jsonl
python helper_code/judge/report_attribute_scores.py --input results/judge/swe_pro_attr_judgments.jsonl --latex
```

The report gives, per attribute, the number of judgments, the mean N, D, G and HVM, and a
95% interval for HVM bootstrapped over instances (identifiers of one instance are not
independent). Attributes exist on different subsets (`signature` only on callables, `path`
and `is_new_file` only where the identifier lives in a file), so the means are over
different populations. On the paper's 787 judgments over 68 instances, the structural
attributes have a mean HVM of +1.39 and the semantic ones -0.05.
