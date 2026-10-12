"""Dry-run of the OpenDDIL broker flip: the flip is values (two switches + the secret file), nothing else.

Renders the chart with the committed values-sandbox.yaml PLUS an in-test override holding ONLY what the
flip adds: the two `enabled: true` switches, a FAKE 64-hex clientSecret and a FAKE secret-name for the leaf (the PEM itself lives in a Secret made out of band).
Builds on tests/test_oidc_broker_realm_roundtrip.py (PR #29) and tests/fake_keycloak_curl.py.

Run: uv run --frozen python -m pytest tests/test_oidc_broker_flip_dry_run.py -v
"""
from __future__ import annotations

import base64
import json
import secrets
import shutil

import pytest
import yaml

from tests.test_oidc_broker_chart import (
    _CHART, _REPO, _SANDBOX, _docs, _job, _render, _render_fails, _script, _set,
)
from tests.test_oidc_broker_realm_roundtrip import (
    _FLOW, _SEED, _broker_body, _idp, _mappers, _run, _seeded, needs_bash,
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_ISSUER = "https://openddil.cortex.edgy-solutions.com/idp/realms/openddil"
_FAKE_SECRET = secrets.token_hex(32)  # 64 hex, generated in-test
_SECRET_KEY = "broker-openddil-client-secret"


def _override(tmp_path, secret: str = "keycloak-openddil-trust", name: str = "flip.yaml") -> list[str]:
    p = tmp_path / name
    p.write_text(yaml.safe_dump({"keycloak": {
        "brokers": {"openddil": {"enabled": True, "clientSecret": _FAKE_SECRET}},
        "truststore": {"enabled": True, "existingSecret": secret, "key": "ca.pem"}}}), encoding="utf-8")
    return ["-f", str(p)]


@pytest.fixture(scope="module")
def flipped(tmp_path_factory) -> str:
    return _render(*_SANDBOX, *_override(tmp_path_factory.mktemp("flip")))


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX)


def _by_kind(rendered: str, kind: str) -> list[dict]:
    return [d for d in _docs(rendered) if d["kind"] == kind]


def _keycloak_sts(rendered: str) -> dict:
    (sts,) = [d for d in _by_kind(rendered, "StatefulSet") if d["metadata"]["name"] == "t-keycloak"]
    return sts


