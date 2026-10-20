"""The review card's leaf (pcn/pdn) comes from the ingest row, else from the extraction's TITLE
evidence; a defaulted doc_type is never shown as a leaf (pre-191 rows show None, not an invented PCN)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402
from tests.test_ingest_review_card_routes import (  # noqa: E402,F401
    ID, REVIEW, FakeS3, _as, _cleanup, _gate, _get, _objects, _row,
)

leaf = gateway._review_leaf


def _rv(dt, src="title"):
    d = {"doc_type": dt}
    if src is not None:
        d["doc_type_source"] = src
    return d


def test_row_wins_over_extraction():
    assert leaf("pcn", _rv("PDN")) == ("pcn", "ingest")


def test_row_is_normalised():
    assert leaf("PDN ", None) == ("pdn", "ingest")


def test_pre_191_row_reads_extraction_title():
    assert leaf("sustainment", _rv("PDN")) == ("pdn", "extraction-title")


def test_none_row_lowercase_review():
    assert leaf(None, _rv("pcn")) == ("pcn", "extraction-title")


@pytest.mark.parametrize("src", ["no-title-evidence", "title-ambiguous", "defaulted", None])
def test_non_title_source_is_not_evidence(src):
    assert leaf("sustainment", _rv("PCN", src)) == (None, None)


def test_unknown_doc_type_refused():
    assert leaf("sustainment", _rv("ECN")) == (None, None)


@pytest.mark.parametrize("rv", [None, {}])
def test_empty_review(rv):
    assert leaf("sustainment", rv) == (None, None)


def _body(monkeypatch, content_kind, **rv):
    review = {**REVIEW, **rv}
    fake = FakeS3(_objects(review=review))
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    _gate(monkeypatch, row=_row(content_kind=content_kind))
    _as(monkeypatch, "alice@example.com")
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200, r.text
    return r.json()


def test_route_pre_191_row_gets_leaf_from_title(monkeypatch):
    b = _body(monkeypatch, "sustainment", doc_type="PDN", doc_type_source="title")
    assert b["leaf"] == "pdn" and b["leaf_source"] == "extraction-title"
    assert b["content_kind"] == "sustainment"


def test_route_defaulted_doc_type_is_no_leaf(monkeypatch):
    b = _body(monkeypatch, "sustainment", doc_type="PCN", doc_type_source="no-title-evidence")
    assert b["leaf"] is None and b["leaf_source"] is None


def test_route_pcn_row_is_ingest_leaf(monkeypatch):
    b = _body(monkeypatch, "pcn")
    assert b["leaf"] == "pcn" and b["leaf_source"] == "ingest"
