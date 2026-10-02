"""`explain` is dispatched under the asker's own identity, not svc:supervisor.

engine-docs' page gate (dark until ENABLE_AGENTIC_AUTH) withholds a page unless the ASKER may
invoke every verb the page explains. The asker it sees is whoever the supervisor dispatched as.
As svc:supervisor the gate would decide about the service, so it would grant or deny for
everyone at once. This seals the prerequisite before the gate is turned on.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest


@pytest.mark.parametrize("verb_iri", [
    "mesh:explain",
    "https://w3id.org/iagent/mesh#explain",
    "explain",
])
def test_explain_needs_the_callers_identity_in_every_spelling(verb_iri):
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    assert _verb_needs_caller_identity({"verb_iri": verb_iri}), (
        f"{verb_iri} would dispatch as svc:supervisor, so the docs page gate would decide "
        f"about the service instead of the person asking"
    )


def test_the_verb_engine_docs_registers_is_the_one_listed():
    """The control on the NAME: the set holds a local name and engine-docs registers an IRI.
    Read the registered verb from engine-docs' source rather than restating it, so a rename
    there reds here instead of silently dropping the caller's identity."""
    import re

    src = (Path(__file__).resolve().parents[2] / "agent_fleet" / "docs_agent" / "main.py").read_text(
        encoding="utf-8")
    registered = set(re.findall(r'"verb":\s*"(mesh:[A-Za-z]+)"', src))
    assert registered, "no `\"verb\": \"mesh:...\"` entry found in engine-docs' VERBS"
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    missing = sorted(v for v in registered if not _verb_needs_caller_identity({"verb_iri": v}))
    assert not missing, f"engine-docs registers {missing}, which dispatch as svc:supervisor"


def test_a_verb_not_listed_still_dispatches_as_the_service():
    """The other side: the allow-list did not become a catch-all."""
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    assert not _verb_needs_caller_identity({"verb_iri": "mesh:finProgramBrief"})
    assert not _verb_needs_caller_identity({"verb_iri": "mesh:explainer"})
