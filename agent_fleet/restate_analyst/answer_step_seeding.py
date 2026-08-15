"""Answer -> workflow-step seeding — the PURE core (ADR-0028 Use-3, ADR-0029 Slice 4).

Turn a Q&A answer (an SPO op that ran) into a workflow step (an SPO tuple). Native: the
seed extracts the (subject, verb) provenance the answer already carries (the gateway's
``routing`` — src/iagent/gateway.py) and produces an ``spo_operation`` step. Pure, no network
— the analogue of the Slice-2 enforcement funnel. Design: docs/reference/slice-4-answer-step-seeding.md.

Three guarantees:
  * NOT SEEDABLE from a fallback / ungrounded answer — refuse honestly, never fabricate a
    non-routable tuple into a durable workflow.
  * NOT SEEDABLE from a WEAK-PROVENANCE answer — provenance includes HOW the answer resolved,
    and an answer that came back *plausible but weak* (engine-o's recall-override guard: the
    classifier overrode strong vector recall with no phone-book confirmation) must not seed. A
    wrong answer is transient; a wrong answer SEEDED into a repeatable workflow is the error made
    durable and re-executable. The rule falls out of the slice's own principle — weak provenance
    shouldn't seed.
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

# The recall-override guard (agent_fleet/ontology_service/recall_guard.py) caps a weak-path
# answer's reported confidence at exactly this ceiling. Seeding treats a subject confidence AT OR
# BELOW it as weak provenance. Kept in sync with recall_guard._RECALL_OVERRIDE_CEIL by intent.
_WEAK_CONFIDENCE_CEIL = 0.50


def _is_weak_provenance(about: dict, *, confidence_floor: float) -> Optional[str]:
    """Return a refusal reason when the answer resolved via the WEAK path, else None.

    Two discriminators, deliberately BOTH — one precise, one live:

    * ``about.recall_override`` — engine-o's explicit honest-degradation flag. PRECISE, but
      ⚠️ DORMANT-UNTIL-WIRED: engine-o emits ``provenance.recall_override`` yet the supervisor's
      ``_resolve_subject`` DISCARDS it (src/iagent/defs/dynamic_supervisor.py — a
      [[resolution-discard-pattern]] instance, sitting beside two sibling fields whose own
      comments name the pattern), so it does not yet reach ``routing.about``. Threading it is the
      producer-side fix that lands with the S4 driver (design §3.1). Until then this branch
      cannot fire — which is exactly why it is not the ONLY gate.
    * ``about.confidence <= confidence_floor`` — the LIVE proxy today. The guard caps the weak
      path at 0.50 and THAT cap DOES propagate (confidence_score -> subject_confidence ->
      routing.about.confidence), so a capped/low subject confidence is observable now. A genuinely
      low-confidence answer failing this too is correct: a shaky answer should not seed a durable,
      re-executable workflow regardless of the mechanism that made it shaky.

    Absent confidence (older materializations that predate the field) is NOT treated as weak — the
    flag remains the precise signal for those once threaded; we do not fabricate weakness."""
    if about.get("recall_override"):
        return "answer resolved via the WEAK path (recall_override) — weak provenance does not seed"
    conf = about.get("confidence")
    if conf is not None and float(conf) <= confidence_floor:
        return (f"answer subject confidence {float(conf):.2f} <= {confidence_floor:.2f} "
                f"(weak/recall-override-capped provenance) — does not seed")
    return None


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
    confidence_floor: float = _WEAK_CONFIDENCE_CEIL,
) -> tuple[Optional[dict], Optional[str]]:
    """Extract an ``spo_operation`` step from an answer's ``routing`` provenance.

    Returns ``(step, None)`` for a grounded, non-fallback, strong-provenance answer; ``(None,
    reason)`` otherwise — so a UI can say WHY an answer can't become a step (never a fabricated
    step). ``expected_output`` is the verb's FIXED output type (ADR-0030) when provided — NOT the
    answer's rendered content (that is this run's projection of the type, not the type)."""
    r = routing or {}
    if r.get("fallback"):
        return None, "answer was a generalist fallback — no grounded (subject, verb) to seed"
    about = r.get("about") or {}
    subject = str(about.get("uri") or "").strip()
    verb = str((r.get("action") or {}).get("iri") or "").strip()
    if subject in _UNGROUNDED:
        return None, "answer subject not grounded (UNKNOWN) — nothing to seed"
    if verb in _UNGROUNDED:
        return None, "answer verb not grounded (UNKNOWN) — nothing to seed"
    # Weak provenance does not seed — a plausible-but-weak answer wrong-seeded into a durable
    # workflow makes the error re-executable (design §2.1). This gate is ANDed after grounding:
    # the subject/verb are present but resolved via the weak path.
    weak = _is_weak_provenance(about, confidence_floor=confidence_floor)
    if weak:
        return None, weak
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
    confidence_floor: float = _WEAK_CONFIDENCE_CEIL,
) -> dict:
    """Seed a step AND enforce it against the SEEDER's authorized sets — an answer is provenance,
    not authority (design §3). Raises ``ValueError`` when the answer isn't seedable
    (fallback/ungrounded) and ``PickRefused`` when the seeded (subject, verb) isn't eligible for
    the seeder — exactly as if the seeder had authored the step by hand. Seeding is a SOURCE,
    never a bypass. ``authorized_subjects``/``authorized_verbs`` are the seeder's CURRENT sets
    (Slice-2's ``authorized_operation_subjects`` + ``authorized_verbs`` for the subject)."""
    step, reason = seed_step_from_answer(
        routing, verb_output_uri=verb_output_uri, step_id=step_id, confidence_floor=confidence_floor)
    if step is None:
        raise ValueError(reason)
    # Inherit the enforcement — the seeded subject + verb must be eligible for the SEEDER NOW.
    validate_pick(step["subject"], authorized_subjects, key="uri")
    validate_pick(step["verb"], authorized_verbs, key="verb_iri")
    return step
