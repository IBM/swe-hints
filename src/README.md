# Hints Pipeline

End-to-end pipeline for generating identifier-level hints from SWE-bench Pro
(Python subset), controlled by two independent dimensions:

1. **Which identifiers** — usage operator (step 1)
2. **How much to reveal** — taxonomy level (step 2)
3. **How to enrich semantics** — LLM-based post-processing (after step 2)



## Constructing `repos-dir` (SWE-bench Pro Python)

The Python subset of SWE-bench Pro covers three GitHub repositories.
Step 1 resets each repo to a `base_commit` and applies the patch, so
**full history is required** (no shallow clones).

### Clone the three repos

```bash
mkdir -p repos/swe_pro_python_repos

git clone https://github.com/ansible/ansible.git \
    repos/swe_pro_python_repos/ansible

git clone https://github.com/qutebrowser/qutebrowser.git \
    repos/swe_pro_python_repos/qutebrowser

git clone https://github.com/internetarchive/openlibrary.git \
    repos/swe_pro_python_repos/openlibrary
```

### Verify

```bash
ls repos/swe_pro_python_repos/
# ansible/   openlibrary/   qutebrowser/

git -C repos/swe_pro_python_repos/ansible      log --oneline -1
git -C repos/swe_pro_python_repos/qutebrowser  log --oneline -1
git -C repos/swe_pro_python_repos/openlibrary  log --oneline -1
```

### Important: directory names must match the repo slug

`identifier_usage.py` derives the local directory name as:
```python
repo_name = instance["repo"].split("/")[-1]
# "ansible/ansible"             -> "ansible"
# "qutebrowser/qutebrowser"     -> "qutebrowser"
# "internetarchive/openlibrary" -> "openlibrary"
```

So the directory names inside `repos/swe_pro_python_repos/` must be exactly
`ansible`, `qutebrowser`, and `openlibrary`.

### If you accidentally shallow-cloned

```bash
git -C repos/swe_pro_python_repos/ansible      fetch --unshallow
git -C repos/swe_pro_python_repos/qutebrowser  fetch --unshallow
git -C repos/swe_pro_python_repos/openlibrary  fetch --unshallow
```

---

## Step 1 — Identifier usage extraction

Runs once per dataset. Resets each repo to `base_commit`, diffs before/after
the patch, and stores the four read/write identifier sets for every instance.

```bash
python -m src.identifier_usage \
  --input     /path/to/swebench_pro_python.jsonl \
  --repos-dir repos/swe_pro_python_repos \
  --output    results/step1_usage.jsonl \
  --skip-errors
```

**Output format** (one JSON line per instance):
```json
{
  "instance_id": "instance_ansible__ansible-...",
  "code_read":  ["BaseRole", "TaskInclude", ...],
  "code_write": ["RoleInclude", "load_data", ...],
  "test_read":  ["RoleInclude", "load_data", ...],
  "test_write": ["test_load", ...]
}
```

To debug a single instance:
```bash
python -m src.identifier_usage \
  --input     /path/to/swebench_pro_python.jsonl \
  --repos-dir repos/swe_pro_python_repos \
  --output    results/step1_debug.jsonl \
  --instance-id "instance_ansible__ansible-a26c325b..."
```

---

## Step 2 — Hint construction

Runs fast (no repo needed). Loads step 1 output + the augmented dataset,
applies a **usage operator** to select identifiers, then projects each
identifier to a **taxonomy level** controlling how much information to reveal.

```bash
python -m src.identifier_information \
  --usage      results/step1_usage.jsonl \
  --augmented  /path/to/swebench_pro_augmented.jsonl \
  --operator   forward \
  --level      WeakSFunc \
  --output     results/hints_forward_WeakSFunc.jsonl \
  --skip-errors
```

**Output format** (one JSON line per instance):
```json
{
  "instance_id": "instance_ansible__ansible-...",
  "operator": "forward",
  "level": "WeakSFunc",
  "identifiers": [
    {"name": "RoleInclude", "entity_type": "class", "weak_semantics": "..."},
    {"name": "load_data",   "entity_type": "function", "weak_semantics": "..."}
  ]
}
```

---

## After Step 2 — Semantic enrichment

[`enrich_semantics.py`](src/enrich_semantics.py) runs **after step 2**. It reads a
hints JSONL produced by [`identifier_information.py`](src/identifier_information.py:1)
and overwrites `weak_semantics` / `strong_semantics` for every identifier using an
LLM, with prompt context built from:

