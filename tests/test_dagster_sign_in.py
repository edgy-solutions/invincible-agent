"""The optional Dagster sign-in (oauth2-proxy): off by default, refuses to render unsafe.

Run: uv run --frozen pytest tests/test_dagster_sign_in.py -v
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_P = "dagster.webserver."

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_ENABLED = [
    "--set", _P + "ingress.enabled=true",
    "--set", _P + "signIn.enabled=true",
    "--set", _P + "signIn.existingSecret=s",
    "--set", _P + "signIn.allowedRoles={admin}",
]


def _run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )


def _render(*extra: str) -> list[dict]:
    r = _run(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _dagster_ingress(docs):
    got = [d for d in docs if d["kind"] == "Ingress" and d["metadata"]["name"] == "t-dagster"]
    assert len(got) == 1
    return got[0]


def _backend(docs):
    return _dagster_ingress(docs)["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]


def _signin_objects(docs):
    return [d for d in docs if "signin" in d["metadata"]["name"]]


def test_default_render_has_no_proxy_and_ingress_points_at_the_webserver():
    ing = ["--set", _P + "ingress.enabled=true"]
    default = _render(*ing)
    control = _render(*ing, "--set", _P + "signIn.clientId=x")
    assert not _signin_objects(default)
    assert not _signin_objects(control)
    assert _backend(default)["name"] == "t-dagster"
    assert _backend(default) == _backend(control)
    assert _backend(default)["port"]["number"] == 3000


def test_enabled_renders_a_proxy_by_digest_with_secrets_by_reference():
    docs = _render(*_ENABLED)
    dep = [d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-dagster-signin"]
    svc = [d for d in docs if d["kind"] == "Service" and d["metadata"]["name"] == "t-dagster-signin"]
    assert len(dep) == 1 and len(svc) == 1
    c = dep[0]["spec"]["template"]["spec"]["containers"][0]
    assert c["image"].startswith("quay.io/oauth2-proxy/oauth2-proxy@sha256:")
    assert "--allowed-role=admin" in c["args"]
    assert "--upstream=http://t-dagster:3000" in c["args"]
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in c["env"]}
    assert env["OAUTH2_PROXY_CLIENT_SECRET"] == {"name": "s", "key": "client-secret"}
    assert env["OAUTH2_PROXY_COOKIE_SECRET"] == {"name": "s", "key": "cookie-secret"}
    sc = c["securityContext"]
    assert sc["runAsNonRoot"] and sc["readOnlyRootFilesystem"]
    assert sc["capabilities"]["drop"] == ["ALL"]
    # no rendered proxy object carries a value for either key: only references
    text = yaml.safe_dump(_signin_objects(docs))
    assert "value:" not in text
    assert not [d for d in docs if d["kind"] == "Secret" and "signin" in d["metadata"]["name"]]
    b = _backend(docs)
    assert b["name"] == "t-dagster-signin" and b["port"]["number"] == 4180


# (case id, the field the refusal names, args that break exactly that field)
_REFUSALS = [
    ("existingSecret", "signIn.existingSecret", ["--set", _P + "signIn.existingSecret="]),
    ("allowList", "signIn.allowedRoles", ["--set", _P + "signIn.allowedRoles=null"]),
    ("issuer", "signIn.issuerUrl",
     ["--set", "cortexUi.env.VITE_KEYCLOAK_REALM_URL=", "--set", "keycloak.enabled=false",
      "--set", "externalKeycloak.url=", "--set", "externalKeycloak.realmUrl=",
      "--set", "keycloak.realm="]),
    ("ingress", "ingress.enabled", ["--set", _P + "ingress.enabled=false"]),
    ("host", "ingress.hosts", ["--set", _P + "ingress.hosts=null"]),
]


@pytest.mark.parametrize("name,key,breaker", _REFUSALS, ids=[r[0] for r in _REFUSALS])
def test_refusal_names_its_key_and_its_control_renders(name, key, breaker):
    control = _run(*_ENABLED)
    assert control.returncode == 0, control.stderr[-500:]
    r = _run(*_ENABLED, *breaker)
    assert r.returncode != 0, f"{name}: expected a render refusal"
    assert key in r.stderr, r.stderr[-500:]
    assert "dagster.webserver.signIn" in r.stderr or "dagster.webserver.ingress" in r.stderr
