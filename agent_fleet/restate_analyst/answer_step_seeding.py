"""Answer -> workflow-step seeding — the PURE core (ADR-0028 Use-3, ADR-0029 Slice 4).

Turn a Q&A answer (an SPO op that ran) into a workflow step (an SPO tuple). Native: the
seed extracts the (subject, verb) provenance the answer already carries (the gateway's
``routing`` — src/iagent/gateway.py) and produces an ``spo_operation`` step. Pure, no network
— the analogue of the Slice-2 enforcement funnel. Design: docs/plans/slice-4-answer-step-seeding.md.

Two guarantees:
  * NOT SEEDABLE from a fallback / ungrounded answer — refuse honestly, never fabricate a
    non-routable tuple into a durable workflow.
  * INHERITS ENFORCEMENT — a seeded step is validated against the SEEDER's authorized sets
    (select-from-authorized-set). An answer is provenance, not authority; seeding is an
    alternate SOURCE, never an authz bypass.
"""
from __future__ import annotations

from typing import Optional

try:  # same lazy-import dance as the other restate_analyst cores
    from spo_interview import validate_pick, PickRefused  # type: ignore[no-redef]  # noqa: F401
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.spo_interview import validate_pick, PickRefused  # noqa: F401

_UNGROUNDED = {"", "UNKNOWN"}


def _seed_step_id(subject_uri: str, verb_iri: str) -> str:
    """A readable step id from the SPO local names, e.g. 'lookupOwnership_Dataset'."""
    subj = subject_uri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    verb = verb_iri.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return f"{verb}_{subj}" if (verb and subj) else (verb or subj or "spo_step")


def seed_step_from_answer(
    routing: dict,
    *,
    verb_output_uri: Optional[str] = None,
    step_id: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Extract an ``spo_operation`` step from an answer's ``routing`` provenance.

    Returns ``(step, None)`` for a grounded, non-fallback answer; ``(None, reason)`` otherwise —
    so a UI can say WHY an answer can't become a step (never a fabricated step). ``expected_output``
    is the verb's FIXED output type (ADR-0030) when provided — NOT the answer's rendered content
    (that is this run's projection of the type, not the type)."""
    r = routing or {}
    if r.get("fallback"):
        return None, "answer was a generalist fallback — no grounded (subject, verb) to seed"
    subject = str((r.get("about") or {}).get("uri") or "").strip()
    verb = str((r.get("action") or {}).get("iri") or "").strip()
    if subject in _UNGROUNDED:
        return None, "answer subject not grounded (UNKNOWN) — nothing to seed"
    if verb in _UNGROUNDED:
        return None, "answer verb not grounded (UNKNOWN) — nothing to seed"
    step: dict = {
        "kind": "spo_operation",
        "id": step_id or _seed_step_id(subject, verb),
        "subject": subject,
        "verb": verb,
    }
    if verb_output_uri:
        step["expected_output"] = verb_output_uri
    return step, None


def seed_and_validate_step(
    routing: dict,
    *,
    authorized_subjects: list[dict],
    authorized_verbs: list[dict],
    verb_output_uri: Optional[str] = None,
    step_id: Optional[str] = None,
) -> dict:
    """Seed a step AND enforce it against the SEEDER's authorized sets — an answer is provenance,
    not authority (design §3). Raises ``ValueError`` when the answer isn't seedable
    (fallback/ungrounded) and ``PickRefused`` when the seeded (subject, verb) isn't eligible for
    the seeder — exactly as if the seeder had authored the step by hand. Seeding is a SOURCE,
    never a bypass. ``authorized_subjects``/``authorized_verbs`` are the seeder's CURRENT sets
    (Slice-2's ``authorized_operation_subjects`` + ``authorized_verbs`` for the subject)."""
    step, reason = seed_step_from_answer(routing, verb_output_uri=verb_output_uri, step_id=step_id)
    if step is None:
        raise ValueError(reason)
    # Inherit the enforcement — the seeded subject + verb must be eligible for the SEEDER NOW.
    validate_pick(step["subject"], authorized_subjects, key="uri")
    validate_pick(step["verb"], authorized_verbs, key="verb_iri")
    return step
