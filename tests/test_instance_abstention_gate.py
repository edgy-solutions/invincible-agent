"""ADR-0026 abstention-gate arc — the structural instance-not-found gate.

THE BUG (see [[project_abstention_gate_llm_mediated]]): when the LLM
extracted an ``instance_identifier`` the phone book couldn't resolve, the
resolver fell back to the LLM's CLASS guess unconditionally. So whether a
query naming a NON-EXISTENT specific individual (``foo.bar.zzz_nope``)
abstained or got a confident-wrong class answer rode on LLM sampling — a
no-margin, LLM-mediated gate.

THE FIX: a STRUCTURAL gate (never a second LLM judgment) over two
deterministic signals — the identifier's FORM and the recorded
resolution FACT (``instance_match``).

THE WHOLE VERIFICATION is this two-fixture pair (the arc's STOP
condition):
  1. ``foo.bar.zzz_nope`` (instance-shaped, providers returned empty)
     → abstains with ``instance_not_found``.
  2. a generic term the extractor over-eagerly flagged (NOT
     instance-shaped) → returns None, i.e. keeps the class contest
     (the intentional class-fallback still resolves).

Hermetic: the gate is a pure function. No cluster, no LLM, no network.

Run:
    uv run pytest tests/test_instance_abstention_gate.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The gate lives with the (already pure) instance-resolution decision
# table so the form-check primitive has ONE home — Hole 2
# ([[resolve-instance-provider-gap]]) draws the same primitive from here.
_ONTO = Path(__file__).resolve().parent.parent / "agent_fleet" / "ontology_service"
if str(_ONTO) not in sys.path:
    sys.path.insert(0, str(_ONTO))

from instance_resolution import (  # noqa: E402
    decide_instance_abstention,
    instance_not_found_message,
    is_instance_shaped,
)


# ---------------------------------------------------------------------------
# THE TWO-FIXTURE STOP CONDITION
# ---------------------------------------------------------------------------
def test_named_nonexistent_instance_abstains_structurally():
    """FIXTURE 1 — ``foo.bar.zzz_nope`` is instance-shaped (dotted) and the
    providers were asked and returned empty. The gate must abstain with
    ``instance_not_found`` — WITHOUT any LLM in the loop. Before this
    gate, the call site fell back to the LLM's class guess and the
    abstention depended on LLM sampling."""
    reason = decide_instance_abstention(
        identifier="foo.bar.zzz_nope",
        instance_subject=None,       # phone book found nothing
        instance_match="empty",      # providers answered cleanly: no match
    )
    assert reason == "instance_not_found", (
        "a specific named individual the registry genuinely doesn't know "
        "must abstain structurally, not ride on the LLM's class guess"
    )


def test_generic_term_falls_back_to_class_contest():
    """FIXTURE 2 — a generic term the extractor over-eagerly flagged as an
    identifier is NOT instance-shaped. The gate must return None so the
    LLM's class contest still resolves it. Abstaining here would wrongly
    refuse a valid class query — the false-positive we must not produce."""
    reason = decide_instance_abstention(
        identifier="mechanics",      # a plain generic word, no structure
        instance_subject=None,
        instance_match="empty",
    )
    assert reason is None, (
        "a generic term must class-fallback (resolve), never abstain — "
        "the discriminator is FORM, and 'mechanics' has no instance form"
    )


# ---------------------------------------------------------------------------
# The two deterministic signals, pinned independently.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("token", [
    "foo.bar.zzz_nope",              # dotted qualified name
    "urn:li:dataset:(x,y,z)",        # namespace-qualified urn
    "DMC-AE-A-00",                   # coded ALLCAPS-hyphen token
    "asset1234",                     # embedded digits
])
def test_instance_shaped_true_for_structured_tokens(token):
    assert is_instance_shaped(token) is True


@pytest.mark.parametrize("token", [
    "mechanics",                     # plain generic word
    "customer records",             # natural-language phrase
    "aircraft engine",               # multi-word generic
    "",                              # empty
    "   ",                           # whitespace only
])
def test_instance_shaped_false_for_generic_terms(token):
    assert is_instance_shaped(token) is False


# ---------------------------------------------------------------------------
# Infra non-answers must NOT be reported as not-found (the honest-"no"
# guard: timeout/error/no_providers is "we didn't get a trustworthy no",
# not "the registry knows there's no such thing").
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("infra_match", ["timeout", "error", "no_providers"])
def test_infra_non_answer_does_not_abstain_as_not_found(infra_match):
    reason = decide_instance_abstention(
        identifier="foo.bar.zzz_nope",   # instance-shaped, but...
        instance_subject=None,
        instance_match=infra_match,      # ...we never got a clean "no"
    )
    assert reason is None, (
        f"instance_match={infra_match!r} is an infra non-answer; telling "
        f"the user 'no provider knows it' would misreport an outage as a "
        f"not-found"
    )


def test_resolved_instance_is_not_an_abstention():
    """When the phone book DID resolve, the gate never fires."""
    reason = decide_instance_abstention(
        identifier="foo.bar.zzz_nope",
        instance_subject="idp:SomeClass",   # resolved
        instance_match="exact",
    )
    assert reason is None


def test_abstention_message_is_actionable():
    """Honest-empty is only honest if it tells the user what to do: the
    message must name the exact token and offer a next step."""
    msg = instance_not_found_message("foo.bar.zzz_nope")
    assert "foo.bar.zzz_nope" in msg
    # names a concrete next action, not a bare 'unknown'
    assert "category" in msg.lower() or "identifier" in msg.lower()
