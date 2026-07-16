"""SPO interview — the PURE core (ADR-0029 Slice 2, design: docs/plans/slice-2-spo-interview.md).

Re-aims the interrogator PATTERN (mesh-informed select-from-authorized-set) at the
SPO ``WorkflowDefinition`` model, superseding the BPMN-fused machinery. This module is
the enforceable, testable core — the analogue of ``spo_step_executor.py``: no Restate,
no live LLM. A thin BAML/VirtualObject driver (built next) wires the conversation.

What makes this stronger than the old BPMN interview (all three, per the design doc):

* **The verb question** — the old interview asked subject (ontology class) + object
  (data source) but NEVER a verb. Here ``authorized_verbs`` sources the predicate from
  Engine O ``/find_compatible_verbs``, so the offered verbs are structurally eligible
  for the chosen subject BY CONSTRUCTION (Decision A: un-doomable for structural modes).
* **Server-side pick validation** — the old exact-match constraint was prompt-only.
  ``validate_pick`` REFUSES a pick not in the computed authorized set (select-from-
  authorized-set *enforced*, not merely prompted).
* **Termination = the definition VALIDATES** — the old interview ended on an LLM
  ``is_ready_to_compile`` flag. ``try_finalize`` ends when ``WorkflowDefinition``
  validates against its schema (server-side, deterministic — Decision B).

Permission is ADVISORY at authoring (Decision A): each offered verb is annotated with
what the *initiator* will need; the actual check is pre-flight (per-run) + dispatch
(per-step), against the initiator, never the author. A definition is authored ONCE and
run by MANY, so it is never bound to the author's grants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import yaml

try:  # same lazy-import dance as spo_step_executor / _run_definition
    from workflow_definition import WorkflowDefinition  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_definition import WorkflowDefinition

ENGINE_O_URL_DEFAULT = "http://iagent-engine-o:8084"
_HTTP_TIMEOUT = 15.0


class PickRefused(ValueError):
    """A pick was not in the computed authorized set — select-from-authorized-set is
    ENFORCED server-side, not left to the model's good behavior."""


# ---------------------------------------------------------------------------
# Authorized-set computation (the "keeper" pattern, now with the verb question)
# ---------------------------------------------------------------------------

def _parse_classes(payload: dict) -> list[dict]:
    """PURE: Engine O ``/classes`` response -> the authorized SUBJECT set. Each entry
    keeps ``uri`` (the pick key) + ``label`` (for presentation)."""
    out = []
    for c in (payload or {}).get("classes") or []:
        uri = str(c.get("uri") or "").strip()
        if uri:
            out.append({"uri": uri, "label": str(c.get("label") or "")})
    return out


def _parse_verbs(payload: dict) -> list[dict]:
    """PURE: Engine O ``/find_compatible_verbs`` response -> the authorized VERB set for
    a subject, each annotated with an ADVISORY permission requirement (Decision A). The
    verb set is already structural (domain ∩ arity ∩ argument-fit) — the server filtered
    it; here we surface, per verb, what the eventual INITIATOR will need."""
    out = []
    for v in (payload or {}).get("verbs") or []:
        iri = str(v.get("verb_iri") or "").strip()
        if not iri:
            continue
        out.append({
            "verb_iri": iri,
            "verb_local": str(v.get("verb_local") or ""),
            "output_uri": str(v.get("output_uri") or ""),  # -> expected_output, auto-derived
            "endpoint_url": str(v.get("endpoint_url") or ""),
            # ADVISORY ONLY — never a gate here; the initiator is checked at pre-flight
            # (per-run) and dispatch (per-step). Authoring does not bind the author's grants.
            "requires_advisory": {
                "domains": list(v.get("domains") or []),
                "owner_persona": v.get("owner_persona"),
            },
        })
    return out


