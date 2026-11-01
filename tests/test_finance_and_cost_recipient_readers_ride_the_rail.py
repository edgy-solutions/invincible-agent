"""Finance's and cost's recipient readers are the `recipient_readers` policy rail, not code.

Architect, 2026-10-27 ruling 4 (refined 10-28): "gov writes the rail shape (a recipient_readers
family with grantors); fin and cost each move their own RECIPIENT_READERS onto it." The rows are
policy/recipient_readers.yaml's `finance` and `cost` owners; the BFF and each owning engine ask
`can_read_recipient(<owner>, scope, authz_id)`. Every row below is READ from that file through the
sync's own loader (tests/recipient_rail_double.py) -- no reader and no scope is typed here.

  arm a  each owner, each shipped row: the BFF doors (download, picker) and the owning engine's door
         admit the row's readers and refuse a non-reader with the existing 403.
  arm b  Topaz raises: the doors answer 503 (never 403); the pickers answer 503 naming the owner
         (ruled 10-31; was: omitted), and are unaffected by an owner they never ask (finance).
  arm c  the request the door sends is `check_payload(<owner>, scope, authz_id)`, and the owner is
         a key of the yaml (read, never typed).
  arm d  a tmp rail file that adds a reader for an existing scope admits that reader with no code
         change (test 3 of the 2026-10-30 standing rule).
  arm e  (in tests/security/test_recipient_readers_rail.py) PENDING is empty and no table is left.

Run:  uv run --no-sync pytest tests/test_finance_and_cost_recipient_readers_ride_the_rail.py -q
"""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml

httpx = pytest.importorskip("httpx")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.cost_agent import main as cost_main  # noqa: E402
from agent_fleet.cost_agent import measures  # noqa: E402
from agent_fleet.cost_agent import seed as cost_seed  # noqa: E402
from agent_fleet.finance_agent import export as fin_export  # noqa: E402
from agent_fleet.finance_agent import main as fin_main  # noqa: E402
from agent_fleet.utils import recipient_readers as rr  # noqa: E402
from src.iagent import gateway  # noqa: E402
from tests.recipient_rail_double import Rail, install, rail_rows, serve_no_plan_profiles  # noqa: E402

_RAIL_FILE = pathlib.Path(__file__).resolve().parents[1] / "policy" / "recipient_readers.yaml"
STRANGER = "mallory@example.com"
BEARER = {"Authorization": "Bearer t"}

#: owner key -> how to name the package file of one of that owner's scopes. The owner KEYS are looked
#: up in the shipped rows below, so a renamed yaml key makes these tests find no rows and red.
OWNERS = {
    "cost": lambda scope: cost_seed.artifact_filenames(scope)[0],
    "finance": lambda scope: fin_export.artifact_filenames(scope)[0],
}
ROWS = [(owner, scope, reader) for (owner, scope), readers in sorted(rail_rows().items())
        if owner in OWNERS for reader in readers]


def _row_params():
    return [pytest.param(o, s, r, id=f"{o}:{s}:{r.split('@')[0]}") for o, s, r in ROWS]


class _Caller:
    def __init__(self, authz_id): self.authz_id = authz_id


class _User:
    def __init__(self, authz_id):
        self.authz_id = authz_id
        self.id = "sub-" + str(authz_id)
        self.email = authz_id
        self.roles = []
        self.persona = None
        self.entitled_domains = []
        self.is_authenticated = True


class _Resp:
    def __init__(self, status=200, content=b"<html>ok</html>"):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": "text/html"}

    def json(self):
        return {}


@pytest.fixture
def rail(monkeypatch):
    return install(monkeypatch)


