"""THE CHART SHIPS NO DEFAULT FOR A CREDENTIAL (0.4.93).

A Keycloak client secret, an admin password or a bucket key with a literal default in
`values.yaml` or a template is a credential published with the chart: every deployment that
did not override it ran on a value anyone could read, and every new realm was imported with it.

So there is no default. Each reader `required`s its key, an unset key stops the render and the
message NAMES the key. Keys covered: the 16 `keycloak.*ClientSecret` keys (15 read by
`secrets.yaml`, `docToolsClientSecret` read only by the realm import, `caseRunnerClientSecret`
once defaulted only inside a template) and 7 non-client keys.

Existing realms keep the secret they were imported with; reconcile never rotates one, so this
protects a NEW realm only. Rotation is a separate decision.

The suite renders with `scripts/values-render-placeholders.yaml` (tests/conftest.py inserts it
into every `helm template`). THIS file turns that off so it can see the refusal.

An assertion message here names a key and never a value.

Run: uv run --frozen pytest tests/test_no_credential_default_chart.py -v
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_OVERLAY = _REPO / "scripts" / "values-render-placeholders.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _flat(d: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in d.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, p + "."))
        else:
            out[p] = v
    return out


_OVERLAY_DOC = yaml.safe_load(_OVERLAY.read_text(encoding="utf-8"))
KEYS = sorted(_flat(_OVERLAY_DOC))
CLIENT_KEYS = [k for k in KEYS if k.endswith("ClientSecret")]


def _render(values: dict | None, tmp_path: Path, monkeypatch) -> subprocess.CompletedProcess:
    monkeypatch.setenv("IAGENT_NO_RENDER_OVERLAY", "1")
    cmd = ["helm", "template", "t", _CHART]
    if values is not None:
        f = tmp_path / "v.yaml"
        f.write_text(yaml.safe_dump(values), encoding="utf-8")
        cmd += ["-f", str(f)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO), timeout=300)


def _without(doc: dict, dotted: str, blank: bool) -> dict:
    d = copy.deepcopy(doc)
    *parents, leaf = dotted.split(".")
    node = d
    for p in parents:
        node = node[p]
    if blank:
        node[leaf] = ""
    else:
        del node[leaf]
    return d


# ── the shape of the set ─────────────────────────────────────────────────────────────────────
def test_the_set_is_sixteen_client_keys_and_seven_others():
    assert len(CLIENT_KEYS) == 16, CLIENT_KEYS
    assert len(KEYS) - len(CLIENT_KEYS) == 7, [k for k in KEYS if k not in CLIENT_KEYS]


# ── control: it renders when every key is set; refuses when none is ──────────────────────────
def test_with_every_key_set_the_chart_renders(tmp_path, monkeypatch):
    r = _render(_OVERLAY_DOC, tmp_path, monkeypatch)
    assert r.returncode == 0, r.stderr[-500:]
    assert "kind: Secret" in r.stdout


def test_on_bare_defaults_the_render_refuses_and_names_a_key(tmp_path, monkeypatch):
    r = _render(None, tmp_path, monkeypatch)
    assert r.returncode != 0
    assert any(k in r.stderr for k in KEYS), r.stderr[-400:]
    assert "is unset" in r.stderr


# ── each key, unset or empty, stops the render and is named ──────────────────────────────────
@pytest.mark.parametrize("blank", [False, True], ids=["absent", "empty-string"])
@pytest.mark.parametrize("key", KEYS)
def test_an_unset_key_refuses_and_names_itself(key, blank, tmp_path, monkeypatch):
    r = _render(_without(_OVERLAY_DOC, key, blank), tmp_path, monkeypatch)
    assert r.returncode != 0, f"{key} unset ({'empty' if blank else 'absent'}) still rendered"
    assert f"{key} is unset" in r.stderr, f"refusal did not name {key}: {r.stderr[-300:]}"


# ── nothing tracked supplies a default ───────────────────────────────────────────────────────
def _get(doc: dict, dotted: str):
    for p in dotted.split("."):
        if not isinstance(doc, dict) or p not in doc:
            return None
        doc = doc[p]
    return doc


def test_values_yaml_carries_no_value_for_any_key():
    doc = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    set_ = [k for k in KEYS if _get(doc, k) not in (None, "")]
    assert not set_, f"values.yaml still ships a default for: {set_}"


def test_the_tracked_sandbox_values_carry_no_credential():
    """Not a client secret, not the neo4j or fuseki password: the sandbox sets all 23 in its
    secret file (values-sandbox.secret.yaml), which is never tracked."""
    doc = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    set_ = [k for k in KEYS if _get(doc, k) not in (None, "")]
    assert not set_, f"values-sandbox.yaml tracks a credential: {set_}"


@pytest.mark.parametrize("key", ["neo4j.auth.password", "fuseki.auth.adminPassword"])
def test_removing_the_sandbox_literal_leaves_the_base_map_in_place(key):
    """A bare `auth:` (null) in a later values file DELETES the base map, and the template then
    fails on a nil pointer rather than naming the key. The sandbox file keeps no empty parent."""
    doc = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    parent = _get(doc, key.rsplit(".", 1)[0])
    assert parent is None or isinstance(parent, dict), f"{key}: parent is {type(parent).__name__}"


def test_no_template_defaults_a_key_it_requires():
    # Whole dotted paths: a bare leaf such as `secretKey` is also a Kubernetes Secret KEY NAME.
    full = "|".join(re.escape(k) for k in KEYS)
    pat = re.compile(r"\.Values\.(%s)[^}]*\|\s*default" % full)
    hits = []
    for p in sorted((_REPO / _CHART / "templates").glob("*")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{p.name}:{n}")
    assert not hits, f"a template defaults a credential key at: {hits}"


# ── the realm import and the Secret read the same value ──────────────────────────────────────
def test_every_client_secret_reaches_the_realm_import_and_the_secret_agrees(tmp_path, monkeypatch):
    r = _render(_OVERLAY_DOC, tmp_path, monkeypatch)
    assert r.returncode == 0, r.stderr[-300:]
    docs = r.stdout.split("\n---\n")
    realm = [d for d in docs if "kind: ConfigMap" in d and '"clients"' in d]
    secret = [d for d in docs if "kind: Secret" in d and "-secrets" in d.split("name:", 1)[-1][:40]]
    assert realm, "no ConfigMap carrying the realm clients"
    assert secret, "no -secrets Secret"
    realm_text, secret_text = "\n".join(realm), "\n".join(secret)
    # caseRunnerClientSecret: the iagent-case-runner CLIENT is declared in values-sandbox.yaml, not
    # in the chart's base clients, so the base realm import does not carry it.
    missing_realm = [k for k in CLIENT_KEYS
                     if not k.endswith("caseRunnerClientSecret")
                     and f"render-only-{k.split('.')[-1]}" not in realm_text]
    assert not missing_realm, f"the realm import does not carry: {missing_realm}"
    # docToolsClientSecret is read only by the realm import; the Secret carries the other 15.
    missing_secret = [k for k in CLIENT_KEYS
                      if not k.endswith("docToolsClientSecret")
                      and f"render-only-{k.split('.')[-1]}" not in secret_text]
    assert not missing_secret, f"the -secrets Secret does not carry: {missing_secret}"
