"""The iagent-mesh-mcp chart: resource-server client hook, required values, optional deployment.

Run: uv run --frozen python -m pytest tests/test_mcp_chart.py -v
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "iagent-mesh-mcp"
_SENTINEL = "SENTINEL-not-a-real-credential-0001"
_DIGEST = "sha256:" + "a" * 64
_MIN = {
    "keycloak.url": "http://kc.example:8080",
    "keycloak.adminSecret.name": "hand-made-admin",
    "client.credentialSecret.name": "hand-made-client",
    "client.exchangeAudience": "some-audience",
}


def _render(values: dict[str, str]) -> subprocess.CompletedProcess:
    args = ["helm", "template", "rel", str(_CHART)]
    for k, v in values.items():
        args += ["--set", f"{k}={v}"]
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def _ok(values: dict[str, str]) -> str:
    r = _render(values)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_hook_job_carries_version_check_exchange_attribute_and_both_mappers():
    out = _ok(_MIN)
    assert "helm.sh/hook" in out and "post-install,post-upgrade" in out
    assert "/admin/serverinfo" in out
    assert "older than 26.2" in out and "exit 3" in out
    assert '"standard.token.exchange.enabled":"true"' in out
    assert out.count("oidc-audience-mapper") == 1  # one shared function adds both
    assert 'ensure_aud audience-self "$CID"' in out
    assert 'ensure_aud audience-exchange "$XAUD"' in out
    assert 'XAUD="some-audience"' in out
    for flag in ('"publicClient":false', '"standardFlowEnabled":false',
                 '"directAccessGrantsEnabled":false', '"serviceAccountsEnabled":false'):
        assert flag in out


def test_secrets_only_via_secretkeyref_and_no_value_in_render():
    vals = {**_MIN, "client.credentialSecret.key": "k", "keycloak.adminSecret.passwordKey": "p"}
    out = _ok(vals)
    assert out.count("secretKeyRef") == 3
    assert "set -x" not in out
    assert "echo \"$CLIENT_SECRET" not in out and "echo $CLIENT_SECRET" not in out
    planted = _ok({**_MIN, "client.clientId": _SENTINEL})  # control: the sentinel is detectable
    assert _SENTINEL in planted
    assert _SENTINEL not in out


@pytest.mark.parametrize("key", list(_MIN))
def test_each_required_value_empty_fails_the_render(key):
    r = _render({**_MIN, key: ""})
    assert r.returncode != 0
    assert "required" in r.stderr


def test_deployment_absent_by_default_and_present_when_enabled():
    out = _ok(_MIN)
    assert "kind: Deployment" not in out and "kind: Service" not in out
    on = _ok({**_MIN, "deployment.enabled": "true", "image.repository": "r/mcp",
              "image.digest": _DIGEST, "bffUrl": "http://bff.example"})
    assert f"r/mcp@{_DIGEST}" in on
    assert "--bff-url" in on and "http://kc.example:8080/realms/invincible-agent" in on
    assert "kind: Service" in on


@pytest.mark.parametrize("digest", ["", "latest", "1.2.3", "sha256:abc", "sha256:" + "A" * 64])
def test_enabled_deployment_requires_a_real_digest(digest):
    r = _render({**_MIN, "deployment.enabled": "true", "image.repository": "r/mcp",
                 "image.digest": digest, "bffUrl": "http://bff.example"})
    assert r.returncode != 0


def test_enabled_deployment_requires_bff_url():
    r = _render({**_MIN, "deployment.enabled": "true", "image.repository": "r/mcp",
                 "image.digest": _DIGEST})
    assert r.returncode != 0 and "bffUrl" in r.stderr


def test_invincible_agent_chart_is_unchanged_by_this_chart():
    # the main chart must not reference the new one; the byte-identical render is checked by the
    # implementer against a pre-change render
    hits = [p for p in (_REPO / "helm" / "invincible-agent").rglob("*")
            if p.is_file() and b"iagent-mesh-mcp" in p.read_bytes()]
    assert hits == []


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh not installed")
def test_the_client_body_is_valid_json_for_a_secret_with_quotes_and_backslashes():
    import json
    import os

    out = _ok(_MIN)
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if "SECRET_JSON=" in ln)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "}")
    script = "\n".join(ln.strip() for ln in lines[start : end + 1]) + "\nbody\n"
    hostile = 'a"b\c\\"d'
    env = {**os.environ, "CID": "iagent-mesh", "CLIENT_SECRET": hostile}
    r = subprocess.run(["sh", "-s"], input=script, capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["secret"] == hostile
