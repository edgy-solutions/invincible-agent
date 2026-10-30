"""Opt-in fixture: treat every kind as ungated at the ingest door.

The files that use this test ingest semantics (routes, leaves, delegates, sniffing), not the
can_drop door. The door is sealed in
tests/security/test_a_restricted_kind_is_dropped_only_by_its_grantees.py. Each file opts in
explicitly with `pytestmark = pytest.mark.usefixtures("can_drop_open")`; this fixture is never
autouse and is never named in conftest.py.

The gateway reads the name as `human_tasks.can_drop_refusal`, which looks up
`capability_object_exists` in the `human_tasks` module globals. So the attribute is patched on
that module object: `src.iagent.human_tasks` (what the tests import through), and
`iagent.human_tasks` too when it is loaded, since one module under two names is two objects.
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def can_drop_open(monkeypatch):
    from src.iagent import human_tasks as ht

    monkeypatch.setattr(ht, "capability_object_exists", lambda capability: False)
    other = sys.modules.get("iagent.human_tasks")
    if other is not None and other is not ht:
        monkeypatch.setattr(other, "capability_object_exists", lambda capability: False)
    yield