def authorized_subjects(
    caller_email: str,
    *,
    engine_o_url: str = ENGINE_O_URL_DEFAULT,
    domain: str = "MAINTENANCE",
) -> list[dict]:
    """Fetch the authorized SUBJECT set (ontology classes) from Engine O, SCOPED TO WHAT
    THE AUTHOR MAY SEE. ``caller_email`` is threaded so Engine O's per-IRI ``can_view``
    compartment filter (the sealed ontology-visibility gate) bounds the menu: an author
    without a compartment grant gets a menu WITHOUT that compartment's classes.

    This threading is LOAD-BEARING for the self-gating property (design §2 Decision A):
    secrecy (compartments) gates the interview's menu automatically via the caller's
    identity — the interview can only author over what the author can SEE — so no separate
    ``can_author`` gate is needed for the compartmented case. Drop the identity and the
    interview would leak compartmented vocabulary into the menu.

    REQUIREMENT ON THE SUBJECT-SOURCE ENDPOINT (design §7): it MUST apply ``can_view`` for
    ``caller_email``. The current ``/classes`` endpoint does NOT — it returns raw SPARQL
    rows ignoring identity, AND returns empty against the un-ingested Fuseki store. So the
    next increment must route the subject menu through a ``can_view``-applying,
    live-ontology-derived source; identity is threaded HERE now so the property holds the
    moment the source is correct. The composed-path seal proves it (author without a
    compartment grant → menu without that compartment's classes — the interview's own
    discriminating seal, same shape as Engine O's)."""
    r = httpx.post(
        f"{engine_o_url}/classes",
        json={"query": "", "domain": domain, "user_email": caller_email},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return _parse_classes(r.json())


def authorized_verbs(
    subject_uri: str,
    *,
    workflow_domain: Optional[str] = None,
    engine_o_url: str = ENGINE_O_URL_DEFAULT,
) -> list[dict]:
    """Fetch the authorized VERB set for ``subject_uri`` — the predicate question the old
    interview never asked. Domain scope is the WORKFLOW's declared domain (Decision A):
    NOT the author's entitlements. ``workflow_domain=None`` -> structural-only (all domains)."""
    if not subject_uri or subject_uri == "UNKNOWN":
        raise ValueError(f"cannot elicit verbs for an unresolved subject ({subject_uri!r})")
    body: dict[str, Any] = {"subject_uri": subject_uri, "max_hops": 5}
    body["entitled_domains"] = [workflow_domain] if workflow_domain else []
    r = httpx.post(f"{engine_o_url}/find_compatible_verbs", json=body, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    return _parse_verbs(r.json())


def validate_pick(pick: str, authorized_set: list[dict], *, key: str = "uri") -> str:
    """SERVER-SIDE select-from-authorized-set enforcement (the old constraint was
    prompt-only). Returns the pick if it EXACTLY matches an entry's ``key``; else raises
    ``PickRefused`` naming the closest options (suggest-closest, but the refusal is hard —
    the model cannot smuggle a hallucinated pick past this)."""
    allowed = [str(e.get(key) or "") for e in authorized_set]
    if pick in allowed:
        return pick
    closest = [a for a in allowed if pick and (pick.lower() in a.lower() or a.lower() in pick.lower())]
    raise PickRefused(
        f"{pick!r} is not in the authorized set — pick an exact match. "
        f"{'Closest: ' + ', '.join(closest[:3]) if closest else 'No close match.'}"
    )


# ---------------------------------------------------------------------------
# Interview state + termination-on-validity (Decision B)
# ---------------------------------------------------------------------------

@dataclass
class InterviewState:
    """The accumulating definition. Steps are appended once complete-for-their-kind; the
    WHOLE thing is authoritative only when ``try_finalize`` model_validates it."""
    id: Optional[str] = None
    name: Optional[str] = None
    classification: Optional[str] = None   # the workflow's declared domain -> verb scope
    participants: list[dict] = field(default_factory=list)
    domain_stages: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    observable_state: Optional[dict] = None

    def _assemble(self) -> dict:
        d: dict[str, Any] = {"id": self.id, "name": self.name, "steps": list(self.steps)}
        if self.classification is not None:
            d["classification"] = self.classification
        if self.participants:
            d["participants"] = self.participants
        if self.domain_stages:
            d["domain_stages"] = self.domain_stages
        if self.observable_state is not None:
            d["observable_state"] = self.observable_state
        return d


def try_finalize(state: InterviewState) -> tuple[Optional[WorkflowDefinition], list[str]]:
    """TERMINATION = the definition VALIDATES (Decision B), server-side. Returns
    ``(definition, [])`` when the accumulated state is a valid ``WorkflowDefinition``;
    otherwise ``(None, gaps)`` where ``gaps`` are human-readable missing/invalid fields
    that drive the next question. The schema's required fields ARE the completeness
    predicate — an LLM cannot declare 'done' past a definition that doesn't validate."""
    from pydantic import ValidationError
    try:
        wf = WorkflowDefinition.model_validate(state._assemble())
        return wf, []
    except ValidationError as exc:
        gaps: list[str] = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", ()))
            gaps.append(f"{loc or '<root>'}: {e.get('msg', 'invalid')}")
        return None, gaps


def emit_definition_yaml(definition: WorkflowDefinition) -> str:
    """Produce the ``policy/workflows/<id>.yaml`` content the HUMAN commits (Decision C —
    the interview authors, the human asserts; NO auto-write, NO auto-compile). Round-trips
    through ``load_workflow_definition``. Block style (never flow) so the file reviews
    cleanly and never flattens into an inline map."""
    body = definition.model_dump(exclude_none=True)
    header = (
        f"# SPO-native WorkflowDefinition authored via the SPO interview (ADR-0029 Slice 2).\n"
        f"# The interview AUTHORS; a human ASSERTS by committing this file (git-blame stays\n"
        f"# human). Reviewed like the grant files. Steps execute as the workflow INITIATOR;\n"
        f"# permission is checked at pre-flight (per-run) + dispatch (per-step), NOT baked in.\n"
    )
    return header + yaml.safe_dump(body, default_flow_style=False, sort_keys=False, allow_unicode=True)
