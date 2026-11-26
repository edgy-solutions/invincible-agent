"""The /search_predicates routing row records the verified caller, never the body's user_id.

Ruling (architect, 11-24): "A routing row records the verified caller, never a user_id from the
request body." Fixtures and helpers are imported from the classifier's row test, not copied.
"""
from __future__ import annotations

import asyncio
import json
import sys

from tests.routing.test_the_classifier_writes_its_routing_decision import (  # noqa: F401
    CANDS,
    _hits,
    _Capture,
    ontology_main,
    rows,
)

BODY_LABEL = "body-label"
BODY_EMAIL = "alice@example.invalid"
BOUND_EMAIL = "bound@example.invalid"
BODY_DOMAINS = ["maintenance", "finance"]
BOUND_DOMAINS = ["maintenance"]


def _wire(eo, monkeypatch, hits):
    class _Cs:
        def exists(self, n):
            return True

    class _Client:
        collections = _Cs()

    monkeypatch.setattr(eo, "_WEAVIATE_CLIENT", _Client())
    monkeypatch.setitem(sys.modules, eo.__name__, eo)
    eo.SearchPredicatesResponse.model_rebuild(force=True)

    async def _search(*a, **k):
        return hits
    monkeypatch.setattr(eo, "predicate_hybrid_search", _search)

    async def _bound(request, route=None):
        return request.model_copy(update={"user_email": BOUND_EMAIL,
                                          "entitled_domains": list(BOUND_DOMAINS)}), None
    monkeypatch.setattr(eo, "_bound", _bound)


def _call(eo):
    body = eo.SearchPredicatesRequest(query="q", entitled_domains=list(BODY_DOMAINS),
                                      user_email=BODY_EMAIL, user_id=BODY_LABEL)
    # control: the body's label is present on the request, so a row that carries it would show it
    assert body.user_id == BODY_LABEL
    asyncio.run(eo.search_predicates(body))


def _check(rows):
    assert len(rows) == 1
    row = rows[0]
    assert row["endpoint"] == "/search_predicates"
    assert row["user_id"] == BOUND_EMAIL
    assert row["entitled_domains"] == [d.upper() for d in BOUND_DOMAINS]
    blob = json.dumps(row)
    assert BODY_LABEL not in blob
    assert BODY_EMAIL not in blob


def test_the_no_match_row_names_the_bound_caller(ontology_main, monkeypatch, rows):
    """Control: body.user_id == 'body-label' is asserted before the call, so the absence can fail."""
    _wire(ontology_main, monkeypatch, [])
    _call(ontology_main)
    assert rows and rows[0]["fallback_reason"] == "no_predicate_matched"
    _check(rows)


def test_the_picked_row_names_the_bound_caller(ontology_main, monkeypatch, rows):
    """Control: body.user_id == 'body-label' is asserted before the call, so the absence can fail."""
    _wire(ontology_main, monkeypatch, _hits()[:1])
    _call(ontology_main)
    assert rows and rows[0]["picked_verb"] == CANDS[0]["verb_iri"]
    _check(rows)