@pytest.fixture
def engines(monkeypatch):
    """Both engines' real apps, with nothing on disk: an ADMITTED reader reaches the end of the door
    and gets 404 ("not produced here"); a refused one gets 403 and a rail outage 503."""
    monkeypatch.setattr(measures, "_repo_root", lambda: None)
    monkeypatch.setattr(fin_main, "_repo_root", lambda: None)
    state = {"who": None}
    monkeypatch.setattr(cost_main, "_current_caller", lambda: _Caller(state["who"]))
    monkeypatch.setattr(fin_main, "_current_caller", lambda: _Caller(state["who"]))
    clients = {"cost": TestClient(cost_main.app), "finance": TestClient(fin_main.app)}

    def get(owner, scope, who):
        state["who"] = who
        return clients[owner].get("/artifact/" + OWNERS[owner](scope))

    return get


@pytest.fixture
def bff(monkeypatch):
    """The BFF with the engine behind it stubbed to 200 (so a 200 here means the BFF admitted)."""
    calls = []

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, headers=None, **k):
            calls.append(url)
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    state = {"who": None}
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(state["who"])
    with TestClient(gateway.app) as client:
        def go(path, who):
            state["who"] = who
            return client.get(path, headers=BEARER)
        go.engine_calls = calls
        yield go
    gateway.app.dependency_overrides.clear()


def _bff_download(owner, scope):
    return "/export/package/artifact/" + OWNERS[owner](scope)


def _no_plan(monkeypatch):
    """The plan picker half is not under test here: no profile set, so no plan recipient."""
    def _down(url):
        raise ConnectionError("engine-cost is not under test")
    monkeypatch.setattr(gateway, "_cost_profiles_get", _down)


def test_the_shipped_rows_exist_to_be_tested():
    """CONTROL: the parametrisation below is not empty, and covers both owners."""
    assert {o for o, _s, _r in ROWS} == set(OWNERS), ROWS
    assert all(STRANGER not in r for r in rail_rows().values())


# -- arm a ------------------------------------------------------------------------------------

@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_a_the_engine_door_admits_the_rows_reader_and_refuses_a_stranger(
        rail, engines, owner, scope, reader):
    admitted = engines(owner, scope, reader)
    assert admitted.status_code == 404, (admitted.status_code, admitted.text[:200])  # past the gate
    refused = engines(owner, scope, STRANGER)
    assert refused.status_code == 403, (refused.status_code, refused.text[:200])


@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_a_the_bff_download_door_admits_the_rows_reader_and_refuses_a_stranger(
        rail, bff, owner, scope, reader):
    ok = bff(_bff_download(owner, scope), reader)
    assert ok.status_code == 200, (ok.status_code, ok.text[:200])
    n = len(bff.engine_calls)
    refused = bff(_bff_download(owner, scope), STRANGER)
    assert refused.status_code == 403, (refused.status_code, refused.text[:200])
    assert len(bff.engine_calls) == n, "a refused caller reached the engine"


def test_a_a_reader_of_one_owner_is_not_a_reader_of_the_other(rail, bff):
    """CONTROL: each owner is entitled independently. A cost reader asking for a finance scope's
    package is refused, though the caller IS a shipped reader (of another owner)."""
    cost_reader = next(r for o, _s, r in ROWS if o == "cost")
    fin_scope = next(s for o, s, _r in ROWS if o == "finance")
    rail.rows[("finance", fin_scope)] = tuple(
        r for r in rail.rows[("finance", fin_scope)] if r != cost_reader)
    assert bff(_bff_download("finance", fin_scope), cost_reader).status_code == 403


@pytest.mark.parametrize("reader", sorted({r for o, _s, r in ROWS if o == "cost"}))
def test_a_the_bff_picker_lists_exactly_the_cost_scopes_the_person_reads(
        rail, bff, monkeypatch, reader):
    serve_no_plan_profiles(monkeypatch)  # the plan half is answerable (a 503 otherwise) and empty
    want = sorted(s for (o, s), rs in rail_rows().items() if o == "cost" and reader in rs)
    assert want, "control: the person reads some cost scope"
    got = bff("/export/package/recipients", reader)
    assert got.status_code == 200, got.text
    assert sorted(r["value"] for r in got.json()["recipients"]) == want
    assert gateway._export_recipients_for(_User(reader)) == want


