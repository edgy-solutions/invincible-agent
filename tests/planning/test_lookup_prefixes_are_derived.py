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


def test_every_declared_namespace_is_EXPANDABLE_by_the_lookup():
    """The seal that would have been red before `cost:` was added."""
    missing = {p: iri for p, iri in declared_namespaces().items()
               if p not in _IRI_PREFIXES_FOR_LOOKUP and p not in _EXEMPT}
    assert not missing, (
        "these namespaces are declared in setup/ontologies and cannot be expanded by the "
        f"presentation lookup: {missing}. Any binding row using one would register, report "
        "ACCEPTED, and never match a payload — a card falling through to KNOWLEDGE_DOCUMENT "
        "with 'No content available'. Add them to _IRI_PREFIXES_FOR_LOOKUP, or exempt them in "
        "_EXEMPT with the reason.")


def test_the_expansions_AGREE_with_the_ontologies():
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
