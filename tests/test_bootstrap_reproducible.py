"""The executable definition of bootstrap-state-debt compliance.

Law: docs/principles/bootstrap-state-debt.md — deployed state must be reproducible from
`helm install` alone; direct durable-store mutation from scripts/ is never a fix.

THIS TEST IS THE DEFINITION OF "DONE." The compliance contract:

  1. Stand up a THROWAWAY namespace.
  2. `helm install` the chart + let the GATED seed Jobs run (demoSeed.enabled-style).
     Run NO hand scripts from scripts/ — none.
  3. Assert routing reaches green.

If any of the assertions below fails on a namespace that got ONLY helm-install (no hand
scripts), then some dependency is satisfied only by a hand-run script — i.e. it is
bootstrap-state debt, and THIS TEST FAILS BY CONSTRUCTION. That is exactly the property the
law needs: a hand-seeded dependency cannot pass.

The single most load-bearing probe is `/find_compatible_verbs` on a catalog subject: it
returns verbs only if the idp:* classes were MERGEd, their subClassOf edges formed (the
phase5 gap — now folded into the doc-tools ingest asset, commit 3dbc83a0), AND the verbs
were registered (the mesh-registrar chain). One green call proves the whole reproducible
chain; a flat/empty result is the fingerprint of a fresh cluster missing a hand-run step.

HOW TO RUN (needs a live cluster — cannot be sealed offline):
    BOOTSTRAP_TEST_ENGINE_O=http://<engine-o-in-throwaway-ns>:8084 \
    BOOTSTRAP_TEST_SUBJECT=http://invincible-agent/idp#Dataset \
    pytest tests/test_bootstrap_reproducible.py -v
Skipped otherwise (it stands up nothing itself — the throwaway namespace + helm install is
the operator's setup, so the test asserts the RESULT of a helm-only install, never mutates).
"""
from __future__ import annotations

import os

import pytest

_ENGINE_O = os.environ.get("BOOTSTRAP_TEST_ENGINE_O", "").strip()
_SUBJECT = os.environ.get("BOOTSTRAP_TEST_SUBJECT", "http://invincible-agent/idp#Dataset").strip()

pytestmark = pytest.mark.skipif(
    not _ENGINE_O,
    reason=(
        "bootstrap-reproducibility test needs a freshly `helm install`ed THROWAWAY namespace: "
        "set BOOTSTRAP_TEST_ENGINE_O=http://<engine-o>:8084 (and optionally BOOTSTRAP_TEST_SUBJECT). "
        "It asserts routing is green with NO hand-run scripts — the executable definition of the "
        "bootstrap-state-debt law (docs/principles/bootstrap-state-debt.md)."
    ),
)


def _post(path: str, body: dict) -> dict:
    import httpx
    r = httpx.post(f"{_ENGINE_O}{path}", json=body, timeout=20.0)
    r.raise_for_status()
    return r.json()


def test_catalog_subject_resolves_compatible_verbs_after_helm_only():
    """THE compliance probe: on a helm-only cluster, a catalog subject must resolve to its
    compatible verbs. Empty => the idp hierarchy / subClassOf edges / verb registrations did
    NOT reproduce from `helm install` alone => a hand-run step is load-bearing => DEBT."""
    resp = _post("/find_compatible_verbs", {"subject_uri": _SUBJECT, "max_hops": 5, "entitled_domains": []})
    verbs = [v.get("verb_iri") for v in (resp.get("verbs") or [])]
    assert verbs, (
        f"NO compatible verbs for {_SUBJECT!r} on a helm-only cluster. Routing did not reproduce "
        f"from `helm install` alone — a hand-run script (subClassOf edges? verb registration?) is "
        f"load-bearing. That is bootstrap-state debt (docs/principles/bootstrap-state-debt.md), and "
        f"this failure is the definition of non-compliance."
    )


def test_subclassof_hierarchy_formed_after_helm_only():
    """The idp subClassOf walk must have formed (the phase5 gap): a child catalog class must
    reach its parent's verbs, which only happens if the subClassOf edges were MERGEd by the
    ingest asset (doc-tools 3dbc83a0), not a hand-run of phase5_catalog_verb_migration.py."""
    child = os.environ.get("BOOTSTRAP_TEST_CHILD_SUBJECT", "http://invincible-agent/idp#Dashboard")
    resp = _post("/find_compatible_verbs", {"subject_uri": child, "max_hops": 5, "entitled_domains": []})
    assert resp.get("verbs"), (
        f"child class {child!r} resolved NO verbs — its subClassOf* walk to the catalog parent did "
        f"not form on a helm-only cluster. The subClassOf edges must come from the reproducible "
        f"ingest asset, never a hand-run script."
    )
