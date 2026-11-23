#!/usr/bin/env python3
"""Generate the SKOS export of the two vocabulary files (openddil ADR-0056 §10).

ADR-0056 §10, an owed row: "A SKOS export of the dimension vocabulary and the lifecycle vocabulary.
Each term gets an identity under §1, and an equivalence across the two sides is `skos:exactMatch`
with an owner."

    policy/registry/lifecycle_status.yaml      -> policy/registry/lifecycle_status.skos.ttl
    policy/classification/dimensions.yaml      -> policy/classification/dimensions.skos.ttl

Each vocabulary is a `skos:ConceptScheme` and each term a `skos:Concept`. The IRI of each is its
identity from the file (`urn:uuid:<v7>`), so the export mints nothing and names no namespace of its
own. A hierarchical dimension's order (least restrictive first) is an `skos:OrderedCollection`.
`required` and `empty_means` are policy, not vocabulary, and are not exported. No equivalence row
exists yet, so there is no `skos:exactMatch`: the other side has no identities to match.

The files are validated first (validate_policy's own checks); a file with errors is not exported.
Output is deterministic and LF-only, so `--check` compares bytes.

Usage:  uv run python scripts/generate_vocabulary_skos.py [--check]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "policy"
sys.path.insert(0, str(_POLICY / "sync"))

import validate_policy as vp  # noqa: E402

LIFECYCLE = ("registry/lifecycle_status.yaml", "registry/lifecycle_status.skos.ttl")
DIMENSIONS = ("classification/dimensions.yaml", "classification/dimensions.skos.ttl")

_PREFIXES = ("@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
             "@prefix dcterms: <http://purl.org/dc/terms/> .\n")


def _lit(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _header(source: str) -> str:
    return (f"# GENERATED from policy/{source} by scripts/generate_vocabulary_skos.py. Do not edit.\n"
            "# Regenerate after changing the source; --check fails while this file is stale.\n"
            + _PREFIXES)


def _scheme(identity: str, label: str, source: str, owner: str) -> str:
    return (f"\n<{identity}> a skos:ConceptScheme ;\n"
            f"    skos:prefLabel {_lit(label)} ;\n"
            f"    dcterms:source {_lit('policy/' + source)} ;\n"
            f"    dcterms:rightsHolder {_lit(owner)} .\n")


def _concept(identity: str, term: str, scheme: str) -> str:
    return (f"\n<{identity}> a skos:Concept ;\n"
            f"    skos:inScheme <{scheme}> ;\n"
            f"    skos:topConceptOf <{scheme}> ;\n"
            f"    skos:notation {_lit(term)} ;\n"
            f"    skos:prefLabel {_lit(term)} .\n")


def lifecycle_ttl(raw: dict) -> str:
    src = LIFECYCLE[0]
    out = [_header(src), _scheme(raw["identity"], "lifecycle_status", src, raw["owner"])]
    out += [_concept(raw["identities"][s], s, raw["identity"]) for s in raw["statuses"]]
    return "".join(out)


def dimensions_ttl(raw: dict) -> str:
    src = DIMENSIONS[0]
    out = [_header(src)]
    rows = raw.get("dimensions") or []
    if not rows:
        out.append("\n# No dimension is declared.\n")
    for row in rows:
        scheme = row["identity"]
        out.append(_scheme(scheme, row["name"], src, row["owner"]))
        out += [_concept(row["identities"][v], v, scheme) for v in row["vocabulary"]]
        if row["type"] == "hierarchical":
            members = " ".join(f"<{row['identities'][v]}>" for v in row["vocabulary"])
            out.append(f"\n[] a skos:OrderedCollection ;\n"
                       f"    skos:prefLabel {_lit(row['name'] + ', least restrictive first')} ;\n"
                       f"    skos:memberList ( {members} ) .\n")
    return "".join(out)


def build() -> tuple[dict[str, str], list[str]]:
    """The rendered exports by output path (relative to policy/), and the validation errors."""
    users = (yaml.safe_load((_POLICY / "users.yaml").read_text(encoding="utf-8")) or {}).get("users") or []
    ls_raw = yaml.safe_load((_POLICY / LIFECYCLE[0]).read_text(encoding="utf-8"))
    cd_raw = yaml.safe_load((_POLICY / DIMENSIONS[0]).read_text(encoding="utf-8"))
    errors = vp.lifecycle_status_errors(ls_raw, users)
    errors += vp.classification_dimensions_errors(cd_raw, users)[0]
    errors += vp.term_identity_collisions({LIFECYCLE[0]: ls_raw, DIMENSIONS[0]: cd_raw})
    if errors:
        return {}, errors
    return {LIFECYCLE[1]: lifecycle_ttl(ls_raw), DIMENSIONS[1]: dimensions_ttl(cd_raw)}, []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if an export is missing or differs from its source")
    args = ap.parse_args()
    rendered, errors = build()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2
    stale = []
    for rel, text in rendered.items():
        path = _POLICY / rel
        want = text.encode("utf-8")
        if args.check:
            if not path.is_file() or path.read_bytes() != want:
                stale.append(rel)
        else:
            path.write_bytes(want)
            print(f"wrote policy/{rel}")
    if stale:
        for rel in stale:
            print(f"STALE: policy/{rel} (run scripts/generate_vocabulary_skos.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