@pytest.mark.parametrize("reader", sorted({r for o, _s, r in ROWS if o == "finance"}))
def test_a_the_fin_scope_list_is_exactly_the_scopes_the_person_reads(rail, reader):
    want = sorted(s for (o, s), rs in rail_rows().items() if o == "finance" and reader in rs)
    assert want and gateway._fin_export_recipients_for(_User(reader)) == want
    assert gateway._fin_export_recipients_for(_User(STRANGER)) == []


def test_a_the_move_changed_nobody_s_access():
    """The one place the readers are TYPED, on purpose: the rows as the code tables held them
    before the move (ruling 4: "move", not "re-grant"). Every other arm reads the yaml, so it
    follows an edit; this one is what makes dropping a reader from a moved row red. Retire it
    when a grantor first edits one of these rows through the rail."""
    held_in_code = {
        ("finance", "program_office.NP-MERIDIAN"): {"alice@example.com"},
        ("cost", "notional-customer-alpha"): {"alice@example.com"},
        ("cost", "notional-customer-beta"): {"bob@example.com"},
    }
    shipped = {k: set(v) for k, v in rail_rows().items() if k[0] in OWNERS}
    assert shipped == held_in_code


# -- arm b ------------------------------------------------------------------------------------

@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_b_a_rail_outage_at_the_engine_door_is_a_503_never_a_403(
        rail, engines, owner, scope, reader):
    rail.down = True
    got = engines(owner, scope, reader)
    assert got.status_code == 503, (got.status_code, got.text[:200])
    assert got.json()["detail"] == {"reason": "recipient_readers_unavailable"}


@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_b_a_rail_outage_at_the_bff_download_door_is_a_503_never_a_403(
        rail, bff, owner, scope, reader):
    rail.down = True
    got = bff(_bff_download(owner, scope), reader)
    assert got.status_code == 503, (got.status_code, got.text[:200])
    assert got.json()["detail"] == {"reason": "recipient_readers_unavailable"}
    assert bff.engine_calls == [], "the BFF forwarded while it could not ask the rail"


def test_b_an_outage_for_one_owner_leaves_the_other_owners_door_alone(rail, bff):
    """The outage is the OWNER's: finance down does not 503 a cost download."""
    rail.down_owners = {"finance"}
    scope, reader = next((s, r) for o, s, r in ROWS if o == "cost")
    assert bff(_bff_download("cost", scope), reader).status_code == 200
    fscope = next(s for o, s, _r in ROWS if o == "finance")
    assert bff(_bff_download("finance", fscope), reader).status_code == 503


@pytest.mark.parametrize("down,owner", [("cost", "cost"), ("plan", "plan")])
def test_b_the_picker_is_a_503_naming_the_owner_when_cost_or_plan_is_down(
        rail, bff, monkeypatch, down, owner):
    """Was `..._omits_cost_recipients_when_cost_is_down_and_still_lists_the_plan_ones`: ruled
    10-31, an outage answers 503 and is never omitted (and 'no readers' is the 403)."""
    plan_scope = next(s for (o, s) in rail_rows() if o == "plan")
    plan_reader = rail_rows()[("plan", plan_scope)][0]
    with TestClient(cost_main.app) as cost:
        monkeypatch.setattr(gateway, "_cost_profiles_get",
                            lambda url: cost.get("/answers_export/profiles"))
        monkeypatch.setattr("agent_fleet.utils.export_capability.can_export", lambda *a, **k: True)
        # control: all owners up -> the person's cost scopes AND the plan scope
        up = [r["value"] for r in bff("/export/package/recipients", plan_reader).json()["recipients"]]
        assert plan_scope in up and len(up) > 1, up
        rail.down_owners = {down}
        got = bff("/export/package/recipients", plan_reader)
        assert got.status_code == 503, got.text
        assert got.json()["detail"] == {"reason": "recipient_readers_unavailable", "owner": owner}


