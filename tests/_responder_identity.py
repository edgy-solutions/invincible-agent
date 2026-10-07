"""Identify WHAT answers at a URL, not just WHETHER something does.

A bare TCP connect (or even an HTTP GET that only checks for a 2xx) cannot distinguish an
absent service from a FOREIGN one holding the same port. On a shared workstation a port
number is not a reservation: `localhost:8084` can be Engine O one day and an unrelated
container's `/health` the next, and both answer a plain socket probe. The TCP-only gate
then runs ~36 tests against the wrong service, and they fail with whatever status that
service happens to return (405, a parse error, ...) — a red that is actually an
environment fact (R-086: a suite that could not run is void, not red), not a defect in
the thing under test.

This module adds the third state the TCP probe cannot see:

    absent   — nothing answered (refused / timed out / DNS failure)
    foreign  — something answered, but its response does not match what the
               caller expects from the real service (wrong shape, wrong content)
    expected — something answered and it matches

Callers supply an `is_expected` predicate keyed to the real producer's actual response
shape (see `is_engine_o` / `is_weaviate` below), so the probe reads from the producer
rather than restating an assumption about it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

_CACHE: dict[tuple[str, str], "Identity"] = {}

#: The routing integration suite's target, in ONE place. Ruled by Chris 2026-10-06: a
#: non-colliding port, so the suite's default stops depending on whatever else is bound to
#: :8084 on this machine (measured: an OpenDDIL demo container, see conftest.py's header).
#: Lane 1's port-forward then targets THIS port: `kubectl -n sandbox port-forward svc/iagent-engine-o
#: 18084:8084`. Five modules plus this suite's conftest used to each restate
#: `os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")` independently; `routing_base_url()`
#: below is the one place that default lives now. `tests/routing/test_a_foreign_responder_is_void_not_red.py`
#: seals that no other file spells a default for the same env var.
ENGINE_O_TEST_DEFAULT = "http://localhost:18084"


def routing_base_url() -> str:
    """The routing suite's target: ``ROUTING_TEST_BASE_URL``, defaulting to a non-colliding port."""
    return os.getenv("ROUTING_TEST_BASE_URL", ENGINE_O_TEST_DEFAULT)


@dataclass(frozen=True)
class Identity:
    state: str  # "absent" | "foreign" | "expected"
    detail: str


def _printable(raw: bytes, limit: int = 80) -> str:
    text = raw.decode("utf-8", errors="replace")[:limit]
    return "".join(ch if ch.isprintable() or ch in "\n\r\t" else "?" for ch in text)


def probe(
    url: str,
    path: str,
    is_expected: Callable[[int, str, bytes], bool],
    timeout: float = 1.5,
) -> Identity:
    """Fetch `url + path` and classify the response as absent / foreign / expected.

    Cached per (url, path) for the session — repeated calls within one test run must not
    re-issue the request (and must not let a transient hiccup on the second call flip the
    verdict the rest of the suite already skipped or ran against).
    """
    key = (url, path)
    if key in _CACHE:
        return _CACHE[key]

    target = url.rstrip("/") + path
    status: int
    content_type: str
    body: bytes
    try:
        with urllib.request.urlopen(target, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as e:
        # An HTTP error status is still a RESPONSE — some other service, or even the real
        # service in a documented error posture (Engine O's 503 "not-ready" is one), is
        # there and spoke. Only a connection-level failure means nothing is listening.
        status = e.code
        content_type = e.headers.get("Content-Type", "") if e.headers else ""
        body = e.read() if hasattr(e, "read") else b""
    except (urllib.error.URLError, OSError, TimeoutError):
        identity = Identity(state="absent", detail=f"no response from {target}")
        _CACHE[key] = identity
        return identity

    if is_expected(status, content_type, body):
        identity = Identity(state="expected", detail=f"{status} {content_type}")
    else:
        identity = Identity(
            state="foreign",
            detail=f"status={status} content-type={content_type!r} body={_printable(body)!r}",
        )
    _CACHE[key] = identity
    return identity


def is_engine_o(status: int, content_type: str, body: bytes) -> bool:
    """True iff this is Engine O's own `/health` response.

    Derived from the producer, `agent_fleet/ontology_service/main.py`'s `@app.get("/health")`
    (~line 4831-4865), not restated independently:
      - ready:     200, JSON object with `jena_configured` (and `neo4j_configured`) keys.
      - not-ready: 503, JSON object whose `missing` is a list and whose `detail` names what's
                   missing — the deploy-fault posture, still genuinely Engine O.
    Anything else (wrong status, non-JSON, JSON missing those keys — e.g. a Prometheus
    text/plain 200, or a bare `{"status": "ok"}` from an unrelated service) is foreign.
    """
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(obj, dict):
        return False
    if status == 200 and "jena_configured" in obj:
        return True
    if status == 503 and isinstance(obj.get("missing"), list) and "engine-o" in str(obj.get("detail", "")):
        return True
    return False


def void_reason(url: str, detail: str) -> str:
    """Shared VOID skip-reason text for a foreign responder, naming the URL that collided.

    Per R-086 ("a suite that could not run is void, not red"): these tests did not run, and
    that must be reported as no information, never as a pass.
    """
    return (
        f"VOID — a DIFFERENT service answers at {url} ({detail}). This is a port collision, "
        f"not the expected service: these tests did not run. Point them elsewhere or free the "
        f"port. A void run is not a green — it must be reported as no information, not as a pass."
    )


def is_weaviate(status: int, content_type: str, body: bytes) -> bool:
    """True iff this is Weaviate's own `/v1/meta` response (status 200, JSON object with
    `version` and `modules` keys — Weaviate's documented `/v1/meta` shape)."""
    if status != 200:
        return False
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(obj, dict) and "version" in obj and "modules" in obj
