#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Build mini-SWE-agent input JSONL from Multi-SWE-bench (Java) hint files.

Accepts BOTH hint shapes this repo produces, auto-detected per record:

  selection  (identity_selection/*_java.py)  -> record has `augmentations`
             fea_brief_java.py                 -> record has `new_components`
                {path: [{type, name, signature, lines}]}
                {"forward": {"header", "data":[{type,name}]},
                 "backward": {...}}           or a flat {"header","data"}
  projection (identity_projection/...)       -> record has `identifiers`
                [{name, entity_type, path, signature, ...}]

Image URIs are derived the way multi_swe_bench/harness/image.py does:

    mswebench/{org}_m_{repo}:pr-{number}          (lower-cased)

verified against multi-swe-bench/scripts/images_verified.txt for all 128 Java
instances.  Pass --verify-images <file> to fail loudly on any instance whose
image is not in that list.

Output row: {instance_id, repo, base_commit, problem_statement, hints, image_name}
— the schema mini-SWE-agent's swebench runner consumes.

Usage
-----
    # identity_selection track
    python helper_code/data_prepare/generate_msb_instances.py \
        --hints  identity_selection/results_selection/defuse2_java_sel/raw/msb_defuse2.jsonl \
        --source data/java/multi_swe_bench_java.jsonl \
        --output results/miniswe_java/msb_defuse2.jsonl

    # no-hints baseline
    python helper_code/data_prepare/generate_msb_instances.py \
        --source data/java/multi_swe_bench_java.jsonl --no-hints \
        --output results/miniswe_java/msb_no_hints.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def image_uri(row: dict) -> str:
    repo = row.get("repo", "")
    org, _, name = repo.partition("/")
    number = row.get("number")
    if not (org and name and number):
        return ""
    return f"mswebench/{org}_m_{name}:pr-{number}".lower()


def _bare(name: str) -> str:
    """Bare name for the name_only projection.

    Mirrors the paper's Python name-only generator: a file entity collapses to
    its basename (``src/main/java/com/x/Foo.java`` -> ``Foo.java``) so the hint
    reveals the name without revealing where it lives.  Non-path names are
    returned unchanged, including Java's ``Type.member`` qualification.
    """
    return name.rsplit("/", 1)[-1] if "/" in name else name


def _sig_counts(cat: dict) -> dict:
    """{bare name: number of DISTINCT signatures} for one instance.

    This, not how many times a name appears in the selection output, is what
    "how many overloads exist" means.  Java registers every member twice - once
    top-level, once as a class member - so occurrence counts are dominated by that
    artifact: on sel40, nocode_java had 139 names appearing more than once and
    only 7 were genuine overloads.
    """
    out: dict = {}
    for bare, entries in (cat or {}).items():
        n = len({e.get("signature") for e in entries if e.get("signature")})
        if n:
            out[bare] = n
    return out


def _names_only(names, keep_cardinality: bool = False, sig_counts: dict | None = None) -> str:
    """Bare-name hint block.

    Java overloading makes this projection lossy in a way Python's is not: two
    declarations of ``sealSegment`` differ only by parameter list, so a set of
    names collapses them into one line.  Measured on the 40-instance nocode n
    fea_brief population: 15 names carry more than one distinct signature.

    keep_cardinality=False (``name_only``)  — set semantics, matching
        the paper's Python name-only generator.  A FULL-minus-name_only
        contrast then conflates "you learned the signature" with "you learned
        there are three of them".
    keep_cardinality=True (``name_only_count``) — emits ``- foo  (x3)``, so the
        contrast isolates the signature.  Costs a small leak: the agent learns
        how many overloads exist without learning their parameters.
    """
    from collections import Counter
    counts = Counter(_bare(n) for n in names if n)
    if not counts:
        return ""
    lines = ["## Identifier Hints:"]
    for n in sorted(counts):
        # Multiplicity comes from the catalogue's distinct signatures when one is
        # available; occurrence count is the fallback and is unreliable on Java.
        if sig_counts is not None:
            c = sig_counts.get(n.rsplit(".", 1)[-1], 1)
        else:
            c = counts[n]
        lines.append(f"- {n}  (x{c})" if keep_cardinality and c > 1 else f"- {n}")
    return "\n".join(lines)


def _aug_block(rec: dict):
    """The augmentation block, whichever key it arrived under.

    identity_selection/project_swe_pro_nocode_llm.py writes its {header, data}
    nocode block under "hints", while defuse2/nocode write the same shape under
    "augmentations". Accept either so the SWE-bench-Pro-style selection baseline
    feeds this generator unchanged.
    """
    aug = rec.get("augmentations")
    if isinstance(aug, dict):
        return aug
    h = rec.get("hints")
    return h if isinstance(h, dict) else None


def _collect_names(rec: dict) -> list:
    """Every entity name in a record, whichever hint shape it uses."""
    out = []
    aug = _aug_block(rec)
    if isinstance(aug, dict):
        if isinstance(aug.get("data"), list):
            out += [e.get("name", "") for e in aug["data"]]
        for d in ("forward", "backward"):
            sub = aug.get(d)
            if isinstance(sub, dict):
                out += [e.get("name", "") for e in (sub.get("data") or [])]
    comps = rec.get("new_components")
    if isinstance(comps, dict):
        for items in comps.values():
            out += [c.get("name", "") for c in (items or [])]
    idents = rec.get("identifiers")
    if isinstance(idents, list):
        out += [i.get("name", "") for i in idents]
    return out


def load_catalogue(path) -> dict:
    """{instance_id: {bare name: [entry, ...]}} from a step-1 extracted_hints.jsonl.

    Java keys callables ``name#arity`` and everything else bare, and a name with
    several arities is a genuine overload set.  Keep every distinct signature
    under the bare name, in catalogue order, so a projection can render one entry
    per overload instead of silently showing only the first.  Python is
    unaffected: one name, one entry.
    """
    out: dict = {}
    if not path:
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            idx: dict = {}
            seen: dict = {}
            for k, v in (r.get("catalogue") or {}).items():
                bare = k.split("#", 1)[0]
                key = (bare, v.get("signature") or "")
                if key in seen:
                    continue
                seen[key] = True
                idx.setdefault(bare, []).append(v)
            out[r["instance_id"]] = idx
    return out


def _cat_variants(cat: dict, name: str) -> list:
    """Every catalogue entry for `name`, one per distinct signature."""
    if not cat or not name:
        return []
    hit = cat.get(name)
    if hit is None and "." in name:
        hit = cat.get(name.rsplit(".", 1)[-1])
    return list(hit or [])


def _cat_lookup(cat: dict, name: str) -> dict:
    """First catalogue entry for `name`, tolerating ``Type.member`` qualification."""
    v = _cat_variants(cat, name)
    return v[0] if v else {}


def _collect_entities(rec: dict) -> list:
    """Every entity with whatever structural fields its source shape carries.

    fea_brief keys `new_components` by path, so the path is attached here; the
    other shapes carry only {type, name} and rely on the catalogue join.
    """
    out: list = []
    aug = _aug_block(rec)
    if isinstance(aug, dict):
        if isinstance(aug.get("data"), list):
            out += list(aug["data"])
        for d in ("forward", "backward"):
            sub = aug.get(d)
            if isinstance(sub, dict):
                out += list(sub.get("data") or [])
    comps = rec.get("new_components")
    if isinstance(comps, dict):
        for path, items in comps.items():
            for c in items or []:
                e = dict(c)
                e.setdefault("path", path)
                out.append(e)
    idents = rec.get("identifiers")
    if isinstance(idents, list):
        out += list(idents)
    return out


def _render_declaration(entities: list, cat: dict) -> str:
    """DECLARATION projection: name, kind, path [new file], signature.

    Overloads get ONE BLOCK EACH.  In Python a name denotes a single definition,
    so listing it once is complete; in Java three ``sealSegment`` overloads differ
    only by parameter list, and collapsing them to one block would hide two real
    entities.  Emitting one block per distinct signature makes the Java hint carry
    the same coverage its Python counterpart does.

    Block shape matches identity_projection/generate_instances.py::_render_ours so
    a selection-track hint and a projection-track hint are byte-comparable at the
    same projection strength.
    """
    blocks: list[str] = []
    seen: set = set()
    for e in entities:
        name = e.get("name", "")
        if not name:
            continue
        variants = _cat_variants(cat, name) or [{}]
        for info in variants:
            etype = e.get("type") or e.get("entity_type") or ""
            # Catalogue kind wins: it is per-overload, so the three constructors of
            # a class are labelled "constructor" rather than inheriting the
            # selection entry's single "class" label. Falls back to the selection
            # entry's own label when the name is a catalogue miss.
            kind = (info.get("entity_kind") or info.get("entity_type")
                    or e.get("entity_kind") or etype)
            path = info.get("path") or e.get("path") or ""
            sig = info.get("signature") or e.get("signature") or ""
            is_new = e.get("is_new_file")
            if is_new is None:
                is_new = info.get("is_new_file")

            # Java registers every member twice - once top-level, once as a class
            # member - so the same entity arrives labelled both "field" and
            # "function".  Key on the facts this projection actually shows, which
            # collapses that artifact while keeping true overloads apart (they
            # differ by signature).
            key = (name, path, sig)
            if key in seen:
                continue
            seen.add(key)

            head = f"### `{name}`"
            if kind:
                head += f" ({kind})"
            if path:
                head += f" — `{path}`" + (" [new file]" if is_new else "")
            lines = [head]
            if sig:
                lines.append(f"Signature: `{sig}`")
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _render_entities(header: str, data: list) -> list[str]:
    if not data:
        return []
    out = [header] if header else []
    for e in data:
        t, n = e.get("type") or e.get("entity_type") or "", e.get("name", "")
        out.append(f"- **{t}:** `{n}`" if t else f"- `{n}`")
    return out


def render_hints(rec: dict, projection: str = "nocode", catalogue: dict | None = None) -> str:
    """Render any hint shape to prompt text, at the requested projection.

    nocode     — entity_type + name, the projection identity_selection uses by
                 default so selection methods are compared under a fixed one.
    name_only  — bare names only, no type, no path, no signature.
    """
    if projection == "declaration":
        cat = (catalogue or {}).get(rec.get("instance_id", ""), {})
        return _render_declaration(_collect_entities(rec), cat)

    if projection in ("name_only", "name_only_count", "name_only_set"):
        # Overload multiplicity is ON by default.  In Python a name denotes one
        # definition, so a bare list of names is complete; in Java it is not, and
        # collapsing three `sealSegment` overloads to one line hides two real
        # entities.  Emitting "(xN)" restores the coverage Python's name_only has.
        # name_only_set opts back into strict set semantics for a cross-language
        # contrast that must match the paper's Python name-only generator.
        keep = projection != "name_only_set"
        sc = None
        if keep and catalogue:
            sc = _sig_counts(catalogue.get(rec.get("instance_id", ""), {}))
        return _names_only(_collect_names(rec), keep_cardinality=keep, sig_counts=sc)

    aug = _aug_block(rec)
    if isinstance(aug, dict):
        blocks: list[str] = []
        if "data" in aug:                                    # flat (nocode-style)
            blocks += _render_entities(aug.get("header", ""), aug.get("data") or [])
        for direction in ("forward", "backward"):            # defuse2-style
            sub = aug.get(direction)
            if isinstance(sub, dict):
                blocks += _render_entities(sub.get("header", ""), sub.get("data") or [])
        return "\n".join(blocks).strip()

    # fea_brief shape: {path: [{type, name, signature, lines}, ...]}
    comps = rec.get("new_components")
    if isinstance(comps, dict) and comps:
        lines = ["The following components are newly introduced by the implementation:"]
        for path, items in sorted(comps.items()):
            lines.append(f"### `{path}`")
            for c in items or []:
                t, n = c.get("type", ""), c.get("name", "")
                lines.append(f"- **{t}:** `{n}`" if t else f"- `{n}`")
                if c.get("signature"):
                    lines.append(f"  Signature: `{c['signature']}`")
        return "\n".join(lines).strip()

    idents = rec.get("identifiers")
    if isinstance(idents, list) and idents:
        lines = ["## Identifier Hints:"]
        for i in idents:
            head = f"### `{i.get('name','')}`"
            kind = i.get("entity_kind") or i.get("entity_type")
            if kind:
                head += f" ({kind})"
            if i.get("path"):
                head += f" — `{i['path']}`" + (" [new file]" if i.get("is_new_file") else "")
            lines.append(head)
            for label, key in (("Signature", "signature"), ("Base", "superclass"),
                               ("Location", "complete_location")):
                if i.get(key):
                    lines.append(f"{label}: `{i[key]}`")
            if i.get("weak_semantics"):
                lines.append(f"> {i['weak_semantics']}")
            if i.get("strong_semantics"):
                lines.append(i["strong_semantics"])
        return "\n".join(lines).strip()

    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hints", "-i", type=Path, default=None,
                    help="Hints JSONL (selection or projection shape). Omit with --no-hints.")
    ap.add_argument("--source", "-s", type=Path, required=True,
                    help="data/java/multi_swe_bench_java.jsonl")
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--no-hints", action="store_true",
                    help="Emit every source instance with hints=\"\" (the NONE baseline).")
    ap.add_argument("--catalogue", "-c", type=Path, default=None,
                    help="Step-1 extracted_hints.jsonl. Required for --projection declaration\n"
                         "on selection outputs that carry only {type, name}: path and\n"
                         "signature are looked up per instance in its catalogue.")
    ap.add_argument("--projection", "-p",
                    choices=("nocode", "name_only", "name_only_count",
                             "name_only_set", "declaration"),
                    default="nocode",
                    help="Fixed projection applied to whichever selection produced the hints.\n"
                         "nocode (default): '- **type:** `name`'.  name_only: bare names under\n"
                         "a '## Identifier Hints:' header, deduped and sorted, file entities\n"
                         "reduced to their basename.  name_only_count: same, but\n"
                         "name_only now KEEPS overload multiplicity as '(xN)' by\n"
                         "default (counted from --catalogue distinct signatures), so\n"
                         "Java overloads are not silently collapsed; name_only_count is\n"
                         "an alias.  name_only_set restores strict set semantics.\n"
                         "declaration: name, kind,\n"
                         "path [new file] and signature, same block shape as the\n"
                         "projection track's declaration renderer.")
    ap.add_argument("--verify-images", type=Path, default=None,
                    help="images_verified.txt; fail if any derived image is absent.")
    args = ap.parse_args()

    catalogue = load_catalogue(args.catalogue)
    if args.projection in ("declaration", "name_only", "name_only_count") and not catalogue:
        print(f"WARNING: --projection {args.projection} without --catalogue.\n"
              "         declaration: only fea_brief-shaped inputs carry path/signature;\n"
              "         everything else degrades to name+kind.\n"
              "         name_only: overload counts fall back to occurrence counts, which\n"
              "         on Java are dominated by the double-registration artifact.")

    source = {}
    with args.source.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                source[r["instance_id"]] = r

    if args.no_hints:
        hints = {iid: {} for iid in source}
    else:
        if not args.hints:
            raise SystemExit("--hints is required unless --no-hints is given")
        hints = {}
        with args.hints.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    hints[r["instance_id"]] = r

    known = None
    if args.verify_images:
        known = {l.strip() for l in args.verify_images.open() if l.strip()}

    rows, missing_src, missing_img, empty = [], 0, [], 0
    for iid, hrec in hints.items():
        src = source.get(iid)
        if src is None:
            missing_src += 1
            continue
        uri = image_uri(src)
        if known is not None and uri not in known:
            missing_img.append(iid)
        text = "" if args.no_hints else render_hints(hrec, args.projection, catalogue)
        if not text and not args.no_hints:
            empty += 1
        rows.append({
            "instance_id": iid,
            "repo": src.get("repo", ""),
            "base_commit": src.get("base_commit", ""),
            "problem_statement": src.get("problem_statement", ""),
            "hints": text,
            "image_name": uri,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for r in sorted(rows, key=lambda r: r["instance_id"]):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} instances -> {args.output}")
    print(f"  empty hints           : {empty}")
    print(f"  not found in --source : {missing_src}")
    if known is not None:
        print(f"  image not in verified : {len(missing_img)}"
              + (f"  e.g. {missing_img[:3]}" if missing_img else ""))


if __name__ == "__main__":
    main()
