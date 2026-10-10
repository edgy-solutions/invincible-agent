"""The OpenDDIL broker segment, EXECUTED against a stateful Keycloak admin-API double, and the
realm it leaves behind asserted as JSON (not as script text).

  Deliverable A  round trip: seed a realm export, run the rendered broker/IdP/flow segment, dump the
                 realm, load the dump into a FRESH double, run again: dump equal, no state-changing
                 POST. Assertions 1-5 are on the dumped JSON (mapper, trustEmail, first-login flow,
                 simulated first broker login).
  Deliverable B  keycloak.retiredUsers: render guards + behaviour against the double.
  Deliverable C  grants bind to the brokered sub: join seals over policy/ and values-sandbox.yaml.

No Docker, no live Keycloak. The double is tests/fake_keycloak_curl.py; it is installed as a bash
function named `curl` (the pattern of tests/test_oidc_broker_chart.py).

Run: uv run python -m pytest tests/test_oidc_broker_realm_roundtrip.py -v
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import yaml

from tests.test_oidc_broker_chart import (
    _BASH, _CHART, _REPO, _SANDBOX, _render, _render_fails, _script, _set,
)

_FAKE = (Path(__file__).resolve().parent / "fake_keycloak_curl.py").as_posix()
_SEED = json.loads((Path(__file__).resolve().parent / "fixtures" / "keycloak_realm_export_seed.json")
                   .read_text(encoding="utf-8"))
_ISSUER = "https://idp.example.test/realms/openddil"
_ALIAS = "openddil"
_FLOW = "openddil-first-login"
_BROKER = ["--set", "keycloak.brokers.openddil.enabled=true",
           "--set", "keycloak.brokers.openddil.existingSecret=x",
           "--set", f"keycloak.brokers.openddil.issuer={_ISSUER}"]
# The spec's independent list of link-capable authenticators / sub-flows (NOT derived from the script).
_LINK_NAMES = {"idp-review-profile", "idp-auto-link", "idp-confirm-link", "idp-detect-existing-broker-user",
               "idp-email-verification", "idp-username-password-form",
               "Handle Existing Account", "Account verification options",
               "Verify Existing Account by Re-authentication"}
_VALUES = yaml.safe_load((_REPO / _CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
_PRINCIPALS = {p["username"]: p["sub"] for p in _VALUES["keycloak"]["brokers"]["openddil"]["principals"]}

needs_bash = pytest.mark.skipif(_BASH is None, reason="a POSIX bash is not available")


# ------------------------------------------------------------------ the harness

@pytest.fixture(scope="module")
def broker_script() -> str:
    return _script(_render(*_SANDBOX, *_BROKER))


@pytest.fixture(scope="module")
def retired_script() -> str:
    return _script(_render(*_SANDBOX))


def _segment(script: str, start: str, end: str, *, end_inclusive: bool = False) -> str:
    a = script.index(start)
    b = script.index(end, a)
    if end_inclusive:
        b = script.index("\n", b)
    return script[a:b]


def _broker_segments(script: str) -> tuple[str, str]:
    """(create/reconcile segment, broker readback segment) cut out of the rendered job."""
    create = _segment(script, 'echo "== broker openddil =="', "# ── READBACK GATE")
    readback = _segment(script, 'IDP=$(curl -sf -H "$AUTH" "$API/identity-provider/instances/openddil"',
                        "guarded executions disabled)", end_inclusive=True)
    return create, readback


def _seeded(state: dict) -> dict:
    s = copy.deepcopy(state)
    for u in s["users"]:
        u.setdefault("id", str(uuid.uuid5(uuid.NAMESPACE_DNS, u["username"])))
    return s


class Run:
    def __init__(self, rc: int, out: str, err: str, state: dict, calls: list[dict]):
        self.rc, self.out, self.err, self.state, self.calls = rc, out, err, state, calls

    def posts(self) -> list[str]:
        """State-changing POSTs. import-config is Keycloak's stateless discovery read; excluded."""
        return [c["p"] for c in self.calls
                if c["m"] == "POST" and not c["p"].endswith("/identity-provider/import-config")]


