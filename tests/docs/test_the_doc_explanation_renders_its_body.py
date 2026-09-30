"""engine-docs' answer must actually reach the card -- today it does not.

THE DEFECT (rev-157 census, `docs/measurements/2026-09-26-*`). `agent_fleet/docs_agent/main.py`
answers `mesh:explain` (`docs:DocExplanation`) with one of two flat shapes:

    HIT:     {"archetype": "KNOWLEDGE_DOCUMENT", "subject": <iri>,
              "pages": [{"page_iri", "title", ..., "body": <markdown>}, ...], "page_count": N}
    ABSTAIN: {"archetype": "KNOWLEDGE_DOCUMENT", "page_iri": None, "subject": <iri>,
              "abstained": True, "reason": "no_page_explains_this_subject", "body": <short str>}

`presentation_agent` had NO capability row naming this subject, so the live fleet fell through
to `__system_default__`'s KNOWLEDGE_DOCUMENT path with no binding at all. Even with a row,
`_render_document_deterministic` composes markdown ONLY from `summary` / `summary_text` /
`structured_data` -- none of which this payload carries -- so the card still says "No content
available.": the row alone does not fix it, and the renderer alone (with no row) never reaches
the payload either. Both halves are sealed here.

FOUR ARMS, KEYED ON WHAT THE ARM CAN SEE:
  - the table:   the row exists, points at the right archetype, and is the ONLY row for this
                 subject (a second row would shadow the first at registration and nobody would
                 notice which one served).
  - HIT:         `pages[].body`, in order, joined -- proves the loop and the join, not just
                 "some text got through".
  - ABSTAIN:     the flat `body` -- proves the composer takes BOTH shapes engine-docs emits, not
                 only the one with `pages`.
  - CONTROL (no body at all): still "No content available." -- proves the new arm is KEYED ON
    the body shape, not a blanket "always found something" change that would mask a real miss.
  - CONTROL (summary AND body both present): byte-identical to the pre-existing summary-only
    output -- proves `summary` still wins and `body` is not appended alongside it, so no
    existing caller's card can change shape from this fix.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PRESENTATION_DIR = ROOT / "agent_fleet" / "presentation_agent"
if str(_PRESENTATION_DIR) not in sys.path:
    sys.path.insert(0, str(_PRESENTATION_DIR))

from agent_fleet.presentation_agent.capabilities import (  # noqa: E402
    PRESENTATION_CAPABILITIES,
    canonical_iri_for_lookup,
)

_DOC_EXPLANATION_IRI = "http://invincible-agent/docs#DocExplanation"


def _import_presentation_main():
    """Import `presentation_agent.main` FOR REAL, with `baml_client` stubbed.

    ⛔ CALLED LAZILY, FROM INSIDE EACH TEST -- never at module level. Same hazard documented in
    `tests/routing/test_a_menu_on_the_wire_can_be_answered.py::_import_engine_f`: pytest imports
    every test module before running any test, so a module-level stub would sit in
    `sys.modules` during OTHER files' collection too. `main.py` does `from baml_client import b`
    at import time and `baml_client` is generated, not installed in this venv -- so the import
    must be made to work (a real stub) rather than skipped (`importorskip` would make this file
    report green while asserting nothing).
    """
    if "baml_client" not in sys.modules:
        stub = types.ModuleType("baml_client")
        stub.b = types.SimpleNamespace()
        stub.__path__ = []  # type: ignore[attr-defined]  # a PACKAGE, not a bare module
        sys.modules["baml_client"] = stub
    import agent_fleet.presentation_agent.main as _m
    return _m


PERSONA = "ARCHITECT"


def _wrapped(expert_response):
    """The shape cortex-bff actually sends: a list of wrappers, the payload under
    `expert_response`. `_extract_agent_response` descends into exactly this."""
    return [{"persona": PERSONA, "user_persona": PERSONA, "answerer_persona": PERSONA,
             "predicate_verb_iri": "docs:explain", "sub_query": "explain this",
             "expert_response": expert_response}]


def _hit_payload():
    return {
        "archetype": "KNOWLEDGE_DOCUMENT",
        "subject": "http://invincible-agent/mesh#Archetype",
        "pages": [
            {
                "archetype": "KNOWLEDGE_DOCUMENT_PAGE",
                "page_iri": "docs:runbook-adding-an-archetype",
                "title": "Runbook -- adding an archetype",
                "doc_kind": "how-to",
                "audience_hint": "ARCHITECT",
                "explains": ["mesh:Archetype"],
                "cited_seals": [],
                "source": "docs/pages/aaaa/adding-an-archetype.md",
                "body_sha": "aaaa",
                "body": "ALPHA-PAGE-MARKER first page body text.",
            },
            {
                "archetype": "KNOWLEDGE_DOCUMENT_PAGE",
                "page_iri": "docs:runbook-adding-an-engine",
                "title": "Runbook -- adding an engine",
                "doc_kind": "how-to",
                "audience_hint": "ARCHITECT",
                "explains": ["mesh:Archetype"],
                "cited_seals": [],
                "source": "docs/pages/bbbb/adding-an-engine.md",
                "body_sha": "bbbb",
                "body": "BETA-PAGE-MARKER second page body text.",
            },
        ],
        "page_count": 2,
    }


def _abstain_payload():
    return {
        "archetype": "KNOWLEDGE_DOCUMENT",
        "page_iri": None,
        "subject": "http://invincible-agent/mesh#NoSuchThing",
        "abstained": True,
        "reason": "no_page_explains_this_subject",
        "body": "ABSTAIN-MARKER: no page explains this subject.",
    }


# ── the table ────────────────────────────────────────────────────────────────────────────

def test_docs_explanation_has_exactly_one_capability_row():
    rows = [
        c for c in PRESENTATION_CAPABILITIES
        if canonical_iri_for_lookup(c["subject_uri"]) == _DOC_EXPLANATION_IRI
    ]
    assert len(rows) == 1, (
        f"expected exactly one capability row for docs:DocExplanation, found {len(rows)}: "
        f"{rows} -- a second row would shadow the first at registration with no signal of "
        f"which one served"
    )
    assert rows[0]["archetype"] == "KNOWLEDGE_DOCUMENT", (
        "docs:DocExplanation must render as KNOWLEDGE_DOCUMENT -- it is markdown prose, not "
        "rows, a chart, or a graph"
    )


# ── HIT: pages[].body, in order, joined ─────────────────────────────────────────────────

def test_hit_payload_renders_both_page_bodies():
    pf = _import_presentation_main()
    doc = pf._render_document_deterministic(
        _wrapped(_hit_payload()), PERSONA, subject_concept="docs:DocExplanation",
    )
    markdown = doc["components"][0]["markdown_content"]
    assert "ALPHA-PAGE-MARKER" in markdown
    assert "BETA-PAGE-MARKER" in markdown
    assert "No content available" not in markdown
    # order matters: the first page's body must precede the second's, not just both present.
    assert markdown.index("ALPHA-PAGE-MARKER") < markdown.index("BETA-PAGE-MARKER")


# ── ABSTAIN: the flat body, not pages ───────────────────────────────────────────────────

def test_abstain_payload_renders_its_flat_body():
    pf = _import_presentation_main()
    doc = pf._render_document_deterministic(
        _wrapped(_abstain_payload()), PERSONA, subject_concept="docs:DocExplanation",
    )
    markdown = doc["components"][0]["markdown_content"]
    assert "ABSTAIN-MARKER" in markdown
    assert "No content available" not in markdown


# ── CONTROL: neither shape present -- the arm must not be always-on ────────────────────

def test_control_payload_with_no_body_shape_still_says_no_content():
    pf = _import_presentation_main()
    doc = pf._render_document_deterministic(
        _wrapped({"archetype": "SOMETHING_ELSE", "not_a_body_field": "irrelevant"}),
        PERSONA, subject_concept="docs:DocExplanation",
    )
    markdown = doc["components"][0]["markdown_content"]
    assert markdown == "No content available.", (
        "a payload with neither pages[].body nor a flat body must fall through exactly as "
        "before -- if this now finds content, the new arm is keyed on something broader than "
        "the body shape and would mask a genuine miss"
    )


# ── CONTROL: summary wins, body is not appended alongside it ────────────────────────────

def test_control_summary_beats_body_byte_identical_to_pre_existing_output():
    pf = _import_presentation_main()
    payload_summary_only = {"summary": "the pre-existing summary text"}
    payload_summary_and_body = {
        "summary": "the pre-existing summary text",
        "body": "a body field that must NOT appear alongside the summary",
    }
    doc_old = pf._render_document_deterministic(
        _wrapped(payload_summary_only), PERSONA, subject_concept="docs:DocExplanation",
    )
    doc_new = pf._render_document_deterministic(
        _wrapped(payload_summary_and_body), PERSONA, subject_concept="docs:DocExplanation",
    )
    old_markdown = doc_old["components"][0]["markdown_content"]
    new_markdown = doc_new["components"][0]["markdown_content"]
    assert old_markdown == "the pre-existing summary text"
    assert new_markdown == old_markdown, (
        "a payload carrying both `summary` and `body` must render BYTE-IDENTICAL to a "
        "summary-only payload -- summary wins, body is not appended, and no existing caller's "
        "card can change shape from this fix"
    )
    assert "must NOT appear" not in new_markdown