# ---------------------------------------------------------------- arm 1: the flip is the switches
def test_arm1_the_flip_renders_the_openddil_broker(flipped, sandbox):
    s = _script(flipped)
    assert "== broker openddil ==" in s
    assert 'BALIAS="openddil"' in s
    assert f"{_ISSUER}/.well-known/openid-configuration" in s
    assert "iagent-broker" in s
    assert f'BFLOW="{_FLOW}"' in s
    sub = s[s.index('"name": "openddil-sub-to-authz-id"'):]
    sub = sub[:sub.index('echo "   created"')]
    assert '"syncMode": "FORCE"' in sub and '"claim": "sub"' in sub, "sub mapper is not a FORCE sub mapper"
    env = {e["name"]: e for e in _job(flipped)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["BROKER_OPENDDIL_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"] == {
        "name": "t-secrets", "key": _SECRET_KEY}
    # the negative half of the pair: the committed values alone render none of it
    assert "== broker openddil ==" not in _script(sandbox) and "identity-provider" not in _script(sandbox)
    assert "BROKER_OPENDDIL" not in json.dumps(_job(sandbox)) and "openddil-first-login" not in sandbox


# ---------------------------------------------------------------- arm 2: by reference only
def test_arm2_the_secret_value_is_only_in_the_secret_object(flipped):
    b64 = base64.b64encode(_FAKE_SECRET.encode()).decode()
    hits = []
    for d in _docs(flipped):
        txt = json.dumps(d)
        if _FAKE_SECRET in txt or b64 in txt:
            hits.append((d["kind"], d["metadata"]["name"]))
    assert hits == [("Secret", "t-secrets")], hits
    (sec,) = [d for d in _by_kind(flipped, "Secret") if d["metadata"]["name"] == "t-secrets"]
    got = sec.get("stringData", {}).get(_SECRET_KEY) or base64.b64decode(sec["data"][_SECRET_KEY]).decode()
    assert got == _FAKE_SECRET
    assert _FAKE_SECRET not in _script(flipped)


# ---------------------------------------------------------------- arm 3: the pinned leaf reaches Keycloak
def test_arm3_the_pinned_leaf_reaches_keycloak(flipped, tmp_path):
    pod = _keycloak_sts(flipped)["spec"]["template"]
    c = pod["spec"]["containers"][0]
    env = {e["name"]: e.get("value") for e in c["env"]}
    assert env.get("KC_TRUSTSTORE_PATHS", "").endswith("/ca.pem"), env
    (m,) = [m for m in c["volumeMounts"] if m["mountPath"] == "/opt/keycloak/conf/truststores"]
    assert m["readOnly"] is True
    (v,) = [v for v in pod["spec"]["volumes"] if v["name"] == m["name"]]
    assert v["secret"]["secretName"] == "keycloak-openddil-trust" and "configMap" not in v
    assert not [d for d in _by_kind(flipped, "ConfigMap") if "truststore" in d["metadata"]["name"]]
    # the chart cannot see the Secret's content; naming a different Secret changes the annotation
    other = _render(*_SANDBOX, *_override(tmp_path, "keycloak-openddil-trust-2"))
    a = pod["metadata"]["annotations"]["checksum/truststore"]
    b = _keycloak_sts(other)["spec"]["template"]["metadata"]["annotations"]["checksum/truststore"]
    assert a != b, "a different trust source must roll Keycloak"


def test_arm3_enabled_with_no_source_fails_the_render():
    err = _render_fails(*_SANDBOX, *_set("keycloak.truststore.enabled", True),
                        *_set("keycloak.truststore.existingSecret", ""))
    assert "existingSecret" in err and "existingConfigMap" in err


# ---------------------------------------------------------------- arm 4: an untrusted self-signed issuer
def test_arm4_enabled_https_broker_without_truststore_fails_and_publicca_passes():
    on = [*_SANDBOX, *_set("keycloak.brokers.openddil.enabled", True),
          *_set("keycloak.brokers.openddil.clientSecret", _FAKE_SECRET)]
    err = _render_fails(*on)
    assert "keycloak.truststore.enabled is false" in err and "openddil" in err
    assert "== broker openddil ==" in _script(_render(*on, *_set("keycloak.brokers.openddil.publicCA", True)))


# ---------------------------------------------------------------- arm 5: reconcile against the fake Keycloak
@pytest.fixture(scope="module")
def passes(flipped):
    body = _broker_body(_script(flipped))
    first = _run(body, _seeded(_SEED))
    return first, _run(body, first.state)


@needs_bash
def test_arm5_one_pass_builds_the_idp_flow_and_both_mappers(passes):
    first, _ = passes
    assert first.rc == 0 and "FAIL" not in first.out, first.out[-1500:]
    (idp,) = _idp(first.state)
    assert idp["config"]["issuer"] == _ISSUER and idp["firstBrokerLoginFlowAlias"] == _FLOW
    ms = _mappers(first.state)
    sub = [m for m in ms if m["config"].get("claim") == "sub"]
    assert len(sub) == 1 and sub[0]["config"]["syncMode"] == "FORCE", ms
    assert [m for m in ms if m["identityProviderMapper"] == "oidc-username-idp-mapper"]


@needs_bash
def test_arm5_second_pass_changes_nothing(passes):
    first, second = passes
    assert first.posts(), "positive control: the first pass must have written"
    assert second.rc == 0 and "FAIL" not in second.out
    assert second.posts() == [], second.posts()
    deletes = [c for c in second.calls if c["m"] == "DELETE"]
    assert deletes == [], deletes
    # The script re-PUTs the IdP instance every pass (so a rotated secret lands); that is a refresh,
    # not a change: the dump below must be identical. Anything else PUT is a defect.
    puts = sorted({c["p"] for c in second.calls if c["m"] == "PUT"})
    assert puts == ["/identity-provider/instances/openddil"], puts
    assert second.state == first.state


# ---------------------------------------------------------------- arm 6: committed values enable nothing
def test_arm6_committed_sandbox_values_enable_no_broker_and_no_truststore(sandbox):
    v = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))["keycloak"]
    assert v["brokers"]["openddil"]["enabled"] is False and v["truststore"]["enabled"] is False
    assert not v["brokers"]["openddil"].get("clientSecret") and "caPem" not in v["truststore"]
    assert "truststore" not in sandbox and "KC_TRUSTSTORE_PATHS" not in sandbox
    assert "broker-openddil-client-secret" not in sandbox