def _run(body: str, state: dict, *, refuse_delete: bool = False) -> Run:
    with tempfile.TemporaryDirectory(prefix="ia-kc-double-") as td:
        sp, lp = Path(td, "realm.json"), Path(td, "calls.log")
        sp.write_text(json.dumps(state), encoding="utf-8")
        lp.write_text("", encoding="utf-8")
        harness = f"""set -eu
AUTH="Authorization: Bearer x"; API="http://kc/admin/realms/r"; rc=0
curl() {{ "$FAKE_PY" "$FAKE_SCRIPT" "$@"; }}
{body}
exit $rc
"""
        env = {**os.environ, "FAKE_PY": Path(sys.executable).as_posix(), "FAKE_SCRIPT": _FAKE,
               "FAKE_KC_STATE": sp.as_posix(), "FAKE_KC_LOG": lp.as_posix(),
               "FAKE_KC_REFUSE_DELETE": "1" if refuse_delete else "0",
               "BROKER_OPENDDIL_CLIENT_SECRET": "dummy-not-a-secret",
               "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}
        r = subprocess.run([_BASH, "-c", harness], capture_output=True, text=True, timeout=120, env=env)
        calls = [json.loads(l) for l in lp.read_text(encoding="utf-8").splitlines() if l]
        return Run(r.returncode, r.stdout, r.stderr, json.loads(sp.read_text(encoding="utf-8")), calls)


def _broker_body(script: str) -> str:
    create, readback = _broker_segments(script)
    return create + "\n" + readback


@pytest.fixture(scope="module")
def roundtrip(broker_script):
    body = _broker_body(broker_script)
    first = _run(body, _seeded(_SEED))
    second = _run(body, first.state)  # a FRESH double loaded from the first dump
    return first, second


# ------------------------------------------------------------------ helpers over the exported JSON

def _idp(state: dict, alias: str = _ALIAS) -> list[dict]:
    return [i for i in state["identityProviders"] if i["alias"] == alias]


def _mappers(state: dict, alias: str = _ALIAS) -> list[dict]:
    return [m for m in state["identityProviderMappers"] if m["identityProviderAlias"] == alias]


def _flow_executions(state: dict, top: str) -> list[tuple[str, str]]:
    """(name, requirement) for every execution in the flow tree; name = authenticator, or the
    sub-flow alias with the copy prefix removed (ASSUMED naming, see fake_keycloak_curl.py)."""
    flows = {f["alias"]: f for f in state["authenticationFlows"]}
    out: list[tuple[str, str]] = []

    def walk(alias: str) -> None:
        for ex in flows[alias]["authenticationExecutions"]:
            if ex.get("authenticatorFlow"):
                name = ex["flowAlias"]
                out.append((name[len(top) + 1:] if name.startswith(top + " ") else name, ex["requirement"]))
                walk(ex["flowAlias"])
            else:
                out.append((ex["authenticator"], ex["requirement"]))
    walk(top)
    return out


def _can_link(state: dict, top: str) -> bool:
    return any(n in _LINK_NAMES and r != "DISABLED" for n, r in _flow_executions(state, top))


def _first_broker_login(state: dict, alias: str, token: dict) -> dict:
    """What Keycloak's first broker login yields, computed from the EXPORTED mappers + flow."""
    idp = _idp(state, alias)[0]
    flow = idp["firstBrokerLoginFlowAlias"]
    attrs: dict[str, list[str]] = {}
    username = None
    for m in _mappers(state, alias):
        cfg = m["config"]
        if m["identityProviderMapper"] == "oidc-user-attribute-idp-mapper" and cfg["claim"] in token:
            attrs[cfg["user.attribute"]] = [token[cfg["claim"]]]
        elif m["identityProviderMapper"] == "oidc-username-idp-mapper":
            username = re.sub(r"\$\{CLAIM\.([^}]+)\}", lambda g: str(token[g.group(1)]), cfg["template"])
    existing = [u for u in state["users"] if u.get("email") == token.get("email")]
    linked = existing[0]["username"] if existing and _can_link(state, flow) else None
    return {"username": username, "attributes": attrs, "linked_to": linked}


# ------------------------------------------------------------------ A: round trip

@needs_bash
def test_the_harness_ran_clean_both_passes(roundtrip):
    first, second = roundtrip
    for n, r in (("first", first), ("second", second)):
        assert r.rc == 0, f"{n} pass rc={r.rc}\n{r.out[-1500:]}\n{r.err[-800:]}"
        assert "FAIL" not in r.out, r.out
        assert not [c for c in r.calls if c["m"].startswith("UNHANDLED")], r.calls


@needs_bash
def test_second_pass_dump_equals_the_first(roundtrip):
    first, second = roundtrip
    assert second.state == first.state, "the segment is not idempotent: the realm changed on the second pass"


@needs_bash
def test_second_pass_posts_nothing_that_changes_state(roundtrip):
    first, second = roundtrip
    assert first.posts(), "positive control: the first pass must have POSTed (copy, IdP, mappers)"
    assert second.posts() == [], f"second pass made state-changing POSTs: {second.posts()}"


@needs_bash
def test_unrelated_realm_content_is_untouched(roundtrip):
    first, _ = roundtrip
    assert first.state["users"] == _seeded(_SEED)["users"]
    assert _idp(first.state, "corp-oidc") == _SEED["identityProviders"] and _mappers(first.state, "corp-oidc")
    flows = {f["alias"]: f for f in first.state["authenticationFlows"]}
    for f in _SEED["authenticationFlows"]:
        assert flows[f["alias"]] == f, f"built-in flow {f['alias']} was edited by a copy"


@needs_bash
def test_1_sub_is_preserved_by_exactly_one_force_mapper(roundtrip, broker_script):
    state = roundtrip[0].state
    sub = [m for m in _mappers(state) if m["config"].get("claim") == "sub"]
    assert len(sub) == 1, [m["name"] for m in _mappers(state)]
    m = sub[0]
    assert m["config"]["user.attribute"] == "authz_id", m["config"]
    assert m["config"]["syncMode"] == "FORCE", f"sub mapper syncMode is {m['config']['syncMode']!r}, not FORCE"
    # The type and config KEYS the script actually sends (derived from the rendered script).
    block = _segment(broker_script, f'"name": "{_ALIAS}-sub-to-authz-id"', 'echo "   created"')
    sent_type = re.search(r'"identityProviderMapper": "([^"]+)"', block).group(1)
    sent_keys = set(re.findall(r'"([A-Za-z.]+)":', block.split('"config": {')[1]))
    assert m["identityProviderMapper"] == sent_type == "oidc-user-attribute-idp-mapper"
    assert set(m["config"]) == sent_keys == {"syncMode", "claim", "user.attribute"}


@needs_bash
def test_2_username_mapper_yields_openddil_dot_preferred_username(roundtrip):
    state = roundtrip[0].state
    um = [m for m in _mappers(state) if m["identityProviderMapper"] == "oidc-username-idp-mapper"]
    assert len(um) == 1
    assert um[0]["config"]["template"] == "openddil.${CLAIM.preferred_username}"
    got = _first_broker_login(state, _ALIAS, {"sub": "S", "preferred_username": "liaison.coalition"})
    assert got["username"] == "openddil.liaison.coalition"


@needs_bash
def test_3_idp_is_enabled_on_the_guarded_flow_and_does_not_trust_email(roundtrip):
    (idp,) = _idp(roundtrip[0].state)
    assert idp["firstBrokerLoginFlowAlias"] == _FLOW
    assert idp["trustEmail"] is False, f"trustEmail is {idp['trustEmail']!r}"
    assert idp["enabled"] is True
    assert idp["providerId"] == "oidc" and idp["config"]["issuer"] == _ISSUER


@needs_bash
def test_4_no_link_execution_is_enabled_in_the_first_login_flow(roundtrip):
    state = roundtrip[0].state
    execs = _flow_executions(state, _FLOW)
    link = [(n, r) for n, r in execs if n in _LINK_NAMES]
    enabled = [(n, r) for n, r in link if r != "DISABLED"]
    assert not enabled, f"link/review executions not DISABLED: {enabled}"
    # positive control: the flow HAS such executions, present and disabled (not vacuous)
    assert len(link) >= 6 and all(r == "DISABLED" for _, r in link), link
    # ...and the account-creating execution survives, or nobody could ever log in
    assert ("idp-create-user-if-unique", "ALTERNATIVE") in execs


@needs_bash
def test_4_positive_control_the_seed_flow_does_have_the_executions():
    names = {n for n, r in _flow_executions(_seeded(_SEED), "first broker login") if r != "DISABLED"}
    assert {"idp-review-profile", "idp-auto-link", "idp-confirm-link", "idp-email-verification",
            "idp-username-password-form", "Handle Existing Account"} <= names


@needs_bash
def test_5_first_broker_login_binds_authz_id_to_the_upstream_sub_and_never_links(roundtrip):
    state = roundtrip[0].state
    s = _PRINCIPALS["liaison.coalition"]
    token = {"sub": s, "preferred_username": "liaison.coalition", "email": "x@y"}
    got = _first_broker_login(state, _ALIAS, token)
    assert got["attributes"]["authz_id"] == [s]
    assert got["username"] == "openddil.liaison.coalition"
    assert any(u["email"] == "x@y" for u in state["users"]), "positive control: a local user shares the email"
    assert got["linked_to"] is None and not _can_link(state, _FLOW)
    assert s in _PRINCIPALS.values()
    # the simulation is able to link when the flow allows it (the seed's built-in flow)
    probe = copy.deepcopy(state)
    probe_idp = _idp(probe)[0]
    probe_idp["firstBrokerLoginFlowAlias"] = "first broker login"
    probe["authenticationFlows"] = _seeded(_SEED)["authenticationFlows"]
    assert _first_broker_login(probe, _ALIAS, token)["linked_to"] == "local.xy"


# ------------------------------------------------------------------ B: retired users

_RETIRED = ["operator.atlantia", "operator.borduria", "liaison"]


def _retired_values(names: list[str]) -> list[str]:
    return _set("keycloak.retiredUsers", names)


def test_base_default_retired_users_is_empty_and_the_sandbox_names_the_three():
    base = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    assert base["keycloak"]["retiredUsers"] == []
    assert _VALUES["keycloak"]["retiredUsers"] == _RETIRED


def test_base_render_has_no_retired_user_step():
    assert "retired user" not in _script(_render())


def test_retired_user_in_non_interactive_list_fails_the_render():
    err = _render_fails(*_SANDBOX, *_retired_values(["platform-registrar"]))
    assert "platform-registrar" in err and "retiredUsers" in err


def test_retired_user_in_local_human_list_fails_the_render():
    err = _render_fails(*_SANDBOX, *_retired_values(["alice"]))
    assert "alice" in err and "retiredUsers" in err


@pytest.mark.parametrize("bad", ["a b", "x'; rm -rf /", "$(id)", "", "a/b", "u\"q"])
def test_retired_user_that_is_not_a_plain_username_fails_the_render(bad):
    err = _render_fails(*_SANDBOX, *_retired_values([bad]))
    assert "retiredUsers" in err and "plain username" in err


def _retired_bodies(script: str) -> tuple[str, str]:
    create = _segment(script, "# RETIRED USER:", "# ── READBACK GATE")
    rb_from = script.index("RU=", script.index("== readback =="))
    readback = script[rb_from:script.index("CID=", rb_from)]
    return create, readback


def _retired_state(*users: dict) -> dict:
    s = _seeded(_SEED)
    s["users"] = [{"enabled": True, **u, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, u["username"]))} for u in users]
    return s


