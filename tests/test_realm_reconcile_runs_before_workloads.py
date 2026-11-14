"""The realm reconcile lands before any workload changes on an upgrade, and depends on nothing the
release has not yet replaced.

0.4.85's roll failed in two steps. The reconcile Job could not start (its script was one over-long
`sh -c` argument), and because it was a POST-upgrade hook the new workloads (the BFF, which requires
`aud: cortex-bff`) were already live while the audience mappers it adds had not been created. Moving
it to pre-upgrade makes a failed reconcile stop the roll before anything changes.

A pre-upgrade hook runs while the release's own non-hook objects are still the OLD ones. So the Job
must not depend on any of them: its script (ConfigMap), its request bodies and a non-existingSecret
broker's client secret (Secret) are hook objects of the same phase at a lower weight, so Helm creates
them first. A broker `existingSecret` is made out of band and is the only other thing it may name.

On a fresh install Keycloak is created by this very release, so the reconcile stays post-install.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet"}
# a broker whose client secret is a chart value (not an existingSecret): its key lives in the bodies Secret
_INLINE_BROKER = ["--set-json", "keycloak.brokers.openddil.existingSecret=null",
                  "--set", "keycloak.brokers.openddil.clientSecret=probe-not-a-real-secret"]


def _render(*extra: str, upgrade: bool) -> list[dict]:
    # never a *.secret.yaml: only the committed sandbox values
    cmd = ["helm", "template", "t", str(_CHART), "-f", str(_SANDBOX), *extra]
    if upgrade:
        cmd.append("--is-upgrade")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-1500:]}"
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    assert docs
    return docs


@pytest.fixture(scope="module")
def upgrade() -> list[dict]:
    return _render(upgrade=True)


@pytest.fixture(scope="module")
def install() -> list[dict]:
    return _render(upgrade=False)


@pytest.fixture(scope="module")
def upgrade_inline_broker() -> list[dict]:
    return _render(*_INLINE_BROKER, upgrade=True)


def _hooks(doc: dict) -> set[str]:
    return {h.strip() for h in ((doc.get("metadata") or {}).get("annotations") or {}).get("helm.sh/hook", "").split(",") if h.strip()}


def _weight(doc: dict) -> int:
    return int(doc["metadata"]["annotations"].get("helm.sh/hook-weight", "0"))


def _reconcile_objects(docs: list[dict]) -> dict[str, dict]:
    """The three hook objects of the realm reconcile, by role."""
    def one(kind: str, suffix: str) -> dict:
        (d,) = [d for d in docs if d["kind"] == kind and d["metadata"]["name"] == f"t-{suffix}"]
        return d
    return {"job": one("Job", "realm-reconcile"),
            "script": one("ConfigMap", "realm-reconcile-script"),
            "bodies": one("Secret", "realm-reconcile-bodies")}


# ------------------------------------------------------------------ the phases

def test_on_upgrade_the_reconcile_objects_are_pre_upgrade_hooks_and_not_post_upgrade(upgrade):
    objs = _reconcile_objects(upgrade)
    for role, d in objs.items():
        assert _hooks(d) == {"pre-upgrade"}, f"{role}: {sorted(_hooks(d))}"
        assert "post-upgrade" not in _hooks(d)


def test_on_upgrade_the_configmap_and_secret_come_before_the_job(upgrade):
    o = _reconcile_objects(upgrade)
    assert _weight(o["script"]) < _weight(o["job"]) and _weight(o["bodies"]) < _weight(o["job"])
    assert (_weight(o["script"]), _weight(o["bodies"]), _weight(o["job"])) == (1, 1, 2)
    for role in ("script", "bodies"):
        assert o[role]["metadata"]["annotations"]["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"
    assert o["job"]["metadata"]["annotations"]["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"


def test_on_upgrade_no_workload_is_a_hook_so_every_workload_change_follows_the_pre_upgrade_phase(upgrade):
    workloads = [d for d in upgrade if d["kind"] in _WORKLOADS]
    assert len(workloads) > 5, "positive control: the render has workloads"
    assert any(d["kind"] == "StatefulSet" for d in workloads) and any(d["kind"] == "Deployment" for d in workloads)
    hooked = [f"{d['kind']}/{d['metadata']['name']}" for d in workloads if _hooks(d)]
    assert not hooked, f"a workload is a hook, so it is not changed after the pre-upgrade phase: {hooked}"


def test_on_install_the_reconcile_objects_are_post_install_hooks_and_not_pre_install(install):
    for role, d in _reconcile_objects(install).items():
        assert _hooks(d) == {"post-install"}, f"{role}: {sorted(_hooks(d))}"
        assert "pre-install" not in _hooks(d)


def test_the_other_hooks_stay_post_upgrade(upgrade):
    """Only the reconcile moved. The syncs that assume identities and the engines' startup stay after the roll."""
    names = {d["metadata"]["name"]: _hooks(d) for d in upgrade if d["kind"] in ("Job", "CronJob") and _hooks(d)}
    for suffix in ("-restate-init", "-prime-substrate"):
        got = [h for n, h in names.items() if n.endswith(suffix)]
        if got:
            assert all("post-upgrade" in h and "pre-upgrade" not in h for h in got), (suffix, got)
    assert any("post-upgrade" in h for h in names.values()), "positive control: some hook is still post-upgrade"


# ------------------------------------------------------------------ the Job depends on nothing release-managed

