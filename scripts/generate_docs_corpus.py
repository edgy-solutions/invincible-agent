#!/usr/bin/env python
"""Generate `setup/ontologies/docs_corpus.ttl` from the runbook corpus's own frontmatter.

WHY A GENERATED SEED TTL RATHER THAN AN INGEST ASSET, AND THE FORK IS NAMED BECAUSE IT IS REAL.
ADR-0037's resolved open question puts the markdown-to-triples converter in `doc-tools`
(`ontology_assets.py`), calling it *"a cross-repo build dependency this ADR did not name."* That
is right for the half it was written about and wrong for this half, and the split follows
ADR-0036's seed/overlay line rather than a preference:

    THE PLATFORM CORPUS IS SEED.    Its markdown lives in THIS repo. Every other seed vocabulary
                                    here is a file under setup/ontologies/ named by a manifest
                                    row. A doc-tools asset would have to reach INTO this repo to
                                    read pages that ship with it.
    THE WORK-SIDE CORPUS IS OVERLAY. Its markdown arrives from a customer directory, at runtime,
                                    which is exactly what an ingest asset is for. That stays
                                    doc-tools' (`doc-tools-7f`), unchanged.

**Each layer's producer sits where its source lives.** The output of both is the same triples
against the same declared vocabulary, so the split costs no compatibility — an overlay page and a
seed page are indistinguishable to a reader, which is the property ADR-0036 exists to give.

GENERATED, NEVER HAND-EDITED, AND CHECKED IN. Same discipline as
`scripts/generate_canvas_schema.py`: the artifact is committed so a reviewer can read what will
prime, and `--check` fails if the committed file has drifted from the frontmatter. A generated
file that is not checked in is a build step nobody can review; one that is checked in and
unchecked is a copy that silently stops matching its source.

    python scripts/generate_docs_corpus.py            # write it
    python scripts/generate_docs_corpus.py --check    # fail if it has drifted
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNBOOKS = ROOT / "docs" / "runbooks"
OUT = ROOT / "setup" / "ontologies" / "docs_corpus.ttl"

MESH = "http://invincible-agent/mesh#"
DOCS = "http://invincible-agent/docs#"

#: Kept in step with `tests/test_doc_page_frontmatter.py`, which is the seal over the SAME two
#: exclusions and states why each is not a page.
NOT_PAGES = {"README.md", "_TEMPLATE.md"}
NO_TARGETS = "none"

HEADER = """# GENERATED FILE — DO NOT EDIT.
#
# Produced by `scripts/generate_docs_corpus.py` from the frontmatter of `docs/runbooks/*.md`.
# Committed so a reviewer can read what will prime; `--check` fails if it has drifted from the
# pages it was derived from.
#
# THIS IS THE SEED HALF OF THE DOC CORPUS. The work-side half arrives as an ADR-0036 overlay
# through doc-tools' ingest, produces the same triples against the same vocabulary, and is
# deliberately indistinguishable to a reader.
#
# The vocabulary itself (mesh:DocPage, mesh:explains, mesh:audience_hint, mesh:doc_kind) is
# declared in mesh_system.ttl and primes with the MESH domain — a page here asserting a type that
# was never declared is the fail-by-passing case ADR-0037 §1 exists to refuse.

@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""


