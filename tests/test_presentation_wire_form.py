"""A presentation registration must put FULL IRIs on the wire, like an engine does.

THE DEFECT, measured 2026-08-21 against the live substrate. doc-tools' linker materializes a
registration by MATCHing both triple endpoints as :OntologyClass nodes, and those nodes hold
FULL IRIs. Engine registrations satisfy that because their callers pass full form.
PRESENTATION_CAPABILITIES uses COMPACT form, so a presentation's MATCH missed on BOTH ends and
the row was never created -- the third of three independent reasons rendersAs rows never
reached Weaviate.

This is the compact-vs-full hazard at the REGISTRATION boundary. The read side folds both
forms (`canonical_iri_for_lookup`), which is exactly why the write side must not rely on that:
a producer has to pick one convention, and it must be the one the graph stores.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_presentation_wire_form.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.utils.mesh_registration import _expand_mesh_iri  # noqa: E402
from agent_fleet.presentation_agent.capabilities import (  # noqa: E402
    PRESENTATION_CAPABILITIES,
)

_MESH = "http://invincible-agent/mesh#"


def test_compact_mesh_form_expands():
    assert _expand_mesh_iri("mesh:ChartWidget") == _MESH + "ChartWidget"


def test_compact_idp_form_expands():
    assert _expand_mesh_iri("idp:Dataset") == "http://invincible-agent/idp#Dataset"


def test_expansion_is_IDEMPOTENT():
    """Every engine registration already passes full form. If expansion mangled those, this
    fix would break the path it is trying to join."""
    full = _MESH + "OwnershipFact"
    assert _expand_mesh_iri(full) == full


def test_an_UNKNOWN_prefix_is_left_alone_not_guessed():
    """Inventing a namespace would fabricate the same phantom class Contract D exists to
    refuse. Passing it through unchanged lets the MATCH fail loudly instead."""
    assert _expand_mesh_iri("pcn:SustainmentNotice") == "pcn:SustainmentNotice"
    assert _expand_mesh_iri("") == ""


def test_EVERY_capability_endpoint_expands_to_a_full_iri():
    """The property that actually matters: after expansion, nothing a presentation puts on
    the wire is still in compact form, because the linker MATCHes on the stored full IRI."""
    for cap in PRESENTATION_CAPABILITIES:
        for key in ("subject_uri", "object_uri"):
            expanded = _expand_mesh_iri(cap[key])
            assert expanded.startswith("http"), (
                f"{cap[key]} did not expand to a full IRI — the linker's MATCH will miss "
                f"and the presentation will never materialize"
            )
            assert ":" in expanded and not expanded.startswith("mesh:")


# ── THE REGISTRATION NAME IS ALSO WIRE ────────────────────────────────────────────────
#
# The tests above pin the two triple ENDPOINTS onto the wire in full-IRI form. The
# registration NAME is the third thing that crosses, and it crosses somewhere stricter:
# inside a DataHub URN,
#
#     urn:li:mlModel:(urn:li:dataPlatform:mesh,presentation_<archetype>_for_<slug>,PROD)
#
# where a colon is the URN's own delimiter.
#
# `capability_slug` read `.replace("mesh:", "")` for as long as every capability was a
# `mesh:` one — a literal that is indistinguishable from a general rule until a second
# namespace exists. Engine F (ADR-0045) is that second namespace, and all six of its rows
# came out as `presentation_period_series_for_fin:burnrateseries`.
#
# THE REASON IT WENT UNCAUGHT IS THE REASON THIS TEST IS NEW: the function used to live in
# presentation_agent/main.py, which imports baml_client and therefore cannot be imported
# outside the container. Nothing under tests/ could reach it. The fix was to move it beside
# the table it names — an untestable module is where a `mesh:`-shaped assumption goes to
# survive.

from agent_fleet.presentation_agent.capabilities import capability_slug


def test_no_capability_slug_carries_a_prefix_into_the_urn():
    """The property, asserted over the real table rather than over examples."""
    for cap in PRESENTATION_CAPABILITIES:
        slug = capability_slug(cap["subject_uri"])
        assert ":" not in slug, (
            f"{cap['subject_uri']} -> {slug!r} puts a URN delimiter inside a URN component"
        )
        assert slug and slug == slug.lower()


def test_capability_slug_strips_ANY_prefix_not_just_mesh():
    """The generalisation, stated directly so a future namespace inherits it."""
    assert capability_slug("mesh:OwnershipFact") == "ownershipfact"
    assert capability_slug("fin:BurnRateSeries") == "burnrateseries"
    assert capability_slug("idp:Dataset") == "dataset"
    assert capability_slug("pcn:SustainmentNotice") == "sustainmentnotice"


def test_capability_slug_is_byte_identical_for_every_pre_existing_mesh_row():
    """A widened rule must not quietly RENAME anything already registered.

    Registration name is URN identity: had the new rule differed on any `mesh:` row, the
    next startup would have created a second capability rather than upserting the one that
    exists. This pins the widening as strictly additive.
    """
    for cap in PRESENTATION_CAPABILITIES:
        if cap["subject_uri"].startswith("mesh:"):
            legacy = cap["subject_uri"].replace("mesh:", "").lower()
            assert capability_slug(cap["subject_uri"]) == legacy


def test_capability_slug_handles_BOTH_spellings_because_two_callers_send_different_ones():
    """The defect that produced a colon inside a DataHub URN, from the other direction.

    presentation_agent sends COMPACT (`fin:BurnRateSeries`). The gateway receives whatever a
    frontend declares and can see the FULL IRI. Two implementations existed and each was correct
    only on the input its author happened to have:

        this one (before):  strip a compact prefix  -> mangled a full IRI to
                            `//invincible-agent/fin#burnrateseries`
        gateway's (before): rsplit("#")             -> a NO-OP on a compact curie, so the whole
                            `fin:BurnRateSeries` survived into the URN

    One implementation now, imported by both, and this pins the property rather than the callers.
    """
    for compact, full, expected in [
        ("fin:BurnRateSeries", "http://invincible-agent/fin#BurnRateSeries", "burnrateseries"),
        ("mesh:OwnershipFact", "http://invincible-agent/mesh#OwnershipFact", "ownershipfact"),
        ("idp:Dataset", "http://invincible-agent/idp#Dataset", "dataset"),
    ]:
        assert capability_slug(compact) == expected
        assert capability_slug(full) == expected, (
            f"{full} did not reduce to its local name — a full IRI reaching the gateway would "
            f"put a slash and a hash inside a URN component"
        )
        assert capability_slug(compact) == capability_slug(full), (
            "the two spellings must produce the SAME slug, or one subject registers under two "
            "urns depending on which caller wrote it"
        )
