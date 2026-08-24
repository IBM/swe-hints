#!/usr/bin/env python3
"""
Download datasets from HuggingFace into identity_selection/data_selection/huggingface/.

Datasets:
  - Doc2Feat-bench/Doc2Feat-bench_Verified  → as-is
  - ScaleAI/SWE-bench_Pro                   → Python instances only (repo_language == "python")
  - microsoft/FEA-Bench                      → lite instances only (from instances_lite.json)
  - nebius/SWE-rebench-leaderboard           → 2026 partitions only

Run from project root or any directory:
    python3 identity_selection/data_selection/huggingface/download.py
Output files land next to this script.
"""

import json
import pathlib
import urllib.request

from datasets import load_dataset

OUT_DIR = pathlib.Path(__file__).parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

FEA_LITE_URL = (
    "https://raw.githubusercontent.com/microsoft/FEA-Bench/main/instances_lite.json"
)


def write_jsonl(records: list, path: pathlib.Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  wrote {path.name}  ({path.stat().st_size // 1024} KB,  {len(records)} rows)")


def all_rows(ds) -> list:
    rows = []
    for split in ds:
        rows.extend(ds[split].to_list())
    return rows


# ---------------------------------------------------------------------------
# Doc2Feat-bench/Doc2Feat-bench_Verified  — as-is
# ---------------------------------------------------------------------------
print("==> Doc2Feat-bench/Doc2Feat-bench_Verified")
ds = load_dataset("Doc2Feat-bench/Doc2Feat-bench_Verified")
write_jsonl(all_rows(ds), OUT_DIR / "doc2feat_verified.jsonl")

# ---------------------------------------------------------------------------
# ScaleAI/SWE-bench_Pro  — Python instances only
# ---------------------------------------------------------------------------
print("==> ScaleAI/SWE-bench_Pro  (Python only, field: repo_language)")
ds = load_dataset("ScaleAI/SWE-bench_Pro")
records = [row for row in all_rows(ds) if (row.get("repo_language") or "").lower() == "python"]
write_jsonl(records, OUT_DIR / "swebench_pro_python.jsonl")

# ---------------------------------------------------------------------------
# microsoft/FEA-Bench  — lite instances only
# ---------------------------------------------------------------------------
print("==> microsoft/FEA-Bench  (lite instances only)")
print(f"  fetching lite instance list from GitHub …")
with urllib.request.urlopen(FEA_LITE_URL, timeout=30) as resp:
    raw = resp.read().decode()
lite_ids: set = set(json.loads(raw))
print(f"  {len(lite_ids)} lite instance ids")

lite_json_path = OUT_DIR / "instances_lite.json"
lite_json_path.write_text(raw, encoding="utf-8")
print(f"  wrote {lite_json_path.name}")

ds = load_dataset("microsoft/FEA-Bench")
records = [row for row in all_rows(ds) if row.get("instance_id") in lite_ids]
write_jsonl(records, OUT_DIR / "fea_bench_lite.jsonl")

# ---------------------------------------------------------------------------
# nebius/SWE-rebench-leaderboard  — 2026 partitions only
# ---------------------------------------------------------------------------
print("==> nebius/SWE-rebench-leaderboard  (2026 partitions only)")
ds = load_dataset("nebius/SWE-rebench-leaderboard")
records = []
for split in ds:
    if split.startswith("2026_"):
        records.extend(ds[split].to_list())
write_jsonl(records, OUT_DIR / "swe_rebench_leaderboard.jsonl")

print("\nAll done.")