def test_b_the_cost_picker_survives_a_dead_finance_rail(rail, bff, monkeypatch):
    # UNCHANGED BY THE 10-31 RULING (an outage is 503): the picker lists cost and plan recipients and
    # never asks the finance owner, so finance's outage is not the picker's outage. Finance's
    # export is the template door.
    serve_no_plan_profiles(monkeypatch)  # the plan half is answerable (a 503 otherwise) and empty
    reader = next(r for o, _s, r in ROWS if o == "cost")
    want = sorted(s for (o, s), rs in rail_rows().items() if o == "cost" and reader in rs)
    rail.down_owners = {"finance"}
    got = bff("/export/package/recipients", reader)
    assert got.status_code == 200 and sorted(r["value"] for r in got.json()["recipients"]) == want


def test_b_the_function_forms(rail):
    reader = next(r for o, _s, r in ROWS if o == "cost")
    rail.down = True
    with pytest.raises(HTTPException) as e:
        gateway._export_recipients_for(_User(reader))
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        gateway._fin_export_recipients_for(_User(reader))
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        gateway._picker_scopes(_User(reader))
    assert e.value.status_code == 503 and e.value.detail["owner"] == "cost"


def _post_export(monkeypatch, who, scope):
    monkeypatch.setattr(
        gateway, "_resolve_export_answers",
        lambda ids, user_id: [{"id": i, "verb_iri": "mesh#Foo", "subject_instance_id": "inst-1"}
                              for i in ids])
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(who)
    body = {"answers": [{"artifact_id": "a1"}]}
    if scope is not None:
        body["recipient_scope"] = scope
    try:
        with TestClient(gateway.app) as client:
            return client.post("/export/package", json=body, headers=BEARER)
    finally:
        gateway.app.dependency_overrides.clear()


def test_b_the_export_door_is_a_503_and_the_409_listing_omits_cost_when_the_rail_is_down(
        rail, monkeypatch):
    _no_plan(monkeypatch)
    scope, reader = next((s, r) for o, s, r in ROWS if o == "cost")
    rail.down = True
    got = _post_export(monkeypatch, reader, scope)
    assert got.status_code == 503, (got.status_code, got.text[:200])
    assert got.json()["detail"] == {"reason": "recipient_readers_unavailable"}
    listed = _post_export(monkeypatch, reader, None)
    assert listed.status_code == 409 and listed.json()["detail"]["options"] == []


def test_b_the_export_door_refuses_a_stranger_with_the_existing_403_when_the_rail_is_up(
        rail, monkeypatch):
    _no_plan(monkeypatch)
    scope = next(s for o, s, _r in ROWS if o == "cost")
    got = _post_export(monkeypatch, STRANGER, scope)
    assert got.status_code == 403
    assert got.json()["detail"]["reason"] == "not_a_recipient_you_may_export_to"


# -- arm c ------------------------------------------------------------------------------------

class _TopazHttp:
    """Topaz at the HTTP layer: records the body of each directory check and answers True."""

    def __init__(self):
        self.bodies = []

    def install(self, monkeypatch):
        outer = self

        class _R:
            def raise_for_status(self): ...
            def json(self): return {"check": True}

        class _C:
            def __init__(self, *a, **k): ...
            def __enter__(self): return self
            def __exit__(self, *a): return False

            def post(self, path, json=None):
                outer.bodies.append(json)
                return _R()

        monkeypatch.setattr(rr.httpx, "Client", _C)
        monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://topaz.test")


@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_c_the_engine_door_sends_check_payload_for_the_rows_owner(
        monkeypatch, engines, owner, scope, reader):
    topaz = _TopazHttp()
    topaz.install(monkeypatch)
    got = engines(owner, scope, reader)
    assert got.status_code == 404, got.text[:200]  # admitted
    assert topaz.bodies == [rr.check_payload(owner, scope, reader)], topaz.bodies


