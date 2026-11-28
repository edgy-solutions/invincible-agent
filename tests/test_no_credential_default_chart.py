"""THE CHART SHIPS NO DEFAULT FOR A CREDENTIAL (0.4.94).

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


# ── the CLASS seal: independent of the overlay (gov's item 3 on #586) ─────────────────────────
# The seal above takes its census from the overlay, so a credential the overlay omits is invisible
# to it. This one reads every tracked values file and every template for the CLASS: a leaf named
# like a credential, with a value, and a `default "<literal>"` on such a read.
#
# A leaf that is a Kubernetes object or key NAME is not a credential; the allowlist names those by
# FULL PATH, never by leaf: `secretKey` names a key at keycloak.brokers.openddil.secretKey and is a
# credential at minioBucketInit.secretKey.
_CRED_LEAF = re.compile(r"(?i)(password|secret|accesskey|access_key|aws_\w*key)")
# Leaves that name a Secret object or a key in one, throughout the chart.
_NAME_LEAVES = {"secretref", "secretname", "existingsecret", "pgpasswordsecretkey"}
# Full paths whose value is a NAME.
_NAME_PATHS = {
    "primeSubstrate.caBundle.secretKey",
    "cortexBff.tlsTrust.secretKey",
    "keycloak.brokers.openddil.secretKey",
}
# Full paths that ARE credentials with a literal, exempt BY NAME, for one stated reason: the
# Postgres literals are the Postgres-literals PR, which follows #586. Remove these three when it lands.
_POSTGRES_PENDING = {
    "postgresql.auth.password",
    "postgresql.auth.postgresPassword",
    "externalPostgresql.password",
}
_ALLOW = _NAME_PATHS | _POSTGRES_PENDING
_TRACKED_VALUES = ("values.yaml", "values-sandbox.yaml")


def _is_cred_leaf(path: str) -> bool:
    leaf = path.rsplit(".", 1)[-1]
    return bool(_CRED_LEAF.search(leaf)) and leaf.lower() not in _NAME_LEAVES


def _walk(d, p=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _walk(v, f"{p}{k}.")
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _walk(v, f"{p}{i}.")
    else:
        yield p[:-1], d


def _literal_credentials(doc) -> list[str]:
    """Full paths in one values document that carry a non-empty scalar under a credential-like leaf
    and are not on the allowlist. Paths only: never the value."""
    return sorted(p for p, v in _walk(doc)
                  if _is_cred_leaf(p) and v not in (None, "") and p not in _ALLOW)


_DEFAULT_AFTER = re.compile(r"\.Values\.([\w.]+)[^}]*?\|\s*default\s+\"[^\"]+\"")
_DEFAULT_BEFORE = re.compile(r"default\s+\"[^\"]+\"\s+\.Values\.([\w.]+)")


def _defaulted_credential_reads(text: str) -> list[int]:
    """Line numbers where a credential-like `.Values` read is piped into `default "<literal>"`."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for rx in (_DEFAULT_AFTER, _DEFAULT_BEFORE):
            for m in rx.finditer(line):
                if _is_cred_leaf(m.group(1)):
                    hits.append(n)
    return sorted(set(hits))


@pytest.mark.parametrize("name", _TRACKED_VALUES)
def test_no_tracked_values_file_carries_a_credential_literal(name):
    doc = yaml.safe_load((_REPO / _CHART / name).read_text(encoding="utf-8"))
    assert not _literal_credentials(doc), (
        f"{name} carries a non-empty value under a credential-like key at: {_literal_credentials(doc)}")


def test_the_class_allowlist_has_no_stale_entry():
    """Every allowlisted path is still a non-empty leaf in a tracked file; an entry that matches
    nothing hides the next literal that takes its place."""
    present = set()
    for name in _TRACKED_VALUES:
        doc = yaml.safe_load((_REPO / _CHART / name).read_text(encoding="utf-8"))
        present |= {p for p, v in _walk(doc) if v not in (None, "")}
    stale = sorted(_ALLOW - present)
    assert not stale, f"allowlisted paths that no tracked values file sets: {stale}"


def test_no_template_pipes_a_credential_read_into_a_literal_default():
    hits = []
    for p in sorted((_REPO / _CHART / "templates").glob("*")):
        for n in _defaulted_credential_reads(p.read_text(encoding="utf-8")):
            hits.append(f"{p.name}:{n}")
    assert not hits, f"a template defaults a credential-like read to a literal at: {hits}"


def test_the_class_seal_fires_on_a_literal_put_back():
    """CONTROL. The seal must see the literal that was removed from values.yaml (userDeployments
    pub-tools codeLocation.env AWS_SECRET_ACCESS_KEY), a key the overlay does not name."""
    doc = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    env = doc["userDeployments"]["pub-tools"]["codeLocation"]["env"]
    assert "AWS_SECRET_ACCESS_KEY" in env and _literal_credentials(doc) == []
    env["AWS_SECRET_ACCESS_KEY"] = "x"
    assert _literal_credentials(doc) == ["userDeployments.pub-tools.codeLocation.env.AWS_SECRET_ACCESS_KEY"]


