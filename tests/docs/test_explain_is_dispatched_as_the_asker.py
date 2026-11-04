"""`explain` is dispatched under the asker's own identity, not svc:supervisor.

engine-docs' page gate (dark until ENABLE_AGENTIC_AUTH) withholds a page unless the ASKER may
invoke every verb the page explains. The asker it sees is whoever the supervisor dispatched as.
As svc:supervisor the gate would decide about the service, so it would grant or deny for
everyone at once.

Since the architect ruling of 2026-11-02 the dispatch forwards the caller on every verb for a
run that has a person, so this no longer reads a per-verb set: the real dispatch is driven in
tests/identity/test_the_dispatch_forwards_the_caller.py. What stays here is the control on the
NAME engine-docs registers, so that `explain` is still a verb the supervisor can route to.
"""
from __future__ import annotations

import re
from pathlib import Path


def test_engine_docs_still_registers_the_explain_verb():
    src = (Path(__file__).resolve().parents[2] / "agent_fleet" / "docs_agent" / "main.py").read_text(
        encoding="utf-8")
    registered = set(re.findall(r'"verb":\s*"(mesh:[A-Za-z]+)"', src))
    assert "mesh:explain" in registered, sorted(registered)
