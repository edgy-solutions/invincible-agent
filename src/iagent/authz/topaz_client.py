"""Topaz Directory client + per-token entitlement cache.

Per ADR-0026 step 3.

Design:
    * Sync `httpx.Client` calls — matches cortex-bff's sync
      `get_current_user` dependency; async can come later.
    * Per-token cache keyed by (sub, jti) with TTL = token lifetime.
      Miss + reachable → fetch fresh. Miss + unreachable →
      `AuthorizationUnavailable` (translated to HTTP 503).
    * Cache serves the WHOLE entitlement matrix. `check_cell` does a
      local lookup against the cached matrix — not a topaz round-trip
      per request. Correct because:
        - Live topaz mutations from the sync tool land in the
          Directory; cached tokens see the OLD matrix until the token
          expires + refreshes (the cache-without-revocation-hook
          divergence window this ADR explicitly names as a known-stale
          interim posture — see ADR-0026 "Cache-without-revocation-
          hook is a known-stale authz window" in Negative).
        - Server-side hook to evict cache on Topaz change events is
          the deferred amendment; not shipped here.

Public API:
    TopazDirectoryClient(url, timeout=5.0)
        .get_entitlements(user_id) -> Entitlements
        .close()

    EntitlementCache(client)
        .get(sub, jti, exp) -> Entitlements
            Serves cached matrix or fetches on miss. Uses `exp` from
            the JWT to compute TTL; evicts stale entries lazily.

    Entitlements (Pydantic)
        .cells: list[EntitlementCell]
        .default: EntitlementCell | None
        .contains(persona, domain) -> bool
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from pydantic import BaseModel


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors — translated at the FastAPI layer to distinct HTTP codes.
# ---------------------------------------------------------------------------


class AuthorizationUnavailable(Exception):
    """Topaz is unreachable AND we have no cached matrix for this token.

    Translated to HTTP 503 (`authorization_unavailable`) — NOT 500,
    NOT 403. The caller can tell "auth service is down" from "you're
    denied" per ADR-0026's honest-degradation posture.
    """


class CellNotEntitled(Exception):
    """User requested a (persona, domain) cell not in their matrix.

    Translated to HTTP 403 (`cell_not_entitled`) with the user's
    entitled cells in the body — the caller knows what would work.
    """

    def __init__(self, user_id: str, persona: str, domain: str, entitled_cells: list):
        self.user_id = user_id
        self.persona = persona
        self.domain = domain
        self.entitled_cells = entitled_cells
        super().__init__(
            f"user {user_id!r} not entitled to persona={persona!r}, "
            f"domain={domain!r}; entitled cells: {entitled_cells}"
        )


# ---------------------------------------------------------------------------
# Entitlement models.
# ---------------------------------------------------------------------------


class EntitlementCell(BaseModel):
    """One cell of the entitlement matrix: user CAN assume this
    persona in this domain."""

    persona: str
    domain: str

    def key(self) -> tuple[str, str]:
        return (self.persona, self.domain)


class Entitlements(BaseModel):
    """Full entitlement matrix for a user.

    `cells` is the flat list of every (persona, domain) pair the user
    can assume. `default` is the picker's initial selection (`None`
    when the user has no seeded default — cortex-ui falls back to the
    first cell in `cells`).
    """

    cells: list[EntitlementCell] = []
    default: Optional[EntitlementCell] = None
    # Provenance flag per ADR-0025's `entitlement_source` pattern
    # extended for step 3:
    #   "topaz"        — fresh matrix from topaz (cache miss).
    #   "cache"        — served from per-token cache (cache hit).
    #   "jwt-legacy"   — Keycloak persona-attribute path (Tier 3a
    #                    interim from step 1 — reader still exists;
    #                    scheduled for removal in step 6).
    #   "fallback"     — no topaz + no cache + no JWT claim → default
    #                    to (USER_PERSONA_FALLBACK, entitled_domains).
    #                    Transitional; goes away when topaz-only lands.
    source: str = "topaz"

    def contains(self, persona: str, domain: str) -> bool:
        return any(c.persona == persona and c.domain == domain for c in self.cells)

    def personas(self) -> list[str]:
        """Deduped list of personas the user is entitled to."""
        seen: set[str] = set()
        out: list[str] = []
        for c in self.cells:
            if c.persona not in seen:
                seen.add(c.persona)
                out.append(c.persona)
        return out

    def domains_for(self, persona: str) -> list[str]:
        """Deduped list of domains the user is entitled to under a
        given persona."""
        seen: set[str] = set()
        out: list[str] = []
        for c in self.cells:
            if c.persona == persona and c.domain not in seen:
                seen.add(c.domain)
                out.append(c.domain)
        return out


# ---------------------------------------------------------------------------
# Topaz HTTP client.
# ---------------------------------------------------------------------------


class TopazDirectoryClient:
    """Thin sync HTTP client for topaz's Directory v3 REST gateway.

    Only surfaces the endpoints ADR-0026 step 3 needs:
        - list a user's `member` relations → derive their groups
        - list a group's `assumable_by` relations (via cell.assumable_by
          with subject_type=group) → derive that group's grants
        - check a permission (fallback path if the client wants to
          verify without walking the graph)

    Instantiated once per cortex-bff process; not thread-safe for
    concurrent access to a single request (httpx.Client itself is,
    but the higher-level API is scoped per-call).
    """

    def __init__(self, url: str, timeout_seconds: float = 5.0):
        self._url = url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._url,
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def get_entitlements(self, user_id: str) -> Entitlements:
        """Compute the user's full (persona, domain) matrix.

        Two topaz round-trips:
          1. List `member` relations where subject_id = user_id →
             the user's group memberships.
          2. For each group, list `assumable_by` relations from cells
             to that group#member → the group's grants.

        Then flatten to `cells`. Raises `AuthorizationUnavailable` if
        either topaz call errors (network, 5xx). 404s are treated as
        empty — a user with no relations is not entitled to anything,
        which is the honest default.
        """
        try:
            groups = self._list_user_groups(user_id)
            cells: list[EntitlementCell] = []
            seen: set[tuple[str, str]] = set()
            for group_id in groups:
                for cell in self._list_group_grants(group_id):
                    key = cell.key()
                    if key not in seen:
                        seen.add(key)
                        cells.append(cell)
            return Entitlements(cells=cells, default=None, source="topaz")
        except httpx.HTTPError as e:
            logger.error(
                "TOPAZ DIRECTORY UNAVAILABLE: get_entitlements(%s) "
                "failed: %r",
                user_id,
                e,
            )
            raise AuthorizationUnavailable(
                f"topaz directory unreachable: {e}"
            ) from e

    # -- internal ---------------------------------------------------------

    def _list_user_groups(self, user_id: str) -> list[str]:
        """Return the group IDs the user is a member of."""
        page_token = ""
        groups: list[str] = []
        while True:
            params: dict[str, str] = {
                "subject_type": "user",
                "subject_id": user_id,
                "relation": "member",
                "object_type": "group",
            }
            if page_token:
                params["page.token"] = page_token
            r = self._client.get("/api/v3/directory/relations", params=params)
            if r.status_code == 404:
                return []
            r.raise_for_status()
            body = r.json()
            for rel in body.get("results") or body.get("relations") or []:
                if rel.get("object_type") == "group":
                    groups.append(rel["object_id"])
            page_token = (body.get("page") or {}).get("next_token", "")
            if not page_token:
                break
        return groups

    def _list_group_grants(self, group_id: str) -> list[EntitlementCell]:
        """Return the (persona, domain) cells a group grants."""
        page_token = ""
        cells: list[EntitlementCell] = []
        while True:
            params: dict[str, str] = {
                "object_type": "cell",
                "relation": "assumable_by",
                "subject_type": "group",
                "subject_id": group_id,
                "subject_relation": "member",
            }
            if page_token:
                params["page.token"] = page_token
            r = self._client.get("/api/v3/directory/relations", params=params)
            if r.status_code == 404:
                return []
            r.raise_for_status()
            body = r.json()
            for rel in body.get("results") or body.get("relations") or []:
                cell_id: str = rel.get("object_id", "")
                # cell_id shape: "<PERSONA>:<DOMAIN>"
                if ":" not in cell_id:
                    logger.warning(
                        "malformed cell id %r from topaz — expected "
                        "<PERSONA>:<DOMAIN>; skipping",
                        cell_id,
                    )
                    continue
                persona, domain = cell_id.split(":", 1)
                cells.append(EntitlementCell(persona=persona, domain=domain))
            page_token = (body.get("page") or {}).get("next_token", "")
            if not page_token:
                break
        return cells


# ---------------------------------------------------------------------------
# Per-token cache.
# ---------------------------------------------------------------------------


@dataclass
class _CachedEntry:
    entitlements: Entitlements
    expires_at: float  # UNIX seconds


class EntitlementCache:
    """In-process cache of Entitlements keyed by JWT (sub, jti).

    TTL = token's `exp` claim. Miss → asks the client for a fresh
    matrix and caches. On cache miss + topaz unreachable, raises
    `AuthorizationUnavailable`.

    Not distributed — one cache per cortex-bff replica. Fine for
    entitlement matrices (small, per-user); if we ever need cross-
    replica invalidation (revocation hook, ADR-0026 deferred #2),
    that'll be a proper backing store, not this in-process dict.

    Thread-safe via a coarse lock — cortex-bff sees low enough
    concurrency that finer-grained locking isn't worth the read
    complexity.
    """

    def __init__(self, client: TopazDirectoryClient):
        self._client = client
        self._entries: dict[tuple[str, str], _CachedEntry] = {}
        self._lock = threading.Lock()

    def get(self, sub: str, jti: str, exp: float) -> Entitlements:
        """Return cached matrix or fetch fresh.

        Uses `(sub, jti)` as the key. `exp` is the JWT's expiry
        (UNIX seconds); entries beyond expiry are evicted lazily.
        """
        key = (sub, jti)
        now = time.time()

        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                # Update the returned copy's source flag so downstream
                # observability can distinguish cache hits from fresh
                # fetches without another network trip.
                cached = entry.entitlements.model_copy(update={"source": "cache"})
                return cached

        # Fetch outside the lock — the topaz call can take milliseconds
        # to seconds; holding the lock during network I/O is wasteful.
        # Redundant simultaneous fetches for the same key are cheap
        # (both hit topaz once each; whichever finishes first wins the
        # cache slot).
        fresh = self._client.get_entitlements(sub)

        with self._lock:
            self._entries[key] = _CachedEntry(
                entitlements=fresh,
                expires_at=exp,
            )
            # Opportunistic cleanup — reap entries expired > 60s ago.
            self._evict_expired(now - 60.0)
        return fresh

    def invalidate(self, sub: str, jti: str) -> None:
        """Explicit eviction. Used on logout or by the revocation
        hook when it lands (ADR-0026 deferred #2)."""
        with self._lock:
            self._entries.pop((sub, jti), None)

    def _evict_expired(self, threshold: float) -> None:
        """Called under `self._lock`."""
        stale = [k for k, v in self._entries.items() if v.expires_at < threshold]
        for k in stale:
            self._entries.pop(k, None)
