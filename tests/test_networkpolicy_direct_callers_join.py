"""networkPolicy.directCallers -- one population, two renderings, and the join between them.

The store policy (ingress) and the engine policy (egress) are two halves of one admission. Each
half passing its own arms is how the gate shipped cutting the callers it admitted (measurement
2026-10-08): every endpoint verified, the join unasserted. `networkPolicy.directCallers` is the
single population both templates render from; THIS file asserts the join on the RENDER.

  1  THE JOIN        every rendered egress pair to a store with an ingress policy is admitted by
                     that store's ingress, on that port; every directCallers ingress admission whose
                     caller is an engine with an egress policy is admitted by that engine's egress.
  2  non-vacuity     directCallers-driven egress AND ingress were rendered (the join has a subject).
  3  provenance      every entry carries `via` and an `expires` that has not passed.
  4  reality         every `store` and every caller names a component the chart renders and (so)
                     selects a pod; an engine that is disabled in sandbox is refused.
  5  gate off        the sandbox values render zero NetworkPolicies without the flag.

(The exact-equality per-store arm lives in test_networkpolicy_admits_the_allowlist_by_component.py.)

Run: uv run pytest tests/test_networkpolicy_direct_callers_join.py -v
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"
_COMP = "app.kubernetes.io/component"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None,
    reason="the `helm` binary is not on PATH: a declared condition, not a probe of any cluster",
)


def _render(*extra: str) -> list[dict]:
    cmd = ["helm", "template", "iagent", str(_CHART), "-f", str(_SANDBOX), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"helm template failed: {proc.stderr[-2000:]}"
    return [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict)]


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    return _render("--set", "networkPolicy.enabled=true")


def _policies(docs, kind_key):
    return [d for d in docs if d.get("kind") == "NetworkPolicy" and kind_key in d["spec"]["policyTypes"]]


def _component(pol) -> str:
    return pol["spec"]["podSelector"]["matchLabels"][_COMP]


def _peer_components(peers) -> list[str]:
    return [(p.get("podSelector") or {}).get("matchLabels", {}).get(_COMP)
            for p in peers or [] if (p.get("podSelector") or {}).get("matchLabels", {}).get(_COMP)]


def _egress_pairs(docs) -> set[tuple[str, str, int]]:
    """(engine, target component, port) for every rule whose destination is a chart component."""
    out = set()
    for pol in _policies(docs, "Egress"):
        for rule in pol["spec"].get("egress") or []:
            for tgt in _peer_components(rule.get("to")):
                for port in rule.get("ports") or []:
                    out.add((_component(pol), tgt, int(port["port"])))
    return out


def _ingress_triples(docs) -> set[tuple[str, str, int]]:
    """(caller, store, port) for every ingress rule on a store policy."""
    out = set()
    for pol in _policies(docs, "Ingress"):
        for rule in pol["spec"].get("ingress") or []:
            for caller in _peer_components(rule.get("from")):
                for port in rule.get("ports") or []:
                    out.add((caller, _component(pol), int(port["port"])))
    return out


def _entries():
    cfg = (yaml.safe_load(_SANDBOX.read_text(encoding="utf-8")).get("networkPolicy") or {})
    for caller, entries in (cfg.get("directCallers") or {}).items():
        for e in entries or []:
            yield caller, e


# ---------------------------------------------------------------------------------------------
# 1. THE JOIN
# ---------------------------------------------------------------------------------------------
def test_THE_JOIN_EGRESS_TO_A_STORE_IS_ADMITTED_BY_THE_STORE_AND_THE_REVERSE(docs):
    egress, ingress = _egress_pairs(docs), _ingress_triples(docs)
    stores = {s for _c, s, _p in ingress}
    engines_with_egress = {c for c, _t, _p in egress}

    # egress -> ingress: an engine rule to a store that has an ingress policy
    refused = sorted(
        (eng, tgt, port) for eng, tgt, port in egress
        if tgt in stores and (eng, tgt, port) not in ingress
    )
    assert not refused, (
        "the engine's egress admits a store the store's ingress does not admit it to "
        f"(engine, store, port): {refused}"
    )

    # ingress (directCallers-driven) -> egress: an engine caller with an egress policy
    cut = []
    for caller, e in _entries():
        store = e["store"]
        if caller not in engines_with_egress or store not in stores:
            continue
        for _c, s, port in (t for t in ingress if t[0] == caller and t[1] == store):
            if (caller, store, port) not in egress:
                cut.append((caller, store, port))
    assert not cut, (
        "the store's ingress admits a directCallers engine whose egress policy does not reach it "
        f"(engine, store, port): {sorted(cut)}"
    )


# ---------------------------------------------------------------------------------------------
# 2. the join has a subject
# ---------------------------------------------------------------------------------------------
def test_THE_POPULATION_RENDERS_BOTH_HALVES(docs):
    egress, ingress = _egress_pairs(docs), _ingress_triples(docs)
    engines = {c for c, _t, _p in egress}
    stores = {s for _c, s, _p in ingress}
    driven_egress = [(c, e["store"]) for c, e in _entries()
                     if c in engines and any(x[0] == c and x[1] == e["store"] for x in egress)]
    driven_ingress = [(c, e["store"]) for c, e in _entries()
                      if e["store"] in stores and any(x[0] == c and x[1] == e["store"] for x in ingress)]
    assert driven_egress, "no directCallers entry rendered an engine egress rule: the join has no subject"
    assert driven_ingress, "no directCallers entry rendered a store ingress admission: the join has no subject"
    # a directCallers caller that is NOT otherwise in the six admitted must show up on ingress
    assert any(x[0] == "cortex-bff" and x[1] == "postgresql" for x in ingress)


# ---------------------------------------------------------------------------------------------
# 3. provenance and expiry
# ---------------------------------------------------------------------------------------------
def test_EVERY_ENTRY_HAS_VIA_AND_AN_UNEXPIRED_EXPIRES():
    today = date.today()
    seen = 0
    for caller, e in _entries():
        seen += 1
        where = f"{caller} -> {e.get('store')}"
        assert str(e.get("via") or "").strip(), f"{where}: no `via` (the config key that put it here)"
        raw = e.get("expires")
        assert raw, f"{where}: no `expires`"
        when = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
        assert today <= when, (
            f"{where} expired {when} and is still present ({(today - when).days} days over). "
            "Move the caller onto a Mesh* service and delete the entry, or re-rule the date."
        )
    assert seen, "values-sandbox.yaml carries no directCallers entries"


# ---------------------------------------------------------------------------------------------
# 4. every name is a component the chart renders
# ---------------------------------------------------------------------------------------------
def test_EVERY_STORE_AND_CALLER_NAMES_A_COMPONENT_THE_CHART_RENDERS():
    rendered = {
        (d["metadata"].get("labels") or {}).get(_COMP)
        for d in _render() if d.get("kind") in ("Deployment", "StatefulSet")
    } - {None}
    assert rendered, "the render found no workloads"
    bad = []
    for caller, e in _entries():
        for role, name in (("caller", caller), ("store", e["store"])):
            if name not in rendered:
                bad.append(f"{role} {name!r} (entry {caller} -> {e['store']})")
    assert not bad, (
        "directCallers names a component no rendered workload carries (a selector that matches no "
        "pod is valid YAML and silently admits nothing; a disabled engine is refused): "
        + "; ".join(sorted(set(bad)))
    )


# ---------------------------------------------------------------------------------------------
# 5. the gate stays off
# ---------------------------------------------------------------------------------------------
def test_THE_GATE_OFF_RENDERS_ZERO_NETWORKPOLICIES_WITH_THE_SANDBOX_VALUES():
    cfg = yaml.safe_load(_SANDBOX.read_text(encoding="utf-8")).get("networkPolicy") or {}
    assert not cfg.get("enabled"), "values-sandbox.yaml turns the gate on; this roll is the proposal"
    assert cfg.get("directCallers"), "the population is empty: this arm would be vacuous"
    assert [d for d in _render() if d.get("kind") == "NetworkPolicy"] == []