- structural identifier facts already present in the step 2 output
- `problem_statement` from the source SWE-bench JSONL
- filtered `patch` and `test_patch` context around the identifier name

Typical usage:

```bash
python -m src.enrich_semantics \
  --hints   results/hints_communication_All.jsonl \
  --source  data/swebench_pro_python.jsonl \
  --output  results/hints_communication_All_enriched.jsonl \
  --skip-errors
```

Useful modes:

```bash
# Smoke-test one instance
python -m src.enrich_semantics \
  --hints   results/hints_communication_All.jsonl \
  --source  data/swebench_pro_python.jsonl \
  --output  /tmp/enriched_one.jsonl \
  --instance-id "instance_ansible__ansible-..."

# Dry-run: build prompts only, no LLM calls
python -m src.enrich_semantics \
  --hints   results/hints_communication_All.jsonl \
  --source  data/swebench_pro_python.jsonl \
  --output  /tmp/enriched_dry.jsonl \
  --dry-run \
  --limit 2
```

Environment variables used by [`enrich_semantics.py`](src/enrich_semantics.py:61):

- `ENRICH_MODEL`
- `ENRICH_API_BASE`
- `ENRICH_API_KEY`

---

## Usage operators (step 1 dimension)

| Operator        | Formula                                       | Meaning                          |
|-----------------|-----------------------------------------------|----------------------------------|
| `forward`       | `code_write ∩ test_read`                      | New APIs defined in code, used in tests |
| `backward`      | `code_read ∩ test_write`                      | Test fixtures used in code       |
| `communication` | `(code_write ∩ test_read) ∪ (code_read ∩ test_write)` | forward ∪ backward       |
| `intersection`  | `(code_read ∪ code_write) ∩ (test_read ∪ test_write)` | Any shared identifier    |
| `code_only`     | `code_read ∪ code_write`                      | Everything touched by code patch |
| `test_only`     | `test_read ∪ test_write`                      | Everything touched by test patch |
| `union`         | all four sets                                 | Everything from both patches     |

---

## Taxonomy levels (step 2 dimension)

Selected nodes from the hint taxonomy (coarse → fine):

| Node          | Fields revealed                                              |
|---------------|--------------------------------------------------------------|
| `File`        | name, entity_type                                            |
| `FileLoc`     | + path                                                       |
| `Class`       | name, entity_type                                            |
| `WeakSClass`  | + weak_semantics (short description)                         |
| `StrongSClass`| + strong_semantics (detailed docstring)                      |
| `LocParClass` | + partial_location                                           |
| `LocCompClass`| + complete_location                                          |
| `Func`        | name, entity_type                                            |
| `Sign`        | + signature                                                  |
| `InN`         | + input_spec, input_names                                    |
| `InT`         | + input_spec, input_types                                    |
| `OutPT`       | + output_partial_type                                        |
| `OutCT`       | + output_partial_type, output_complete_type                  |
| `WeakSFunc`   | + weak_semantics                                             |
| `StrongSFunc` | + weak_semantics, strong_semantics                           |
| `LocParFunc`  | + partial_location                                           |
| `LocCompFunc` | + partial_location, complete_location                        |
| `ExceptType`  | + exception_types                                            |
| `ExceptValue` | + exception_types, exception_values                          |

Use `with_nodes(["Sign", "WeakSFunc"])` in the Python API to combine multiple nodes.

---

## Typical experiment run

```bash
# 1. Extract once (slow, needs repos)
python -m src.identifier_usage \
  --input     data/swebench_pro_python.jsonl \
  --repos-dir repos/swe_pro_python_repos \
  --output    results/step1_usage.jsonl \
  --skip-errors

# 2. Generate hints for different operator × level combinations (fast)
for op in forward communication intersection; do
  for level in File WeakSFunc Sign LocParFunc; do
    python -m src.identifier_information \
      --usage     results/step1_usage.jsonl \
      --augmented data/swebench_pro_augmented.jsonl \
      --operator  $op \
      --level     $level \
      --output    results/hints_${op}_${level}.jsonl \
      --skip-errors
  done
done

# 3. Optionally enrich semantics after step 2 (LLM-based)
python -m src.enrich_semantics \
  --hints   results/hints_communication_All.jsonl \
  --source  data/swebench_pro_python.jsonl \
  --output  results/hints_communication_All_enriched.jsonl \
  --skip-errors
```

# Made with Bob
