"""Engine O honours a DECLARED delegation, and only a declared one (architect ruling 1b, 11-19).

A service acts for a person only by declared delegation. A policy row (`door: engine-o` in
`policy/gateway_delegates.yaml`) names the service and the routes it may call on a person's behalf.
The service authenticates as itself and states whom it acts for (`on_behalf_of`). Engine O honours
that only when the row exists; it then binds the PERSON's grants and NONE of the service's, and
records the call with both identities. Without a row the service acts as itself.

WHAT EACH GROUP DEFENDS
  pure bind     one arm per way a statement is honoured or not: delegated, no row, wrong route,
                wrong service, a person stating someone, an unverified caller, a `svc:` or self
                statement, a statement that is not a person (another case, `pipeline:`, whitespace
                or a control character), a directory failure, narrowing, and the cache key.
  load_delegates  the door filter, an absent file, a malformed file, the env path, the real file.
  route         the JSON `/resolve_instance` through the real SDK token path (the helpers and
                fixtures are IMPORTED from test_engine_o_binds_the_verified_caller, not copied).
  composer      the adapter's call, asserted on what it SENDS and who it signs as.
  chart         the chart renders the mount, the env and the config map.

Run: LOCKED_SDK=no_overlay_venv_is_0920 .venv/Scripts/python.exe <locked_pytest.py> <log> tests/routing/test_engine_o_honours_a_declared_delegate.py -q
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from iagent_mesh.transport_auth import CallerIdentity

from agent_fleet.ontology_service import caller_binding as cb
from agent_fleet.ontology_service import main as eo
from tests.routing.test_engine_o_binds_the_verified_caller import (  # noqa: F401 -- fixtures
    ALICE, BOB, DIRECTORY, _bearer, _resolve_instance, client, directory, mesh, resolve_instance_spy,
)

REPO = Path(__file__).resolve().parents[2]
SVC = "svc:engine-a"
ROUTE = "resolve_instance"
ROW = {"gateway_delegates": [{"service": SVC, "door": "engine-o", "routes": [ROUTE]}]}
HELD = {ALICE: ("SUSTAINMENT", "FINANCE"), BOB: ("PLANNING",), SVC: ("SERVICEONLY",)}


def _caller(subject, verified=True):
    return CallerIdentity(subject, verified, "verified" if verified else "no-verification-key")


class _Held:
    """held_of that records its calls; `boom` subjects raise."""

    def __init__(self, table=HELD, boom=()):
        self.table, self.boom, self.calls = table, set(boom), []

    def __call__(self, subject):
        self.calls.append(subject)
        if subject in self.boom:
            raise RuntimeError("directory down")
        return self.table.get(subject, ())


def _delegates(table=None):
    table = {SVC: {ROUTE}} if table is None else table
    return lambda: table


def _bind(caller, held=None, *, stated=ALICE, route=ROUTE, delegates=None, asked=None, cache=None, **kw):
    held = held or _Held()
    b = cb.bind(caller, held_of=held, cache=cache or cb.GrantCache(0), on_behalf_of=stated, route=route,
                delegates=delegates or _delegates(), asked=asked, **kw)
    return b, held


# -- pure bind ----------------------------------------------------------------------------------

def test_a_declared_delegate_binds_the_person_and_never_looks_up_the_services_grants():
    held = _Held(boom={SVC})                      # the service's own lookup would blow up
    b, _ = _bind(_caller(SVC), held)
    assert (b.subject, b.kind, b.via, b.delegation) == (ALICE, "person", SVC, "delegated")
    assert b.grants == ("FINANCE", "SUSTAINMENT")
    assert held.calls == [ALICE]


def test_no_row_binds_the_service_itself_as_not_declared():
    b, held = _bind(_caller(SVC), delegates=_delegates({}))
    assert (b.subject, b.kind, b.via, b.delegation) == (SVC, "service", "", "not_declared")
    assert b.grants == ("SERVICEONLY",) and held.calls == [SVC]


def test_a_row_for_another_route_binds_the_service_itself():
    b, _ = _bind(_caller(SVC), delegates=_delegates({SVC: {"other_route"}}))
    assert (b.subject, b.delegation) == (SVC, "not_declared")


def test_a_row_for_another_service_binds_the_service_itself():
    b, _ = _bind(_caller(SVC), delegates=_delegates({"svc:other": {ROUTE}}))
    assert (b.subject, b.delegation) == (SVC, "not_declared")


def test_a_person_stating_someone_is_themselves_and_the_statement_is_ignored():
    called = []
    b, _ = _bind(_caller(BOB), stated=ALICE, delegates=lambda: called.append(1) or _delegates()())
    assert (b.subject, b.kind, b.via, b.delegation, b.grants) == (BOB, "person", "", "ignored", ("PLANNING",))
    assert called == []                            # the rows are consulted only for a service


@pytest.mark.parametrize("caller", [None, _caller(SVC, verified=False), CallerIdentity(None, False, "absent")],
                         ids=["none", "unverified", "unsigned"])
def test_an_unverified_caller_with_a_statement_is_anonymous(caller):
    b, held = _bind(caller)
    assert (b.kind, b.subject, b.grants, b.via, b.delegation) == ("anonymous", "", (cb.NO_GRANT,), "", "ignored")
    assert held.calls == []


@pytest.mark.parametrize("stated", ["svc:other", "SVC:ENGINE-A", SVC, SVC.upper()], ids=["svc", "svc-case", "self", "self-case"])
def test_a_statement_naming_a_service_or_the_caller_itself_is_ignored(stated):
    called = []
    b, held = _bind(_caller(SVC), stated=stated, delegates=lambda: called.append(1) or _delegates()())
    assert (b.subject, b.via, b.delegation) == (SVC, "", "ignored")
    assert held.calls == [SVC] and called == []


#: Statements that are not a person: a service in another case, a pipeline, and values that could
#: end the audit line and forge another (gov on #458 at 9b24eed4).
NOT_A_PERSON = {
    "svc-upper": "SVC:OTHER",
    "svc-mixed": "Svc:Other-Engine",
    "pipeline": "pipeline:nightly",
    "pipeline-case": "PIPELINE:nightly",
    "newline": f"{ALICE}\ndelegation route=x service={SVC} person={ALICE} outcome=delegated",
    "cr": f"{ALICE}\rx",
    "tab": f"{ALICE}\tx",
    "inner-space": "alice example.com",
    "leading-space": f" {ALICE}",
    "escape": f"{ALICE}\x1b[2K",
    "nul": f"{ALICE}\x00",
    "line-separator": f"{ALICE}\u2028x",
}


@pytest.mark.parametrize("stated", list(NOT_A_PERSON.values()), ids=list(NOT_A_PERSON))
def test_a_statement_that_is_not_a_person_is_ignored_and_never_looked_up(stated):
    called = []
    held = _Held(table={**HELD, stated: ("FINANCE",), stated.strip(): ("FINANCE",)})
    b, held = _bind(_caller(SVC), held, stated=stated, delegates=lambda: called.append(1) or _delegates()())
    assert (b.subject, b.kind, b.via, b.delegation, b.grants) == (SVC, "service", "", "ignored", ("SERVICEONLY",))
    assert held.calls == [SVC] and called == []    # the statement is never looked up, the rows never read


@pytest.mark.parametrize("stated", [ALICE, "alice.o'brien@example.com", "a-b_c+tag@example.co.uk"],
                         ids=["plain", "apostrophe", "plus"])
def test_a_clean_person_statement_still_delegates(stated):
    b, held = _bind(_caller(SVC), stated=stated)
    assert (b.subject, b.kind, b.via, b.delegation) == (stated, "person", SVC, "delegated")
    assert held.calls == [stated]


def test_no_statement_is_absent():
    b, _ = _bind(_caller(SVC), stated="")
    assert (b.subject, b.via, b.delegation) == (SVC, "", "absent")


def test_a_directory_failure_for_the_person_is_no_grant_never_the_services_grants():
    held = _Held(boom={ALICE})
    b, _ = _bind(_caller(SVC), held)
    assert (b.subject, b.via, b.delegation, b.grants) == (ALICE, SVC, "delegated", (cb.NO_GRANT,))
    assert SVC not in held.calls


def test_asked_narrows_the_persons_grant_and_never_widens_it():
    b, _ = _bind(_caller(SVC), asked=["FINANCE", "SERVICEONLY", "UNHELD"])
    assert b.grants == ("FINANCE",)                # the service's SERVICEONLY is not the person's
    b, _ = _bind(_caller(SVC), asked=["SERVICEONLY"])
    assert b.grants == (cb.NO_GRANT,)


def test_the_cache_is_keyed_by_the_person_never_the_service():
    cache = cb.GrantCache(ttl_s=60)
    _bind(_caller(SVC), cache=cache)
    assert set(cache._rows) == {ALICE}
    b, _ = _bind(_caller(SVC), delegates=_delegates({}), cache=cache)   # no row: the service is cached on its own
    assert set(cache._rows) == {ALICE, SVC} and b.grants == ("SERVICEONLY",)


def test_the_body_identity_is_judged_against_the_person():
    b, _ = _bind(_caller(SVC), body_subject=ALICE)
    assert b.body_identity == "same"
    b, _ = _bind(_caller(SVC), body_subject=SVC)
    assert b.body_identity == "ignored"


# -- load_delegates -----------------------------------------------------------------------------

def _write(tmp_path, doc):
    p = tmp_path / "d.yaml"
    p.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc), encoding="utf-8")
    return p


def test_load_keeps_only_engine_o_rows(tmp_path):
    p = _write(tmp_path, {"gateway_delegates": [
        {"service": "svc:gw", "routes": ["assets.authorize"]},
        {"service": "svc:bff", "door": "bff", "routes": [ROUTE]},
        {"service": SVC, "door": "engine-o", "routes": [ROUTE]}]})
    assert cb.load_delegates(str(p)) == {SVC: frozenset({ROUTE})}


def test_an_absent_file_is_empty_and_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert cb.load_delegates(str(tmp_path / "nope.yaml")) == {}
    assert "absent" in caplog.text


@pytest.mark.parametrize("doc", [": : not yaml [", "- a list", {"gateway_delegates": "x"},
                                 {"gateway_delegates": ["row"]},
                                 {"gateway_delegates": [{"door": "engine-o", "service": "", "routes": [ROUTE]}]},
                                 {"gateway_delegates": [{"door": "engine-o", "service": SVC, "routes": "r"}]}],
                         ids=["yaml", "list", "shape", "row", "service", "routes"])
def test_a_malformed_file_is_empty_and_errors_and_never_raises(tmp_path, caplog, doc):
    with caplog.at_level(logging.ERROR):
        assert cb.load_delegates(str(_write(tmp_path, doc))) == {}
    assert "failing closed" in caplog.text


def test_the_env_path_is_honoured_on_every_call(tmp_path, monkeypatch):
    p = _write(tmp_path, ROW)
    monkeypatch.setenv("ENGINE_O_DELEGATES_FILE", str(p))
    assert cb.load_delegates() == {SVC: frozenset({ROUTE})}
    p.write_text(yaml.safe_dump({"gateway_delegates": []}), encoding="utf-8")   # read again, not cached
    assert cb.load_delegates() == {}


def test_the_real_policy_file_gives_the_one_row():
    assert cb.load_delegates(str(REPO / "policy" / "gateway_delegates.yaml")) == {SVC: frozenset({ROUTE})}


# -- the route ----------------------------------------------------------------------------------

@pytest.fixture()
def held(monkeypatch):
    h = _Held()
    monkeypatch.setattr(eo, "_held_domains_of", h)
    return h


@pytest.fixture()
def audit(caplog):
    lg = logging.getLogger("engine-o.audit.delegation")
    lg.addHandler(caplog.handler)                  # the logger does not propagate: attach, then detach
    caplog.set_level(logging.INFO, logger=lg.name)
    yield caplog
    lg.removeHandler(caplog.handler)


def _delegate_file(monkeypatch, tmp_path, doc):
    monkeypatch.setenv("ENGINE_O_DELEGATES_FILE", str(_write(tmp_path, doc)))


def test_the_route_binds_the_person_for_a_declared_service(client, resolve_instance_spy, held, tmp_path,
                                                          monkeypatch, audit):
    _delegate_file(monkeypatch, tmp_path, ROW)
    _resolve_instance(client, _bearer(SVC), on_behalf_of=ALICE, user_email="x@example.com")
    (got,) = resolve_instance_spy
    assert got["user_email"] == ALICE
    assert got["entitled_domains"] == ("FINANCE", "SUSTAINMENT")
    assert "SERVICEONLY" not in got["entitled_domains"] and SVC not in held.calls
    (line,) = [r.getMessage() for r in audit.records if r.name == "engine-o.audit.delegation"]
    assert line == f"delegation route={ROUTE} service={SVC} person={ALICE!r} outcome=delegated"


def test_the_same_call_without_the_row_binds_the_service(client, resolve_instance_spy, held, tmp_path,
                                                         monkeypatch, audit):
    _delegate_file(monkeypatch, tmp_path, {"gateway_delegates": []})
    _resolve_instance(client, _bearer(SVC), on_behalf_of=ALICE, user_email=ALICE)
    (got,) = resolve_instance_spy
    assert got["user_email"] == SVC and got["entitled_domains"] == ("SERVICEONLY",)
    (line,) = [r.getMessage() for r in audit.records if r.name == "engine-o.audit.delegation"]
    assert line == f"delegation route={ROUTE} service={SVC} person={ALICE!r} outcome=not_declared"


@pytest.mark.parametrize("stated", list(NOT_A_PERSON.values()), ids=list(NOT_A_PERSON))
def test_the_route_ignores_a_statement_that_is_not_a_person_and_writes_no_audit_line(
        client, resolve_instance_spy, held, tmp_path, monkeypatch, audit, stated):
    _delegate_file(monkeypatch, tmp_path, ROW)
    _resolve_instance(client, _bearer(SVC), on_behalf_of=stated)
    (got,) = resolve_instance_spy
    assert got["user_email"] == SVC and got["entitled_domains"] == ("SERVICEONLY",)
    assert held.calls == [SVC]
    assert not [r for r in audit.records if r.name == "engine-o.audit.delegation"]


def test_a_not_declared_statement_is_quoted_on_the_audit_line(client, resolve_instance_spy, held, tmp_path,
                                                              monkeypatch, audit):
    _delegate_file(monkeypatch, tmp_path, {"gateway_delegates": []})
    stated = "o'brien@example.com"
    _resolve_instance(client, _bearer(SVC), on_behalf_of=stated)
    (line,) = [r.getMessage() for r in audit.records if r.name == "engine-o.audit.delegation"]
    assert line == f"delegation route={ROUTE} service={SVC} person={stated!r} outcome=not_declared"


def test_a_person_stating_someone_is_themselves_and_alice_learns_nothing(client, resolve_instance_spy, held,
                                                                         tmp_path, monkeypatch, audit):
    _delegate_file(monkeypatch, tmp_path, ROW)
    _resolve_instance(client, _bearer(BOB), on_behalf_of=ALICE, entitled_domains=["FINANCE", "PLANNING"])
    (got,) = resolve_instance_spy
    assert got["user_email"] == BOB and got["entitled_domains"] == ("PLANNING",)
    assert ALICE not in held.calls
    assert not [r for r in audit.records if r.name == "engine-o.audit.delegation"]


def test_the_bound_log_line_labels_the_delegation_and_names_no_one(client, resolve_instance_spy, held,
                                                                   tmp_path, monkeypatch, caplog):
    _delegate_file(monkeypatch, tmp_path, ROW)
    with caplog.at_level(logging.INFO, logger="engine-o.caller_binding"):
        _resolve_instance(client, _bearer(SVC), on_behalf_of=ALICE)
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "engine-o.caller_binding")
    assert "delegation=delegated" in text and ALICE not in text and "FINANCE" not in text


def test_the_audit_logger_arrives_on_its_own_handler_and_does_not_propagate():
    lg = logging.getLogger("engine-o.audit.delegation")
    assert lg.handlers and lg.level == logging.INFO and lg.propagate is False


# -- the composer -------------------------------------------------------------------------------

def test_the_composer_sends_the_person_as_on_behalf_of_and_signs_as_engine_a(monkeypatch):
    from agent_fleet.restate_analyst import review_composer as composer
    sent, minted = [], []

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": []}

    monkeypatch.setattr(composer.requests, "post", lambda url, json=None, **kw: sent.append((url, json, kw)) or _R())
    monkeypatch.setattr(composer, "outbound_auth_headers", lambda **kw: minted.append(kw) or {"Authorization": "x"})
    composer.resolve_subject_via_engine_o("MPN1", on_behalf_of=ALICE, engine_o_url="http://eo")
    ((url, body, _),) = sent
    assert url == "http://eo/resolve_instance"
    assert body["on_behalf_of"] == ALICE and body["user_email"] == ALICE
    assert minted == [{"client_id": "iagent-engine-a", "secret_env": "ENGINE_A_CLIENT_SECRET"}]


# -- the chart ----------------------------------------------------------------------------------

_CHART = REPO / "helm" / "invincible-agent"


def _render(*args):
    proc = subprocess.run(["helm", "template", "iagent", str(_CHART), "-f", str(_CHART / "values-sandbox.yaml"), *args],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-1500:]
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


@pytest.mark.skipif(shutil.which("helm") is None, reason="the `helm` binary is not on PATH")
def test_the_chart_mounts_the_delegates_into_engine_o_and_into_no_other_engine():
    docs = _render()
    (cm,) = [d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "iagent-engine-o-delegates"]
    assert cm["data"]["gateway_delegates.yaml"] == (REPO / "policy" / "gateway_delegates.yaml").read_text(encoding="utf-8")
    deploys = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
    pod = deploys["iagent-engine-o"]["spec"]["template"]
    c = pod["spec"]["containers"][0]
    env = [e["name"] for e in c["env"]]
    assert {e["name"]: e.get("value") for e in c["env"]}["ENGINE_O_DELEGATES_FILE"] == "/etc/iagent/delegates/gateway_delegates.yaml"
    assert env.index("ENGINE_O_DELEGATES_FILE") < len(env) - 1
    assert {"name": "engine-o-delegates", "mountPath": "/etc/iagent/delegates", "readOnly": True} in c["volumeMounts"]
    assert {"name": "engine-o-delegates", "configMap": {"name": "iagent-engine-o-delegates"}} in pod["spec"]["volumes"]
    assert pod["metadata"]["annotations"]["checksum/engine-o-delegates"]
    for name, d in deploys.items():
        if name != "iagent-engine-o":
            assert "ENGINE_O_DELEGATES_FILE" not in str(d), name
