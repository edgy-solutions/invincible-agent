"""Engine O binds the caller's identity and grants from the VERIFIED caller, never the request body.

The order (architect, 11-19): in engine O the caller's identity and grants come from the verified
caller, never the request body, including the input-declared pool scoped by the caller's grant.

Pure and dep-free (stdlib only) so it unit-tests without the engine-o import chain; ``main.py``
imports it flatten-aware, as ``recall_guard`` and ``input_declared``.

The rule, in one place:

* The caller is the SDK's ``CallerIdentity`` (``iagent_mesh.transport_auth.current_caller()``).
  Only ``verified=True`` is a caller. Posture is OBSERVE fleet-wide, so a forged, unsigned,
  expired or key-less token is ADMITTED with its CLAIMED subject in ``authz_id`` and
  ``verified=False``: that claimed subject is anonymous here, never a person.
* The grant is what the directory says the verified subject holds (``held_of``). The body may
  NARROW it (``asked``), never widen it: grants = held ∩ asked, or held when nothing was asked.
* A body subject is never used for anything but a ``body_identity`` label (absent/same/ignored).

A DECLARED DELEGATION (architect ruling 1b, 11-19): a service acts for a person only by declared
delegation.

* A policy row (``policy/gateway_delegates.yaml``, ``door: engine-o``) names the service and the
  routes it may call on a person's behalf, and nothing else.
* The service authenticates as itself and states whom it acts for (``on_behalf_of``).
* Engine O honours the statement only when the row exists for that service on that route. It then
  binds the PERSON's grants and NONE of the service's own (the service's grants are never looked
  up on that path), and records the call as delegated with both identities (``Binding.via``).
* Without a row the service acts as itself. A statement from a person, from an anonymous or
  unverified caller, or one naming the caller itself, is ignored. So is a statement that is not a
  person: one starting with a non-person prefix (``svc:``, ``pipeline:``, compared casefolded), or
  one containing whitespace or a control character (it could forge an audit line).
"""
from __future__ import annotations

import logging
import os
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

#: The ONE domain sent downstream when the caller holds none. It can never be a real domain
#: (domains are uppercase identifiers), so every "empty entitled_domains = unscoped" site
#: downstream sees a NON-EMPTY scope that matches nothing, while a domain-agnostic predicate
#: (one whose own ``domains`` is empty) still matches. No grant is never unscoped.
NO_GRANT = "-no-grant-"

ANONYMOUS = "anonymous"
PERSON = "person"
SERVICE = "service"


@dataclass(frozen=True)
class Binding:
    subject: str                    # "" when anonymous
    kind: str                       # "person" | "service" | "anonymous"
    grants: tuple[str, ...]         # uppercase, never empty: (NO_GRANT,) when none
    body_identity: str              # "absent" | "same" | "ignored"
    via: str = ""                   # the authenticated service when delegated, else ""
    #: "absent" (no statement) | "delegated" | "not_declared" (a verified service stated a person
    #: and no row covers it) | "ignored" (a statement from a person, an anonymous or unverified
    #: caller, or one naming a svc: or the caller itself)
    delegation: str = "absent"


class GrantCache:
    """A small TTL cache of ``held_of`` keyed by subject. Failures are NOT cached."""

    def __init__(self, ttl_s: Optional[float] = None, clock: Callable[[], float] = time.monotonic):
        if ttl_s is None:
            try:
                ttl_s = float(os.getenv("ENGINE_O_GRANT_TTL_S", "30"))
            except ValueError:
                ttl_s = 30.0
        self.ttl_s = ttl_s
        self._clock = clock
        self._rows: dict[str, tuple[float, tuple[str, ...]]] = {}

    def get(self, subject: str, held_of: Callable[[str], Iterable[str]]) -> tuple[str, ...]:
        """The subject's held domains; raises whatever ``held_of`` raises (and caches nothing)."""
        now = self._clock()
        if self.ttl_s > 0:
            hit = self._rows.get(subject)
            if hit is not None and now - hit[0] < self.ttl_s:
                return hit[1]
        held = tuple(str(d).strip().upper() for d in held_of(subject) if str(d).strip())
        if self.ttl_s > 0:
            self._rows[subject] = (now, held)
        return held


_DEFAULT_CACHE = GrantCache()

#: The routes a delegate row may name (architect 11-19). validate_policy.ENGINE_O_DELEGATE_ROUTES is
#: a copy, sealed by tests/security/test_gateway_delegates_rail.py.
DELEGATE_ROUTES = ("resolve_instance",)
_DOOR = "engine-o"


