"""`_fill_slots_from_query` forwards the ROUTE'S OWN CLASS, so engine-o's DOCS pool gate can
fire even when the caller's acting domain is not DOCS.

MEASURED 2026-09-30: the UI sends domains=['MESH'] (cortex hides DOCS from the picker).
`/resolve` routed "how do I add an engine" to subject mesh:DocPage at 0.97, but nothing carried
that class onward to `/fill_slots` — the supervisor had it in `telemetry["subject_uri"]` (see
the `predicate_routing_score` log line a few lines above the call site in
`execute_subtask`) and never forwarded it. `/fill_slots` gated on `_acts_in_docs(['MESH'])`,
false, and the subject pool never ran.

THIS FILE SEALS THE WIRE ONLY: that `subject_uri` leaves this process on the POST body. What
engine-o does with it is `tests/docs/test_the_docs_subject_pool_binds_the_page.py`'s job.

Run: uv run --frozen pytest tests/routing/test_fill_slots_forwards_the_routed_subject.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.defs.dynamic_supervisor import _fill_slots_from_query  # noqa: E402
from iagent.defs import dynamic_supervisor as _ds  # noqa: E402

_DOCPAGE = "http://invincible-agent/mesh#DocPage"


class _Log:
    def warning(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass


class _Context:
    log = _Log()


class _Resp:
    status_code = 200

    def json(self):
        return {"slots": {}, "resolution": {}}


def test_fill_slots_from_query_forwards_the_routed_subject_uri(monkeypatch):
    posted: dict = {}

    def _fake_post(url, json=None, timeout=None):
        posted.update(json or {})
        return _Resp()

    monkeypatch.setattr(_ds.requests, "post", _fake_post)
    _fill_slots_from_query(
        _Context(),
        query="how do I add an engine",
        verb_iri="mesh:explain",
        declarations=[],
        acting_domains=["MESH"],
        subject_uri=_DOCPAGE,
    )
    assert posted.get("subject_uri") == _DOCPAGE, posted


def test_fill_slots_from_query_defaults_subject_uri_to_empty(monkeypatch):
    """A caller that does not name a routed class — same default `FillSlotsRequest` uses."""
    posted: dict = {}

    def _fake_post(url, json=None, timeout=None):
        posted.update(json or {})
        return _Resp()

    monkeypatch.setattr(_ds.requests, "post", _fake_post)
    _fill_slots_from_query(
        _Context(),
        query="how do I add an engine",
        verb_iri="mesh:explain",
        declarations=[],
        acting_domains=["MESH"],
    )
    assert posted.get("subject_uri") == "", posted
