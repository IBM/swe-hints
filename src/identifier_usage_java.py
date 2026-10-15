#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Step 1 for JAVA: identifier usage extraction (relaxed scope).

Standalone counterpart of ``python -m src.identifier_usage`` for Java
repositories.  Same CLI surface, same control flow, same JSONL schema:

    {instance_id, code_read, code_write, test_read, test_write, catalogue}

so step 2 (``python -m src.identifier_information``) and everything downstream
consume the output unchanged.

    python -m src.identifier_usage_java \
        --input data/java/swebench_multilingual_java.jsonl \
        --repos-dir repos/java_repos \
        --output results/java_proj/extracted_hints.jsonl --skip-errors

ADDITIVE ONLY.  Not a single frozen module is modified.  ``IdentifierUsage``
(the pydantic record) and ``get_doc_content`` are imported READ-ONLY from
``src.identifier_usage`` so the emitted schema and the
problem-statement filter are guaranteed identical to the Python path; local
fallbacks are used if that import ever fails.  The git helpers (``_reset`` /
``_apply_patch``) are re-implemented here rather than imported, because they are
private names in a frozen module.

Flow (identical to the Python path)
-----------------------------------
    git reset --hard / clean / checkout <base_commit>
    parse every .java file the patch touches      -> before-state tokens
    git apply <patch>
    parse them again                              -> after-state tokens
    set-difference on typed (name, entity_type) tokens, projected to bare names

Java-specific details live in ``src/lang/java_usage.py`` (WRITE/READ rules,
``package_declaration``-based ``path_to_module``, and the same-package implicit
import rule).  Two of them matter here:

* ``local_modules`` is the union of the BEFORE and AFTER states **of both
  patches**.  A file added by the patch has no before-state package, and the
  before/after states must be gated by the same key set or the set-difference
  invents WRITEs.  Spanning both patches is what makes the same-package rule
  reach across the impl/test boundary: the test carries no import for a class in
  its own package AND does not touch that class's file, so the Python path's
  per-patch, before-state-only key set could never classify it.  (Both changes
  are Java-only; the Python module is untouched.)
* New ``.java`` file paths are added to ``code_write`` verbatim, mirroring the
  new-``.py``-file rule; ``IdentifierUsage.get_with`` recognises them by the "/".

Catalogue
---------
Rich per-entity records (CONTRACT 1) come from ``src/lang/java_extractor.py``.
If that module is absent or raises, the catalogue is left empty and every name
degrades downstream to ``{name, entity_type: "variable"}`` — exactly the
degradation ``src/identifier_information.py`` already applies to Python names
with no catalogue entry.  ``--catalogue require`` turns the absence into an error.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Literal, Optional

from unidiff import PatchSet

from src.lang.java_usage import (
    JAVA_EXTENSIONS,
    extract_entities,
    local_module_keys,
    names as _names,
    parse as _java_parse,
)

UsageOperator = Literal[
    "intersection",
    "communication",
    "forward",
    "backward",
    "code_only",
    "test_only",
    "union",
]


# ---------------------------------------------------------------------------
# Read-only reuse of the frozen record + doc filter
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised by the import itself
    from src.identifier_usage import IdentifierUsage, get_doc_content
except Exception:  # pragma: no cover - fallback, keeps this module standalone
    from pydantic import BaseModel, model_validator

    class IdentifierUsage(BaseModel):  # type: ignore[no-redef]
        code_read: list
        code_write: list
        test_read: list
        test_write: list
        catalogue: dict = {}

        @model_validator(mode="before")
        @classmethod
        def _sort(cls, values: dict) -> dict:
            for k in ("code_read", "code_write", "test_read", "test_write"):
                if k in values and isinstance(values[k], (list, set)):
                    values[k] = sorted(values[k])
            return values

        def get_with(self, operator: UsageOperator) -> list:
            cr, cw = set(self.code_read), set(self.code_write)
            tr, tw = set(self.test_read), set(self.test_write)
            new_files = {n for n in cw if "/" in n}
            if operator == "intersection":
                result = (cr | cw) & (tr | tw) | new_files
            elif operator == "communication":
                result = (cw & tr) | (cr & tw) | new_files
            elif operator == "forward":
                result = cw & tr | new_files
            elif operator == "backward":
                result = cr & tw
            elif operator == "code_only":
                result = cr | cw
            elif operator == "test_only":
                result = tr | tw
            elif operator == "union":
                result = cr | cw | tr | tw
            else:
                raise ValueError(f"Unknown operator: {operator!r}")
            return sorted(result)

    def get_doc_content(instance: dict) -> str:  # type: ignore[no-redef]
        if "doc_changes" in instance:
            items = instance.get("doc_changes") or []
            return "\n".join(
                str(item.get("metadata", "")) for item in items if isinstance(item, dict)
            )
        if "problem_info" in instance:
            pi = instance.get("problem_info") or {}
            return "\n".join(filter(None, [pi.get("pr_title", ""), pi.get("pr_body", "")]))
        return instance.get("problem_statement", "") or ""


