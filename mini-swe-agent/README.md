# Mini SWE Agent Set up

### 1. Set up mini swe agent using the offical github repo: https://github.com/swe-agent/mini-swe-agent. 

Then, cd `mini-swe-agent`. From now on, `mini-swe-agent` is the place where your `mini-swe-agent` lives.

### 2. Copy/replace files to desire places as shown below:

For three yamls files
```
mini-swe-agent/rits_swebench_claude_haiku.yaml
mini-swe-agent/rits_swebench_ds.yaml
mini-swe-agent/rits_swebench_gpt_oss_120b_json_tool_call.yaml
```
Put those inside `mini-swe-agent`


For more yaml files inside `config/benchmark`:
```
mini-swe-agent/config/doc2feat.yaml
mini-swe-agent/config/swebench_pro_hints_json_tool_call.yaml
mini-swe-agent/config/swebench_pro_hints.yaml
mini-swe-agent/config/swerebench_hints.yaml
```

Put those inside `mini-swe-agent/src/minisweagent/config/benchmarks`


For files under `model_registry_cost` folder:
```
mini-swe-agent/model_registry_cost
mini-swe-agent/model_registry_cost/ds_litellm_model_registry.json
mini-swe-agent/model_registry_cost/litellm_model_registry.json
mini-swe-agent/model_registry_cost/oss_litellm_model_registry.json
```

Put the `model_registry_cost` folder under `mini-swe-agent` directly.

For files under `run/benchmarks`:
```
mini-swe-agent/run/benchmarks/doc2feat.py
mini-swe-agent/run/benchmarks/swebench.py
```
Put those files under `mini-swe-agent/src/minisweagent/run/benchmarks`

For the file `mini-swe-agent/run/utilities/mini_extra.py`, put it under `mini-swe-agent/src/minisweagent/run/utilities`

### 3. Prepare the data

Refer to `data_pre` folder, where the scripts are adapted from https://github.com/scaleapi/SWE-bench_Pro-os/blob/main/helper_code/generate_sweagent_instances.py

For instance, for swe bench pro, do:
```python data_pre/generate_minisweagent_instances.py \
  --dockerhub_username jefzda \
  --output_path mini_swe_instances.jsonl
  --python_only
```

### 4. Execute mini swe agent:

```
mini-extra swebench \
  -c swebench_pro_hints.yaml  \
  -c rits_swebench.yaml  \
  --subset mini_swe_instances.jsonl \
  --workers 32 \
  --output ./output/YOUR_OUTPUT_FOLDER
```

### 5. Evaluate

For SWE Bench Pro
```
python eval/gather_patches.py \
    --directory ./output/YOUR_OUTPUT_FOLDER\
    --prefix NAME\
    --output NAME.json \
    --mini
```


Then, 
```
python swe_bench_pro_eval.py \
    --raw_sample_path=PYTHON_ALL.jsonl \
    --patch_path=NAME.json \
    --output_dir=results/NAME\
    --scripts_dir=run_scripts \
    --num_workers=100 \
    --dockerhub_username=jefzda \
    --use_local_docker
```
where `PYTHON_ALL.jsonl` is parsed from the official SWE Bench Pro huggingface dataset, and select the python instances.
