"""A picked measure's message is a LABEL: with `message_is_label` the supervisor never runs the
slot filler on it. The control: the same config without the flag does run it.

Drives the real `execute_subtask` (routing stubbed to a matched verb that declares a slot, the
run stopped right after the `subtask_slots_decision` materialization) with `_fill_slots_from_query`
patched. The doubles' REQUESTS are what is asserted: whether the filler was called.

Run: uv run pytest tests/routing/test_a_label_is_never_slot_filled.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

_ASSET = "subtask_slots_decision"


class _Stop(BaseException):
    """Aborts the routed path right after the slots decision is materialized."""


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    run_id = "run-1"
    log = _Log()

    def get_mapping_key(self):
        return "task_0"

    def log_event(self, ev):
        if list(ev.asset_key.path) == [_ASSET]:
            raise _Stop()


def _cfg(label: bool):
    return SimpleNamespace(
        user_query="Some measure", user_persona="DATA_ENGINEER", user_email="alice@example.com",
        trace_id="t", session_id="s", thread_id="th", entitled_domains=["MAINTENANCE"],
        entity_refs=None, pre_resolved=None, predicate_fallback_score_threshold=0.5,
        slots=None, spoken_slot="", spoken_answer="", bound_slots=None,
        message_is_label=label,
    )


_PRED = {"verb_iri": "mesh:goodVerb", "score": 0.9, "endpoint": "http://x",
         "owner_persona": "DATA_ENGINEER",
         "slots": [{"name": "program_id", "class_uri": "http://example.invalid/ont#Thing",
                    "mandatory": True}]}
_TEL = {"fallback_reason": "", "subject_uri": "mesh:Lot", "subject_instance_id": "",
        "subject_instance_label": ""}


def _drive(monkeypatch, label: bool) -> list:
    calls: list = []

    def _filler(*a, **k):
        calls.append(k)
        return SimpleNamespace(slots={}, resolution={}, fill_slots="")

    monkeypatch.setattr(ds, "_fill_slots_from_query", _filler)
    monkeypatch.setattr(ds, "_classify_route",
                        lambda *a, **k: (ds._ROUTING_MATCHED, dict(_PRED), dict(_TEL)))
    monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
    with pytest.raises(_Stop):
        ds.execute_subtask.compute_fn.decorated_fn(
            _Ctx(), _cfg(label), {"sub_query": "Some measure"})
    return calls


def test_a_label_is_never_slot_filled(monkeypatch):
    assert _drive(monkeypatch, label=True) == [], "the slot filler ran on a label"


def test_the_CONTROL_the_same_config_without_the_flag_slot_fills(monkeypatch):
    calls = _drive(monkeypatch, label=False)
    assert len(calls) == 1 and calls[0]["query"] == "Some measure"
