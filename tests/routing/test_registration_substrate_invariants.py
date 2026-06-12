"""Standing-guard invariants for the registration substrate.

These tests pin two bug classes that surfaced during Recipe v2 /
Gate 6 (2026-06-12) as permanent tripwires, so the next provider
to join (provider #3 — the DMC phone book the docs phase will ship)
doesn't re-introduce either shape silently.

The two classes:

  **Multi-provider edge collision.** ``aitool_linker``'s match-key
  inside ``apoc.merge.relationship`` used to be ``{iri: verb_iri}``.
  N providers offering the same predicate collapsed into ONE edge
  with last-write-wins semantics — Engine E silently overwrote
  Engine D's row when both registered for mesh:resolveInstance.
  Fix landed in doc-tools a44b9fb: identity is now
  ``(verb_iri, _tool_urn)``. This file pins that the match-key
  includes ``_tool_urn``.

  **Phone book returning compact URIs Neo4j cannot find.** Engine D's
  ``_DATAHUB_TO_IDP`` and ``_column_match`` were returning
  ``idp:Table`` etc. — but ``idp_extension.ttl``'s canonical ingest
  expanded those to ``http://invincible-agent/idp#Table`` when
  writing ``:OntologyClass`` nodes. Engine O's compat-walk
  string-matches on uri, found nothing, and Contract B then
  correctly short-circuited to UNKNOWN. The earlier "16/17 green"
  matrix was the same Contract B hole masking it. Fix landed in
  engine-d 4c74eee. This file pins that every value in any phone-
  book's class map is a canonical URI form that exists in Neo4j.

Both bugs are the same kind: a registration-path component said
something the substrate could not find. Same disease, two layers.
The guards are pure-pattern unit tests — they run on every CI tick
without a cluster.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Multi-provider edge collision — match-key must include _tool_urn
# ---------------------------------------------------------------------------

# The substrate-write site for AITool predicate edges lives in the
# doc-tools sibling repo. We resolve via a relative path because both
# repos sit under the same git root in this dev environment; CI mirrors
# this layout. When this layout no longer holds (e.g., doc-tools split
# into a separate workspace), this guard moves with it — the standing
# rule is "the matchKey for apoc.merge.relationship MUST distinguish
# providers," and the rule travels with the matcher.
_DOC_TOOLS_AITOOL_LINKER = (
    _REPO_ROOT.parent / "doc-tools" / "doc_tools" / "assets" / "aitool_linker.py"
)


@pytest.mark.skipif(
    not _DOC_TOOLS_AITOOL_LINKER.exists(),
    reason=(
        "doc-tools sibling repo not present in this CI environment. The "
        "rule still stands: any apoc.merge.relationship call writing an "
        "AITool predicate edge MUST include _tool_urn in its match-key. "
        "When doc-tools is reachable, this test fails red the moment the "
        "rule is broken."
    ),
)
def test_aitool_link_matchkey_includes_tool_urn() -> None:
    """The apoc.merge.relationship match-key in aitool_linker MUST
    include ``_tool_urn`` so each provider's registration lives as
    its own Neo4j edge rather than overwriting whichever rolled
    last. This pins the doc-tools a44b9fb fix."""
    src = _DOC_TOOLS_AITOOL_LINKER.read_text(encoding="utf-8")

    assert "apoc.merge.relationship" in src, (
        f"\n  {_DOC_TOOLS_AITOOL_LINKER.name}: lost the apoc.merge.relationship "
        f"writer that materializes AITool predicate edges. If the writer "
        f"moved, move this guard with it; the standing rule (match-key "
        f"must distinguish providers) goes wherever the merge call goes."
    )

    # The match_key local variable was introduced in a44b9fb. It must
    # include _tool_urn. The check is permissive on formatting (quote
    # style, whitespace) but strict on the field name.
    matchkey_pattern = re.compile(
        r"""match_key\s*=\s*\{[^}]*['"]_tool_urn['"][^}]*\}""",
        re.MULTILINE | re.DOTALL,
    )
    assert matchkey_pattern.search(src), (
        f"\n  {_DOC_TOOLS_AITOOL_LINKER.name}: match_key for "
        f"apoc.merge.relationship does NOT include _tool_urn.\n"
        f"\n  Recipe v2 / Gate 6 (2026-06-12) caught this: two providers "
        f"registering the same predicate collapsed into ONE Neo4j edge "
        f"with last-write-wins. Engine E silently overwrote Engine D for "
        f"mesh:resolveInstance until the (verb_iri, _tool_urn) identity "
        f"landed in a44b9fb. Provider #3 (DMC phone book, queued in the "
        f"docs phase) recurs the same collision shape; this guard turns "
        f"red BEFORE the silent overwrite ships.\n"
    )


# ---------------------------------------------------------------------------
# Phone-book class URIs MUST be canonical (the form Neo4j actually stores)
# ---------------------------------------------------------------------------

_ENGINE_D_MAIN = _REPO_ROOT / "agent_fleet" / "datahub_wrapper" / "main.py"


