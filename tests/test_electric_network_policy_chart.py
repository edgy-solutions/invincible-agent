"""Only the BFF reaches Electric: the network policy's selectors, port and population are DERIVED from the
render, never restated here.

* the policy selects exactly the pod labels of the rendered Electric Deployment;
* it admits exactly the pod labels of the rendered Deployment that carries ELECTRIC_UPSTREAM_URL (the BFF),
  and nothing else, on exactly the port Electric's container listens on;
* census: the set of pod templates that name the Electric service is exactly that one consumer, so a NEW
  consumer fails here until it is added to the policy;
* its own switch (`electric.networkPolicy.enabled`) turns it off, with a control that it is OFF by default
  while the fleet gate `networkPolicy.enabled` is off.

Rendering proves nothing about enforcement: whether this cluster's CNI enforces NetworkPolicy is a roll check.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_REL = "rel"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*extra: str, on: bool = True) -> list[dict]:
    sw = ["--set", "electric.networkPolicy.enabled=true"] if on else []
    r = subprocess.run(["helm", "template", _REL, str(_CHART), *sw, *extra], capture_output=True, text=True,
                       cwd=str(_REPO), timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _pod(doc: dict) -> dict:
    return (doc.get("spec") or {}).get("template", {}).get("spec") or {}


def _policy(docs):
    return [d for d in docs if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == f"{_REL}-electric-ingress"]


def _workloads(docs):
    return [d for d in docs if d.get("kind") in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob")]


def _containers(doc):
    pod = _pod(doc) or (doc.get("spec", {}).get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec") or {})
    return list(pod.get("containers") or []) + list(pod.get("initContainers") or [])


def _electric(docs):
    out = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == f"{_REL}-electric"]
    assert len(out) == 1
    return out[0]


def _consumers(docs):
    """Workloads (other than Electric itself) whose containers name the Electric service or its upstream env."""
    el = f"{_REL}-electric"
    found = []
    for d in _workloads(docs):
        if d["metadata"]["name"] == el:
            continue
        if any(el in json.dumps(c) or "ELECTRIC_UPSTREAM_URL" in json.dumps(c) for c in _containers(d)):
            found.append(d)
    return found


def _labels(doc):
    return doc["spec"]["template"]["metadata"]["labels"]


def _selector(labels):
    return {k: labels[k] for k in ("app.kubernetes.io/name", "app.kubernetes.io/component")}


def test_the_policy_selects_electric_and_admits_only_the_bff_on_electrics_port():
    docs = _render()
    (pol,) = _policy(docs)
    el = _electric(docs)
    (bff,) = _consumers(docs)
    spec = pol["spec"]
    assert spec["policyTypes"] == ["Ingress"]
    assert spec["podSelector"]["matchLabels"] == _selector(_labels(el))
    (rule,) = spec["ingress"]
    assert rule["from"] == [{"podSelector": {"matchLabels": _selector(_labels(bff))}}]
    port = el["spec"]["template"]["spec"]["containers"][0]["ports"][0]["containerPort"]
    assert rule["ports"] == [{"protocol": "TCP", "port": port}]


def test_the_only_consumer_of_electric_is_one_pod_template_and_it_is_the_bff():
    docs = _render()
    consumers = _consumers(docs)
    assert [c["metadata"]["name"] for c in consumers] == [f"{_REL}-cortex-bff"]   # control: found, not vacuous
    assert _labels(consumers[0])["app.kubernetes.io/component"] != _labels(_electric(docs))["app.kubernetes.io/component"]


def test_it_is_off_by_default_and_on_with_its_own_switch_while_the_fleet_gate_is_off():
    assert _policy(_render(on=False)) == []   # enabling a perimeter is the operator's decision
    docs = _render()
    assert len(_policy(docs)) == 1
    assert not [d for d in docs if d.get("kind") == "NetworkPolicy"
                and d["metadata"]["name"].endswith(("-engine-o-ingress", "-weaviate-ingress"))]


def test_its_own_switch_turns_it_off():
    assert _policy(_render("--set", "electric.networkPolicy.enabled=false")) == []
    assert _policy(_render("--set", "electric.enabled=false")) == []


def test_the_direct_ingress_admits_the_controller_namespace_when_enabled():
    docs = _render("--set", "electric.ingress.enabled=true",
                   "--set", "networkPolicy.ingressControllerNamespaceSelector.name=ingress")
    (pol,) = _policy(docs)
    froms = pol["spec"]["ingress"][0]["from"]
    assert len(froms) == 2 and froms[1] == {"namespaceSelector": {"matchLabels": {"name": "ingress"}}}
    # and not when the ingress is off (control: the BFF alone)
    (pol,) = _policy(_render("--set", "networkPolicy.ingressControllerNamespaceSelector.name=ingress"))
    assert len(pol["spec"]["ingress"][0]["from"]) == 1


def test_a_new_consumer_of_electric_is_seen_by_the_census():
    # the census's own positive control: a second pod that names Electric is reported, so the sole-consumer
    # seals above go red until the policy admits it on purpose.
    docs = _render("--set", "cortexUi.env.ELECTRIC_UPSTREAM_URL=http://rel-electric:3000")
    assert sorted(c["metadata"]["name"] for c in _consumers(docs)) == [f"{_REL}-cortex-bff", f"{_REL}-cortex-ui"]