def load_delegates(path: Optional[str] = None) -> dict[str, frozenset[str]]:
    """Service -> the routes it may call on a person's behalf: the rows with ``door: engine-o`` in
    the delegates file. Read ON EVERY CALL from env ENGINE_O_DELEGATES_FILE, default
    ``/app/policy/gateway_delegates.yaml``. Rows of any other door are ignored. An absent file is
    ``{}`` and a warning; unreadable YAML, a wrong shape, a malformed row or a missing yaml module
    is ``{}`` and an error: FAILS CLOSED, and never raises."""
    path = path or os.environ.get("ENGINE_O_DELEGATES_FILE") or "/app/policy/gateway_delegates.yaml"
    try:
        import yaml  # noqa: PLC0415 -- lazy: the module stays stdlib-only
        try:
            with open(path, encoding="utf-8") as fh:
                parsed = yaml.safe_load(fh)
        except FileNotFoundError:
            logger.warning("%s is absent: an absent file is an empty list (no delegate)", path)
            return {}
        rows = parsed.get("gateway_delegates") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise ValueError("top level is not a mapping with a `gateway_delegates` list")
        out: dict[str, set[str]] = {}
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"row {i} is not a mapping")
            if row.get("door") != _DOOR:
                continue
            svc, routes = row.get("service"), row.get("routes")
            if (not isinstance(svc, str) or not svc.strip() or not isinstance(routes, list)
                    or not all(isinstance(r, str) for r in routes)):
                raise ValueError(f"row {i}: `service` is not a non-empty string or `routes` is not a list of strings")
            out.setdefault(svc.strip(), set()).update(r for r in routes if r in DELEGATE_ROUTES)
        return {k: frozenset(v) for k, v in out.items()}
    except Exception as exc:  # noqa: BLE001 -- fail closed
        logger.error("%s unreadable, failing closed (no delegate): %s", path, exc)
        return {}


def _is_person(subject: str) -> bool:
    s = subject.strip()
    return bool(s) and not s.startswith("svc:")


#: Identity prefixes that name a non-person. A pipeline is not a delegate and acts as itself
#: (policy/gateway_delegates.yaml), and a service is never a person, in any case.
NON_PERSON_PREFIXES = ("svc:", "pipeline:")


def _is_stated_person(raw: str) -> bool:
    """Whether an UNVERIFIED statement may name a person: non-empty, no whitespace or control
    character anywhere in the raw value, and no non-person prefix, compared casefolded."""
    if not raw or any(c.isspace() or unicodedata.category(c).startswith("C") for c in raw):
        return False
    return not raw.casefold().startswith(NON_PERSON_PREFIXES)


def _anonymous(body_subject: str) -> Binding:
    return Binding("", ANONYMOUS, (NO_GRANT,), _body_identity(body_subject, ""))


def _body_identity(body_subject: str, subject: str) -> str:
    b = (body_subject or "").strip()
    if not b:
        return "absent"
    return "same" if subject and b.casefold() == subject.casefold() else "ignored"


def bind(caller, *, body_subject: str = "", asked=None,
         held_of: Callable[[str], Iterable[str]],
         cache: Optional[GrantCache] = None,
         on_behalf_of: str = "", route: str = "",
         delegates: Callable[[], Mapping[str, Iterable[str]]] = load_delegates) -> Binding:
    """The caller's binding. ``caller`` is a ``CallerIdentity`` or None; never the body.

    ``on_behalf_of`` is a statement, honoured only for a verified service with a delegate row for
    ``route`` (see the module docstring); ``delegates`` is called only then."""
    stated = (on_behalf_of or "").strip()
    subject = (getattr(caller, "authz_id", None) or "").strip() if caller is not None else ""
    if caller is None or not getattr(caller, "verified", False) or not subject:
        return _with_delegation(_anonymous(body_subject), "ignored" if stated else "absent")

    use_cache = cache or _DEFAULT_CACHE
    wanted = [str(d).strip().upper() for d in (asked or ()) if str(d).strip()]
    kind = PERSON if _is_person(subject) else SERVICE
    via, delegation, who = "", "absent", subject
    if stated:
        delegation = "ignored"
        if (kind == SERVICE and _is_stated_person(on_behalf_of or "")
                and stated.casefold() != subject.casefold()):
            if route in set(delegates().get(subject, ())):
                who, kind, via, delegation = stated, PERSON, subject, "delegated"
            else:
                delegation = "not_declared"

    try:
        held = set(use_cache.get(who, held_of))
    except Exception as exc:  # noqa: BLE001 -- fail closed; log the type only, no values
        logger.warning("grant lookup failed (%s); binding no grant", type(exc).__name__)
        held = set()

    if wanted:
        seen: set[str] = set()
        grants = []
        for d in wanted:
            if d in held and d not in seen:
                seen.add(d)
                grants.append(d)
    else:
        grants = sorted(held)
    return Binding(who, kind, tuple(grants) or (NO_GRANT,), _body_identity(body_subject, who),
                   via, delegation)


def _with_delegation(b: Binding, delegation: str) -> Binding:
    return Binding(b.subject, b.kind, b.grants, b.body_identity, b.via, delegation)
