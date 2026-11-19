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
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

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


def _is_person(subject: str) -> bool:
    s = subject.strip()
    return bool(s) and not s.startswith("svc:")


def _anonymous(body_subject: str) -> Binding:
    return Binding("", ANONYMOUS, (NO_GRANT,), _body_identity(body_subject, ""))


def _body_identity(body_subject: str, subject: str) -> str:
    b = (body_subject or "").strip()
    if not b:
        return "absent"
    return "same" if subject and b.casefold() == subject.casefold() else "ignored"


def bind(caller, *, body_subject: str = "", asked=None,
         held_of: Callable[[str], Iterable[str]],
         cache: Optional[GrantCache] = None) -> Binding:
    """The caller's binding. ``caller`` is a ``CallerIdentity`` or None; never the body."""
    subject = (getattr(caller, "authz_id", None) or "").strip() if caller is not None else ""
    if caller is None or not getattr(caller, "verified", False) or not subject:
        return _anonymous(body_subject)

    kind = PERSON if _is_person(subject) else SERVICE
    try:
        held = set((cache or _DEFAULT_CACHE).get(subject, held_of))
    except Exception as exc:  # noqa: BLE001 -- fail closed; log the type only, no values
        logger.warning("grant lookup failed (%s); binding no grant", type(exc).__name__)
        held = set()

    wanted = [str(d).strip().upper() for d in (asked or ()) if str(d).strip()]
    if wanted:
        seen: set[str] = set()
        grants = []
        for d in wanted:
            if d in held and d not in seen:
                seen.add(d)
                grants.append(d)
    else:
        grants = sorted(held)
    return Binding(subject, kind, tuple(grants) or (NO_GRANT,), _body_identity(body_subject, subject))
