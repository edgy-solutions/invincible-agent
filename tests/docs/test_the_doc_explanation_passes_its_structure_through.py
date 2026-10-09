"""engine-docs' KNOWLEDGE_DOCUMENT payload must reach cortex-ui as STRUCTURE, not markdown alone.

THE CONTRACT OWNER is cortex-ui (`../cortex-ui` commit a425186,
`src/archetypes/knowledge-document/knowledgeDocumentView.ts`): it draws structure when the card carries a
NON-EMPTY `pages` list, or when `abstained` is literally `True` -- anything else falls back to
`markdown_content`. `_render_document_deterministic` composed markdown from `summary` /
`summary_text` / `structured_data` only (see `test_the_doc_explanation_renders_its_body.py`,
removed in 8a5c7923) and never put `pages` / `abstained` / `subject` / `page_count` / `reason` /
`body` on the component at all -- so engine-docs' own shape never reached cortex as structure,
even once the markdown carried the prose.

FIVE ARMS PLUS THE SEAL-POPULATION PIN:
  - the table:    one row for docs:DocExplanation, archetype KNOWLEDGE_DOCUMENT.
  - HIT:          a `pages` payload passes `subject`, `pages`, `page_count` through UNCHANGED,
                  and the markdown stays "No content available." -- the passthrough rides
                  BESIDE the markdown, it does not feed it.
  - ABSTAIN:      an `abstained: True` payload passes `abstained`, `reason`, `body`, `subject`.
  - CONTROL:      a `summary`-shaped payload (with stray `subject`/`body` that are not the
                  discriminator) gets no passthrough keys at all -- the component key set is
                  exactly the pre-existing four.
  - CONTROL:      `pages: []` and `abstained: "true"` (a string) each pass NOTHING through --
                  the discriminator mirrors cortex's own truthiness/type checks exactly.
  - THE PIN:      the fields the MARKDOWN composer reads (extracted the same way
                  `test_slot_disposition.py::test_the_fallback_renders_the_ask_rather_than_silence`
                  extracts them) are exactly {"summary", "summary_text", "structured_data"} --
                  never widened by this change. A passthrough key read inside the composer would
                  change that seal's population and silently loosen what it protects.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PRESENTATION_DIR = ROOT / "agent_fleet" / "presentation_agent"
if str(_PRESENTATION_DIR) not in sys.path:
    sys.path.insert(0, str(_PRESENTATION_DIR))

import types
from types import SimpleNamespace

from tests.conftest import stub_modules

from agent_fleet.presentation_agent.capabilities import (  # noqa: E402
    PRESENTATION_CAPABILITIES,
    canonical_iri_for_lookup,
)

_DOC_EXPLANATION_IRI = "http://invincible-agent/docs#DocExplanation"

PERSONA = "ARCHITECT"


def _stub_baml_client():
    stub = types.ModuleType("baml_client")
    stub.b = SimpleNamespace()
    stub.__path__ = []  # type: ignore[attr-defined]  # a PACKAGE, not a bare module
    return stub


def _import_presentation_main():
    """Import `presentation_agent.main` FOR REAL, with `baml_client` stubbed via the shared
    harness. `main.py` does `from baml_client import b` at import time and `baml_client` is
    generated, not installed in this venv."""
    with stub_modules({"baml_client": _stub_baml_client()}):
        import agent_fleet.presentation_agent.main as _m
    return _m


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
                "body": "ALPHA-PAGE-MARKER first page body text.",
            },
            {
                "archetype": "KNOWLEDGE_DOCUMENT_PAGE",
                "page_iri": "docs:runbook-adding-an-engine",
                "title": "Runbook -- adding an engine",
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


# ── HIT: subject, pages, page_count pass through unchanged; markdown untouched ──────────

def test_hit_payload_passes_pages_and_page_count_through():
    pf = _import_presentation_main()
    payload = _hit_payload()
    doc = pf._render_document_deterministic(
        _wrapped(payload), PERSONA, subject_concept="docs:DocExplanation",
    )
    component = doc["components"][0]
    assert component.get("subject") == payload["subject"]
    assert component.get("pages") == payload["pages"]
    assert component.get("page_count") == payload["page_count"]
    assert component["markdown_content"] == "No content available.", (
        "the passthrough rides BESIDE the markdown -- it must not change what the composer "
        "puts in markdown_content"
    )


# ── ABSTAIN: abstained, reason, body, subject pass through ──────────────────────────────

def test_abstain_payload_passes_abstained_reason_body_subject_through():
    pf = _import_presentation_main()
    payload = _abstain_payload()
    doc = pf._render_document_deterministic(
        _wrapped(payload), PERSONA, subject_concept="docs:DocExplanation",
    )
    component = doc["components"][0]
    assert component.get("abstained") is True
    assert component.get("reason") == payload["reason"]
    assert component.get("body") == payload["body"]
    assert component.get("subject") == payload["subject"]


# ── CONTROL: a summary-shaped payload with stray subject/body gets no passthrough ───────

def test_control_summary_payload_with_stray_fields_gets_no_passthrough():
    pf = _import_presentation_main()
    payload = {
        "summary": "the pre-existing summary text",
        "subject": "http://invincible-agent/mesh#NotTheDiscriminator",
        "body": "a body field that is not the abstain/pages discriminator",
    }
    doc = pf._render_document_deterministic(
        _wrapped(payload), PERSONA, subject_concept="docs:DocExplanation",
    )
    component = doc["components"][0]
    assert set(component) == {
        "archetype", "source_persona", "subject_concept", "markdown_content",
    }, (
        f"a payload with neither a non-empty `pages` list nor `abstained is True` must add NO "
        f"passthrough keys -- got {sorted(component)}"
    )
    assert component["markdown_content"] == payload["summary"]


# ── CONTROL: empty pages / non-bool abstained pass nothing through ──────────────────────

def test_control_empty_pages_list_passes_nothing_through():
    pf = _import_presentation_main()
    payload = {"pages": [], "subject": "http://invincible-agent/mesh#X"}
    doc = pf._render_document_deterministic(
        _wrapped(payload), PERSONA, subject_concept="docs:DocExplanation",
    )
    component = doc["components"][0]
    assert "pages" not in component
    assert "subject" not in component
    assert set(component) == {
        "archetype", "source_persona", "subject_concept", "markdown_content",
    }, "an empty pages list is not a non-empty list -- cortex falls back to markdown for it too"


def test_control_stringly_true_abstained_passes_nothing_through():
    pf = _import_presentation_main()
    payload = {"abstained": "true", "subject": "http://invincible-agent/mesh#X"}
    doc = pf._render_document_deterministic(
        _wrapped(payload), PERSONA, subject_concept="docs:DocExplanation",
    )
    component = doc["components"][0]
    assert "abstained" not in component
    assert "subject" not in component
    assert set(component) == {
        "archetype", "source_persona", "subject_concept", "markdown_content",
    }, (
        "cortex checks `abstained is True` (a literal bool), not truthiness -- the string "
        "\"true\" must not trigger the passthrough either"
    )


# ── THE PIN: the markdown composer's own read-set must not have widened ─────────────────

def test_the_markdown_composers_read_set_is_still_exactly_summary_and_structured_data():
    """Mirrors `test_slot_disposition.py::test_the_fallback_renders_the_ask_rather_than_silence`'s
    own extraction, over the SAME function. If a passthrough key were read inside this function
    (rather than by the separate helper the passthrough lives in), it would silently widen the
    population that seal treats as "what the markdown reads" -- this pin catches that before
    that seal has to."""
    src = (Path(__file__).resolve().parents[2]
           / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and "No content available" in ast.dump(n)), None)
    assert fn is not None, "the KNOWLEDGE_DOCUMENT composer moved -- find it before trusting this"

    read_keys = {
        node.args[0].value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "agent_response"
        and node.args and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert read_keys == {"summary", "summary_text", "structured_data"}, (
        f"the composer now reads {sorted(read_keys)} -- a passthrough key read inside this "
        f"function would change test_slot_disposition.py's own extracted population, not just "
        f"add a feature here"
    )
