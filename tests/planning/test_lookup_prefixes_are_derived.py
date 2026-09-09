"""Every namespace this fleet declares must be expandable by the presentation lookup.

THE THIRD TIME A PREFIX REGISTRY HAS BITTEN AN ENGINE whose predecessor's fix was three lines
away. `fin:` was added after six finance binding rows registered, reported ACCEPTED, and never
matched a payload; the warning was written beside it; `cost:` was then omitted anyway and would
have swallowed all seven cost rows the same way.

WHY IT IS SO EASY TO MISS. Nothing fails. `canonical_iri_for_lookup` passes an unknown prefix
through verbatim BY DESIGN — it will not fabricate an expansion it does not know — so the row
registers, the selector accepts it, and the payload simply never matches. The card falls through
to KNOWLEDGE_DOCUMENT with "No content available", which is indistinguishable from having no
binding at all, from the engine being down, and from the verb never having been built.

SO THE POPULATION IS DERIVED, NOT REMEMBERED. The expected prefixes are read out of the
ontology files the fleet actually loads. A hand-kept list here would be the same defect one
level up: a registry someone maintains by remembering to.

Sibling laws this is an instance of: the reregister hook's hand-kept directory map (stopped at
one engine, hid every later one), the six-table verb check in engine-cost's boot (four were
compared, two drifted), and the phantom service URL.
"""
from __future__ import annotations

import re
from pathlib import Path

from agent_fleet.presentation_agent.capabilities import (
    _IRI_PREFIXES_FOR_LOOKUP,
    PRESENTATION_CAPABILITIES,
    canonical_iri_for_lookup,
)
from agent_fleet.utils.mesh_registration import _IRI_PREFIXES, _expand_mesh_iri

#: THERE ARE TWO TABLES AND THEY DO DIFFERENT JOBS, which is legitimate — but they must agree
#: on the SET of namespaces or a row goes onto the wire in a form the reader can fold and the
#: linker cannot match.
#:
#:   _IRI_PREFIXES              WRITE side. Decides the form the graph STORES.
#:   _IRI_PREFIXES_FOR_LOOKUP   READ side. Folds compact and full to one token.
#:
#: The read side folding both forms is exactly why a write-side omission passes every local
#: check: `cost:` was added to the reader when the cost bindings landed and not to the writer,
#: and the first version of THIS FILE checked only the reader — a population derived correctly
#: and then applied to one of its two consumers.
_TABLES = {
    "write (_IRI_PREFIXES)": _IRI_PREFIXES,
    "read (_IRI_PREFIXES_FOR_LOOKUP)": _IRI_PREFIXES_FOR_LOOKUP,
}

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGIES = ROOT / "setup" / "ontologies"

#: Only OUR namespaces. `owl:`, `rdfs:`, `prov:` and friends are never subject or object URIs in
#: a binding row, and requiring expansions for them would be a false population.
_OURS = re.compile(r"@prefix\s+([A-Za-z][\w-]*):\s*<(http://invincible-agent/[^>]*)>")

#: A namespace that is declared but deliberately NOT expandable here must say why. AN EXEMPTION
#: IS A CLAIM — writing it down is what stops an omission from looking like a decision.
_EXEMPT: dict[str, str] = {}


def declared_namespaces() -> dict[str, str]:
    """prefix -> expansion, read from every ontology the fleet loads."""
    found: dict[str, str] = {}
    for path in sorted(ONTOLOGIES.glob("*.ttl")):
        for prefix, iri in _OURS.findall(path.read_text(encoding="utf-8")):
            found[prefix + ":"] = iri
    return found


def test_the_scan_ACTUALLY_FINDS_the_namespaces():
    """Positive control. A regex that matched nothing would make every test below vacuous, and
    it would pass forever — which is exactly how a derived population turns back into a
    remembered one without anybody editing a list.
    """
    found = declared_namespaces()
    assert len(found) >= 4, f"only {len(found)} namespaces found: {sorted(found)}"
    for expected in ("mesh:", "fin:", "cost:", "idp:"):
        assert expected in found, f"{expected} is declared in the ontologies and was not found"


