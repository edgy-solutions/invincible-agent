"""What Restate's ingress does with a body, for the test doubles that stand in for it.

The ingress answers HTTP 400 to a request carrying a body when the handler declares no input
parameter, and (symmetrically) to a request with no body when it declares one. "Declares input" is
derived from the REAL handler in `iagent.supervisor_service` (more than the one `ctx` parameter),
never from a typed list.
"""
from __future__ import annotations

import inspect

from src.iagent import supervisor_service as svc

REFUSAL = {"message": "input validation error: Expected body and content-type to be empty"}


def handler_declares_input(handler: str) -> bool:
    """`run/send` and `run` are the `run` handler."""
    name = handler.split("/", 1)[0]
    return len(inspect.signature(getattr(svc, name)).parameters) > 1


def refuses(handler: str, *, has_body: bool) -> bool:
    """True when the ingress would answer 400 to this call."""
    return has_body != handler_declares_input(handler)


def request_has_body(request) -> bool:
    """An httpx.Request carrying a body or a content-type."""
    return bool(request.content) or "content-type" in request.headers
