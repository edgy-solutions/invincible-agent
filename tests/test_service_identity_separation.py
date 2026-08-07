"""Each service identity mints with ITS OWN credentials — pinned, because a name lied once.

THE BUG THIS EXISTS FOR (2026-08-07). `mint_service_token()` has a GENERAL name and
REVIEW-STARTER-SPECIFIC behaviour: it reads REVIEW_STARTER_CLIENT_ID/SECRET. The supervisor's
dispatch mint was wired against the NAME, so every specialist POST would have carried
`svc:review-starter` — a role holding `can_invoke(mesh:startReview)`. A confused deputy
introduced while fixing the confused deputy, inert only because nothing verifies tokens yet.

THE MISS IS THE INSTRUCTIVE PART. The wiring commit checked that a mint HAPPENED and a token
ATTACHED — presence checks — but never decoded WHOSE token. **The mint's witness is the
decoded subject, not the 200.** These pins encode that: every mint call site names its own
credential pair, and no call site may reach the misnamed general wrapper.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_IDENTITY = _ROOT / "agent_fleet" / "utils" / "service_identity.py"
_SUPERVISOR = _ROOT / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_general_mint_comes_FROM_THE_SDK_not_a_local_copy():
    """CONTRACT MOVED, deliberately. This asserted `def mint_token(...)` lived HERE. The one
    implementation now lives in the SDK leaf (iagent_mesh.service_identity), and the platform
    holds only thin per-identity BINDINGS. Asserting the import — rather than a local def —
    is the stronger property: it cannot be satisfied by a second copy."""
    s = _src(_IDENTITY)
    assert re.search(r"from iagent_mesh\.service_identity import .*mint_token", s), (
        "the platform must CONSUME the SDK's mint, not define its own"
    )


def test_no_inline_mint_survives_in_the_platform():
    """ONE IMPLEMENTATION, PROVEN BY ABSENCE. The two mints were never transcriptions — they
    had different env contracts and had already drifted. A stray inline body here would be
    the drift re-seeded, so the token-endpoint call and its response parsing must appear
    NOWHERE in the platform's identity module."""
    s = _src(_IDENTITY)
    for stray in ("httpx.post", "access_token", "grant_type"):
        assert stray not in s, (
            f"inline mint body survives ({stray!r}) — that is a second implementation"
        )


def test_supervisor_mints_its_OWN_identity_not_the_review_starters():
    """THE REGRESSION PIN. `mint_service_token()` here means the supervisor dispatches as
    svc:review-starter, carrying that role's capability grant on every specialist call."""
    s = _src(_SUPERVISOR)
    assert "mint_supervisor_token" in s, "supervisor must mint its own identity"
    assert not re.search(r"import\s+mint_service_token|mint_service_token\(\)", s), (
        "supervisor reaches the REVIEW-STARTER mint — confused deputy"
    )


def test_supervisor_credentials_are_its_own_env_pair():
    s = _src(_IDENTITY)
    m = re.search(r"def mint_supervisor_token.*?(?=\ndef |\Z)", s, re.S)
    assert m, "mint_supervisor_token missing"
    assert "SUPERVISOR_CLIENT_ID" in m.group(0) and "SUPERVISOR_CLIENT_SECRET" in m.group(0)
    assert "REVIEW_STARTER" not in m.group(0), "supervisor must not read review-starter env"


def test_the_sensors_path_is_untouched():
    """UNTOUCHED-BEHAVIOUR SEAL. The fix must not move the sensor off svc:review-starter —
    its capability grant targets that subject by name."""
    s = _src(_IDENTITY)
    m = re.search(r"def mint_service_token.*?(?=\ndef |\Z)", s, re.S)
    assert m and "REVIEW_STARTER_CLIENT_ID" in m.group(0), (
        "the review-starter mint changed — the sensor's identity must be stable"
    )
    assert "mint_service_token" in _src(_SENSOR) or "REVIEW_STARTER_CLIENT_ID" in _src(_SENSOR)


def test_the_misnamed_wrapper_carries_its_anti_propagation_marker():
    """A general NAME over specific BEHAVIOUR is the defect's root. Leaving the name
    unmarked is how the next caller repeats it — so the marker is part of the fix."""
    s = _src(_IDENTITY)
    m = re.search(r"def mint_service_token.*?(?=\ndef |\Z)", s, re.S)
    body = m.group(0)
    assert "NEW CALLERS" in body and "DO NOT USE" in body.upper()
    assert "mint_token" in body, "the marker must name the general function as the destination"