def _frontmatter(path: pathlib.Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return yaml.safe_load(text[3:end]) or {}


def _title(path: pathlib.Path) -> str:
    """The page's own H1, read from the BODY. Not the filename: the heading is what a human wrote.

    THE FIRST VERSION READ THE FRONTMATTER'S COMMENTS AS HEADINGS, and it did not look wrong — it
    produced a plausible sentence for every page, because a YAML comment and a markdown H1 begin
    with the same two characters. Three pages came out labelled with the middle of an explanatory
    comment. Skipping past the frontmatter terminator is the fix; RUNNING the generator and
    reading its output is what caught it, which a schema check never would have.
    """
    text = path.read_text(encoding="utf-8")
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ")


def _escape(text: str) -> str:
    """Turtle string escaping. The characters are NAMED rather than written, because this file is
    a template of a template and an escape written literally collapses one layer early."""
    out = text.replace(chr(92), chr(92) * 2)          # backslash
    out = out.replace(chr(34), chr(92) + chr(34))     # double quote
    out = out.replace(chr(10), chr(92) + "n")         # newline
    return out


def pages() -> list[pathlib.Path]:
    return sorted(p for p in RUNBOOKS.glob("*.md") if p.name not in NOT_PAGES)


def page_locator(path: pathlib.Path) -> tuple[str, str]:
    """-> (body_sha, bucket-relative object key). THE ONE PLACE EITHER IS COMPUTED.

    `setup/prime_databases.py` imports this rather than recomputing, and that is deliberate: the
    key is content-addressed, so a second implementation that hashed differently would upload to a
    key nothing points at and the failure would be a page that resolves to nothing at answer time
    — silent, and only at the moment a reader asks. One function, imported by both, and a seal
    asserting the committed TTL agrees with what this returns.

    The key is bucket-RELATIVE, matching `CANONICAL_TTL_MANIFEST`'s `s3_key` convention: the bucket
    is resolved from `ONTOLOGY_BUCKET` at read time so a locator does not hard-code one
    deployment's bucket.
    """
    body_sha = hashlib.sha256(page_bytes(path)).hexdigest()
    return body_sha, f"docs/pages/{body_sha}/{path.name}"


def page_bytes(path: Path) -> bytes:
    """The page's bytes with LINE ENDINGS NORMALISED — the form git stores and Linux reads.

    ⛔ WITHOUT THIS THE CORPUS CANNOT BE GENERATED CORRECTLY ON WINDOWS, and the failure is
    silent until a prime runs. Measured 2026-09-14 on `rolling-a-service.md`:

        working tree (CRLF)   899eb4469f5b   <- what the generator wrote into the TTL
        git blob / image (LF) 1b6db61a4e32   <- what every consumer computes

    `git` checks these out with CRLF on Windows and stores LF, so hashing the working-tree bytes
    makes the sha a property of WHOSE MACHINE RAN THE GENERATOR. A Windows regeneration writes a
    sha no Linux consumer can ever reproduce; the prime then refuses the whole upload, and it
    refuses CORRECTLY — the key would name a body nothing could resolve.

    It cost a fleet roll: the drift had been red for days, I regenerated on Windows, committed,
    rolled, and the prime refused again with a DIFFERENT wrong sha. The second failure looked
    identical to the first, which is what makes this worth a paragraph rather than a line.

    THE UPLOAD USES THIS TOO (`prime_databases.upload_doc_pages`), so the stored object and its
    declared sha agree on every platform rather than only on the one that happens to run CI.
    """
    # The characters are NAMED, never written: an escape for a line ending, inside a file
    # about line endings, is exactly where an escape collapses into the byte it denotes.
    CRLF, LF = bytes([13, 10]), bytes([10])
    return path.read_bytes().replace(CRLF, LF)


def _prefix_bindings(used: set[str]) -> str:
    """`@prefix` lines for exactly the prefixes the corpus uses, sourced from the WRITE-SIDE table.

    THE TABLE IS THE AUTHORITY AND IS NOT RESTATED. `agent_fleet/utils/mesh_registration.py`
    decides the stored form of every IRI on the wire. A prefix bound here but absent there would
    produce a TTL that parses cleanly and rows that match nothing — the defect that has already
    shipped three times. Deriving both from one table makes them agree by construction rather
    than by review.
    """
    # THE REPO ROOT IS NOT ON THE PATH FOR A SCRIPT RUN FROM IT. `agent_fleet` is a top-level
    # directory rather than an installed package, so `python scripts/…` cannot see it. Imported
    # HERE rather than at module scope, and by path rather than through `iagent`, for the reason
    # `generate_canvas_schema.py` records: `src/iagent/__init__.py` opens Postgres connections
    # before reaching a class, and a generator must not need infrastructure to produce a file.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agent_fleet.utils.mesh_registration import _IRI_PREFIXES

    unknown = sorted(x for x in used if x + ":" not in _IRI_PREFIXES)
    if unknown:
        raise SystemExit(
            "REFUSED: the corpus uses prefix(es) " + ", ".join(unknown) + " that the write-side "
            "table does not register. An unregistered prefix is passed through VERBATIM, so the "
            "row would be stored compact and match nothing. Register it in "
            "agent_fleet/utils/mesh_registration.py first — declaration before registration.")
    return "".join(
        "@prefix " + x + ": <" + _IRI_PREFIXES[x + ":"] + "> .\n" for x in sorted(used))


def render() -> str:
    blocks = []
    used_prefixes = {"docs", "mesh"}
    for p in pages():
        fm = _frontmatter(p)
        if fm is None:
            raise SystemExit(
                f"REFUSED: {p.name} has no frontmatter, so it would become no row at all — and a "
                f"missing row is indistinguishable from a page nobody wrote. Add the doc model "
                f"or add it to NOT_PAGES with a reason.")
        missing = [k for k in ("iri", "explains", "doc_kind", "audience_hint") if k not in fm]
        if missing:
            raise SystemExit(f"REFUSED: {p.name} is missing {', '.join(missing)}")

        iri = str(fm["iri"])
        if not iri.startswith("docs:"):
            raise SystemExit(
                f"REFUSED: {p.name} declares {iri!r}, which is not in the docs: namespace. An "
                f"unregistered prefix is passed through verbatim and the row matches nothing.")

        body_sha, key = page_locator(p)
        lines = [f"{iri} a mesh:DocPage ;",
                 f'  rdfs:label "{_escape(_title(p))}" ;',
                 f'  mesh:doc_kind "{_escape(str(fm["doc_kind"]))}" ;',
                 f'  mesh:audience_hint "{_escape(str(fm["audience_hint"]))}" ;',
                 f'  mesh:source "{key}" ;',
                 f'  mesh:body_sha "{body_sha}"']

        targets = fm["explains"]
        if targets == NO_TARGETS or not targets:
            # `explains: none` is ADMITTED AND MARKED — the row exists and says it explains
            # nothing yet, which is a different fact from having no row.
            lines[-1] += " ."
            lines.append(f"# {p.name}: explains none — an honest row, not an omission.")
        else:
            lines[-1] += " ;"
            for target in targets:
                if ":" in str(target):
                    used_prefixes.add(str(target).split(":", 1)[0])
            joined = " ,\n    ".join(str(t) for t in targets)
            lines.append(f"  mesh:explains {joined} .")
        blocks.append("\n".join(lines))
    return HEADER + _prefix_bindings(used_prefixes) + "\n" + "\n\n".join(blocks) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed TTL has drifted from the frontmatter")
    args = ap.parse_args()

    body = render()

    # A generator that finds nothing and exits 0 is indistinguishable from one that succeeded.
    if len(pages()) < 5:
        print(f"REFUSED: only {len(pages())} pages found — the corpus glob has stopped seeing "
              f"the runbooks", file=sys.stderr)
        return 2

    if args.check:
        if not OUT.is_file():
            print(f"MISSING: {OUT.relative_to(ROOT)} has never been generated", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != body:
            print(f"DRIFTED: {OUT.relative_to(ROOT)} does not match the frontmatter it is "
                  f"derived from. Re-run without --check.", file=sys.stderr)
            return 1
        print(f"OK: {OUT.relative_to(ROOT)} matches {len(pages())} pages")
        return 0

    OUT.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} from {len(pages())} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
