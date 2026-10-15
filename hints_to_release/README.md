# DefUse hints released with the paper

Hints for four Python benchmarks, with the identifiers selected by DefUse, rendered under
three projections. Each folder in `rendered/` is one projection:

| folder | projection | what the hint shows for each identifier |
|---|---|---|
| `nameonly` | Name Only | its name |
| `declaration` | Declaration | its name, kind, file path, whether the file is new, and its signature |
| `swe_pro` | Pro | Declaration plus a one-sentence description and a short paragraph on behaviour, both written by Claude Haiku 4.5 from the reference patch |

Each file is one benchmark, ready to run with mini-swe-agent: one JSON object per line with
`instance_id`, `repo`, `problem_statement`, `hints` (the text inserted into the agent's
prompt), `base_commit`, and `image_name` (the container image; Doc2Feat-bench images are
named by the runner).

| file | benchmark | instances |
|---|---|---|
| `swe_pro.jsonl` | SWE-bench Pro | 68 |
| `feabench.jsonl` | FEA-Bench | 44 |
| `doc2feat.jsonl` | Doc2Feat-bench (NoCode-bench) | 21 |
| `swerebench.jsonl` | SWE-rebench | 14 |

These are the instances where DefUse selects at least one identifier, i.e. the population
of the paper's projection comparison.

## Run them

Install mini-swe-agent with this repository's overlay and write a model config
([mini-swe-agent/README.md](../mini-swe-agent/README.md), sections 1 and 3), then, from the
mini-swe-agent folder:

```bash
R=/path/to/swe-hints/hints_to_release/rendered
P=declaration                        # or nameonly, swe_pro

mini-extra swebench -c swebench_pro_hints.yaml -c my_model.yaml \
    --subset $R/$P/swe_pro.jsonl    --workers 8 --output ./output/swe_pro_$P
mini-extra swebench -c swerebench_hints.yaml   -c my_model.yaml \
    --subset $R/$P/swerebench.jsonl --workers 8 --output ./output/swerebench_$P
mini-extra swebench -c swerebench_hints.yaml   -c my_model.yaml \
    --subset $R/$P/feabench.jsonl   --workers 8 --output ./output/feabench_$P
mini-extra doc2feat -c doc2feat.yaml           -c my_model.yaml \
    --subset $R/$P/doc2feat.jsonl   --workers 8 --output ./output/doc2feat_$P
```

Add `-c daytona.yaml` last to run in Daytona instead of local Docker (section 4 there).
Score the patches with each benchmark's official evaluator (section 5 there). To make hints
for another benchmark or another projection, start from the root [README.md](../README.md).
