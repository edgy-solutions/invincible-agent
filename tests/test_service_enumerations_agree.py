"""Two seals enumerate "the mesh services". They must not disagree.

MEASURED 2026-08-21, and this is why the file exists. Engine P was born with no transport-auth
dependency AND no manifest rows. Exactly one of the two guards caught it:

    tests/test_transport_auth_applied_everywhere.py   GLOB over agent_fleet/*/main.py   -> CAUGHT
    tests/test_endpoint_gating_manifest.py            hand-kept SERVICE_FILES dict      -> BLIND

The glob's own comment says why it wins: *"the population is broad, and the single exclusion
below is NAMED."* A derived population cannot forget a new member. A hand-kept one forgets
silently, and its silence is indistinguishable from coverage — the phantom-scope shape
(`legacy-dns-guard-phantom-scope`), arriving through an enumeration rather than a path.

WHY THIS TEST AND NOT "JUST DERIVE SERVICE_FILES". The manifest dict maps a service NAME to a
source PATH, and three of its entries are not `agent_fleet/*/main.py` at all — the projector
lives under `src/iagent/`, the domain broker under `helm/.../files/`. A glob cannot produce
that mapping without inventing naming rules, and inventing them would trade a visible gap for
an invisible one. So the dict stays hand-kept and this test makes forgetting it FAIL rather
than pass quietly: the derived population becomes the floor the hand-kept one must cover.

The reverse direction is deliberately NOT asserted. SERVICE_FILES legitimately contains
entries the app-glob never sees, and requiring symmetry would force the glob to widen into
paths it has no business scanning.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load(mod_name: str):
    """Import a sibling test module for its constants without running its tests."""
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / "tests" / f"{mod_name}.py")
    assert spec and spec.loader, f"cannot load tests/{mod_name}.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def populations():
    gating = _load("test_endpoint_gating_manifest")
    transport = _load("test_transport_auth_applied_everywhere")
    return gating, transport


def test_both_enumerations_are_inhabited(populations):
    """Positive control. If either population came back empty the comparison below would pass
    over nothing — this file's own subject, applied to itself."""
    gating, transport = populations
    assert len(gating.SERVICE_FILES) >= 10, "SERVICE_FILES shrank — the dict or the import moved"
    assert len(transport._APPS) >= 5, "the app glob matched almost nothing — the glob broke"


def test_every_globbed_app_is_declared_in_the_gating_manifests_service_list(populations):
    """THE SEAL. A mesh app the route-declaration check cannot see is an undeclared surface
    that reports as covered.

    Adding a service here is two lines; the failure this prevents is an engine shipping ten
    routes with no gating posture and a green manifest suite saying nothing was wrong.
    """
    gating, transport = populations
    declared_paths = {
        str((_ROOT / rel).resolve()) for rel in gating.SERVICE_FILES.values()
    }
    missing = sorted(
        str(p.relative_to(_ROOT)) for p in transport._APPS
        if str(p.resolve()) not in declared_paths
    )
    assert not missing, (
        "mesh app(s) found by the transport-auth glob but ABSENT from "
        "test_endpoint_gating_manifest.SERVICE_FILES:\n  "
        + "\n  ".join(missing)
        + "\n\nThe gating check is parametrised over that dict, so these services' routes are "
        "not checked for a declared posture AT ALL — and the suite passes, which is worse than "
        "failing. Add the service to SERVICE_FILES and give it manifest rows."
    )


def test_every_declared_service_file_exists(populations):
    """The cheap other half: a dict entry pointing at a moved or deleted file makes that
    service's route check pass over an empty source, which reads exactly like compliance."""
    gating, _ = populations
    gone = sorted(rel for rel in gating.SERVICE_FILES.values() if not (_ROOT / rel).is_file())
    assert not gone, f"SERVICE_FILES entries whose source is missing: {gone}"