@pytest.mark.parametrize("line", [
    '{{ .Values.domainBroker.s3AccessKey | default "x" | quote }}',
    '{{ default "x" .Values.someDeployment.apiPassword }}',
])
def test_the_template_seal_fires_on_a_literal_default(line):
    """CONTROL for the template half of the class seal."""
    assert _defaulted_credential_reads(line) == [1]


def test_the_template_seal_lets_a_name_default_through():
    assert _defaulted_credential_reads('{{ default "password" .Values.electric.db.secret.key }}') == []
    assert _defaulted_credential_reads('{{ .Values.domainBroker.pgPasswordSecretKey | default "x" }}') == []


# ── the MinIO pair has ONE home (gov's item 1) ─────────────────────────────────────────────
def _render_files(extra: list[str], tmp_path: Path, monkeypatch, values: dict | None = None):
    monkeypatch.setenv("IAGENT_NO_RENDER_OVERLAY", "1")
    cmd = ["helm", "template", "t", _CHART, "-f", str(_OVERLAY), *extra]
    if values is not None:
        f = tmp_path / "v2.yaml"
        f.write_text(yaml.safe_dump(values), encoding="utf-8")
        cmd += ["-f", str(f)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO), timeout=300)


def test_every_minio_consumer_takes_the_one_pair(tmp_path, monkeypatch):
    """Seven sites carried the pair as literals: four userDeployments env maps, agentFleet.env,
    cortexBff.env and domainBroker's access-key default. All now resolve from
    minioBucketInit.accessKey / .secretKey, so a rotation of two values moves all of them."""
    r = _render_files(["-f", str(_REPO / _CHART / "values-sandbox.yaml")], tmp_path, monkeypatch)
    assert r.returncode == 0, r.stderr[-400:]
    assert "minio-sandbox" not in r.stdout, "a rendered object still carries the old MinIO literal"
    acc = r.stdout.count("render-only-minioBucketInit-accessKey")
    sec = r.stdout.count("render-only-minioBucketInit-secretKey")
    # access key: the bucket-init job + 7 sites; secret key: the job + the 6 env sites (the domain
    # broker's secret has its own required key, domainBroker.s3SecretKey).
    assert acc >= 8, f"access key reaches {acc} places, expected the job and seven consumers"
    assert sec >= 7, f"secret key reaches {sec} places, expected the job and six consumers"


@pytest.mark.parametrize("key", ["accessKey", "secretKey"])
def test_an_unset_minio_pair_refuses_and_names_itself(key, tmp_path, monkeypatch):
    r = _render_files(["-f", str(_REPO / _CHART / "values-sandbox.yaml")], tmp_path, monkeypatch,
                      {"minioBucketInit": {key: ""}})
    assert r.returncode != 0
    assert f"minioBucketInit.{key} is unset" in r.stderr, r.stderr[-300:]


# ── externalNeo4j.password (gov's item 2) ───────────────────────────────────────────────────
def test_an_external_neo4j_without_a_password_refuses_and_names_it(tmp_path, monkeypatch):
    base = {"neo4j": {"enabled": False}, "externalNeo4j": {"uri": "bolt://external:7687"}}
    r = _render_files([], tmp_path, monkeypatch, base)
    assert r.returncode != 0
    assert "externalNeo4j.password is unset" in r.stderr, r.stderr[-300:]
    ok = _render_files([], tmp_path, monkeypatch,
                       {**base, "externalNeo4j": {**base["externalNeo4j"], "password": "render-only-ext"}})
    assert ok.returncode == 0, ok.stderr[-300:]


# ── the realm import is the ONLY guard when reconcile is off (gov's item 4) ──────────────────
def test_with_reconcile_off_the_realm_import_alone_refuses_an_unset_doc_tools_secret(tmp_path, monkeypatch):
    """`keycloak.docToolsClientSecret` is read only by the realm import (keycloak-configmap.yaml)
    and the reconcile helper; `secrets.yaml` does not carry it. With reconcile OFF the realm
    import's `required` is its only guard, so dropping it renders `"secret": ""`. The parametrized
    case above (reconcile on) cannot see that, because the helper refuses first.

    Reconcile ALONE (the helper's `required` dropped, the realm import's kept) is equivalent by
    reach, judged by reading and not by measurement: realm-reconcile-job.yaml renders only under
    keycloak.enabled AND reconcileClients.enabled, while keycloak-configmap.yaml renders under
    keycloak.enabled and ranges over the same $allServiceClients. Wherever the helper renders, the
    realm import's `required` fires first on the same key. Do not re-chase it."""
    doc = copy.deepcopy(_OVERLAY_DOC)
    doc["keycloak"]["reconcileClients"] = {"enabled": False}
    doc["keycloak"]["docToolsClientSecret"] = ""
    r = _render(doc, tmp_path, monkeypatch)
    assert r.returncode != 0, "reconcile off and an empty docToolsClientSecret still rendered"
    assert "keycloak.docToolsClientSecret is unset" in r.stderr, r.stderr[-300:]