def _run_retired(script: str, state: dict, **kw) -> Run:
    create, readback = _retired_bodies(script)
    return _run(create + "\n" + readback, state, **kw)


_NAMES = lambda r: [u["username"] for u in r.state["users"]]  # noqa: E731


@needs_bash
def test_retired_user_without_a_link_is_deleted(retired_script):
    r = _run_retired(retired_script, _retired_state({"username": "liaison", "email": "liaison@example.com"}))
    assert r.rc == 0, r.out + r.err
    assert "liaison" not in _NAMES(r), "an unlinked retired user must be deleted"
    assert [c["m"] for c in r.calls if c["m"] == "DELETE"] == ["DELETE"]


@needs_bash
def test_retired_user_with_a_federated_link_is_kept_and_logged(retired_script):
    link = [{"identityProvider": "openddil", "userId": "33333333-3333-4333-8333-333333333333", "userName": "x"}]
    r = _run_retired(retired_script, _retired_state({"username": "liaison", "federatedIdentities": link}))
    assert r.rc == 0, r.out + r.err
    assert "liaison" in _NAMES(r), "a brokered shadow must not be deleted"
    assert not [c for c in r.calls if c["m"] == "DELETE"]
    assert "KEPT" in r.out and "liaison" in r.out


@needs_bash
def test_absent_retired_user_costs_only_the_lookup(retired_script):
    # the decoy `liaison-ops` matches `liaison` as a SUBSTRING: only exact=true keeps it alive.
    r = _run_retired(retired_script, _retired_state({"username": "liaison-ops"}))
    assert r.rc == 0, r.out + r.err
    assert _NAMES(r) == ["liaison-ops"], f"a non-exact lookup deleted a different user: {_NAMES(r)}"
    assert {c["m"] for c in r.calls} == {"GET"}
    assert all(c["p"].startswith("/users?username=") and "exact=true" in c["p"] for c in r.calls), r.calls