def _extract_class_uris_from_engine_d() -> list[str]:
    """Pull every class_uri value out of Engine D's main.py — both
    the _DATAHUB_TO_IDP map and the inline strings inside
    _column_match. Pure regex; doesn't import the module (we don't
    want to pay Engine D's import cost in CI)."""
    src = _ENGINE_D_MAIN.read_text(encoding="utf-8")

    found: list[str] = []

    # _DATAHUB_TO_IDP entries — "ENTITY_TYPE": "<uri>"
    map_entry_re = re.compile(
        r"""['"](?:DATASET|DASHBOARD|CHART|DATA_FLOW|DATA_JOB)['"]"""
        r"""\s*:\s*['"]([^'"]+)['"]""",
    )
    found.extend(map_entry_re.findall(src))

    # Inline class_uri="..." literals inside _column_match (etc.)
    inline_re = re.compile(r"""['"]class_uri['"]\s*:\s*['"]([^'"]+)['"]""")
    found.extend(inline_re.findall(src))

    return found


def test_engine_d_class_uris_are_canonical_full_iri_form() -> None:
    """Every idp:* class URI Engine D returns to the router MUST be
    the full IRI form (``http://invincible-agent/idp#X``) that
    idp_extension.ttl's canonical ingest writes into Neo4j. The
    compact ``idp:X`` form does NOT exist as a :OntologyClass node
    after canonical ingest, so handing it back as ``resolved_uri``
    makes the compat-walk find zero verbs — and (since Contract B
    shipped) correctly returns UNKNOWN. This pins the engine-d
    4c74eee fix.

    Rule:
      - idp:* URIs MUST start with ``http://invincible-agent/idp#``.
      - Compact prefix ``idp:`` followed by a class name is
        forbidden as a phone-book return value.
      - Other namespaces (mro:*, mesh:*, ...) are NOT checked here —
        Neo4j stores those as compact for now; that's a separate
        canonicalization arc the user has flagged for the substrate-
        debt track.
    """
    if not _ENGINE_D_MAIN.exists():
        pytest.skip(f"Engine D main.py not found at {_ENGINE_D_MAIN}")

    class_uris = _extract_class_uris_from_engine_d()
    assert class_uris, (
        "No class_uri values found in Engine D's main.py — either the "
        "extraction regex broke or the file was reorganized. Update the "
        "extractor; the rule (canonical URI form on phone-book returns) "
        "still applies."
    )

    forbidden_compact_idp = re.compile(r"^idp:[A-Z]")
    violations = [u for u in class_uris if forbidden_compact_idp.match(u)]

    assert not violations, (
        f"\n  Engine D phone-book violations: returns compact idp:* URIs "
        f"that Neo4j does not store.\n"
        f"  Offending values: {sorted(set(violations))}\n"
        f"  Expected form: http://invincible-agent/idp#<Class>\n"
        f"\n  Recipe v2 / Gate 6 (2026-06-12) caught this at the matrix "
        f"layer: every override row went RED 8/18 because the compact "
        f"form didn't match any :OntologyClass node and the compat-walk "
        f"returned []. The earlier '16/17 green' was the same Contract B "
        f"hole masking it — the LLM was picking verbs from the "
        f"unconstrained Weaviate pool. This guard turns red BEFORE the "
        f"compact form ships again, on Engine D or on any future phone "
        f"book that gets added under the same pattern (DMC provider, "
        f"etc.)."
    )


def test_engine_d_idp_namespace_uris_resolve_to_extension_namespace() -> None:
    """Every full-IRI idp:* URI Engine D returns MUST be under the
    canonical extension namespace ``http://invincible-agent/idp#`` —
    not a typo'd close-but-different namespace. Belt-and-suspenders
    on the previous test: catches the case where someone "fixes"
    compact form by hand-typing a full IRI with a wrong prefix.
    """
    if not _ENGINE_D_MAIN.exists():
        pytest.skip(f"Engine D main.py not found at {_ENGINE_D_MAIN}")

    class_uris = _extract_class_uris_from_engine_d()
    # An idp:* URI is anything that LOOKS like one — full IRI or
    # compact. We check that any URI mentioning the idp namespace
    # uses the exact canonical prefix.
    idp_uris = [u for u in class_uris if "idp" in u.lower()]
    canonical_prefix = "http://invincible-agent/idp#"

    misnamed = [u for u in idp_uris if not u.startswith(canonical_prefix)]
    assert not misnamed, (
        f"\n  Engine D returns idp:* URIs with a non-canonical prefix:\n"
        f"  Offending values: {sorted(set(misnamed))}\n"
        f"  Expected canonical prefix: {canonical_prefix}\n"
        f"\n  The compact prefix 'idp:' is also a violation (it's caught "
        f"by the sibling test above); this guard catches the more subtle "
        f"case where a refactor swaps the namespace to something close-"
        f"but-different that Neo4j also doesn't store."
    )
