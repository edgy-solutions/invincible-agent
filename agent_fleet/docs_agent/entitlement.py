"""Serve-time entitlement for `mesh:explain` -- the second worksite, ADDED to resolve time.

THE RULE. ADR-0037:179: a page whose `explains` names a verb the asker cannot invoke is
"dropped or surfaced honestly as 'exists but not in your entitlements'". ADR-0025:291: the
worksite resolves the IRI, asks the one decider, and honours the answer. This module is that
worksite inside engine-docs, ruled 2026-09-30 on the three forks the 09-29 report left open:

  * WHO IS ASKED ABOUT -- the asker, on the on-behalf-of token. That is the token the supervisor
    redeems from the vault and dispatches with (`_CALLER_IDENTITY_VERBS`), which the SDK's
    transport dependency verifies into `CallerIdentity.authz_id`. It is NOT
    `Initiator.on_behalf_of`: that field is provenance only and never a gate input (ruling
    2026-09-26 §4), and a value the caller types into an envelope is the forgeable-actor shape
    the identity-propagation plan forbids ("the actor must be a claim the minting authority
    asserts, never a value a caller supplies"). An UNVERIFIED caller therefore has no identity
    here, whatever it claims.
  * WHAT IS ASKED -- `can_invoke` in the capability namespace, one check per VERB the page
    explains. A class target is not asked here: whether the asker may see a class is the
    resolve-time cell check's question, and serve time ADDS to it rather than re-deciding it.
  * WHERE -- here, after the reader resolves the pages and BEFORE any body is read. A withheld
    page's body is never fetched, so there is nothing of it to leak by a later mistake.

DARK UNTIL THE FLIP. `ENABLE_AGENTIC_AUTH` off -> the gate is not consulted and the response is
byte-for-byte what it was. On -> fail-CLOSED: no verified identity, no directory URL, or any
Topaz error is a deny, never an allow.

TWO PRECONDITIONS OF THE FLIP, both outside this engine, both recorded in
`docs/plans/enable-agentic-auth-flip-packet.md` (named consequence 3):
  1. `explain` is not in `_CALLER_IDENTITY_VERBS`, so today the supervisor dispatches it as
     `svc:supervisor`, and the gate would decide for the service, not the asker.
  2. The capability namespace holds no mesh verb a page explains (`capability_grant_sync`
     carries the direct_call grants and `mesh:startReview`). Every verb-bearing page would be
     withheld from every caller.
Neither is a defect of this gate -- it would refuse correctly -- but either one alone makes the
flip read as "docs went dark", so both are written down where the flip is decided.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Iterable, List, Tuple

import httpx

logger = logging.getLogger(__name__)

# Read at import, like engine-o's gates: the posture is a deploy-time fact, and the chart's fleet
# configmap is where it is set (`enforcement.agenticAuth`).
ENABLE_AGENTIC_AUTH = os.getenv("ENABLE_AGENTIC_AUTH", "false").lower() in ("true", "1", "yes")
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "")

MESH_NS = "http://invincible-agent/mesh#"

#: The ADR-0037:179 wording, as a machine reason and as the sentence a reader is shown.
WITHHELD_REASON = "exists_but_not_in_your_entitlements"
WITHHELD_SENTENCE = "This page exists but is not in your entitlements."

#: The outcome when EVERY resolved page is withheld. Distinct from an abstain on purpose: "no page
#: explains this" is a gap in the writing; "pages explain this and you may read none" is a
#: decision about the asker, and rendering the two alike tells the asker the corpus is empty.
UNENTITLED = "unentitled"


def _local_name(target: str) -> str:
    t = (target or "").strip()
    for sep in ("#", "/", ":"):
        if sep in t:
            t = t.rsplit(sep, 1)[-1]
    return t


def classify_target(target: str) -> str:
    """'verb', 'class', or 'undecided' -- by the local name's leading character.

    The corpus follows the RDF naming convention the registry does: verbs (properties) are
    lowerCamel (`seedCanvas`), classes UpperCamel (`ProductionLot`). Anything else is UNDECIDED
    and the caller treats it as a verb, i.e. ASKS -- an unknown shape must not be waved through
    as a class the gate does not check.
    """
    local = _local_name(target)
    if not local or not local[0].isalpha():
        return "undecided"
    return "verb" if local[0].islower() else "class"


def capability_id(target: str) -> str:
    """The capability object a verb target is checked as: the COMPACT `mesh:` form, the spelling
    the capability namespace already uses (`mesh:startReview`, `mesh:writeDecisionRecord`).
    A verb outside the mesh namespace keeps its own spelling -- the directory will not know it,
    and not-found is a deny, which is the right answer for a verb nobody granted."""
    t = (target or "").strip()
    if t.startswith(MESH_NS):
        return "mesh:" + t[len(MESH_NS):]
    return t


def gated_capabilities(explains: Iterable[str]) -> List[str]:
    """Every capability the page's `explains` obliges the asker to hold, in declared order."""
    out: List[str] = []
    for target in explains or ():
        if classify_target(target) != "class":
            cap = capability_id(target)
            if cap and cap not in out:
                out.append(cap)
    return out


def asker_of(caller: Any) -> str:
    """The VERIFIED asker's authz_id, or "" -- never an unverified claim.

    Under OBSERVE the transport dependency admits unverified callers and says so; an
    entitlement decision keyed on one would be keyed on whatever the request said."""
    if caller is None or not getattr(caller, "verified", False):
        return ""
    return str(getattr(caller, "authz_id", None) or "")


def can_invoke(authz_id: str, capability: str) -> bool:
    """Ask the single decider. Mirrors engine-o's `_can_invoke_capability` exactly.

    Fail-CLOSED on empty identity, empty capability, unset directory URL, or any error."""
    if not authz_id or not capability or not TOPAZ_DIRECTORY_URL:
        return False
    try:
        r = httpx.post(
            f"{TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
            json={
                "object_type": "capability",
                "object_id": capability,
                "relation": "can_invoke",
                "subject_type": "user",
                "subject_id": authz_id,
            },
            timeout=5.0,
        )
        r.raise_for_status()
        return bool(r.json().get("check"))
    except Exception as e:  # noqa: BLE001 -- fail-closed on any error
        logger.warning("engine-docs can_invoke failed capability=%s caller=%s (fail-closed deny): %s",
                       capability, authz_id, e)
        return False


def partition(rows: Iterable[Any], asker: str) -> Tuple[List[Any], List[dict]]:
    """Split resolved pages into (served rows, withheld notices). Bodies are NOT read here.

    A page is withheld when ONE verb it explains is denied -- the asker must hold every one: a
    how-to for a verb you cannot run is the page ADR-0037 drops. A page explaining no verb has
    nothing to ask and is served -- its class targets were the resolve-time check's to decide.
    """
    served: List[Any] = []
    withheld: List[dict] = []
    for row in rows:
        denied = [cap for cap in gated_capabilities(getattr(row, "explains", ()))
                  if not can_invoke(asker, cap)]
        if denied:
            withheld.append({
                "page_iri": row.iri,
                "title": row.title,
                "withheld": True,
                "reason": WITHHELD_REASON,
                "body": WITHHELD_SENTENCE,
            })
            logger.info("engine-docs withheld page=%s asker=%s denied=%s",
                        row.iri, asker or "<unverified>", denied)
        else:
            served.append(row)
    return served, withheld
