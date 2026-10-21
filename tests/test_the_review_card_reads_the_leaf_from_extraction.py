"""The review card's leaf (pcn/pdn) is read from the ingest ROW only (spec 203b): `content_kind` names
the leaf, `leaf_source` is the column as stored (declared | title | corrected) with no default, and
`corrected_by` is `leaf_set_by` for a corrected leaf. review.json no longer contributes a leaf: a pdf
row with no leaf shows `leaf: null` however confident the title is (`title_leaf`, doc-tools' call after
its title read, is what writes `title` onto such a row)."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402
from tests.test_ingest_review_card_routes import (  # noqa: E402,F401
    ID, REVIEW, FakeS3, _as, _cleanup, _gate, _get, _objects, _row,
)


def leaf(row):
    return gateway._row_leaf(row)


def test_the_leaf_is_the_content_kind_lowercased_and_stripped():
    assert leaf({"content_kind": "PDN ", "leaf_source": "declared"}) == ("pdn", "declared", None)


def test_the_source_is_the_stored_column_with_no_default():
    # a NULL source stays None: nothing is computed from the kind any more
    assert leaf({"content_kind": "pcn", "leaf_source": None}) == ("pcn", None, None)
    assert leaf({"content_kind": "pcn"}) == ("pcn", None, None)


def test_a_corrected_leaf_names_who_corrected_it():
    row = {"content_kind": "pcn", "leaf_source": "corrected", "leaf_set_by": "alice"}
    assert leaf(row) == ("pcn", "corrected", "alice")
    # leaf_set_by of a non-corrected source is not a corrector
    assert leaf({"content_kind": "pcn", "leaf_source": "title", "leaf_set_by": "svc:doc-tools"}) == (
        "pcn", "title", None)


@pytest.mark.parametrize("ck", ["pdf", "sustainment", None, "ecn"])
def test_a_kind_that_is_not_a_leaf_is_no_leaf(ck):
    assert leaf({"content_kind": ck, "leaf_source": "title"})[0] is None


def test_none_row_reads_nothing():
    assert leaf(None) == (None, None, None)


def _body(monkeypatch, content_kind, **row_over):
    review = {**REVIEW, **{k: v for k, v in row_over.pop("review", {}).items()}}
    fake = FakeS3(_objects(review=review))
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    _gate(monkeypatch, row=_row(content_kind=content_kind, **row_over))
    _as(monkeypatch, "alice@example.com")
    r = _get(f"/ingest/{ID}/extraction")
    assert r.status_code == 200, r.text
    return r.json()


def test_route_a_pdf_row_with_a_confident_title_still_shows_no_leaf(monkeypatch):
    """The card no longer derives a leaf from review.json."""
    b = _body(monkeypatch, "pdf", review={"doc_type": "PDN", "doc_type_source": "title"})
    assert b["leaf"] is None and b["leaf_source"] is None and b["corrected_by"] is None
    assert b["content_kind"] == "pdf"


def test_route_a_pre_203_style_row_with_no_source_shows_the_leaf_and_a_null_source(monkeypatch):
    b = _body(monkeypatch, "pcn")
    assert b["leaf"] == "pcn" and b["leaf_source"] is None


def test_route_a_declared_leaf_reads_declared(monkeypatch):
    b = _body(monkeypatch, "pcn", leaf_source="declared")
    assert b["leaf"] == "pcn" and b["leaf_source"] == "declared" and b["corrected_by"] is None


def test_route_a_title_leaf_on_the_row_reads_title(monkeypatch):
    b = _body(monkeypatch, "pdn", leaf_source="title", leaf_set_by="svc:doc-tools")
    assert b["leaf"] == "pdn" and b["leaf_source"] == "title" and b["corrected_by"] is None


def test_route_a_corrected_leaf_carries_corrected_by(monkeypatch):
    b = _body(monkeypatch, "pcn", leaf_source="corrected", leaf_set_by="bob@example.com")
    assert b["leaf"] == "pcn" and b["leaf_source"] == "corrected"
    assert b["corrected_by"] == "bob@example.com"
