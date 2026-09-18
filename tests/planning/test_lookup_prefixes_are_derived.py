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

import ast
import re
from pathlib import Path

from agent_fleet.presentation_agent.capabilities import (
    _IRI_PREFIXES_FOR_LOOKUP,
    PRESENTATION_CAPABILITIES,
    canonical_iri_for_lookup,
)
from agent_fleet.utils.mesh_registration import _IRI_PREFIXES, _expand_mesh_iri

#: THE TABLES DO DIFFERENT JOBS, which is legitimate — but they must agree on the SET of
#: namespaces, or a row goes onto the wire in a form one consumer can fold and another cannot.
#:
#:   _IRI_PREFIXES            (utils/mesh_registration)    WRITE. Decides the form the graph STORES.
#:   _IRI_PREFIXES_FOR_LOOKUP (presentation/capabilities)  READ.  Folds compact and full to one token.
#:   _IRI_PREFIXES            (mesh_registrar/v2_substrate) DEDUP. Folds both sides of the sweep's
#:                                                          comparison.
#:
#: THE SET IS DERIVED, because the hand-written one here said TWO and there were THREE. The third
#: (v2_substrate) held only `mesh:`/`idp:` while `fin:`, `cost:`, `safety:` and `docs:` were each
#: added to the other two — four misses, under a comment in that very file instructing the
#: opposite, because nothing read it. A file whose entire thesis is that populations must be
#: derived kept its own population of consumers in a literal.
#:
#: The read side folding both forms is why a write-side omission passes every local check.
ROOT = Path(__file__).resolve().parents[2]
ONTOLOGIES = ROOT / "setup" / "ontologies"