# ---------------------------------------------------------------------------
# Rich catalogue (CONTRACT 1) — optional dependency on src/lang/java_extractor.py
# ---------------------------------------------------------------------------

_RICH_WARNED = False


def _rich_extractor(mode: str = "auto"):
    """Return java_extractor.extract_rich_entities, or None when unavailable."""
    global _RICH_WARNED
    if mode == "off":
        return None
    try:
        from src.lang.java_extractor import extract_rich_entities
        return extract_rich_entities
    except Exception as exc:
        if mode == "require":
            raise RuntimeError(
                f"--catalogue require: src/lang/java_extractor.py unusable ({exc!r})"
            ) from exc
        if not _RICH_WARNED:
            print(f"  WARN no Java rich extractor ({exc!r}); catalogue will be empty")
            _RICH_WARNED = True
        return None


# ---------------------------------------------------------------------------
# Repo helpers (logic re-implemented from the frozen module, not imported)
# ---------------------------------------------------------------------------

def _run(cmd: list, cwd: Path, *, retries: int = 0, delay: float = 2.0) -> None:
    """
    Run a git command.  ``retries`` exists because these benchmark clones are a
    shared resource: another process running step 1 (or a different language
    lane) on the same checkout holds .git/index.lock and every git call in this
    module fails with exit 128 until it lets go.  Retrying is strictly better
    than losing the instance, but it does NOT make concurrent runs correct — two
    processes resetting one clone to different commits will read each other's
    working tree.  Use a private clone (git clone --shared) per lane.
    """
    attempt = 0
    while True:
        try:
            subprocess.run(
                cmd, cwd=str(cwd), check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except subprocess.CalledProcessError:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(delay)


def _reset(repo_dir: Path, commit: str, retries: int = 0) -> None:
    _run(["git", "reset", "--hard", "-q"], repo_dir, retries=retries)
    _run(["git", "clean", "-fdx", "-q"], repo_dir, retries=retries)
    _run(["git", "checkout", "-q", commit], repo_dir, retries=retries)
    _run(["git", "reset", "--hard", "-q"], repo_dir, retries=retries)
    _run(["git", "clean", "-fdx", "-q"], repo_dir, retries=retries)


def _apply_patch(repo_dir: Path, patch_text: str, tag: str) -> bool:
    patch_file = repo_dir / f".swebench_java_{tag}.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        _run(["git", "apply", "--check", patch_file.name], repo_dir)
        _run(["git", "apply", patch_file.name], repo_dir)
        return True
    except subprocess.CalledProcessError:
        return False
    finally:
        try:
            patch_file.unlink()
        except FileNotFoundError:
            pass


def _read_or_none(path: Path) -> Optional[str]:
    """None when the file does not exist in this state (added or deleted)."""
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else None


def _java_files(patch_text: str) -> list:
    if not patch_text.strip():
        return []
    try:
        return [f for f in PatchSet(patch_text.rstrip("\n")) if f.path.endswith(JAVA_EXTENSIONS)]
    except Exception:
        return []


def _added_java_paths(patch_text: str) -> set:
    try:
        return {
            f.path for f in PatchSet(patch_text.rstrip("\n")).added_files
            if f.path.endswith(JAVA_EXTENSIONS)
        }
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

class ScanStats:
    """Counters surfaced by the CLI (parse failures are silent otherwise)."""

    def __init__(self) -> None:
        self.files = 0
        self.parse_errors = 0
        self.patch_apply_failures = 0

    def note(self, code: Optional[str]) -> None:
        if not code:
            return
        self.files += 1
        tree = _java_parse(code)
        if tree is None or tree.root_node.has_error:
            self.parse_errors += 1


def _collect_sources(
    repo_dir: Path,
    base_commit: str,
    patch_text: str,
    tag: str,
    *,
    git_retries: int = 0,
    stats: Optional[ScanStats] = None,
) -> Optional[dict]:
    """
    Reset -> read before-state -> apply patch -> read after-state, for the .java
    files one patch touches.  Returns None when there is nothing to do or the
    patch does not apply.

    Parsing is deliberately NOT done here: ``local_modules`` has to be known
    first, and it spans BOTH patches (see ``usage_from_instance``).
    """
    if not patch_text.strip():
        return None

    _reset(repo_dir, base_commit, git_retries)
    patched_files = _java_files(patch_text)
    if not patched_files:
        return None

    paths = [pf.path for pf in patched_files]
    before_src = {p: _read_or_none(repo_dir / p) for p in paths}

    if not _apply_patch(repo_dir, patch_text, tag):
        if stats is not None:
            stats.patch_apply_failures += 1
        return None

    after_src = {p: _read_or_none(repo_dir / p) for p in paths}
    return {
        "paths": paths,
        "added": _added_java_paths(patch_text),
        "before": before_src,
        "after": after_src,
    }


def _tokens_from_sources(
    src: Optional[dict],
    local_modules: set,
    *,
    same_package: bool = True,
    filter_ubiquitous: bool = False,
    catalogue_mode: str = "auto",
    stats: Optional[ScanStats] = None,
) -> tuple:
    """
    Before/after set-difference over one patch's cached sources.

    Returns ``(new_write_names, new_read_names, catalogue)``.  The catalogue
    covers every top-level entity in the AFTER state of every touched file (new,
    modified and untouched alike), matching the Python path: step 2 must be able
    to look up any name any operator can produce.
    """
    if not src:
        return set(), set(), {}

    new_writes: set = set(src["added"])   # new .java files: path IS the token
    new_reads: set = set()
    catalogue: dict = {}
    rich = _rich_extractor(catalogue_mode)

    for path in src["paths"]:
        before_code = src["before"].get(path) or ""
        after_code = src["after"].get(path) or ""
        if stats is not None:
            stats.note(after_code)

        bw, br = extract_entities(
            before_code, local_modules,
            same_package=same_package, filter_ubiquitous=filter_ubiquitous,
        )
        aw, ar = extract_entities(
            after_code, local_modules,
            same_package=same_package, filter_ubiquitous=filter_ubiquitous,
        )
        new_writes |= _names(aw - bw)
        new_reads |= _names(ar - br)

        if rich is not None and after_code:
            try:
                after_rich = rich(after_code, path, path in src["added"])
            except Exception as exc:
                print(f"  WARN catalogue failed for {path}: {exc!r}")
                after_rich = {}
            for key, info in after_rich.items():
                if key not in catalogue:
                    catalogue[key] = info

    return new_writes, new_reads, catalogue


def _diff_names(
    repo_dir: Path,
    base_commit: str,
    patch_text: str,
    tag: str,
    *,
    same_package: bool = True,
    filter_ubiquitous: bool = False,
    catalogue_mode: str = "auto",
    git_retries: int = 0,
    stats: Optional[ScanStats] = None,
) -> tuple:
    """Single-patch convenience wrapper (debugging); the CLI uses the two halves."""
    src = _collect_sources(repo_dir, base_commit, patch_text, tag,
                           git_retries=git_retries, stats=stats)
    lm = local_module_keys(src["before"]) | local_module_keys(src["after"]) if src else set()
    return _tokens_from_sources(
        src, lm, same_package=same_package, filter_ubiquitous=filter_ubiquitous,
        catalogue_mode=catalogue_mode, stats=None,
    )


# ---------------------------------------------------------------------------
# Catalogue key aliasing (CONTRACT 2 interop)
# ---------------------------------------------------------------------------

def alias_bare_names(catalogue: dict) -> dict:
    """
    Add a bare-name alias for every UNAMBIGUOUS "name#arity" catalogue key.

    CONTRACT 2 keys Java callables as "doThing#2" so an overload set cannot
    silently attach the wrong signature to a hint.  The frozen step 2
    (src/identifier_information.py:568 -> ``if n in catalogue``) looks names up
    by the bare name it got from the four sets, so with arity keys alone every
    Java method degrades to ``{name, entity_type: "variable"}``.

    This adds ``name -> record`` when exactly ONE arity is present for that name
    and the bare key is not already taken (a field or a type of the same name
    wins).  Genuine overloads stay unaliased — attaching the wrong overload is
    worse than no hint, which is the whole point of CONTRACT 2.

    Opt-in (``--catalogue-alias-bare``); the default output keeps exactly the
    keys the extractor produced.
    """
    by_bare: dict = {}
    for key in catalogue:
        bare = key.split("#", 1)[0]
        by_bare.setdefault(bare, []).append(key)

    aliased = dict(catalogue)
    for bare, keys in by_bare.items():
        if bare in catalogue:
            continue                       # bare key already used (field/type)
        if len(keys) == 1:
            aliased[bare] = catalogue[keys[0]]
    return aliased


# ---------------------------------------------------------------------------
# Instance-level extraction
# ---------------------------------------------------------------------------

def usage_from_instance(
    instance: dict,
    repos_dir: Path,
    *,
    same_package: bool = True,
    filter_ubiquitous: bool = False,
    catalogue_mode: str = "auto",
    doc_filter: bool = True,
    alias_bare: bool = False,
    git_retries: int = 0,
    stats: Optional[ScanStats] = None,
) -> IdentifierUsage:
    """Java analogue of ``IdentifierUsage.from_instance``."""
    repo_slug = instance["repo"].replace("/", "__")
    repo_short = instance["repo"].split("/")[-1]
    repo_dir = (
        repos_dir / repo_slug
        if (repos_dir / repo_slug).exists()
        else repos_dir / repo_short
    )
    if not repo_dir.exists():
        raise FileNotFoundError(
            f"Repo not found: {repo_dir}  (instance {instance.get('instance_id')})"
        )

    base_commit = instance["base_commit"]
    code_patch = instance.get("patch") or instance.get("feature_patch", "")
    test_patch = instance.get("test_patch", "")

    # Phase 1 — repo I/O only.  Both patches are collected before anything is
    # parsed, because local_modules must span BOTH of them: a test that uses an
    # impl class from its own package carries no import statement AND does not
    # touch the impl file, so a per-patch key set (what the Python path builds)
    # can never classify it.  See divergence 1 in src/lang/java_usage.py.
    code_src = _collect_sources(repo_dir, base_commit, code_patch, "impl",
                                git_retries=git_retries, stats=stats)
    test_src = _collect_sources(repo_dir, base_commit, test_patch, "test",
                                git_retries=git_retries, stats=stats)

    local_modules: set = set()
    for src in (code_src, test_src):
        if src:
            local_modules |= local_module_keys(src["before"])
            local_modules |= local_module_keys(src["after"])

    # Phase 2 — pure parsing over the cached sources.
    kw = dict(
        same_package=same_package,
        filter_ubiquitous=filter_ubiquitous,
        catalogue_mode=catalogue_mode,
        stats=stats,
    )
    code_w, code_r, code_cat = _tokens_from_sources(code_src, local_modules, **kw)
    test_w, test_r, test_cat = _tokens_from_sources(test_src, local_modules, **kw)

    catalogue = {**test_cat, **code_cat}   # code patch wins on conflict
    if alias_bare:
        catalogue = alias_bare_names(catalogue)

    if doc_filter:
        doc = get_doc_content(instance)
        code_w = {n for n in code_w if n not in doc}
        code_r = {n for n in code_r if n not in doc}
        test_w = {n for n in test_w if n not in doc}
        test_r = {n for n in test_r if n not in doc}

    try:
        _reset(repo_dir, base_commit, git_retries)
    except Exception:
        pass

    return IdentifierUsage(
        code_read=sorted(code_r),
        code_write=sorted(code_w),
        test_read=sorted(test_r),
        test_write=sorted(test_w),
        catalogue=catalogue,
    )


def usage_from_patches(
    code_patch: str,
    test_patch: str,
    *,
    same_package: bool = True,
    filter_ubiquitous: bool = False,
    catalogue_mode: str = "auto",
    alias_bare: bool = False,
) -> IdentifierUsage:
    """
    No-repo fallback: parse the raw patch text as if it were source.

    Mirrors ``IdentifierUsage.from_patches``.  Low fidelity for both languages
    (diff markers are not valid source) — the repo path is the real one.
    """
    cw, cr = extract_entities(code_patch, None,
                              same_package=same_package,
                              filter_ubiquitous=filter_ubiquitous)
    tw, tr = extract_entities(test_patch, None,
                              same_package=same_package,
                              filter_ubiquitous=filter_ubiquitous)
    catalogue: dict = {}
    rich = _rich_extractor(catalogue_mode)
    if rich is not None:
        try:
            catalogue = {**rich(test_patch, "<test_patch>"), **rich(code_patch, "<code_patch>")}
        except Exception:
            catalogue = {}
    if alias_bare:
        catalogue = alias_bare_names(catalogue)
    return IdentifierUsage(
        code_read=sorted(_names(cr)),
        code_write=sorted(_names(cw)),
        test_read=sorted(_names(tr)),
        test_write=sorted(_names(tw)),
        catalogue=catalogue,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Step 1 (JAVA): extract identifier read/write sets from a JSONL dataset.\n"
            "Stores all four sets (code_read, code_write, test_read, test_write)\n"
            "plus the rich catalogue, so step 2 can apply any operator without\n"
            "re-running extraction.  Same schema as src.identifier_usage."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", type=Path, required=True,
                        help="Input JSONL: instance_id, repo, base_commit, patch, test_patch.")
    parser.add_argument("--repos-dir", "-r", type=Path, default=None,
                        help="Directory of cloned Java repos (repos/java_repos).\n"
                             "Omit to parse the raw patch text (low fidelity).")
    parser.add_argument("--instance-id", type=str, default=None,
                        help="Only process this instance (for debugging).")
    parser.add_argument("--output", "-o", type=Path, required=True,
                        help="Output JSONL.")
    parser.add_argument("--skip-errors", action="store_true",
                        help="Skip instances that raise errors instead of stopping.")
    # --- Java-only knobs (documented in src/lang/java_usage.py) --------------
    parser.add_argument("--no-same-package", action="store_true",
                        help="Disable the implicit same-package import rule "
                             "(divergence 1); import-gated only.")
    parser.add_argument("--filter-ubiquitous", action="store_true",
                        help="Drop java.lang / java.util staples (String, List, ...) "
                             "from both sets.")
    parser.add_argument("--no-doc-filter", action="store_true",
                        help="Keep names that also appear in the problem statement "
                             "(the Python path always drops them).")
    parser.add_argument("--git-retries", type=int, default=0,
                        help="Retry git commands N times (2s apart) when another\n"
                             "process holds .git/index.lock on a shared clone.")
    parser.add_argument("--catalogue-alias-bare", action="store_true", default=True,
                        help="Also key unambiguous 'name#arity' catalogue entries by their\n"
                             "bare name, so the frozen step 2 (which looks up bare names)\n"
                             "can resolve Java methods.  Real overloads stay arity-keyed\n"
                             "only, so no wrong signature is ever attached.  ON by default:\n"
                             "without it step 2 emits ZERO function-typed identifiers.")
    parser.add_argument("--no-catalogue-alias-bare", dest="catalogue_alias_bare",
                        action="store_false",
                        help="Emit only the 'name#arity' keys the extractor produced.")
    parser.add_argument("--catalogue", choices=("auto", "off", "require"), default="auto",
                        help="auto: use src/lang/java_extractor.py if importable; "
                             "off: never; require: fail if unusable.")
    args = parser.parse_args()

    try:
        from tqdm import tqdm
    except Exception:  # tqdm is optional here
        def tqdm(it, **kw):
            return it
        tqdm.write = print  # type: ignore[attr-defined]

    instances: list = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))

    if args.instance_id:
        instances = [i for i in instances if i.get("instance_id") == args.instance_id]
        if not instances:
            parser.error(f"instance_id {args.instance_id!r} not found in {args.input}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stats = ScanStats()
    n_ok = n_err = 0
    n_empty_write = 0

    with open(args.output, "w", encoding="utf-8") as out_f:
        for instance in tqdm(instances, desc="Extracting (java)", unit="instance"):
            iid = instance.get("instance_id", "<unknown>")
            try:
                if args.repos_dir is not None:
                    usage = usage_from_instance(
                        instance, args.repos_dir,
                        same_package=not args.no_same_package,
                        filter_ubiquitous=args.filter_ubiquitous,
                        catalogue_mode=args.catalogue,
                        doc_filter=not args.no_doc_filter,
                        alias_bare=args.catalogue_alias_bare,
                        git_retries=args.git_retries,
                        stats=stats,
                    )
                else:
                    usage = usage_from_patches(
                        instance.get("patch", ""),
                        instance.get("test_patch", ""),
                        same_package=not args.no_same_package,
                        filter_ubiquitous=args.filter_ubiquitous,
                        catalogue_mode=args.catalogue,
                        alias_bare=args.catalogue_alias_bare,
                    )
                record = {"instance_id": iid, **usage.model_dump()}
                if not usage.code_write:
                    n_empty_write += 1
                n_ok += 1
            except Exception as exc:
                if not args.skip_errors:
                    raise
                tqdm.write(f"  SKIP {iid}: {exc}")
                record = {"instance_id": iid, "error": repr(exc)}
                n_err += 1

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote {n_ok} records to {args.output}" + (f" ({n_err} errors)" if n_err else ""))
    print(f"  java files parsed: {stats.files}  "
          f"parse errors: {stats.parse_errors}  "
          f"patch-apply failures: {stats.patch_apply_failures}  "
          f"instances with empty code_write: {n_empty_write}")


if __name__ == "__main__":
    _cli()
