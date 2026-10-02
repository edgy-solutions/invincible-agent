"""The origin-entitlement half (architect ruling, 2026-10-02: "ORIGIN, not audience").

An artifact carries `origin = {owner_domain, program}`, set by EVIDENCE (never asked
of the user) — by a resolver that is NOT in scope here (it waits on a
systems_of_record schema from another team; this module invents nothing about it).
A viewer may read an artifact by its origin iff:

    can_consume(viewer's domain role, origin.owner_domain)   -- policy/domain_consumption.yaml
    AND program_member(viewer, origin.program)               -- policy/program_members.yaml,
                                                                 Topaz `program` `can_view_program`

An artifact whose origin is UNRESOLVED (no origin recorded) is visible to its
dropper/owner only — today's behaviour, unchanged by this module. This file builds
the ENTITLEMENT half only: pure functions, no network, no file IO. The gateway reads
domain_consumption.yaml and asks Topaz, then calls these.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Origin:
    """One artifact's recorded origin. `obtained_via` is provenance (how the
    resolver arrived at owner_domain/program) — carried for audit, not consulted by
    any check in this module."""
    owner_domain: str
    program: str
    obtained_via: str


def load_domain_consumption(raw: dict) -> dict[str, frozenset[str]]:
    """PURE: a parsed policy/domain_consumption.yaml dict -> {consumer_domain:
    frozenset(allowed origin domains)}.

    A row's own required-field validation (granted_by/reason/allowed_origins) is
    validate_policy.py's job (it REFUSES a malformed file loudly, at review time);
    THIS loader runs at request time in the gateway and must not raise on a
    well-formed-enough file — a consumer domain with no `allowed_origins` simply
    maps to an empty set (can_consume is False for it), which is the same
    deny-by-default an absent key already produces. Unknown top-level shapes (not a
    mapping, missing `domain_consumption` key) degrade to an empty table rather
    than raising, so a caller that fails to load the file (see
    gateway._load_domain_consumption_table's fail-closed-on-missing-file posture)
    is not also surprised by a malformed-but-present file taking the process down.
    """
    out: dict[str, frozenset[str]] = {}
    table = (raw or {}).get("domain_consumption") or {}
    if not isinstance(table, dict):
        return out
    for consumer, entry in table.items():
        entry = entry or {}
        if not isinstance(entry, dict):
            out[str(consumer)] = frozenset()
            continue
        allowed = [str(o).strip() for o in (entry.get("allowed_origins") or []) if str(o).strip()]
        out[str(consumer)] = frozenset(allowed)
    return out


def can_consume(
    viewer_domains: Iterable[str],
    owner_domain: str,
    table: Mapping[str, frozenset[str]],
) -> bool:
    """True iff SOME viewer domain's row in `table` lists `owner_domain` among its
    allowed origins.

    NO IMPLICIT IDENTITY: a domain not present in `table` (or present with no row
    naming its own domain) may NOT consume its own origin — the row must be
    asserted explicitly in domain_consumption.yaml. `owner_domain == viewer domain`
    with no row is a MISS, not a pass.
    """
    for d in viewer_domains:
        if owner_domain in table.get(d, frozenset()):
            return True
    return False


class DropperNotProgramMember(Exception):
    """Raised when the evidence names a program the dropper (the artifact's own
    producer/owner) is not a member of (ruling item 2). The resolver that sets
    origin is out of scope here; this is the check its caller will wire in once
    that resolution exists — defined now so the obligation has one home."""


def check_dropper_bound(is_member: bool, origin: Origin) -> None:
    """Raise :class:`DropperNotProgramMember` when `is_member` is False — the
    dropper is not a member of the program the evidence names for its own
    artifact. A no-op (returns None) when `is_member` is True."""
    if not is_member:
        raise DropperNotProgramMember(
            f"origin names program {origin.program!r} that its own dropper is not "
            f"a member of (owner_domain={origin.owner_domain!r})"
        )


def origin_visible(
    *,
    viewer_domains: Iterable[str],
    is_program_member: bool,
    origin: Origin | None,
    table: Mapping[str, frozenset[str]],
) -> bool:
    """True iff a non-owner viewer may read an artifact BY ITS ORIGIN.

    False when `origin` is None — an unresolved origin is not a grant; the
    dropper/owner-only path (today's behaviour) handles that artifact instead, and
    this function is never consulted for it. Both conjuncts (can_consume AND
    program_member) must hold; neither alone is sufficient.
    """
    if origin is None:
        return False
    if not is_program_member:
        return False
    return can_consume(viewer_domains, origin.owner_domain, table)