def _derive_prefix_tables() -> dict[str, dict[str, str]]:
    """Every module-level prefix table under agent_fleet/ and src/, by AST.

    BY AST rather than by import: a table can only be checked if it is FOUND, and importing the
    ones we happen to remember is how the count stayed at two.
    """
    tables: dict[str, dict[str, str]] = {}
    for base in ("agent_fleet", "src"):
        for path in sorted((ROOT / base).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in tree.body:                      # MODULE LEVEL ONLY
                names = []
                if isinstance(node, ast.Assign):
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names = [node.target.id]
                for name in names:
                    if "IRI_PREFIX" not in name.upper() or not isinstance(node.value, ast.Dict):
                        continue
                    rel = path.relative_to(ROOT).as_posix()
                    tables[f"{rel}::{name}"] = {
                        k.value: v.value
                        for k, v in zip(node.value.keys, node.value.values)
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
                    }
    return tables


_TABLES = _derive_prefix_tables()

#: Public vocabularies. THE EXCLUSION LIST IS OF THINGS OUTSIDE OUR CONTROL, which is the only
#: kind of hand-kept list that does not rot: `owl:` will not gain a sibling because someone adds
#: an engine. Everything else a fleet ontology declares is OURS by construction, so a NEW
#: internal authority fails loudly instead of being silently dropped —
#: `_OURS` used to match `http://invincible-agent/` alone, and every `internal/sustainment/`
#: namespace (`safety:`, `pcn:`, `ps:`, `qs:`) fell out of the population without a word.
#: `safety:` was in the tables because a person put it there, never because this checked.
_EXTERNAL_AUTHORITIES = ("www.w3.org", "purl.org", "xmlns.com", "schema.org", "usefulinc.com")

_PREFIX_DECL = re.compile(r"@prefix\s+([A-Za-z][\w-]*):\s*<([^>]+)>")

#: EVERY namespace the ontologies declare, beyond the standard vocabularies above, is in the
#: basis or HERE WITH A REASON. Nothing is dropped for matching no pattern — which is how nine
#: of fifteen went unchecked.
#:
#: OWNERSHIP IS NOT EXPANDABILITY, and conflating them is the trap. An EXTERNAL vocabulary still
#: needs a table entry the moment code names it compact, because the graph holds the full IRI
#: either way. Each entry says why THAT prefix needs no expansion, never merely who owns it.
_EXEMPT: dict[str, str] = {
    "ps:": (
        "http://internal/sustainment/product# — declared by a sustainment ontology, named in "
        "compact form by no code path (measured 2026-09-17). Classes load through n10s as full "
        "IRIs and are reached in full form only."
    ),
    "qs:": (
        "http://internal/sustainment/qualification# — same measurement as ps:. Listed separately "
        "rather than folded into one entry because they can stop being true on different days."
    ),
    "mfg:": (
        "http://edgy-solutions.com/ontology/mfg# — a THIRD authority the old regex could not "
        "see. Declared, and named in compact form nowhere in agent_fleet/ or src/."
    ),
    "mil:": (
        "http://edgy-solutions.com/ontology/mil# — declared; its only appearance in code is the "
        "text of a query-parameter DESCRIPTION in gateway.py, which is prose ABOUT the URI and "
        "never a URI on a write path. A name-search for a namespace matches writing about it: "
        "three of the four hits that first looked like uses were a prompt string, a docstring "
        "example, and that description."
    ),
    "iof:": (
        "https://spec.industrialontologies.org/ontology/core/Core/ — Industrial Ontologies "
        "Foundry. Referenced in full IRI form where used; no compact form reaches a write path."
    ),
    "iof-construct:": (
        "https://spec.industrialontologies.org/ontology/construct/ — same standard, same "
        "full-IRI-only usage as iof:."
    ),
    "mro:": (
        "https://spec.industrialontologies.org/ontology/maintenance/... — EXEMPT ON PURPOSE AND "
        "NOT BY ABSENCE, which is the distinction this whole list exists to keep. "
        "`_LABEL_TO_CLASS_URI` in agent_fleet/neo4j_expert/main.py maps Part -> `mro:Part` in "
        "COMPACT form deliberately: mro:Part has no canonical declaration in mro_extension.ttl "
        "and the sandbox substrate holds no full-IRI form, so it stays compact and the widened "
        "substrate guard correctly flags it for resolution. Its three siblings in that same dict "
        "are spelled as full IRIs, which is what makes this row look like an oversight. ADDING "
        "mro: TO THE TABLES WOULD EXPAND IT TO AN IRI NOTHING CARRIES. Revisit when the TBox "
        "declaration lands, or when the row is removed; the trace is in the docstring above "
        "that dict."
    ),
    "s3kl:": (
        "http://www.lksoft.com/s3kl# — a vendor vocabulary; declared, never named compact."
    ),
}

def declared_namespaces() -> dict[str, str]:
    """prefix -> expansion for OUR namespaces, read from every ontology the fleet loads.

    PARTITIONED: every declared prefix is either ours or externally owned. Nothing is dropped
    for matching no pattern, which is how four namespaces went unchecked.
    """
    found: dict[str, str] = {}
    for path in sorted(ONTOLOGIES.glob("*.ttl")):
        for prefix, iri in _PREFIX_DECL.findall(path.read_text(encoding="utf-8")):
            if any(auth in iri for auth in _EXTERNAL_AUTHORITIES):
                continue
            found[prefix + ":"] = iri
    return found


def test_the_scan_ACTUALLY_FINDS_the_namespaces():
    """Positive control. A regex that matched nothing would make every test below vacuous, and
    it would pass forever — which is exactly how a derived population turns back into a
    remembered one without anybody editing a list.
    """
    found = declared_namespaces()
    assert len(found) >= 10, f"only {len(found)} namespaces found: {sorted(found)}"
    # The four on the OTHER authorities are named deliberately. The old regex matched
    # `http://invincible-agent/` only and dropped every one of them, so a floor built from the
    # first four alone would have stayed green through exactly the miss this file now records.
    for expected in ("mesh:", "fin:", "cost:", "idp:", "safety:", "pcn:", "mfg:", "mro:"):
        assert expected in found, f"{expected} is declared in the ontologies and was not found"


def test_the_TABLE_SCAN_actually_finds_the_tables():
    """The other positive control, and the one whose absence cost four namespaces.

    A derivation that found ZERO tables would make the expandability test vacuous and green
    forever. The floor is three because three is what exists; a fourth appearing is not a
    failure, a drop to two is.
    """
    assert len(_TABLES) >= 3, f"only {len(_TABLES)} prefix tables found: {sorted(_TABLES)}"
    for expected in ("mesh_registration", "capabilities", "v2_substrate"):
        assert any(expected in key for key in _TABLES), (
            f"no prefix table found in {expected} — either it was deleted or the AST scan "
            f"stopped seeing it, and a scan that sees less fails OPEN"
        )


# LIFTED OUT AND EXERCISED AGAINST A FIXTURE, because a ratchet that walks its own list has no
# reach on the day that list is empty -- and empty is the state the work is aimed at. Shown on
# 2026-09-18 by lane/91: with their `_KNOWN` emptied (by me), replacing their entire ratchet
# computation with `stale = []` left the suite GREEN. The guard gutted, nothing said.
#
# So the RULE is a function, and the test calls it with data it controls, BOTH DIRECTIONS: an
# entry that stopped being excused must be flagged, and one still excused must not. A ratchet
# that flagged everything would satisfy the live assertion too, for the wrong reason.
def _stale_exempt(exempt, handled) -> list:
    """Exempt prefixes a table now expands. THE RULE, callable with any data."""
    return sorted(set(exempt) & set(handled))


def test_THE_RATCHET_CAN_FAIL_WITH_THE_LIST_EMPTY():
    """`_EXEMPT` shrinks as namespaces gain table entries; at zero the arm below cannot fail."""
    assert _stale_exempt({"x:": "r"}, {"x:"}) == ["x:"], (
        "a prefix that IS in a table was not flagged as a stale exemption"
    )
    assert _stale_exempt({"x:": "r"}, {"y:"}) == [], (
        "a genuinely absent prefix was flagged — a ratchet that flags everything satisfies the "
        "live assertion for the wrong reason"
    )


def test_no_exemption_is_stale():
    """An exemption for a namespace that IS in the tables is a claim nobody re-read. It costs
    nothing today and misleads the next person deciding whether a prefix was considered."""
    handled = {p for t in _TABLES.values() for p in t}
    stale = _stale_exempt(_EXEMPT, handled)
    assert not stale, (
        f"exempt AND present in a table: {stale}. The exemption says the namespace needs no "
        f"expansion; the table says it has one. Delete the exemption."
    )


def test_every_declared_namespace_is_EXPANDABLE_by_EVERY_TABLE():
    """EVERY table, not both — there were three, and the constant said two.

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


def test_EVERY_TABLE_AGREES_on_its_namespace_set():
    """They diverge silently, and the divergence has now shipped four times.

    This does not require them to be one table — they decide different things — only that a
    namespace known to one is known to all. Asserted across the DERIVED set, because the
    version of this test that named two tables was green while the third held two of seven.
    """
    union = {p for t in _TABLES.values() for p in t}
    short = {
        label: sorted(union - set(table))
        for label, table in _TABLES.items()
        if union - set(table)
    }
    assert not short, (
        "tables that cannot expand a namespace a sibling table can:\n  "
        + "\n  ".join(f"{label} is missing {missing}" for label, missing in sorted(short.items()))
        + "\n\nA namespace one table folds and another does not is the silent class: the row "
        "registers, reports accepted, and never matches."
    )
    for prefix in sorted(union):
        expansions = {t[prefix] for t in _TABLES.values() if prefix in t}
        assert len(expansions) == 1, (
            f"{prefix} expands to {sorted(expansions)} across the tables — a prefix pointing "
            f"somewhere else is worse than one that is absent, because the miss looks like a "
            f"data problem rather than a registry one"
        )


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
    for label, table in _TABLES.items():
        for prefix, iri in declared.items():
            if prefix in table:
                assert table[prefix] == iri, (
                    f"{prefix} expands to {table[prefix]!r} in {label} and {iri!r} in the "
                    f"ontology"
                )


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
