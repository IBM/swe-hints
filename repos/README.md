# Cloning the Benchmarks' Repositories

The pipeline (`src/`) and the selection scripts (`identity_selection/`) check out each
task's `base_commit` and apply its patches, so every repository must be a **full clone**
(not shallow). The scripts here clone them; the clones themselves are not part of this
repository. Run them from the repository root, in the environment from the root README's
[Setup](../README.md#setup).

## 1. Clone

`build_swerebench_repos.py` works for any input file: it reads `repo` from every row and
clones `https://github.com/<repo>` with full history into `$REPOS/<name>`. On a re-run it
unshallows or fetches existing clones instead.

```bash
python repos/build_swerebench_repos.py --input $INPUT --repos-dir $REPOS --dry-run   # preview
python repos/build_swerebench_repos.py --input $INPUT --repos-dir $REPOS --skip-errors
```

When it finishes, it prints a step-1 command with its own output path; use the one in
[src/README.md](../src/README.md#3-extract-the-identifiers-step-1) instead, which keeps
everything under `$OUT`.

The other scripts do the same for one benchmark each:

| script | benchmark | default `--repos-dir` |
|---|---|---|
| `build_swe_pro_repos.py` | SWE-bench Pro, Python instances (`--verify-only` checks existing clones without cloning) | `repos/swe_pro_python_repos` |
| `build_feabench_repos.py` | FEA-Bench (needed to rebuild its patches, see [src/README.md](../src/README.md#the-four-benchmarks-in-the-paper)) | `repos/feabench_repos` |
| `build_java_repos.py` | Java; `--input data/java/multi_swe_bench_java.jsonl --repos-dir repos/multi_swe_java_repos` for Multi-SWE-bench | `repos/java_repos` |

## 2. When something goes wrong

- **A base commit was force-pushed away.** GitHub often still serves it by hash:
  `git -C $REPOS/<name> fetch origin <base_commit>`. If that returns 404 the instance cannot
  be processed; `--skip-errors` in the pipeline skips it.
- **The repository is private or not on GitHub.** The scripts only clone
  `https://github.com/<repo>`. Clone it yourself with full history into `$REPOS/<name>`,
  where `<name>` is the part of `repo` after the slash.
- **Two repositories share a name** under different owners. Clone both as
  `$REPOS/<owner>__<name>` and keep no plain `$REPOS/<name>` folder. The `src/` pipeline
  prefers the `<owner>__<name>` folder; `identity_selection/defuse2.py` uses it only when
  no plain `<name>` folder exists.
- **Parallel jobs.** The pipeline resets the clones, so run one job at a time per
  `$REPOS`, or give each job its own copy: `git clone --shared $REPOS/<name> <other_dir>/<name>`.
