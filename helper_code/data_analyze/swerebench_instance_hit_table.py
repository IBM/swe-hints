#!/usr/bin/env python3
"""
swerebench_instance_hit_table.py
=================================
For each swerebench instance show:
  - no_hints_wrong : how many times out of 3 the instance was NOT resolved under no-hints
  - all_hints_correct: how many times out of 3 the instance WAS resolved under all-hints

Usage:
    python3 helper_code/swerebench_instance_hit_table.py
"""

import json
import os
from pathlib import Path

SWE_BENCH_FORK = Path(os.environ.get("SWE_BENCH_FORK_PATH", "SWE-bench-fork"))
PREFIX = "openai__azure__DeepSeek-V4-Flash"
REPS = [0, 1, 2]

def load_resolved(run_id: str) -> set:
    path = SWE_BENCH_FORK / f"{PREFIX}.{run_id}.json"
    d = json.loads(path.read_text())
    return set(d["resolved_ids"])

# Load all reps
no_hints  = [load_resolved(f"swerebench_no_hints_enriched_v3_repeat_{r}")  for r in REPS]
all_hints = [load_resolved(f"swerebench_all_hints_enriched_v3_repeat_{r}") for r in REPS]

# Union of all submitted instance ids
all_ids = sorted(no_hints[0] | no_hints[1] | no_hints[2] |
                 all_hints[0] | all_hints[1] | all_hints[2] |
                 # also include instances that were never resolved in either
                 load_resolved("swerebench_no_hints_enriched_v3_repeat_0") |
                 set(json.loads(
                     (SWE_BENCH_FORK / f"{PREFIX}.swerebench_no_hints_enriched_v3_repeat_0.json").read_text()
                 )["submitted_ids"]))

# Count per instance
rows = []
for iid in all_ids:
    no_wrong  = sum(1 for r in no_hints  if iid not in r)   # wrong = not resolved
    all_cor   = sum(1 for r in all_hints if iid in r)        # correct = resolved
    rows.append((iid, no_wrong, all_cor))

# Sort: most interesting first (no_hints always wrong AND all_hints always correct)
rows.sort(key=lambda x: (-x[1], -x[2], x[0]))

# Print table
header = f"{'instance_id':<55} {'no_hints_wrong/3':>17} {'all_hints_correct/3':>19}"
print(header)
print("-" * len(header))
for iid, nw, ac in rows:
    print(f"{iid:<55} {nw:>17} {ac:>19}")

print()
print(f"Total instances: {len(rows)}")
print(f"Always wrong under no-hints (3/3):    {sum(1 for _,nw,_ in rows if nw==3)}")
print(f"Always correct under all-hints (3/3): {sum(1 for _,_,ac in rows if ac==3)}")
print(f"Both (helped by hints, 3/3):          {sum(1 for _,nw,ac in rows if nw==3 and ac==3)}")
