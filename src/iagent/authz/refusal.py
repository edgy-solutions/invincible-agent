"""A policy refusal names its policy, the binding the caller lacks, and who can grant it.

DRAFT RULE (lane/gov, 2026-10-24; proposal
`docs/proposals/a-policy-refusal-names-its-policy-the-missing-binding-and-who-can-grant-it.md`).
Sealed by `tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`.

A POLICY REFUSAL is a denial that some binding would have turned into an allow: a row on the
policy rail (`policy/*.yaml`), a deployment config entry, or a table still held in code. A denial
no binding can lift (no identity at all; a route pinned to one service; separation of duties) is
not one, and stays as it is.

Its STATUS is 401, 403, or a 409 that asks the caller to CHOOSE or REQUEST something (architect,
2026-10-25, from finance's canvas 409: the `program` binding unbound). A 409 on the target's own
state (already resolved, terminal, immutable) asks neither and is not one. A 409 refusal with no
candidates and no grantor is non-compliant; this helper always fills the grantor, so a 409 built
here is compliant with `candidates` empty, and candidates are additive.

Every policy refusal carries a `refusal` object, the SDK's `iagent_mesh.Refusal` dumped to JSON.
It is built as a `PartialRefusal` and completed here (architect 2026-10-31, fork 2 (b)): only this
layer can say who grants, for an engine's names and a BFF site's alike.

    policy_id        where the binding lives: "<family>" or "<family>:<key>", e.g.
                     "capability_grants:mesh:startReview", "groups", "config:DELEGATE_ON_BEHALF_OF"
    missing_binding  the relation the caller lacks, e.g. "can_invoke(mesh:startReview)"
    grantable_by     "<who>; <how>", READ from this deployment's grantor map, never typed at the
                     call site -- who approves a grant is the deployment's fact, not the platform's
    candidates       what the caller may choose instead; () by default -- an alternative is
                     itself existence-bearing, so a site offers one only where it already tells
                     the caller that set. Ruled 2026-10-27 (ruling 3): only objects the caller
                     already holds a view grant on, never "others exist"; with no grants the list
                     is empty and `grantable_by` is the whole answer

THE EXISTENCE RULE. The fields are a function of the caller, the route and what the caller
sent -- never of whether the target exists or what it holds. An OBJECT-SCOPED family (one whose
key would name a program, an asset, a compartment) is named by its family alone, and the key goes
to the log. So a body that must answer a withheld target exactly as an absent one (ADR-0047 §5.1,
ADR-0049 Ruling 4) stays byte-equal: both carry the same refusal.

THE GRANTOR MAP is ADR-0036 composition, through the SDK's `compose_rows` (ADR-0039 refuses a new
composer): the seed `policy/grantors/` (one file per family, deployment-neutral wording) and the
overlay directories in `GRANTOR_OVERLAY_DIRS` (pathsep-separated, the same form as
`CONTENT_KIND_OVERLAY_DIRS`). An overlay row REPLACES the seed row for its family.

A REFUSAL NEVER BECOMES A 500. A family the composed map does not carry (an overlay tombstoned
it) still refuses with the site's status, and `grantable_by` says the map is missing the row;
it is logged.
A call site naming an object-scoped family WITH a key is a programming error and raises -- the
seal walks every call site, so that cannot ship.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

#: The platform seed: one row per family, deployment-neutral wording.
_SEED_DIR = Path(__file__).resolve().parents[3] / "policy" / "grantors"

#: Pathsep-separated overlay directories -- see `content_kinds._OVERLAY_DIRS_ENV`.
_OVERLAY_DIRS_ENV = "GRANTOR_OVERLAY_DIRS"

@dataclass(frozen=True)
class Grantor:
    family: str
    who: str
    how: str
    object_scoped: bool = False
    #: The rail file the family's rows live in, or None for `config` / `code`.
    rail_file: Optional[str] = None


def _declaration_error():
    from iagent_mesh.declarations import DeclarationError  # noqa: PLC0415
    return DeclarationError


def _build(raw: dict) -> Grantor:
    unknown = set(raw) - {"family", "who", "how", "object_scoped", "rail_file"}
    if unknown:
        raise ValueError(f"unknown field(s) {sorted(unknown)}")
    for f in ("who", "how"):
        if not str(raw.get(f) or "").strip():
            raise ValueError(f"{f!r} is blank -- a grantor nobody can find is not a grantor")
    scoped = raw.get("object_scoped", False)
    if not isinstance(scoped, bool):
        raise ValueError(f"object_scoped must be true or false, not {scoped!r}")
    return Grantor(family=raw["family"], who=raw["who"].strip(), how=raw["how"].strip(),
                   object_scoped=scoped, rail_file=raw.get("rail_file"))


_GRANTORS_CACHE: "dict[str, Grantor] | None" = None


def grantors() -> dict[str, Grantor]:
    """The composed grantor map, by family, cached on success (a transient load error retries)."""
    global _GRANTORS_CACHE
    if _GRANTORS_CACHE is not None:
        return _GRANTORS_CACHE
    from iagent_mesh.declarations import compose_rows  # noqa: PLC0415

    raw = (os.getenv(_OVERLAY_DIRS_ENV) or "").strip()
    overlay_dirs = [p for p in (s.strip() for s in raw.split(os.pathsep)) if p] if raw else []
    rows = compose_rows(_SEED_DIR, overlay_dirs, key_field="family", builder=_build,
                        label="grantor", error=_declaration_error())
    _GRANTORS_CACHE = {g.family: g for g in rows}
    return _GRANTORS_CACHE


def _grantable_by(g: Grantor) -> str:
    return f"{g.who}; {g.how}"


def _complete(partial: Any) -> dict[str, Any]:
    """`partial` (a `PartialRefusal`) with this deployment's grantor, as the wire dict. Raises
    ValueError on a blank family or an object-scoped key."""
    policy_id = partial.policy_id
    family, _, key = policy_id.partition(":")
    if not family:
        raise ValueError(f"a refusal names its policy: {policy_id!r}")
    g = grantors().get(family)
    if g is None:
        logger.error("policy refusal names family %r, which this deployment's grantor map "
                     "does not carry", family)
        grantable_by = (f"not declared in this deployment's grantor map; add "
                        f"policy/grantors/{family}.yaml (or its overlay row)")
    else:
        if g.object_scoped and key:
            raise ValueError(f"{family!r} is object-scoped: name the family alone, and log the "
                             f"key -- a refusal must not differ by the target's existence")
        grantable_by = _grantable_by(g)
    return partial.complete(grantable_by).model_dump(mode="json")


def refusal(policy_id: str, missing_binding: str,
            candidates: "tuple | list" = ()) -> dict[str, Any]:
    """The `refusal` object for one denial. Raises ValueError only on a malformed CALL SITE."""
    from iagent_mesh import PartialRefusal  # noqa: PLC0415

    # Candidates are data, not the call site. The model refuses a blank one, and a bad row must
    # not turn this deny into a 500, so it is omitted, which is what the model asks for.
    offered = [c for c in candidates if isinstance(c, str) and c.strip()]
    if len(offered) != len(candidates):
        logger.error("policy refusal %r omitted %d unusable candidate(s)",
                     policy_id, len(candidates) - len(offered))
    return _complete(PartialRefusal(policy_id=policy_id, missing_binding=missing_binding,
                                    candidates=offered))


def policy_refusal(error: str, *, policy_id: str, missing_binding: str, status_code: int = 403,
                   message: Optional[str] = None, candidates: "tuple | list" = (),
                   extra: Optional[dict[str, Any]] = None) -> HTTPException:
    """`raise policy_refusal("not_entitled_to_x", policy_id=..., missing_binding=...)` at a BFF
    site. `extra` carries what the body already says beside the refusal (finance's `ask`); it
    never replaces `error`, `refusal` or `message`."""
    kept = {k: v for k, v in (extra or {}).items() if k not in ("error", "refusal", "message")}
    detail: dict[str, Any] = {"error": error, **kept,
                              "refusal": refusal(policy_id, missing_binding, candidates)}
    if message:
        detail["message"] = message
    return HTTPException(status_code=status_code, detail=detail)


def relay_refusal(upstream: Any) -> Any:
    """Complete a refusal an ENGINE sent. Engines name `policy_id` and `missing_binding` (they hold
    no grantor map); the BFF is where the caller reads the answer, so the BFF adds `grantable_by`
    -- always from the map, so an engine cannot speak for the deployment. Anything that is not a
    refusal-bearing dict passes through unchanged. Names that cannot be completed lose the envelope
    and the deny still travels: this never raises on an engine's body, and a raise here is a 500."""
    if not isinstance(upstream, dict):
        return upstream
    r = upstream.get("refusal")
    if not (isinstance(r, dict) and r.get("policy_id") and r.get("missing_binding")):
        return upstream
    from iagent_mesh import PartialRefusal  # noqa: PLC0415

    try:
        # The two names alone. Ruling 3: a candidate is an object the caller holds a view grant
        # on, and the BFF cannot check an engine's list against the caller, so a relay offers none.
        partial = PartialRefusal(policy_id=r["policy_id"], missing_binding=r["missing_binding"])
        try:
            filled = _complete(partial)
        except ValueError:
            # An engine named an object-scoped key. Narrow to the family rather than turn the
            # deny into a 500; the key is the engine's to log, never the caller's to read.
            logger.error("engine refusal named a key on an object-scoped family: %r",
                         partial.policy_id)
            filled = _complete(PartialRefusal(policy_id=partial.policy_id.partition(":")[0],
                                              missing_binding=partial.missing_binding))
    except ValueError:
        logger.error("engine refusal could not be completed, relaying the deny without it: %r",
                     r["policy_id"], exc_info=True)
        return {k: v for k, v in upstream.items() if k != "refusal"}
    return {**upstream, "refusal": filled}


#: The message prefix that marks a Restate TerminalError as a carried refusal (architect,
#: 2026-10-27, ruling 1: a TerminalError carries only a string, so the refusal rides as
#: `refusal:` + its JSON and is parsed here). The engines' half is
#: `agent_fleet.utils.terminal_refusal`; two copies because an engine image carries no `src/`,
#: held to the same dict on every message by
#: `tests/security/test_a_relayed_refusal_parses_the_same_on_both_sides.py`. Neither gives way to
#: the SDK's terminal pair: `Refusal.from_terminal` answers None on an engine's body, which has no
#: `grantable_by`, and `PartialRefusal` has no terminal form.
TERMINAL_PREFIX = "refusal:"


def from_terminal(message: Any) -> Optional[dict]:
    """The refusal dict an engine's TerminalError message carries, or None when it carries none:
    not a string, no prefix, or a body that is not a JSON object. Never raises -- this is the
    deny path. The dict is the engine's, unfilled: pass it through `relay_refusal` as
    `{"refusal": ...}` so the grantor comes from this deployment's map."""
    if not isinstance(message, str) or not message.startswith(TERMINAL_PREFIX):
        return None
    try:
        body = json.loads(message[len(TERMINAL_PREFIX):])
    except (ValueError, RecursionError):  # RecursionError: a deeply nested body
        return None
    return body if isinstance(body, dict) else None