@pytest.mark.parametrize("owner,scope,reader", _row_params())
def test_c_the_bff_door_sends_check_payload_for_the_rows_owner(
        monkeypatch, bff, owner, scope, reader):
    topaz = _TopazHttp()
    topaz.install(monkeypatch)
    assert bff(_bff_download(owner, scope), reader).status_code == 200
    assert rr.check_payload(owner, scope, reader) in topaz.bodies
    # EVERY question the BFF asked is the person's, and on this owner's objects
    assert {b["subject_id"] for b in topaz.bodies} == {reader}
    assert {b["object_id"].split(":", 1)[0] for b in topaz.bodies} == {owner}


def test_c_each_owner_constant_is_a_key_of_the_shipped_rail():
    """Join, read from the yaml: the owner strings the consumers hold are keys the rail declares."""
    declared = set(yaml.safe_load(_RAIL_FILE.read_text(encoding="utf-8"))["recipient_readers"])
    assert gateway._COST_OWNER in declared and gateway._FIN_OWNER in declared
    assert cost_main._COST_OWNER == gateway._COST_OWNER
    assert fin_main._FIN_OWNER == gateway._FIN_OWNER
    assert gateway._COST_OWNER != gateway._FIN_OWNER


def test_c_every_scope_an_engine_discloses_has_a_shipped_row():
    """Join: a disclosed scope with no row is a package nobody can fetch. The scopes are the
    engines' own registries; the owners are the engines' own constants."""
    rows = rail_rows()
    assert {(gateway._COST_OWNER, s) for s in cost_seed.RECIPIENT_SCOPES} <= set(rows)
    assert {(gateway._FIN_OWNER, s) for s in fin_export.RECIPIENT_SCOPES} <= set(rows)


# -- arm d: test 3 of the 10-30 rule ------------------------------------------------------------

@pytest.mark.parametrize("owner", sorted(OWNERS))
def test_d_a_row_added_to_the_rail_admits_its_reader_with_no_code_change(
        monkeypatch, tmp_path, engines, bff, owner):
    scope = next(s for (o, s) in rail_rows() if o == owner)
    newcomer = "newcomer@example.com"
    assert newcomer not in rail_rows()[(owner, scope)]
    raw = copy.deepcopy(yaml.safe_load(_RAIL_FILE.read_text(encoding="utf-8")))
    raw["recipient_readers"][owner][scope]["grant_to"].append(newcomer)
    overlay = tmp_path / "recipient_readers.yaml"
    overlay.write_text(yaml.safe_dump(raw), encoding="utf-8")

    install(monkeypatch)  # the shipped rows: the newcomer is refused
    assert engines(owner, scope, newcomer).status_code == 403
    assert bff(_bff_download(owner, scope), newcomer).status_code == 403

    install(monkeypatch, path=overlay)  # the overlay's rows: admitted, nothing else changed
    assert engines(owner, scope, newcomer).status_code == 404  # past the gate
    assert bff(_bff_download(owner, scope), newcomer).status_code == 200
    old = rail_rows()[(owner, scope)][0]  # and the existing readers are still readers
    assert bff(_bff_download(owner, scope), old).status_code == 200


def test_d_the_double_refuses_what_the_loader_refuses(tmp_path):
    """CONTROL for the double: a malformed overlay is refused by the loader, not half-applied."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"recipient_readers": {"cost": {"S": {"granted_by": "x"}}}}))
    with pytest.raises(AssertionError):
        rail_rows(bad)


def test_the_real_function_denies_a_blank_argument_without_asking_topaz():
    """CONTROL: the contract the double mimics -- a missing argument or URL is False (no HTTP), so
    the doors need no special case for a blank caller."""
    assert rr.can_read_recipient("cost", "s", "", directory_url="http://x") is False
    assert rr.can_read_recipient("", "s", "a", directory_url="http://x") is False
    assert rr.can_read_recipient("cost", "s", "a", directory_url="") is False
    assert Rail({})("cost", "s", "") is False
