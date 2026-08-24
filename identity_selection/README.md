# Identity Selection

Given the same projection, we select identities using four methods.

## Methods

### 1. DefUse2 — `defuse2.py`
Extracts module-level WRITE entities from the implementation patch and READ entities
from the test patch, then computes:
- **Forward hints** = impl[WRITE] ∩ test[READ] 
- **Backward hints** = impl[READ] ∩ test[WRITE]

New `.py` files are added to forward hints unconditionally. Entities already
mentioned in the problem statement / doc_changes are filtered out.

### 2. NoCode — `nocode.py`
Based on `augment.py` (NoCode-bench original pipeline).

Extracts all identifiers (functions, classes, fields, error messages) from Python
files touched by the implementation patch, computes the new-entity diff, then
filters to those whose name also appears in the new entities of the test patch.
No READ/WRITE distinction; purely name-based intersection.

### 3. FEA-Brief — `fea_brief.py`
Based on `get_dataset.py` (FEA-Bench) / `add_new_components.py`.

AST-compares old vs new Python files in the implementation patch to find newly
added function/class namespaces. Non-Python files are ignored ("brief" variant).
No test-patch filtering.

Always computes the AST diff on-the-fly from the repo — `--repos` is required
for all four datasets.

### 4. Swe Bench Pro - `swe_pro.py`.
Interface and requirements generation are both handled in this script. Requires LLM for such generation. Currently claude haiku 4.5. Set it at Line 85, Line 86 and Line 103, for model, api base and api key.



## Steps:

### 1. download data inside identity_selection/data_selection/huggingface
`download.py` is present. Run that script inside `identity_selection/data_selection/huggingface`

### 2. For each hint selection pipeline, check corresponding README
Defuse relaxed: `README_commands_defuse_relaxed.md`
FEA Brief: `README_commands_fea_brief.md`
NoCode: `README_commands_nocode.md`
SWE Bench Pro: `README_commands_swe_pro.md`

### 3. Project the generate hints.

Check `README_commands_swe_pro.md`. Create folders if needed.

### 4. Run with mini swe agent.

### 5. Evaluate
Check with each benchmark's own evaluation pipeline presented on GitHub.