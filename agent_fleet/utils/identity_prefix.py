"""The identity prefix: ONE function that composes a client id from a role name.

Several instances can share one Keycloak realm. Each one sets ``IAGENT_IDENTITY_PREFIX`` (the
chart renders it into the shared ConfigMap) and every client id it mints with, or compares
``azp`` against, is ``prefix + role``. With the variable unset or empty nothing changes.

THE RULE (docs/proposals/one-realm-many-instances-the-identity-prefix.md, section 1): call sites
keep the ROLE name (a literal, or the value of an ``*_CLIENT_ID`` env var). The composition
happens exactly once, in the lowest helper before the client id leaves the process: the SDK's
``mint_token(client_id=...)`` or a Keycloak token-endpoint form post. A role that already starts
with the prefix is refused, loudly, so an id is never prefixed twice.

ONE MODULE OBJECT. Both trees import this as ``agent_fleet.utils.identity_prefix`` (the engine
images flatten it to ``utils.identity_prefix``, through the same try/except the neighbouring
imports use). There is no second copy: two copies are two exception classes with one name.
"""
from __future__ import annotations

import os
import re

__all__ = ["PREFIX_ENV", "PREFIX_PATTERN", "IdentityPrefixError", "identity_prefix", "compose_client_id"]

PREFIX_ENV = "IAGENT_IDENTITY_PREFIX"
PREFIX_PATTERN = r"^[a-z][a-z0-9]{0,11}-$"
_PREFIX_RE = re.compile(PREFIX_PATTERN)


class IdentityPrefixError(ValueError):
    """The prefix is malformed, or a role name already carries it."""


def identity_prefix() -> str:
    """The instance's prefix, read from the environment NOW (not at import).

    Unset or empty is ``""``. Anything else must match ``PREFIX_PATTERN`` exactly; whitespace is
    not stripped, so ``" t-"`` is invalid.
    """
    value = os.environ.get(PREFIX_ENV, "")
    if value == "":
        return ""
    if not _PREFIX_RE.fullmatch(value):
        raise IdentityPrefixError(
            f"{PREFIX_ENV}={value!r} does not match the pattern {PREFIX_PATTERN} "
            "(lower-case, at most 12 characters, one trailing hyphen, none inside)"
        )
    return value


def compose_client_id(role: str) -> str:
    """``prefix + role``; the role unchanged when the prefix is empty.

    Refuses an empty role, and a role that already starts with the non-empty prefix (naming it).
    """
    if not role:
        raise IdentityPrefixError("compose_client_id: the role name is empty")
    prefix = identity_prefix()
    if not prefix:
        return role
    if role.startswith(prefix):
        raise IdentityPrefixError(
            f"role name {role!r} already starts with the instance prefix {prefix!r}; "
            "call sites carry the role name only, the prefix is added once at the mint"
        )
    return prefix + role
