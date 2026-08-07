"""LOCK 2 — the acting subject is DERIVED from the front-door identity, never named by a caller.

WHAT THIS PINS. The entitlement subject that eventually reaches the central gateway's
`can_read` decision (as `X-Originator-Email`) must be born from a VERIFIED fact — the
authenticated identity at the front door — and populated at exactly ONE guarded site. A
subject a caller can name is not an identity, it is a request field, and a gate keyed on a
request field is checking who the asker CLAIMED asked.

THE PROPERTY IS CURRENTLY TRUE BY ACCIDENT. Read 2026-08-07: the gateway already passes
`user_email=current_user.authz_id`, `InterviewRequest` exposes no identity field, and nothing
assigns the subject from the request body. Nothing enforces any of that — it holds because
nobody has yet added an identity field to the request model, which is a one-line change away
from silently inverting the whole guarantee. These assertions make the regression fail HERE.

SCOPE — READ THIS BEFORE TRUSTING IT. Lock 2 makes the subject's VALUE trustworthy on the
legitimate path. It does NOT make any engine refuse an unauthenticated caller: no engine
verifies inbound auth today (`ENABLE_AGENTIC_AUTH` dark-launches `core/authz.py`'s
verification, default off, ADR-0025 "flips LAST"). So an in-cluster POST straight to
`/analyze_data` can still supply its own subject. That exposure is LOCK 1 / the flip, and it
is not closed by anything in this file. The honest posture after lock 2: *the identity flowing
to the gateway is derived from a real front-door login and cannot be forged by writing the
field on the legitimate path — but transport auth is still deferred.*

NAMING DEBT, deliberately not fixed here: the parameter is called `user_email` and CARRIES the
authz_id (employee-id at work, email in sandbox). gateway.py:3516 already records that a full
rename through supervisor/Engine D/Engine O is owed. Renaming a live cross-service field is its
own change with its own witness; pinning the DERIVATION is what cannot wait.

Source-text assertions because importing the gateway pulls FastAPI/Dagster/httpx, and the claim
is about WIRING, which the source is the authority on (same rationale as
test_engine_e_trace_join.py).

Run:  uv run --frozen python -m pytest tests/test_subject_derivation.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_GATEWAY = _ROOT / "src" / "iagent" / "gateway.py"
_SUPERVISOR = _ROOT / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_DA = _ROOT / "agent_fleet" / "data_analyst" / "main.py"

# The one field carrying the acting subject across the mesh today.
SUBJECT = "user_email"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- the guarded site: derivation from the verified identity ------------------
def test_gateway_derives_the_subject_from_the_authenticated_user():
    """THE load-bearing assertion. The subject is assigned from `current_user`, the
    front-door-verified principal — not from the request, not from a default."""
    src = _src(_GATEWAY)
    assert re.search(rf"{SUBJECT}\s*=\s*current_user\.authz_id", src), (
        "the acting subject must be derived from current_user.authz_id at the launch site"
    )


def test_the_request_model_cannot_name_the_subject():
    """CAN'T-BE-SET-FROM-THE-REQUEST. If the inbound model ever grows an identity field,
    a caller can assert who they are and the gateway's can_read is checking a claim."""
    src = _src(_GATEWAY)
    m = re.search(r"class InterviewRequest\b.*?(?=\nclass |\n@app\.)", src, re.S)
    assert m, "InterviewRequest not found — did the entry model move?"
    body = m.group(0)
    for forbidden in ("user_email", "authz_id", "on_behalf_of", "originator", "user_id"):
        assert not re.search(rf"^\s+{forbidden}\s*:", body, re.M), (
            f"InterviewRequest exposes {forbidden!r} — a caller could NAME the acting subject"
        )


def test_no_request_sourced_assignment_anywhere_in_the_gateway():
    """The subject must never be read off the inbound body, under any spelling."""
    src = _src(_GATEWAY)
    for pat in (rf"{SUBJECT}\s*=\s*req\.", rf"{SUBJECT}\s*=\s*request\.",
                rf"{SUBJECT}\s*=\s*body", rf"{SUBJECT}\s*=\s*payload"):
        assert not re.search(pat, src), f"subject assigned from the request ({pat})"


# --- the hops: forwarded, never rebuilt --------------------------------------
@pytest.mark.parametrize("path,label", [
    (_SUPERVISOR, "supervisor"),
    (_DA, "Engine DA"),
])
def test_each_hop_forwards_the_subject_rather_than_reconstructing_it(path, label):
    """EVERY REBUILDING HOP IS A DROPPING/FORGING SURFACE. Each consumer must take the
    subject from the value handed to it — config/request — never re-derive it from a
    local default, an env var, or a service identity."""
    src = _src(path)
    assert SUBJECT in src, f"{label} no longer carries the subject field"
    for bad in (rf"{SUBJECT}\s*=\s*os\.getenv", rf"{SUBJECT}\s*=\s*['\"]\w+@",
                rf"{SUBJECT}\s*=\s*SERVICE", rf"{SUBJECT}\s*=\s*['\"]svc:"):
        assert not re.search(bad, src), (
            f"{label} RECONSTRUCTS the subject ({bad}) — it must forward what it was given; "
            "a service identity is the transport, never the acting subject"
        )


def test_da_threads_the_subject_to_the_read_gate():
    """DA's only legitimate use: pass it through to the gateway's email-keyed can_read as
    X-Originator-Email. If this stops, the gate silently evaluates for nobody."""
    src = _src(_DA)
    assert re.search(rf"originator_email\s*=\s*request\.get\(\s*[\"']{SUBJECT}[\"']", src)
    assert "originator_email=originator_email" in src


def test_scope_is_recorded_where_someone_would_over_trust_it():
    """The gap lock 2 does NOT close must stay written down at the seam. A future reader
    seeing 'subject is derived' must not conclude 'endpoint is authenticated'."""
    assert "transport auth is still deferred" in __doc__.replace("\n", " ") or \
           "LOCK 1" in __doc__, "the scope caveat must remain in this module's docstring"
