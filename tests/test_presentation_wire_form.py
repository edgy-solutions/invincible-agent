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
