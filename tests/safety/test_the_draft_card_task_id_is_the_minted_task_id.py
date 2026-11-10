"""The draft card's `review_request.task_id` is the runner's, never Engine S's (ruled 2026-11-07).

Chris's ruling: `task_id` is taken from the runner that mints the task. The card OMITS the field
until the task exists (`task_id` optional, absent-not-null, the same rule as `note`) and is filled
from the runner's answer on creation. Engine S copies no id format. The case key is the owner's
too (`acceptance_request.with_minted_ids` stamps it where the engine's response is read), so the
engine builds neither string: this file replaces the two seals that pinned the mirror.

Arms
  a  before creation the drafted card has NO `task_id` key (absent, not None);
  b  after creation the card carries exactly the id the runner answered. The double answers a
     random token Engine S could not derive, so a copied format cannot pass. Lane 1 fills the card
     (and the dispatch record) from the runner's `opened_task` answer;
  c  no format copy: no string literal in the engine builds a task id or case key, found by
     FORM (the `risk-acceptance-` head, a `~<n>` instance suffix, a `:<step>` tail), with a
     positive control against a planted copy.
"""
from __future__ import annotations

import ast
import asyncio
import re
import secrets
import sys
from pathlib import Path

import pytest

from ._engine_extra import requires_rdflib

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
_ENGINE = _ROOT / "agent_fleet" / "safety_agent"
_HAZARD = "HAZ-1003"
_REQUESTER = "requester@example.org"


def _card():
    from agent_fleet.safety_agent import measures
    out = measures.draft_risk_assessment(hazard_id=_HAZARD)
    assert "review_request" in out, f"the fixture hazard drafted no card: {str(out)[:120]}"
    return out["review_request"]


# --------------------------------------------------------------------------- a: absent, not null
@requires_rdflib
def test_the_drafted_card_has_no_task_id_key_absent_not_none():
    card = _card()
    assert "task_id" not in card, f"task_id is present: {card.get('task_id')!r}"


# --------------------------------------------------------------------------- b: the runner's id
class _Runner:
    """A double for the case runner's ingress. It answers a task id nobody can derive."""

    def __init__(self, token):
        self.token, self.posts = token, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.posts.append(url)
        return self

    def json(self):
        return {"task_id": self.token}

    def raise_for_status(self):
        return None


@requires_rdflib
def test_after_creation_the_card_carries_exactly_the_id_the_runner_answered(monkeypatch):
    import iagent.gateway as gw
    from iagent_pure import acceptance_request as ar
    token = "tok-" + secrets.token_hex(12)
    runner = _Runner(token)
    monkeypatch.setattr(gw.httpx, "AsyncClient", runner)
    rr = ar.with_minted_ids(_card())
    bundle = {"id": "urn:li:answerArtifact:test", "resolved_intent": {},
              "produced_for": {"authz_id": _REQUESTER}}
    err = asyncio.run(gw._open_safety_acceptance(bundle, rr, path="direct", stage_kind="x"))
    assert err is None and runner.posts, "the acceptance did not open"
    [rec] = bundle["resolved_intent"]["acceptance_dispatched"]
    assert rec.get("task_id") == token
    assert rr["task_id"] == token


# --------------------------------------------------------------------------- c: no format copy
_FORMS = (re.compile(r"risk-acceptance-"), re.compile(r"~(\d|\{)"), re.compile(r":(acceptance|concurrence)\b"))


def _format_copies(source: str):
    """String literals, f-string parts included, docstrings excluded, that match an id FORM."""
    tree = ast.parse(source)
    skip = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
            and any(f.search(n.value) for f in _FORMS)]


def test_the_engine_builds_no_task_id_or_case_key_string():
    files = sorted(_ENGINE.glob("*.py"))
    assert files, "no engine source found: instrument failure"
    hits = {f.name: _format_copies(f.read_text(encoding="utf-8")) for f in files}
    assert not {k: v for k, v in hits.items() if v}, hits


def test_control_the_detector_finds_a_planted_copy_of_each_form():
    for planted in ('x = f"risk-acceptance-{h}"', 'x = f"{c}~1:{s}"', 'x = case + "~1"',
                    'x = wf + ":acceptance"'):
        assert _format_copies(planted), planted
    assert not _format_copies('"""risk-acceptance-{h} in a docstring"""\nx = "plain"')