def _refs(job: dict) -> list[tuple[str, str]]:
    """Every (kind, name) the Job's pod spec names: volumes, secretKeyRef, configMapKeyRef, envFrom."""
    spec = job["spec"]["template"]["spec"]
    out: list[tuple[str, str]] = []
    for v in spec.get("volumes") or []:
        if "configMap" in v:
            out.append(("ConfigMap", v["configMap"]["name"]))
        if "secret" in v:
            out.append(("Secret", v["secret"]["secretName"]))
        for src in ((v.get("projected") or {}).get("sources") or []):
            if "configMap" in src:
                out.append(("ConfigMap", src["configMap"]["name"]))
            if "secret" in src:
                out.append(("Secret", src["secret"]["name"]))
    for c in [*(spec.get("containers") or []), *(spec.get("initContainers") or [])]:
        for e in c.get("env") or []:
            vf = e.get("valueFrom") or {}
            if "secretKeyRef" in vf:
                out.append(("Secret", vf["secretKeyRef"]["name"]))
            if "configMapKeyRef" in vf:
                out.append(("ConfigMap", vf["configMapKeyRef"]["name"]))
        for ef in c.get("envFrom") or []:
            if "configMapRef" in ef:
                out.append(("ConfigMap", ef["configMapRef"]["name"]))
            if "secretRef" in ef:
                out.append(("Secret", ef["secretRef"]["name"]))
    return out


def unsafe_dependencies(job: dict, docs: list[dict], existing_secrets: set[str]) -> list[str]:
    """Names the Job uses that are neither a same-phase hook object of lower weight nor a broker existingSecret."""
    phase = _hooks(job)
    by_ident = {(d["kind"], d["metadata"]["name"]): d for d in docs}
    bad = []
    for kind, name in _refs(job):
        if kind == "Secret" and name in existing_secrets:
            continue
        d = by_ident.get((kind, name))
        if d is not None and _hooks(d) == phase and _weight(d) < _weight(job):
            continue
        bad.append(f"{kind}/{name}")
    return sorted(set(bad))


def _existing_secrets(docs: list[dict]) -> set[str]:
    """The broker existingSecret names, read from the values the render used (not typed here)."""
    vals = yaml.safe_load(_SANDBOX.read_text(encoding="utf-8"))
    brokers = (vals.get("keycloak") or {}).get("brokers") or {}
    return {b["existingSecret"] for b in brokers.values() if b.get("enabled") and b.get("existingSecret")}


def test_the_job_names_only_hook_objects_of_its_phase_and_broker_existing_secrets(upgrade):
    job = _reconcile_objects(upgrade)["job"]
    existing = _existing_secrets(upgrade)
    refs = _refs(job)
    # non-vacuous: the Job names the script, the bodies, and an ACTIVE existingSecret broker secret
    assert ("ConfigMap", "t-realm-reconcile-script") in refs and ("Secret", "t-realm-reconcile-bodies") in refs
    assert existing, "positive control: the sandbox renders an active broker with an existingSecret"
    assert any(k == "Secret" and n in existing for k, n in refs), "the active broker's secretKeyRef is not in the Job"
    assert unsafe_dependencies(job, upgrade, existing) == []


def test_the_job_with_a_chart_value_broker_reads_its_secret_from_the_bodies_secret(upgrade_inline_broker):
    docs = upgrade_inline_broker
    o = _reconcile_objects(docs)
    env = {e["name"]: e for e in o["job"]["spec"]["template"]["spec"]["containers"][0]["env"]}
    ref = env["BROKER_OPENDDIL_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "t-realm-reconcile-bodies", "key": "broker-openddil-client-secret"}, ref
    assert "broker-openddil-client-secret" in o["bodies"]["stringData"]
    assert unsafe_dependencies(o["job"], docs, set()) == []


# ------------------------------------------------------------------ control: the dependency check can fire

def test_control_a_broker_secret_pointed_at_the_release_secrets_is_flagged(upgrade_inline_broker):
    docs = upgrade_inline_broker
    job = copy.deepcopy(_reconcile_objects(docs)["job"])
    assert unsafe_dependencies(job, docs, set()) == [], "the unmutated Job is clean (the control's baseline)"
    (c,) = job["spec"]["template"]["spec"]["containers"]
    (env,) = [e for e in c["env"] if e["name"] == "BROKER_OPENDDIL_CLIENT_SECRET"]
    env["valueFrom"]["secretKeyRef"]["name"] = "t-secrets"  # the old, release-managed object
    assert any(d["kind"] == "Secret" and d["metadata"]["name"] == "t-secrets" for d in docs), "t-secrets is rendered"
    assert unsafe_dependencies(job, docs, set()) == ["Secret/t-secrets"]


def test_control_a_volume_of_a_release_configmap_or_a_later_hook_is_flagged(upgrade):
    job = copy.deepcopy(_reconcile_objects(upgrade)["job"])
    existing = _existing_secrets(upgrade)
    job["spec"]["template"]["spec"]["volumes"].append({"name": "x", "configMap": {"name": "t-config"}})
    assert unsafe_dependencies(job, upgrade, existing) == ["ConfigMap/t-config"]
    # same phase but NOT lower weight: the script ConfigMap at the Job's own weight would race it
    job2 = copy.deepcopy(_reconcile_objects(upgrade)["job"])
    docs = copy.deepcopy(upgrade)
    for d in docs:
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-realm-reconcile-script":
            d["metadata"]["annotations"]["helm.sh/hook-weight"] = "2"
    assert unsafe_dependencies(job2, docs, existing) == ["ConfigMap/t-realm-reconcile-script"]
    # and a hook of the wrong phase
    for d in docs:
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-realm-reconcile-script":
            d["metadata"]["annotations"]["helm.sh/hook-weight"] = "1"
            d["metadata"]["annotations"]["helm.sh/hook"] = "post-upgrade"
    assert unsafe_dependencies(job2, docs, existing) == ["ConfigMap/t-realm-reconcile-script"]
