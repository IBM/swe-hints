"""
generate_nameonly_jsonl.py
==========================
Generate a "name-only" mini-SWE-agent input JSONL.

Each identifier is exposed only by its bare name:
  - file entity   → filename stem only (e.g. "http.py", not "src/websockets/http.py")
  - class         → class name
  - function      → function name
  - variable      → variable name

No path, signature, semantics, imports, location, or any other field is revealed.
This sits between the no-hints and all-hints baselines.

Usage
-----
    python leave_one_out/generate_nameonly_jsonl.py \\
        --hints    results/swerebench_v2/hints_communication_all_nonempty_300_enriched.jsonl \\
        --swebench data/swerebench_v2_python_all.jsonl \\
        --output   leave_one_out/output/swerebench_v2_300_name_only_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leave_one_out.taxonomy_game_v3 import (
    LOO_SUBGRAPH_ROOTS,
    available_rows,
    subtree_rows,
)

_swe_pro_path = os.environ.get("SWE_BENCH_PRO_PATH", "")
if _swe_pro_path:
    sys.path.insert(0, _swe_pro_path)
from helper_code.image_uri import get_dockerhub_image_uri


# ---------------------------------------------------------------------------
# Hint rendering — names only
# ---------------------------------------------------------------------------

def render_name_only_hint(instance: dict) -> str:
    """
    Return a hints string that exposes only bare names:
      - Files   : filename stem (e.g. "http.py"), one per line under "## Files"
      - Entities: bare name (e.g. "basic_auth_header"), grouped by entity type
    """
    identifiers = instance.get("identifiers", [])
    if not identifiers:
        return ""

    file_names:     list[str] = []
    class_names:    list[str] = []
    func_names:     list[str] = []
    var_names:      list[str] = []

    seen: set[str] = set()

    for ident in identifiers:
        etype = ident.get("entity_type", "")
        name  = ident.get("name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        if etype == "file" or ("/" in name or name.endswith(".py")):
            # Expose only the filename, not the full path
            file_names.append(Path(name).name)
        elif etype == "class":
            class_names.append(name)
        elif etype == "function":
            func_names.append(name)
        else:
            var_names.append(name)

    all_names = sorted(
        set(file_names) | set(class_names) | set(func_names) | set(var_names)
    )
    lines = ["## Identifier Hints:"]
    lines.extend(f"- {n}" for n in all_names)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_hints(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_swebench_index(paths: list[Path]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                iid = rec.get("instance_id", "")
                if iid:
                    index[iid] = rec
        print(f"  {path.name}: {len(index)} records indexed so far")
    return index


def resolve_image(swe_rec: dict, iid: str, dockerhub: str) -> str:
    if "image_name" in swe_rec:
        return swe_rec["image_name"]
    return get_dockerhub_image_uri(iid, dockerhub, swe_rec.get("repo", ""))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def generate(
    hints_path: Path,
    swebench_paths: list[Path],
    output_path: Path,
    dockerhub: str,
) -> None:
    print(f"Loading hints       : {hints_path}")
    hint_records = load_hints(hints_path)
    print(f"  {len(hint_records)} hint records loaded.")

    print(f"Loading SWE-bench   : {[str(p) for p in swebench_paths]}")
    swe_index = load_swebench_index(swebench_paths)
    print(f"  {len(swe_index)} records indexed total.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = n_missing = n_empty = 0

    with open(output_path, "w", encoding="utf-8") as out:
        for hint_rec in hint_records:
            iid     = hint_rec["instance_id"]
            swe_rec = swe_index.get(iid)
            if swe_rec is None:
                print(f"  WARNING: {iid} not in SWE-bench index — skipping.",
                      file=sys.stderr)
                n_missing += 1
                continue

            coalition    = available_rows(hint_rec)
            active_roots = [r for r in LOO_SUBGRAPH_ROOTS if coalition & subtree_rows(r)]
            image_name   = resolve_image(swe_rec, iid, dockerhub)
            hints        = render_name_only_hint(hint_rec)

            if not hints:
                n_empty += 1

            out.write(json.dumps({
                "instance_id":       iid,
                "image_name":        image_name,
                "problem_statement": swe_rec["problem_statement"],
                "base_commit":       swe_rec["base_commit"],
                "repo":              swe_rec.get("repo", ""),
                "hints":             hints,
                "_coalition_id":     "name_only",
                "_active_rows":      sorted(coalition),
                "_active_roots":     active_roots,
            }, ensure_ascii=False) + "\n")

            n_written += 1

    print(f"\nWrote {n_written} instances → {output_path}")
    if n_empty:
        print(f"  Note: {n_empty} instance(s) had no identifiers → empty hints string.")
    if n_missing:
        print(f"  WARNING: {n_missing} instance(s) skipped (not in SWE-bench index).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate name-only hints JSONL for mini-SWE-agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--hints",    "-i", type=Path, required=True,
                        help="Enriched hints JSONL.")
    parser.add_argument("--swebench", "-s", type=Path, nargs="+", required=True,
                        help="One or more SWE-bench JSONL files.")
    parser.add_argument("--output",   "-o", type=Path, required=True,
                        help="Output JSONL path.")
    parser.add_argument("--dockerhub", "-d", type=str, default="jefzda",
                        help="DockerHub username for swe_pro image URI fallback (default: jefzda).")
    args = parser.parse_args()

    generate(
        hints_path=args.hints,
        swebench_paths=args.swebench,
        output_path=args.output,
        dockerhub=args.dockerhub,
    )


if __name__ == "__main__":
    main()
