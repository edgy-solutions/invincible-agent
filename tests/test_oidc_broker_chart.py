"""OIDC brokering from this realm to OpenDDIL's realm, and ONE identity claim for every species.

What the chart must do (docs/reference/identity-mint-contract.md, "OpenDDIL brokering (sandbox)"):

  (a) the base render is byte-identical to the base sha EXCEPT one explicit line,
      `USER_ENTITLEMENT_CLAIM: "email"`, in the shared `-config` ConfigMap;
  (b) in the sandbox the claim NAME is one string across the BFF env, the service clients'
      authz-id-svc mapper, the cortex-ui attribute mapper and the local users' attribute;
  (c) the realm-reconcile job renders the OpenDDIL IdP, its mappers and the first-login flow;
  (d) NO link-existing-account execution survives in that flow. Asserted twice: on the rendered
      text, and BEHAVIOURALLY, by running the rendered guard loop in a shell against a canned
      Keycloak executions list (a fake `curl` records every PUT);
  (e) the secret reaches the job only through secretKeyRef;
  (f) an enabled broker with an empty issuer / no secret ref / the email claim fails the render;
  (g) onBehalfOf accepts a principal of an ENABLED broker, and the delegate map carries the sub;
  (h) the policy files bind the brokered principal to its sub.

Run: uv run --frozen python -m pytest tests/test_oidc_broker_chart.py -v
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_BASE_SHA = "209077d1"  # master the OIDC change was branched from

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_SANDBOX = ["-f", str(_REPO / _CHART / "values-sandbox.yaml")]
_SECRET = "iagent-broker-openddil"


def _set(path: str, value) -> list[str]:
    return ["--set-json", f"{path}={json.dumps(value)}"]


_BROKER_ON = [*_set("keycloak.brokers.openddil.enabled", True),
              *_set("keycloak.brokers.openddil.existingSecret", _SECRET)]
_LIAISON_SUB = "33333333-3333-4333-8333-333333333333"


def _helm(chart: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", chart, *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )


def _render(*args: str) -> str:
    r = _helm(str(_REPO / _CHART), *args)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-1500:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _render_fails(*args: str) -> str:
    r = _helm(str(_REPO / _CHART), *args)
    assert r.returncode != 0, "expected the render to FAIL, but it succeeded"
    return r.stderr


def _docs(rendered: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(rendered) if d]


def _config(rendered: str) -> dict:
    for d in _docs(rendered):
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-config":
            return d["data"]
    raise AssertionError("no t-config ConfigMap")


def _realm(rendered: str) -> dict:
    for d in _docs(rendered):
        if d["kind"] == "ConfigMap" and d["metadata"]["name"].endswith("-keycloak-realm"):
            return json.loads(d["data"]["realm-export.json"])
    raise AssertionError("no realm ConfigMap")


def _job(rendered: str) -> dict:
    for d in _docs(rendered):
        if d["kind"] == "Job" and d["metadata"]["name"].endswith("-realm-reconcile"):
            return d
    raise AssertionError("no realm-reconcile Job")


def _script(rendered: str) -> str:
    return _job(rendered)["spec"]["template"]["spec"]["containers"][0]["args"][0]


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_SANDBOX)


@pytest.fixture(scope="module")
def broker() -> str:
    """The sandbox with the OpenDDIL broker switched ON and its Secret named (the rendered broker)."""
    return _render(*_SANDBOX, *_BROKER_ON)


@pytest.fixture(scope="module")
def base() -> str:
    return _render()


@pytest.fixture(scope="module")
def base_sha_base() -> str:
    """The BARE render of the chart as it stood at the base sha (git archive, read-only)."""
    with tempfile.TemporaryDirectory(prefix="ia-oidc-base-") as td:
        tar = subprocess.run(["git", "archive", _BASE_SHA, "--", _CHART], capture_output=True,
                             cwd=str(_REPO), timeout=60)
        assert tar.returncode == 0, tar.stderr.decode(errors="replace")
        ex = subprocess.run(["tar", "-x"], input=tar.stdout, capture_output=True, cwd=td, timeout=60)
        assert ex.returncode == 0, ex.stderr.decode(errors="replace")
        r = _helm(str(Path(td) / _CHART))
        assert r.returncode == 0, r.stderr[-1500:]
        return r.stdout


# ------------------------------------------------------------------ (a) base unchanged

def test_base_render_differs_from_the_base_sha_only_by_the_explicit_env(base, base_sha_base):
    # The chart version moves with every bump (labels, default image tags); it is not the
    # contract. Normalize the base sha's version to this chart's before diffing.
    ver = re.search(r"^version:\s*(\S+)", (_REPO / _CHART / "Chart.yaml").read_text(encoding="utf-8"), re.M).group(1)
    old = re.sub(r"0.4.35", ver, base_sha_base)
    # The fleet SDK pin moves the same way (the rendered `iagent-mesh @ .../tags/<v>.tar.gz`), and
    # is not this contract either. Read the pin from values.yaml, never restate it.
    sdk = re.search(r'^\s*meshSdkVersion:\s*"?([^"\s]+)', (_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"), re.M).group(1)
    old = re.sub(r"(iagent-mesh-sdk/archive/refs/tags/)v[0-9.]+(\.tar\.gz)", rf"\g<1>{sdk}\g<2>", old)

    def _split(rendered: str) -> tuple[str, str]:
        """(everything but the realm-reconcile Job, that Job's script)."""
        docs = [d for d in re.split(r"^---$", rendered, flags=re.M) if d.strip()]
        job = [d for d in docs if re.search(r"^kind: Job$", d, re.M) and "-realm-reconcile" in d]
        assert len(job) == 1
        return "---".join(d for d in docs if d is not job[0]), job[0]

    def _diff(a: str, b: str) -> list[str]:
        return [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
                if not l.startswith(("---", "+++", "@@"))]

    old_rest, old_job = _split(old)
    new_rest, new_job = _split(base)
    assert _diff(old_rest, new_rest) == ['+  USER_ENTITLEMENT_CLAIM: "email"']
    # 0.4.38: the reconcile Job's present-branch for an existing authz-id-svc mapper was rewritten
    # (chart-owned stale mapper migrated, not merely counted). The ONLY lines the base render may
    # lose from the Job are the old create-only check and its comment; nothing else is removed.
    removed = {l[1:].strip() for l in _diff(old_job, new_job) if l.startswith("-")}
    assert removed <= {
        "# Keycloak `sub` UUID. Does not overwrite an existing mapper: an operator who",
        "# deliberately changed one should not have it silently reverted by an upgrade.",
        'HAS=$(curl -sf -H "$AUTH" "$API/clients/$UUID/protocol-mappers/models" \\',
        "| grep -c 'authz-id-svc' || true)",
        'if [ "$HAS" = "0" ]; then',
        'echo "   present, mapper ok"',
    }, removed


# ------------------------------------------------------------------ (b) one claim name

def test_the_claim_name_is_one_string_for_every_species(sandbox):
    claim = _config(sandbox)["USER_ENTITLEMENT_CLAIM"]
    assert claim == "authz_id"
    realm = _realm(sandbox)

    svc = [c for c in realm["clients"] if c["clientId"].startswith("iagent-")]
    assert svc, "no service clients rendered: the loop below would pass vacuously"
    for c in svc:
        m = {x["name"]: x for x in c["protocolMappers"]}
        assert m["authz-id-svc"]["config"]["claim.name"] == claim, c["clientId"]

    ui = next(c for c in realm["clients"] if c["clientId"] == "cortex-ui")
    um = {x["name"]: x for x in ui["protocolMappers"]}["authz-id-user"]
    assert um["protocolMapper"] == "oidc-usermodel-attribute-mapper"
    assert um["config"]["claim.name"] == claim and um["config"]["user.attribute"] == claim
    assert um["config"]["access.token.claim"] == "true" and um["config"]["id.token.claim"] == "true"

    assert realm["users"], "no import users"
    for u in realm["users"]:
        assert u["attributes"] == {claim: [u["email"]]}, u["username"]


def test_the_brokered_users_attribute_is_the_same_claim(broker):
    script = _script(broker)
    assert '"user.attribute": "authz_id"' in script and '"claim": "sub"' in script


def test_the_bff_and_every_engine_load_the_config_that_carries_the_claim(sandbox):
    carriers = 0
    for d in _docs(sandbox):
        if d["kind"] != "Deployment":
            continue
        for c in d["spec"]["template"]["spec"]["containers"]:
            refs = [e.get("configMapRef", {}).get("name") for e in c.get("envFrom", [])]
            if "t-config" in refs:
                carriers += 1
                assert not any(e.get("name") == "USER_ENTITLEMENT_CLAIM" for e in c.get("env", [])), (
                    f"{d['metadata']['name']} overrides the shared claim env")
    bff = next(d for d in _docs(sandbox) if d["kind"] == "Deployment" and d["metadata"]["name"] == "t-cortex-bff")
    assert any(e.get("configMapRef", {}).get("name") == "t-config"
               for e in bff["spec"]["template"]["spec"]["containers"][0]["envFrom"])
    assert carriers >= 2


def test_local_human_users_list_is_the_import_population(sandbox):
    values = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    listed = {(u["username"], u["email"]) for u in values["keycloak"]["localHumanUsers"]}
    imported = {(u["username"], u["email"]) for u in _realm(sandbox)["users"]}
    assert listed == imported


def test_reconcile_gives_local_users_and_the_ui_client_the_attribute(sandbox):
    script = _script(sandbox)
    for who in ("alice", "bob", "carol", "agent-user"):
        assert re.search(rf'ensure_attr "{re.escape(who)}" ', script), who
    assert 'UN="platform-registrar"' in script and "ensure_attr $UN " in script
    assert "authz-id-user" in script and '"unmanagedAttributePolicy":"ADMIN_EDIT"' in script


def test_a_stale_service_mapper_claim_is_a_readback_failure(sandbox):
    s = _script(sandbox)
    # The chart's own pre-flip mapper is migrated; one the chart does not own still FAILS the readback.
    assert "stale mapper from before the flip" in s
    assert "operator-owned mapper, not migrated" in s


# ------------------------------------------------------------------ (c) the IdP in the job

def test_reconcile_renders_the_idp_the_mappers_and_the_first_login_flow(broker):
    s = _script(broker)
    for frag in (
        # BODY-specific: the readback loop repeats the short fragments, so they would pass vacuously.
        '"providerId":"oidc","enabled":true,"trustEmail":false,"storeToken":false',
        '"pkceEnabled":"true","pkceMethod":"S256","syncMode":"FORCE"',
        '"firstBrokerLoginFlowAlias":"\'"$BFLOW"\'"', 'BFLOW="openddil-first-login"',
        "/identity-provider/import-config", ".well-known/openid-configuration",
        '"identityProviderMapper": "oidc-user-attribute-idp-mapper"',
        '"identityProviderMapper": "oidc-username-idp-mapper"',
        '"template": "openddil.${CLAIM.preferred_username}"',
        "first%20broker%20login/copy",
    ):
        assert frag in s, frag
    assert "https://openddil.invalid/idp/realms/openddil/.well-known" in s


def test_the_client_secret_reaches_the_job_only_through_secretkeyref(broker):
    job = _job(broker)
    env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    e = env["BROKER_OPENDDIL_CLIENT_SECRET"]
    assert "value" not in e
    assert e["valueFrom"]["secretKeyRef"] == {"name": "iagent-broker-openddil", "key": "client-secret"}
    assert "iagent-broker-openddil" not in json.dumps(_config(broker))


# ------------------------------------------------------------------ (d) no auto-link survives

_LINK_PROVIDERS = ("idp-review-profile", "idp-auto-link", "idp-confirm-link",
                   "idp-email-verification", "idp-username-password-form")


def test_rendered_guard_names_every_link_path_and_only_ever_writes_disabled(broker):
    s = _script(broker)
    guard = s[s.index("is_guarded() {"):s.index('echo "-- first-login flow')]
    for p in _LINK_PROVIDERS:
        assert f'"providerId":"{p}"' in guard, p
    assert '"displayName":"Handle Existing Account"' in guard
    writes = re.findall(r"""sed 's/"requirement":"\[A-Z\]\*"/"requirement":"([A-Z]+)"/'""", s)
    assert writes and set(writes) == {"DISABLED"}, writes


# A canned executions list shaped like Keycloak's 'first broker login' (compact JSON, no trailing
# newline), plus an auto-link execution in ALTERNATIVE: the one a careless copy leaves enabled.
_EXECUTIONS = [
    {"requirement": "REQUIRED", "displayName": "Review Profile", "providerId": "idp-review-profile", "id": "e1"},
    {"requirement": "REQUIRED", "displayName": "User creation or linking", "authenticationFlow": True, "id": "e2"},
    {"requirement": "ALTERNATIVE", "displayName": "Create User If Unique", "providerId": "idp-create-user-if-unique", "id": "e3"},
    {"requirement": "ALTERNATIVE", "displayName": "Handle Existing Account", "authenticationFlow": True, "id": "e4"},
    {"requirement": "ALTERNATIVE", "displayName": "Automatically set existing user", "providerId": "idp-auto-link", "id": "e5"},
    {"requirement": "REQUIRED", "displayName": "Confirm link existing account", "providerId": "idp-confirm-link", "id": "e6"},
    {"requirement": "ALTERNATIVE", "displayName": "Verify existing account by Email", "providerId": "idp-email-verification", "id": "e7"},
    {"requirement": "REQUIRED", "displayName": "Username Password Form for identity provider reauthentication",
     "providerId": "idp-username-password-form", "id": "e8"},
]


def _find_bash() -> str | None:
    for c in ("C:/Program Files/Git/bin/bash.exe", "/usr/bin/bash", "/bin/bash"):
        if Path(c).exists():
            return c
    return None


_BASH = _find_bash()


@pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")
def test_running_the_rendered_guard_disables_every_link_path_and_nothing_else(broker):
    s = _script(broker)
    body = s[s.index("is_guarded() {"):s.index('rm -f "$EXF"') + len('rm -f "$EXF"')]
    # The flow-exists probe and the copy are not under test: start from "present".
    body = body.replace('grep -q "\\"alias\\":\\"$BFLOW\\""', "true")
    executions = json.dumps(_EXECUTIONS, separators=(",", ":"))
    harness = f"""set -eu
AUTH="Authorization: Bearer x"; API="http://kc/admin/realms/r"; BFLOW="openddil-first-login"
EXECS='{executions}'
curl() {{
  case "$*" in
    *"-X PUT"*) while [ $# -gt 0 ]; do [ "$1" = "-d" ] && printf 'PUT %s\n' "$2" >&2; shift; done ;;
    *"/executions"*) printf '%s' "$EXECS" ;;
    *"/authentication/flows"*) printf '[{{"alias":"openddil-first-login"}}]' ;;
  esac
}}
{body}
"""
    r = subprocess.run([_BASH, "-c", harness], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "disabled:" in r.stdout, (r.stdout, r.stderr)
    sent = [json.loads(l[4:]) for l in r.stderr.splitlines() if l.startswith("PUT ")]
    disabled = {x["id"] for x in sent}
    assert all(x["requirement"] == "DISABLED" for x in sent)
    assert disabled == {"e1", "e4", "e5", "e6", "e7", "e8"}, disabled


# ------------------------------------------------------------------ (f) render failures

def test_enabled_broker_with_empty_issuer_fails_the_render():
    err = _render_fails(*_SANDBOX, *_BROKER_ON, *_set("keycloak.brokers.openddil.issuer", ""))
    assert "issuer is empty" in err and "openddil" in err


def test_enabled_broker_on_the_email_claim_fails_the_render():
    err = _render_fails(*_SANDBOX, *_BROKER_ON, *_set("keycloak.authzClaim", "email"))
    assert "authzClaim" in err and "sub" in err


def _no_broker(out: str) -> None:
    job = json.dumps(_job(out))
    assert "identity-provider" not in _script(out) and "BROKER_OPENDDIL" not in job
    assert "openddil-first-login" not in out and "secretKeyRef" not in job


def test_sandbox_renders_no_broker(sandbox, broker):
    _no_broker(sandbox)
    assert "no existingSecret" not in _script(sandbox)  # disabled says nothing; enabled-without-secret says NOTE
    assert "identity-provider" in _script(broker)  # the positive control: the same render, broker on


def test_enabled_broker_with_its_secret_renders_idp_mappers_flow_and_the_secretkeyref(broker):
    s = _script(broker)
    assert "identity-provider" in s and 'BFLOW="openddil-first-login"' in s
    assert '"identityProviderMapper": "oidc-user-attribute-idp-mapper"' in s
    env = {e["name"]: e for e in _job(broker)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["BROKER_OPENDDIL_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"] == {
        "name": _SECRET, "key": "client-secret"}
    other = _render(*_SANDBOX, *_BROKER_ON, *_set("keycloak.brokers.openddil.secretKey", "k2"))
    env = {e["name"]: e for e in _job(other)["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["BROKER_OPENDDIL_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"]["key"] == "k2"


def test_enabled_broker_without_its_secret_renders_nothing_and_does_not_fail(sandbox):
    out = _render(*_SANDBOX, *_set("keycloak.brokers.openddil.enabled", True),
                  *_set("keycloak.brokers.openddil.existingSecret", ""))
    _no_broker(out)
    assert "openddil enabled but no existingSecret: skipped" in _script(out)
    assert "enabled but no existingSecret" not in _script(sandbox)  # sandbox (disabled) says nothing


# ------------------------------------------------------------------ (g) onBehalfOf

def test_onbehalfof_names_a_declared_principal_whether_or_not_the_broker_renders(sandbox, broker):
    want = sorted(["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", _LIAISON_SUB])
    assert json.loads(_config(broker)["DELEGATE_ON_BEHALF_OF"])["svc:openddil"] == want
    assert json.loads(_config(sandbox)["DELEGATE_ON_BEHALF_OF"])["svc:openddil"] == want  # broker off: still renders
    # A name nobody declares is still refused.
    err = _render_fails(*_SANDBOX, *_set("keycloak.brokers.openddil.principals", []))
    assert "operator.atlantia" in err and "declared keycloak.brokers" in err


def test_the_mirrored_users_are_gone_from_the_non_interactive_list(sandbox):
    values = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    assert [u["username"] for u in values["keycloak"]["nonInteractiveUsers"]] == ["platform-registrar"]


# ------------------------------------------------------------------ (h) grants bind to the sub

def test_policy_binds_the_brokered_liaison_to_its_sub():
    users = yaml.safe_load((_REPO / "policy/users.yaml").read_text(encoding="utf-8"))
    ids = [u["id"] for u in (users["users"] if isinstance(users, dict) else users)]
    assert _LIAISON_SUB in ids and "liaison@example.com" not in ids
    grants = yaml.safe_load((_REPO / "policy/task_grants.yaml").read_text(encoding="utf-8"))
    flat = json.dumps(grants)
    assert "liaison@example.com" not in flat
    def _find(node):
        if isinstance(node, dict):
            if "document_promotion:MAINTENANCE" in node:
                return node["document_promotion:MAINTENANCE"]
            for v in node.values():
                r = _find(v)
                if r is not None:
                    return r
        return None

    block = _find(grants)
    assert block is not None and block["grant_to"] == [_LIAISON_SUB]
    # the join: the sub the policy keys on is the one the chart's principal list declares
    vs = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    p = {x["username"]: x["sub"] for x in vs["keycloak"]["brokers"]["openddil"]["principals"]}
    assert p["liaison.coalition"] == _LIAISON_SUB


def test_the_broker_is_disabled_in_the_base_and_in_the_sandbox_with_no_secret_named():
    base_v = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    sb_v = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    assert base_v["keycloak"]["brokers"]["openddil"]["enabled"] is False
    assert sb_v["keycloak"]["brokers"]["openddil"]["enabled"] is False
    assert base_v["keycloak"]["brokers"]["openddil"]["existingSecret"] == ""
    assert sb_v["keycloak"]["brokers"]["openddil"]["existingSecret"] == ""


# ------------------------------------------------------------------ (i) authz_id defaults to email

def _local_users(rendered: str) -> dict[str, dict]:
    """Every LOCAL user the render creates, read from the render: the realm import users, and
    every user the reconcile job gives the attribute (ensure_attr) or creates (UN=)."""
    out: dict[str, dict] = {}
    for u in _realm(rendered)["users"]:
        out[u["username"]] = {"email": u["email"], "import": u.get("attributes", {}).get("authz_id", [None])[0]}
    s = _script(rendered)
    for m in re.finditer(r'^\s*UN="([^"]+)"', s, re.M):
        out.setdefault(m.group(1), {})
    for m in re.finditer(r'ensure_attr (?:"([^"]+)"|\$UN) "([^"]*)"', s):
        who = m.group(1) or re.findall(r'UN="([^"]+)"', s[:m.start()])[-1]
        out.setdefault(who, {})["job"] = m.group(2)
    for m in re.finditer(r"-d '(\{[^']*\"username\"[^']*\})'", s):          # the create body of a non-interactive user
        body = json.loads(m.group(1))
        out.setdefault(body["username"], {})["email"] = body["email"]
    return out


def test_every_local_user_gets_authz_id_equal_to_its_email_by_default(sandbox):
    users = _local_users(sandbox)
    assert len(users) >= 5, users          # positive control: 4 imported + platform-registrar
    assert {"alice", "bob", "carol", "agent-user", "platform-registrar"} <= set(users)
    for name, u in users.items():
        assert u.get("email"), (name, u)
        got = [v for k, v in u.items() if k in ("import", "job")]
        assert got and all(v == u["email"] for v in got), (name, u)
    assert users["alice"].keys() >= {"import", "job"} and "job" in users["platform-registrar"]


def test_an_explicit_authz_id_wins_over_the_email_default():
    out = _render(*_SANDBOX,
                  *_set("keycloak.localHumanUsers", [
                      {"username": "agent-user", "email": "agent@example.com"},
                      {"username": "alice", "email": "alice@example.com", "authzId": "E-1001"},
                      {"username": "bob", "email": "bob@example.com"},
                      {"username": "carol", "email": "carol@example.com"}]),
                  *_set("keycloak.nonInteractiveUsers", [
                      {"username": "platform-registrar", "email": "platform-registrar@example.com", "authzId": "E-9"}]))
    users = {u["username"]: u for u in _realm(out)["users"]}
    assert users["alice"]["attributes"]["authz_id"] == ["E-1001"]
    assert users["bob"]["attributes"]["authz_id"] == ["bob@example.com"]
    s = _script(out)
    assert 'ensure_attr "alice" "E-1001"' in s and 'ensure_attr $UN "E-9"' in s
    assert 'ensure_attr "bob" "bob@example.com"' in s
    assert json.loads(_config(out)["DELEGATE_ON_BEHALF_OF"])["svc:case-runner"] == ["E-9"]


# ------------------------------------------------------------------ (c2) the stale-mapper migration, run

_ENGINE_D = "svc:engine-d"


def _mapper_json(order: str, *, name: str = "email", value: str = _ENGINE_D) -> str:
    """One authz-id-svc mapper as Keycloak returns it: compact, key order NOT fixed."""
    cfg = ('"config":{"claim.name":"%s","claim.value":"%s","jsonType.label":"String",'
           '"access.token.claim":"true"}' % (name, value))
    head = '"id":"m-1234","name":"authz-id-svc"'
    rest = '"protocol":"openid-connect","protocolMapper":"oidc-hardcoded-claim-mapper","consentRequired":false'
    if order == "id-first":
        return "{%s,%s,%s}" % (head, rest, cfg)
    return "{%s,%s,%s}" % (cfg, rest, '"name":"authz-id-svc","id":"m-1234"')  # config first, id last


_OTHER_MAPPER = ('{"id":"m-other","name":"initiator-kind-svc","protocol":"openid-connect",'
                 '"config":{"claim.name":"initiator_kind","claim.value":"delegate"}}')


def _run_engine_d(sandbox: str, mappers: str) -> subprocess.CompletedProcess:
    s = _script(sandbox)
    start = s.index('CID="iagent-engine-d"')
    body = s[start:s.index('CID="iagent-engine-e"', start)]
    harness = """set -eu
AUTH="Authorization: Bearer x"; API="http://kc/admin/realms/r"
curl() {
  case "$*" in
    *"-X PUT"*|*"-X POST"*)
      _m=""; _u=""; _b=""
      while [ $# -gt 0 ]; do
        case "$1" in -X) _m="$2" ;; -d) _b="$2" ;; http*) _u="$1" ;; esac
        shift
      done
      printf '%s %s %s\n' "$_m" "$_u" "$(printf '%s' "$_b" | tr -d ' \n')" >&2 ;;
    *"clients?clientId"*) printf '[{"id":"uuid-1"}]' ;;
    *"protocol-mappers/models"*) printf '%s' "$MAPPERS" ;;
  esac
}
""" + body
    env = {**os.environ, "MAPPERS": mappers}
    return subprocess.run([_BASH, "-c", harness], capture_output=True, text=True, timeout=60, env=env)


def _writes(r: subprocess.CompletedProcess) -> list[tuple[str, str, dict]]:
    out = []
    for l in r.stderr.splitlines():
        m = re.match(r"(PUT|POST) (\S+) (\{.*\})$", l)
        if m:
            out.append((m.group(1), m.group(2), json.loads(m.group(3))))
    return out


@pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")
@pytest.mark.parametrize("order", ["id-first", "id-last"])
def test_a_pre_flip_chart_mapper_is_migrated_in_place(sandbox, order):
    r = _run_engine_d(sandbox, "[%s,%s]" % (_OTHER_MAPPER, _mapper_json(order)))
    assert r.returncode == 0, r.stderr
    w = _writes(r)
    assert [x[0] for x in w] == ["PUT"], w
    _, url, body = w[0]
    assert url == "http://kc/admin/realms/r/clients/uuid-1/protocol-mappers/models/m-1234", url
    assert body["id"] == "m-1234" and body["name"] == "authz-id-svc"
    assert body["config"]["claim.name"] == "authz_id"
    assert body["config"]["claim.value"] == _ENGINE_D
    assert "mapper claim migrated email -> authz_id" in r.stdout


@pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")
def test_an_operator_mapper_is_never_touched(sandbox):
    r = _run_engine_d(sandbox, "[%s]" % _mapper_json("id-first", value="svc:somebody-else"))
    assert r.returncode == 0, r.stderr
    assert _writes(r) == [], r.stderr
    assert "migrated" not in r.stdout


@pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")
def test_a_mapper_already_on_the_claim_is_left_alone(sandbox):
    r = _run_engine_d(sandbox, "[%s]" % _mapper_json("id-first", name="authz_id"))
    assert r.returncode == 0, r.stderr
    assert _writes(r) == [], r.stderr
    assert "present, mapper ok" in r.stdout


@pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")
def test_a_missing_mapper_is_still_created(sandbox):
    r = _run_engine_d(sandbox, "[%s]" % _OTHER_MAPPER)
    assert r.returncode == 0, r.stderr
    w = _writes(r)
    assert [x[0] for x in w] == ["POST"], w
    assert w[0][1].endswith("/clients/uuid-1/protocol-mappers/models")
    assert w[0][2]["config"]["claim.name"] == "authz_id" and w[0][2]["config"]["claim.value"] == _ENGINE_D
