"""Admission validation for frontend capability registrations (ADR-0017 amendment).

WHY THIS EXISTS. `/register_frontend_capabilities` accepted everything: it logged the
payload and returned `accepted=len(capabilities)`. A frontend could advertise an unknown
archetype, an empty subject_uri, or a contract with no fields, and the first anyone would
learn of it is a render that produces nothing - the failure discovered at the far end of
the pipeline, which is the shape this project keeps burying.

The amendment's clause: "a UI registering an archetype with a malformed or
unknown-vocabulary contract is REFUSED LOUDLY AT REGISTRATION, not discovered at render
time." This module is that refusal - the analog of the registrar's Contract-D check on
engine registrations. Same position in the sequence, same job.

WHAT IT DOES NOT DO: entitlement. Engines register with minted service identities because
a verb is a governed capability; a UI's render menu is a client DESCRIBING ITSELF. This
validates well-formedness and vocabulary, never authority. Gating a client's description of
its own screen would be authorization theatre over a non-privileged fact and would make
onboarding a new frontend an authz change. Stated here because the next reader will notice
that everything else which registers has an identity gate and wonder why this does not.

PER-CAPABILITY, NOT PER-BATCH. One malformed row does not refuse the batch: the other
capabilities are real, and refusing them punishes the frontend for an unrelated defect. But
a refused row is REPORTED, never silently dropped - the caller gets index, archetype and
reason, and the server logs the same. A silent drop would reproduce the very defect this
check exists to prevent, one layer earlier.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# The archetype vocabulary: BAML's SemanticArchetype (contracts.baml) PLUS the
# task/observation archetypes the SemanticInterpreter dispatches but the enum does not
# declare. Kept as ONE list because that split is a known defect (finding D4 in the
# contract enumeration), and a validator honouring the split would refuse archetypes the
# UI genuinely renders.
KNOWN_ARCHETYPES = frozenset({
    "PROCESS_TOPOLOGY",
    "HAZARD_DECLARATION",
    "ASSET_STATE_METRIC",
    "KNOWLEDGE_DOCUMENT",
    "CHART_WIDGET",
    "DIGITAL_TWIN_3D",
    "GROUPED_REVIEW",
    "APPROVAL_TASK",
    "TRIAGE_TASK",
    "WORKFLOW_OBSERVATION",
    "INSTANCES_BY_PROPERTY",
    # LIVE VIEWS (ADR-0042). Added 2026-08-22 after all four were REFUSED AT THE DOOR on
    # their first real registration: "a frontend cannot advertise a render the backend has
    # no name for." The gate was right and the vocabulary was short -- the archetypes had
    # been declared in the ontology, exported as contracts, and bound in DERIVED_BINDINGS,
    # and this was the one registry nobody enumerated. See test_archetype_registries_agree.
    "PERIOD_SERIES",
    "THRESHOLD_GRID",
    "MATRIX_GRID",
    "DELTA_SET",
})

# Field encodings a registered contract may declare. `json-string` is the one that
# motivated the typed contract at all: ChartWidget's chart_data is a STRING containing
# JSON, not an array, and no field-name list could ever say so.
KNOWN_ENCODINGS = frozenset({
    "json-string", "string", "number", "boolean", "object", "array", "enum",
})


def _reject(idx: int, archetype: str, reason: str) -> Dict[str, Any]:
    return {"index": idx, "archetype": archetype or "(missing)", "reason": reason}


def validate_capability(cap: Dict[str, Any], idx: int = 0) -> Optional[Dict[str, Any]]:
    """Return a rejection dict, or None when the capability is admissible.

    Checks in the order a reader would ask them:
      1. archetype present and in the known vocabulary
      2. subject_uri / object_uri present - they are the graph keys, and a registration
         with an empty key can never be looked up
      3. if a typed `contract` is present, it is well-formed
    """
    archetype = str(cap.get("archetype") or "").strip()
    if not archetype:
        return _reject(idx, archetype, "archetype is missing or empty")
    if archetype not in KNOWN_ARCHETYPES:
        return _reject(
            idx, archetype,
            "unknown archetype " + repr(archetype) + " - not in the registered vocabulary; "
            "a frontend cannot advertise a render the backend has no name for",
        )

    for key in ("subject_uri", "object_uri"):
        if not str(cap.get(key) or "").strip():
            return _reject(
                idx, archetype,
                key + " is missing or empty - it is the graph key, and a registration "
                "with no key can never be looked up",
            )

    contract = cap.get("contract")
    if contract is None:
        # A legacy row with no typed contract is ADMISSIBLE, deliberately. Migration is
        # row-by-row (slice 1 derives CHART_WIDGET; nine remain hand-authored), and
        # refusing untyped rows would break every frontend on the day this ships.
        return None

    if not isinstance(contract, dict):
        return _reject(idx, archetype, "contract must be an object")

    fields = contract.get("fields")
    if not isinstance(fields, dict) or not fields:
        return _reject(
            idx, archetype,
            "contract.fields must be a non-empty object - a typed contract declaring no "
            "fields validates nothing, which is worse than declaring none",
        )

    for fname, fspec in fields.items():
        if not isinstance(fspec, dict):
            return _reject(idx, archetype, "contract.fields[" + repr(fname) + "] must be an object")
        enc = fspec.get("encoding") or fspec.get("type")
        if enc is None:
            return _reject(
                idx, archetype,
                "contract.fields[" + repr(fname) + "] declares neither `encoding` nor `type` - "
                "the field's shape is exactly what this contract exists to carry",
            )
        if str(enc) not in KNOWN_ENCODINGS:
            return _reject(
                idx, archetype,
                "contract.fields[" + repr(fname) + "] has unknown encoding " + repr(enc)
                + "; known: " + str(sorted(KNOWN_ENCODINGS)),
            )

    reasons = contract.get("refusalReasons")
    if reasons is not None and (
        not isinstance(reasons, (list, tuple))
        or not all(isinstance(r, str) for r in reasons)
    ):
        return _reject(idx, archetype, "contract.refusalReasons must be a list of strings")

    return None


def validate_registration(
    capabilities: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split a registration payload into (admitted, rejected).

    Per-capability, never per-batch - see the module docstring. The rejected list carries
    index, archetype and reason so a caller fixes the row rather than bisecting a payload.
    """
    admitted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for i, cap in enumerate(capabilities or []):
        problem = validate_capability(cap, i)
        if problem is None:
            admitted.append(cap)
        else:
            rejected.append(problem)
    return admitted, rejected
