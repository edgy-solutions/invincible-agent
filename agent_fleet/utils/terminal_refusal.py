"""A policy refusal carried through a Restate `TerminalError`, whose only payload is a string.

Architect, 2026-10-27 (ruling 1 on the policy-refusal rule): the refusal rides as JSON in the
message under a fixed prefix -- `refusal:` followed by the Refusal dict -- and is parsed at the
BFF. The SDK grows a typed `Refusal.to_terminal()` / `from_terminal()` pair in v0.9.12; until it
tags, this module is the engines' half and `src/iagent/authz/refusal.py` (`TERMINAL_PREFIX`,
`from_terminal`) is the BFF's. They are two copies because an engine image carries no `src/`;
`tests/security/test_a_relayed_refusal_parses_the_same_on_both_sides.py` holds the two to the
same dict on every message, so neither side hand-rolls a variant.

An engine holds no grantor map, so it never writes `grantable_by`: the BFF fills it from this
deployment's map (`relay_refusal`), and narrows an object-scoped key an engine should not have
named. Stdlib only -- this runs on the deny path, where an import failure would be a 500.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

#: The message prefix that marks a TerminalError as a carried refusal.
PREFIX = "refusal:"


def to_terminal(policy_id: str, missing_binding: str, candidates: Iterable[str] = ()) -> str:
    """The TerminalError message for a refusal: `refusal:` + its JSON, with sorted keys so one
    refusal is one message."""
    body = {"policy_id": policy_id, "missing_binding": missing_binding,
            "candidates": list(candidates)}
    return PREFIX + json.dumps(body, sort_keys=True, separators=(",", ":"))


def from_terminal(message: Any) -> Optional[dict]:
    """The refusal dict a TerminalError message carries, or None when it carries none: not a
    string, no prefix, or a body that is not a JSON object. Never raises."""
    if not isinstance(message, str) or not message.startswith(PREFIX):
        return None
    try:
        body = json.loads(message[len(PREFIX):])
    except (ValueError, RecursionError):  # RecursionError: a deeply nested body
        return None
    return body if isinstance(body, dict) else None
