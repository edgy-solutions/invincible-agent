"""EVERY PYTHON POD MUST TRUST THE FLEET CA, FROM VALUES ALONE.

Token checking and token minting happen in many pods, not only the BFF. A private-CA issuer is
reachable from a pod only if that pod's Python stack reads a bundle that holds the CA. The chart
carries ONE top-level `tlsTrust`; each pod template that runs this repo's Python images or a
dag-tools image includes the `iagent.tlsTrust.*` helpers. A template that forgets the include is
a pod that cannot verify the issuer, and nothing else notices until a token is refused.

What this file pins:

(a) the DEFAULT render carries no trace of the feature, and setting the key to its own default
    changes no pod spec (the no-op proof);
(b) with `tlsTrust.secretName` set, EVERY container whose image is not in EXEMPT mounts the
    bundle at mountPath and sets both env vars. EXEMPT is explicit (image substring -> reason),
    and each entry must match a rendered image, so the list cannot go stale or match nothing;
(c) the BFF mounts its own `cortexBff.tlsTrust` bundle when set, the global one when not, never both.

The render uses values-sandbox.yaml plus --set flags so that jobs and optional services render;
no secret values file is involved.

Run: uv run --frozen pytest tests/test_every_python_pod_trusts_the_fleet_ca.py -v
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_MOUNT = "/etc/ssl/work-ca-bundle.pem"
_VOLUME = "fleet-ca-bundle"
_ENV = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

# image substring -> why that image is not given the bundle (third-party; not this repo's Python).
EXEMPT: dict[str, str] = {
    "bitnamilegacy/postgresql": "third-party postgres",
    "library/postgres": "third-party postgres (also the postgres-client job image)",
    "curlimages/curl": "third-party curl, shell-only init and reconcile jobs",
    "library/neo4j": "third-party neo4j",
    "secoresearch/fuseki": "third-party fuseki",
    "semitechnologies/weaviate": "third-party weaviate",
    "restatedev/restate": "third-party restate",
    "aserto-dev/topaz": "third-party topaz",
    "berriai/litellm": "third-party litellm",
    "cortex-ui/frontend": "static frontend, no Python",
    "mirror/electric": "third-party electric",
    "mirror/mc": "third-party minio client",
    "quay.io/keycloak/keycloak": "third-party keycloak",
}

# Enable every optional pod that runs our images, so none escapes the census.
_BROAD = [
    "-f", f"{_CHART}/values-sandbox.yaml",
    "--set", "topazSeed.enabled=true",
    "--set", "taskGrantSync.enabled=true",
    "--set", "topazManifestLoad.enabled=true",
    "--set", "litellm.enabled=true",
    "--set", "demoSeed.enabled=true",
    "--set", "ontologySeed.enabled=true",
    "--set", "primeSubstrate.enabled=true",
    "--set", "primeSubstrate.reregisterEngines.enabled=true",
    "--set", "minioBucketInit.enabled=true",
]


def _render(*extra: str) -> list[dict]:
    """Render and parse. A helm error or empty output fails the test: an absence assertion over
    empty output would pass vacuously (tests/test_chart_renders_on_bare_defaults.py)."""
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    assert docs, "rendered YAML held no objects"
    return docs


def _pod_specs(docs: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in docs:
        kind = d.get("kind")
        if kind in ("Deployment", "StatefulSet", "Job"):
            spec = d["spec"]["template"]["spec"]
        elif kind == "CronJob":
            spec = d["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        else:
            continue
        out[f"{kind}/{d['metadata']['name']}"] = spec
    return out


def _containers(spec: dict) -> list[dict]:
    return list(spec.get("initContainers") or []) + list(spec.get("containers") or [])


def _exempt(image: str) -> bool:
    return any(k in image for k in EXEMPT)


@pytest.fixture(scope="module")
def default_docs() -> list[dict]:
    return _render()


@pytest.fixture(scope="module")
def on_docs() -> list[dict]:
    return _render(*_BROAD, "--set", "tlsTrust.secretName=x")


# ---- (a) default render: no trace, and the key's own default is a no-op ----------------------

def test_default_render_has_no_trace_of_the_fleet_bundle(default_docs: list[dict]):
    text = yaml.safe_dump_all(default_docs)
    assert _VOLUME not in text
    assert "SSL_CERT_FILE" not in text
    assert _pod_specs(default_docs), "no pod specs rendered: the control is empty"


def test_setting_the_key_to_its_default_changes_no_pod_spec(default_docs: list[dict]):
    same = _render("--set", "tlsTrust.secretKey=ca.pem")
    a, b = _pod_specs(default_docs), _pod_specs(same)
    assert a.keys() == b.keys()
    for name in a:
        assert a[name] == b[name], f"{name} changed with tlsTrust.secretKey at its default"


# ---- (b) every non-exempt container trusts the bundle ----------------------------------------

def test_every_exempt_entry_matches_a_rendered_image(on_docs: list[dict]):
    images = [c["image"] for s in _pod_specs(on_docs).values() for c in _containers(s)]
    assert images, "no images rendered"
    dead = [k for k in EXEMPT if not any(k in i for i in images)]
    assert not dead, f"exempt entries that match no rendered image (stale or typo): {dead}"


def test_every_container_running_our_images_mounts_the_bundle_and_sets_both_env(on_docs: list[dict]):
    pods = _pod_specs(on_docs)
    checked = 0
    missing: list[str] = []
    for name, spec in pods.items():
        vols = {v["name"]: v for v in spec.get("volumes") or []}
        for c in _containers(spec):
            if _exempt(c["image"]):
                continue
            checked += 1
            where = f"{name}/{c['name']}"
            mounts = {m["name"]: m for m in c.get("volumeMounts") or []}
            env = {e["name"]: e.get("value") for e in c.get("env") or []}
            if (
                _VOLUME not in vols
                or vols[_VOLUME]["secret"]["secretName"] != "x"
                or _VOLUME not in mounts
                or mounts[_VOLUME]["mountPath"] != _MOUNT
                or not mounts[_VOLUME].get("readOnly")
                or any(env.get(k) != _MOUNT for k in _ENV)
            ):
                missing.append(where)
    assert checked >= 25, f"only {checked} non-exempt containers found: the census is too thin"
    assert not missing, f"containers that do not trust the fleet CA: {sorted(missing)}"


def test_exempt_containers_are_left_alone(on_docs: list[dict]):
    for name, spec in _pod_specs(on_docs).items():
        for c in _containers(spec):
            if not _exempt(c["image"]):
                continue
            env = {e["name"] for e in c.get("env") or []}
            mounts = {m["name"] for m in c.get("volumeMounts") or []}
            assert _VOLUME not in mounts and "SSL_CERT_FILE" not in env, f"{name}/{c['name']}"


# ---- (c) the BFF: its own block wins, else the global one, never both -------------------------

def _bff(docs: list[dict]) -> dict:
    specs = {n: s for n, s in _pod_specs(docs).items() if n.endswith("cortex-bff")}
    assert len(specs) == 1, f"expected one cortex-bff pod, found {sorted(specs)}"
    return next(iter(specs.values()))


def _bundle_secrets(spec: dict) -> list[str]:
    return [
        v["secret"]["secretName"]
        for v in spec.get("volumes") or []
        if v["name"] in (_VOLUME, "work-ca-bundle")
    ]


def test_bff_own_block_wins_and_the_global_is_not_mounted_too():
    spec = _bff(_render("--set", "tlsTrust.secretName=g", "--set", "cortexBff.tlsTrust.secretName=y"))
    assert _bundle_secrets(spec) == ["y"]
    c = [c for c in spec["containers"] if c["name"] == "cortex-bff"][0]
    assert sum(1 for m in c["volumeMounts"] if m["mountPath"] == _MOUNT) == 1


def test_bff_uses_the_global_bundle_when_its_own_is_empty():
    spec = _bff(_render("--set", "tlsTrust.secretName=g"))
    assert _bundle_secrets(spec) == ["g"]
    c = [c for c in spec["containers"] if c["name"] == "cortex-bff"][0]
    env = {e["name"]: e.get("value") for e in c["env"]}
    assert all(env.get(k) == _MOUNT for k in _ENV)


def test_bff_with_neither_mounts_nothing():
    assert _bundle_secrets(_bff(_render())) == []