@needs_bash
def test_readback_fails_when_the_delete_was_refused(retired_script):
    r = _run_retired(retired_script, _retired_state({"username": "liaison"}), refuse_delete=True)
    assert r.rc == 1, f"rc={r.rc}\n{r.out}"
    assert "FAIL retired user liaison" in r.out and "liaison" in _NAMES(r)


# ------------------------------------------------------------------ C: grants bind to the sub

_POLICY = _REPO / "policy"


def _yaml(name: str):
    return yaml.safe_load((_POLICY / name).read_text(encoding="utf-8"))


def _scalars(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _scalars(k)
            yield from _scalars(v)
    elif isinstance(node, list):
        for v in node:
            yield from _scalars(v)
    elif isinstance(node, str):
        yield node


def _entitlement_ids(users: object, grants: object) -> list[str]:
    """Every id the policy files use as an entitlement key: users[].id and every grant_to member."""
    ids = [u["id"] for u in (users["users"] if isinstance(users, dict) else users)]

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k == "grant_to" and isinstance(v, list):
                    ids.extend(str(x) for x in v)
                else:
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(grants)
    return ids


def _sub_violations(users: object, grants: object, subs: list[str]) -> list[str]:
    """A sub that appears anywhere in the two files must appear AS an entitlement key, exactly."""
    ids = _entitlement_ids(users, grants)
    bad = []
    for s in subs:
        embedded = [x for x in _scalars([users, grants]) if s in x and x != s]
        if embedded:
            bad.append(f"{s} appears only embedded in {embedded[:2]}")
        if not any(x == s for x in _scalars([users, grants])) and any(s in x for x in ids):
            bad.append(f"{s} is not an entitlement key")
    return bad


def test_c1_every_sub_in_policy_appears_as_the_sub():
    users, grants = _yaml("users.yaml"), _yaml("task_grants.yaml")
    subs = list(_PRINCIPALS.values())
    present = [s for s in subs if s in set(_entitlement_ids(users, grants))]
    assert present, "positive control: at least one principal's sub is bound in policy"
    assert _sub_violations(users, grants, subs) == []
    # mutate a copy: bind the grant to the email form instead of the sub
    liaison = _PRINCIPALS["liaison.coalition"]
    m_grants = json.loads(json.dumps(grants).replace(f'"{liaison}"', f'"{liaison}@example.com"'))
    assert _sub_violations(users, m_grants, subs), "control: an embedded sub must be refused"


def _retired_hits(users: object, grants: object, retired: list[str]) -> list[str]:
    ids = _entitlement_ids(users, grants)
    return [i for i in ids for r in retired if i == r or i.startswith(r + "@")]


def test_c2_no_policy_entry_names_a_retired_username_or_its_email():
    retired = _VALUES["keycloak"]["retiredUsers"]
    assert retired
    files = sorted(_POLICY.glob("**/*.yaml"))
    assert len(files) >= 2
    users, grants = _yaml("users.yaml"), _yaml("task_grants.yaml")
    assert _retired_hits(users, grants, retired) == []
    for f in files:  # every policy yaml, not only the two: any `grant_to` / `users[].id`
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert _retired_hits({"users": []}, doc, retired) == [], f
    # positive controls on a mutated copy
    m_users = copy.deepcopy(users)
    (m_users["users"] if isinstance(m_users, dict) else m_users).append({"id": "liaison@example.com"})
    assert _retired_hits(m_users, grants, retired) == ["liaison@example.com"]
    m_grants = json.loads(json.dumps(grants).replace(_PRINCIPALS["liaison.coalition"], "operator.atlantia"))
    assert _retired_hits(users, m_grants, retired)


def _openddil_on_behalf_of(values: dict) -> list[str]:
    clients = values["keycloak"]["extraServiceClients"]
    (c,) = [c for c in clients if c["clientId"] == "iagent-openddil"]
    return [o["user"] for o in c["onBehalfOf"]]


def _resolve(users_obs: list[str], principals: dict[str, str]) -> dict[str, str]:
    return {u: principals[u] for u in users_obs if u in principals}


def test_c3_every_on_behalf_of_user_resolves_to_a_principal_with_a_sub():
    # SPEC DEVIATION, reported: policy/users.yaml deliberately seeds only liaison.coalition
    # (its comment: operator.atlantia / operator.borduria "hold no grant, so they are not
    # seeded"). So the seal is: every onBehalfOf user resolves to a declared principal, and a
    # resolved sub that policy names anywhere is a users.yaml entry.
    obo = _openddil_on_behalf_of(_VALUES)
    assert obo
    resolved = _resolve(obo, _PRINCIPALS)
    assert sorted(resolved) == sorted(obo), f"unresolvable onBehalfOf users: {set(obo) - set(resolved)}"
    users, grants = _yaml("users.yaml"), _yaml("task_grants.yaml")
    user_ids = {u["id"] for u in (users["users"] if isinstance(users, dict) else users)}
    named = [s for s in resolved.values() if any(s in x for x in _entitlement_ids({"users": []}, grants))]
    assert named, "positive control: some onBehalfOf principal is granted something"
    assert set(named) <= user_ids, f"granted subs missing from users.yaml: {set(named) - user_ids}"
    assert resolved["liaison.coalition"] in user_ids
    # positive controls on mutated copies
    assert _resolve(obo + ["nobody"], _PRINCIPALS).keys() != set(obo + ["nobody"])
    assert not set(named) <= (user_ids - {resolved["liaison.coalition"]})