def test_every_declared_namespace_is_EXPANDABLE_by_BOTH_TABLES():
    """Both, not either. Checking only the reader is how `cost:` reached the wire compact.

    A namespace the READER knows and the WRITER does not is the worst of the three states: the
    row is stored in compact form, every local fold succeeds, and the linker's MATCH against
    full-IRI `:OntologyClass` nodes misses. The capability registers, reports ACCEPTED, and is
    never reachable — and the card silently drops to the BAML-designed fallback, measured at
    ~16.4s against ~0.12s for the hardened path.
    """
    declared = declared_namespaces()
    problems = []
    for label, table in _TABLES.items():
        for prefix, iri in declared.items():
            if prefix not in table and prefix not in _EXEMPT:
                problems.append(f"{prefix} missing from {label}")
    assert not problems, (
        "namespaces declared in setup/ontologies that a prefix table cannot expand:\n  "
        + "\n  ".join(problems))


def test_THE_TWO_TABLES_AGREE_on_their_namespace_set():
    """They diverge silently, and the divergence has now shipped three times.

    This does not require them to be one table — they decide different things — only that a
    namespace known to one is known to the other. The failure is asymmetric and the dangerous
    direction is reader-knows/writer-does-not, so the message names which side is short.
    """
    write, read = set(_IRI_PREFIXES), set(_IRI_PREFIXES_FOR_LOOKUP)
    assert write == read, (
        f"only the WRITER knows {sorted(write - read)}; only the READER knows "
        f"{sorted(read - write)}. A namespace the reader folds and the writer does not put on "
        "the wire is stored compact and never matched.")
    for prefix in write:
        assert _IRI_PREFIXES[prefix] == _IRI_PREFIXES_FOR_LOOKUP[prefix], (
            f"{prefix} expands to two different namespaces on the two sides")


def test_EVERY_BINDING_ROW_SURVIVES_THE_WRITE_PATH():
    """The property the wire-form test states, asserted here against the derived population too
    — because that test enumerates the rows and this file enumerates the NAMESPACES, and the
    defect was a namespace missing rather than a row being wrong."""
    for row in PRESENTATION_CAPABILITIES:
        for field in ("subject_uri", "object_uri"):
            value = row.get(field) or ""
            if not value:
                continue
            assert _expand_mesh_iri(value).startswith("http"), (
                f"{value} stays compact through the WRITE path - the linker will miss it")


def test_the_expansions_AGREE_with_the_ontologies():  # noqa: D401 - reader side
    """A prefix present but pointing somewhere else is worse than one that is absent: it
    expands to a URI no payload carries, and the miss looks like a data problem."""
    declared = declared_namespaces()
    for prefix, iri in declared.items():
        if prefix in _IRI_PREFIXES_FOR_LOOKUP:
            assert _IRI_PREFIXES_FOR_LOOKUP[prefix] == iri, (
                f"{prefix} expands to {_IRI_PREFIXES_FOR_LOOKUP[prefix]!r} in the lookup and "
                f"{iri!r} in the ontology")


def test_every_compact_uri_in_the_binding_table_EXPANDS():
    """Derived from the rows themselves, so a row using an unregistered prefix is caught even
    if that prefix is declared in no ontology file at all."""
    unexpanded = []
    for row in PRESENTATION_CAPABILITIES:
        for field in ("subject_uri", "object_uri"):
            value = row.get(field) or ""
            if not value or value.startswith("http"):
                continue
            if not canonical_iri_for_lookup(value).startswith("http"):
                unexpanded.append(f"{row['subject_uri']} {field}={value}")
    assert not unexpanded, (
        f"binding rows carrying a prefix the lookup cannot expand: {unexpanded}")


def test_an_exemption_is_a_CLAIM_not_an_empty_string():
    for prefix, reason in _EXEMPT.items():
        assert reason and len(reason) > 20, f"{prefix} is exempt without a reason"
