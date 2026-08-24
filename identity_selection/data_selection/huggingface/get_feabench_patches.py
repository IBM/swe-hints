#!/usr/bin/env python3
"""
Convert fea_bench_lite.jsonl to HF Arrow format for use with get_dataset.py.

Run from the hints repo root:
    source .venv/bin/activate
    python identity_selection/data_selection/huggingface/get_feabench_patches.py

Output:
    identity_selection/data_selection/huggingface/fea_bench_lite_hf/
"""

import pathlib
from datasets import load_dataset, DatasetDict

SCRIPT_DIR = pathlib.Path(__file__).parent
LITE_JSONL  = SCRIPT_DIR / "fea_bench_lite.jsonl"
HF_ARROW    = SCRIPT_DIR / "fea_bench_lite_hf"

ds = load_dataset("json", data_files=str(LITE_JSONL), split="train")
DatasetDict({"test": ds}).save_to_disk(str(HF_ARROW))
print(f"Saved {len(ds)} instances to {HF_ARROW}")
