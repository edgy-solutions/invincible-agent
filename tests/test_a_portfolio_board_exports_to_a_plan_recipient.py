"""A Portfolio board exports to a plan recipient through a `policy/exports` profile.

A plan recipient is named by an answer-export profile (`agent_fleet/utils/answer_exports.py`, seed
`policy/exports/plan_answers.yaml`): the profile declares the verbs ("kinds") it takes and the
columns it writes. The BFF decides which answers of a board the recipient takes, engine-cost renders
them (`POST /answers_export`) and serves the file (`GET /artifact/{filename}`). Readers are the
`recipient_readers` rail under owner `plan`; `can_read_recipient` is faked here, keyed on
`(owner, scope, caller)`.

WHICH LAYERS ARE REAL. The gateway is real (stubbed neo4j session, as the mixed-board test does).
engine-cost is REAL, run through ASGI (`TestClient(cost_main.app)`) with its dist directory redirected
at a tmp dir. The profile loader is never stubbed: the seed profile is the subject. The doubles are
neo4j, the Topaz check, and engine-cost's `/measure/package_export` (counted, never served).
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import pathlib
import subprocess
import sys

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent import main as cost_main  # noqa: E402
from agent_fleet.cost_agent import measures  # noqa: E402
from agent_fleet.utils import answer_exports as AE  # noqa: E402
from src.iagent import gateway  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN = "notional-plan-office"
ALPHA = "notional-customer-alpha"
ALICE, BOB = "alice@example.com", "bob@example.com"
GOOD = "sha256:" + "a" * 64


# ── the board ────────────────────────────────────────────────────────────────────────────────
def _rec(aid, *, intent=None, routing=None, question="q?", summary="s", program="PGM-1",
         status="SUCCESS", valid="2026-10-01T00:00:00+00:00"):
    return {
        "id": aid, "is_owner": True, "question_text": question, "summary": summary,
        "status": status, "valid_as_of": valid, "origin_program": program,
        "resolved_intent": None if intent is None else json.dumps(intent),
        "routing_inline": None if routing is None else json.dumps(routing),
    }


#: measured shapes: an intent carrying the verb; a pre-hop answer carrying it in routing only; an
#: abstain (the supervisor chose no verb); and a cost answer.
SCHEDULE = _rec("a-sched", question="What is the schedule?", summary="Schedule: 3 milestones",
                intent={"verb_iri": "mesh:planSchedule", "subject_uri": "mesh:Portfolio/PGM-1"})
PREHOP = _rec("a-prehop", question="Cost curve?", summary="Curve: flat, 12 points",
              intent={"subject_uri": "mesh:Portfolio/PGM-1"},
              routing={"action": {"iri": "mesh:planCostCurve"}})
ABSTAIN = _rec("a-abstain", intent={"verb_iri": "UNKNOWN"}, routing={"action": {"iri": "UNKNOWN"}})
COST = _rec("a-cost", intent={"verb_iri": "mesh:costTrendAnalysis", "subject_instance_id": ""})

BOARD_PLAN = [SCHEDULE, PREHOP, ABSTAIN]
BOARD_MIXED = [COST, SCHEDULE]
BOARD_COST = [COST]
DIFF = _rec("a-diff", intent={"verb_iri": "mesh:planDiff", "subject_uri": "mesh:Portfolio/PGM-1"})
SESSION = _rec("a-session", intent={"verb_iri": "mesh:planSessionChanges",
                                    "subject_uri": "mesh:Portfolio/PGM-1"})
BOARD_SESSION = [DIFF, SESSION]
BOARD_REPORT_AND_SESSION = [SCHEDULE, DIFF, SESSION]


class _Rec:
    def __init__(self, row): self._row = row
    def single(self): return self._row


class _Session:
    def __init__(self, store): self._store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, _cypher, artifact_id=None, user_id=None, **_k):
        return _Rec(self._store.get(artifact_id))


class _Driver:
    def __init__(self, store): self._store = store
    def session(self): return _Session(self._store)


class _CostPackage:
    status_code = 200
    text = ""

    def json(self):
        return {"artifact_sha256": GOOD, "artifact_filename": "cost-validation-x.html",
                "artifact_bytes": 1, "algorithm_sha": "x", "lots_disclosed": [], "sections": []}


class _Caller:
    def __init__(self, authz_id): self.authz_id = authz_id


class _World:
    def __init__(self):
        self.user_id = ALICE
        self.cost_package_calls = 0
        self.rail_down = False
        # (owner, scope, caller) triples the fake rail admits
        self.readers = {("plan", PLAN, ALICE)}
        self.rail_calls: list[tuple] = []


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = _World()
    dist = tmp_path / "dist"
    monkeypatch.setattr(measures, "_repo_root", lambda: tmp_path)
    w.dist = dist

    def fake_can_read(owner, scope, caller_id, **_k):
        w.rail_calls.append((owner, scope, caller_id))
        if w.rail_down:
            raise ConnectionError("topaz is down")
        return (owner, scope, caller_id) in w.readers

    monkeypatch.setattr("agent_fleet.utils.recipient_readers.can_read_recipient", fake_can_read)
    monkeypatch.setattr(cost_main, "can_read_recipient", fake_can_read)
    monkeypatch.setattr(cost_main, "_current_caller", lambda: _Caller(w.user_id))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", None)
    monkeypatch.setattr(gateway, "_PLAN_PROFILES", None)

    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: type("U", (), {
        "authz_id": w.user_id, "id": "sub-" + w.user_id, "email": w.user_id, "roles": [],
        "persona": None, "entitled_domains": [], "is_authenticated": True})()

    with TestClient(cost_main.app) as engine:
        w.engine = engine

        class _Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, json=None, headers=None, **k):
                if url.endswith("/measure/package_export"):
                    w.cost_package_calls += 1
                    return _CostPackage()
                assert url.endswith("/answers_export"), url
                return engine.post("/answers_export", json=json)

            async def get(self, url, headers=None, **k):
                return engine.get(url[url.index("/artifact/"):])

        monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

        def bff(method, path, cards=None, **body):
            if cards is not None:
                monkeypatch.setattr(gateway, "neo4j_driver",
                                    _Driver({c["id"]: c for c in cards}))
                body["answers"] = [{"artifact_id": c["id"]} for c in cards]
            with TestClient(gateway.app) as client:
                if method == "GET":
                    return client.get(path)
                return client.post(path, json=body)

        w.export = lambda cards, scope=PLAN: bff("POST", "/export/package", cards,
                                                   recipient_scope=scope)
        w.offer = lambda cards: bff("POST", "/export/package/recipients", cards)
        w.get = lambda path: bff("GET", path)
        yield w
    gateway.app.dependency_overrides.clear()


def _plan_section(body):
    return next(d for d in body["documents"] if d["status"] == "exists")


def _refused_ids(body):
    return {i: d["reason_code"] for d in body["documents"] if d["status"] == "failed"
            for i in d["answers"]}


def _file_rows(w, section):
    data = (w.dist / section["artifact_filename"]).read_bytes()
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


# ── 1. the loader ────────────────────────────────────────────────────────────────────────────
def test_the_seed_plan_answers_profile_loads():
    profiles = AE.load_answer_export_profiles()
    p = profiles["plan_answers"]
    assert p.recipients == (PLAN,) and p.format == "csv"
    assert [c.as_ for c in p.columns][0] == "Answer"


_GOOD = {
    "name": "p", "format": "csv", "scope": "answer", "label": "P", "kinds": ["mesh:planSchedule"],
    "recipients": ["r-1"], "columns": [{"field": "answer_id", "as": "Answer"}],
}


def _load(tmp_path, *rows, overlay=()):
    import yaml
    seed = tmp_path / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rows):
        (seed / f"{i}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    ov = []
    for j, r in enumerate(overlay):
        d = tmp_path / f"ov{j}"
        d.mkdir(exist_ok=True)
        (d / "x.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
        ov.append(d)
    return AE.load_answer_export_profiles(seed, ov)


@pytest.mark.parametrize("label,edit,fragment", [
    ("unknown key", lambda r: r.update(color="red"), "unknown key"),
    ("missing kinds", lambda r: r.pop("kinds"), "missing required key 'kinds'"),
    ("empty recipients", lambda r: r.update(recipients=[]), "missing required key 'recipients'"),
    ("duplicate as", lambda r: r.update(columns=[{"field": "answer_id", "as": "X"},
                                                 {"field": "summary", "as": "X"}]), "used twice"),
    ("unknown field", lambda r: r.update(columns=[{"field": "nope", "as": "X"}]),
     "outside the answer fields"),
    ("bad format", lambda r: r.update(format="xlsx"), "format 'xlsx'"),
    ("bad scope", lambda r: r.update(scope="row"), "scope 'row'"),
    ("kinds all in a list", lambda r: r.update(kinds=["all"]), "listed explicitly"),
    ("kinds star", lambda r: r.update(kinds=["*"]), "listed explicitly"),
    ("kinds mesh star", lambda r: r.update(kinds=["mesh:*"]), "listed explicitly"),
    ("kinds bare string all", lambda r: r.update(kinds="all"), "listed explicitly"),
])
def test_the_loader_refuses_by_name(tmp_path, label, edit, fragment):
    row = json.loads(json.dumps(_GOOD))
    edit(row)
    with pytest.raises(AE.AnswerExportError) as exc:
        _load(tmp_path, row)
    assert fragment in str(exc.value), label


def test_a_recipient_in_two_profiles_is_refused(tmp_path):
    other = {**json.loads(json.dumps(_GOOD)), "name": "q"}
    with pytest.raises(AE.AnswerExportError) as exc:
        _load(tmp_path, _GOOD, other)
    assert "is named by both" in str(exc.value)


def test_an_overlay_replaces_the_row_whole_and_a_tombstone_removes_it(tmp_path):
    changed = {**json.loads(json.dumps(_GOOD)), "label": "Replaced", "recipients": ["r-2"]}
    got = _load(tmp_path, _GOOD, overlay=[changed])
    assert got["p"].label == "Replaced" and got["p"].recipients == ("r-2",)
    gone = _load(tmp_path / "t", _GOOD, overlay=[{"name": "p", "deleted": True}])
    assert gone == {}


# ── 2. kinds are true ────────────────────────────────────────────────────────────────────────
#: The plan recipient takes REPORT verbs only (ruled 10-29, #148). Engine P declares no marker for
#: a session/scenario-state verb, so the classification is a decision and THIS is where it is
#: recorded: the one place a list is typed. Each SESSION_STATE verb's subject IS a scenario or
#: session; REPORT is everything else Engine P declares.
REPORT = {
    "mesh:planCostCurve", "mesh:planFundingGap", "mesh:planSiteLoad",
    "mesh:planDependencyViolations", "mesh:planDependencyNeighborhood", "mesh:planMaturityGrid",
    "mesh:planCapabilityPath", "mesh:planProcessEvolution", "mesh:planTechFootprint",
    "mesh:planSchedule", "mesh:planCoverageGap",
}
SESSION_STATE = {"mesh:planCommitScenario", "mesh:planDiff", "mesh:planSessionChanges"}


def _engine_p():
    from agent_fleet.planning_agent import main as planning
    return planning


def test_every_engine_p_verb_is_classified_report_or_session_state():
    declared = {v["verb"] for v in _engine_p().VERBS}
    assert not (REPORT & SESSION_STATE), sorted(REPORT & SESSION_STATE)
    assert REPORT | SESSION_STATE == declared, (
        "Engine P's verbs and this classification disagree; a NEW Engine P verb must be classified "
        "as REPORT or SESSION_STATE here (and added to plan_answers.yaml if REPORT): "
        f"{sorted((REPORT | SESSION_STATE) ^ declared)}")


def test_a_writing_verb_is_never_classified_as_a_report():
    planning = _engine_p()
    verb_of = {v["fn"]: v["verb"] for v in planning.VERBS}
    mutating = {verb_of[fn] for fn in planning.MUTATING_VERBS}
    assert mutating and mutating <= SESSION_STATE, sorted(mutating - SESSION_STATE)


def test_plan_answers_kinds_are_exactly_the_report_verbs():
    kinds = set(AE.load_answer_export_profiles()["plan_answers"].kinds)
    assert kinds == REPORT, sorted(kinds ^ REPORT)


def test_every_profiles_kinds_are_disjoint_from_cost_and_fin():
    from agent_fleet.finance_agent.main import VERB_TO_FN
    taken = {"mesh:" + v for v in C.EXPORTABLE} | set(VERB_TO_FN)
    for p in AE.load_answer_export_profiles().values():
        assert not (set(p.kinds) & taken), (p.name, sorted(set(p.kinds) & taken))
        assert not (set(p.kinds) & SESSION_STATE), (p.name, sorted(set(p.kinds) & SESSION_STATE))


# ── 3. render ────────────────────────────────────────────────────────────────────────────────
def _profile(fmt):
    return AE.AnswerExportProfile(
        name="p", format=fmt, scope="answer", label="P", kinds=("mesh:planSchedule",),
        recipients=("r",), columns=(AE.Column("answer_id", "Answer"), AE.Column("summary", "Sum"),
                                    AE.Column("subject", "Subj")))


ROWS = [{"answer_id": "1", "summary": "é, \"q\"", "subject": None},
        {"answer_id": "2", "summary": "x", "subject": "mesh:S"}]


def test_csv_is_crlf_without_bom_and_the_header_is_the_as_list():
    data = AE.render(_profile("csv"), ROWS)
    assert not data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8").split("\r\n")
    assert lines[0] == "Answer,Sum,Subj" and lines[-1] == ""
    assert "\n" not in data.decode("utf-8").replace("\r\n", "")
    assert lines[1] == '1,"é, ""q""",'  # None is written empty


def test_json_keeps_column_order_and_omits_none():
    body = json.loads(AE.render(_profile("json"), ROWS))
    assert list(body["rows"][0]) == ["Answer", "Sum"]
    assert list(body["rows"][1]) == ["Answer", "Sum", "Subj"]


@pytest.mark.parametrize("fmt", ["csv", "json"])
def test_render_is_deterministic(fmt):
    assert AE.render(_profile(fmt), ROWS) == AE.render(_profile(fmt), ROWS)


# ── 4. the Portfolio board exports ──────────────────────────────────────────────────────────
def test_a_portfolio_board_exports_to_the_plan_recipient(world):
    r = world.export(BOARD_PLAN)
    assert r.status_code == 200, r.text
    body = r.json()
    section = _plan_section(body)
    assert section["engine"] == "cost" and section["answers"] == ["a-sched", "a-prehop"]
    assert section["artifact_sha256"].startswith("sha256:")
    assert body["export_id"] == section["artifact_sha256"]
    rows = _file_rows(world, section)
    assert [x["Answer"] for x in rows] == ["a-sched", "a-prehop"]  # the plan answers, board order
    assert rows[1]["Verb"] == "mesh:planCostCurve"  # the pre-hop answer's verb, from routing
    assert rows[0]["Subject"] == "mesh:Portfolio/PGM-1"
    assert _refused_ids(body) == {"a-abstain": "no_verb"}
    assert body["status"] == "partial" and body["reason"] == "1 of 3 answers refused"
    assert world.cost_package_calls == 0  # engine-cost's package_export is not called


# ── 5. a mixed board ─────────────────────────────────────────────────────────────────────────
def test_a_cost_answer_on_a_plan_board_is_refused_as_not_a_kind(world):
    r = world.export(BOARD_MIXED)
    assert r.status_code == 200, r.text
    body = r.json()
    assert _refused_ids(body) == {"a-cost": "not_a_kind_this_recipient_takes"}
    assert _plan_section(body)["answers"] == ["a-sched"]
    assert [x["Answer"] for x in _file_rows(world, _plan_section(body))] == ["a-sched"]
    assert world.cost_package_calls == 0


def test_an_all_cost_board_to_a_plan_recipient_makes_no_engine_call(world):
    r = world.export(BOARD_COST)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "failed" and body["export_id"] is None
    assert body["reason"] == "1 of 1 answers refused"
    assert _refused_ids(body) == {"a-cost": "not_a_kind_this_recipient_takes"}
    assert world.cost_package_calls == 0 and not world.dist.exists()


# ── 6. the offer agrees with the export ──────────────────────────────────────────────────────
def _plan_offer(world, cards):
    r = world.offer(cards)
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["recipients"] if x["value"] == PLAN)


@pytest.mark.parametrize("cards", [BOARD_PLAN, BOARD_MIXED])
def test_the_offer_equals_what_the_export_took_and_refused(world, cards):
    offer = _plan_offer(world, cards)
    body = world.export(cards).json()
    took = _plan_section(body)["answers"]
    assert offer["offered"] is True and offer["exports"] == took
    assert {i["answer_id"]: i["reason_code"] for i in offer["refused"]} == _refused_ids(body)
    assert offer["label"] == PLAN  # cost's entries are labelled with the bare scope


def test_an_all_cost_board_is_not_offered_to_the_plan_recipient(world):
    offer = _plan_offer(world, BOARD_COST)
    assert offer["offered"] is False and offer["reason_code"] == "takes_none_of_these_answers"
    assert offer["exports"] == []
    assert [i["reason_code"] for i in offer["refused"]] == ["not_a_kind_this_recipient_takes"]


# ── 7. readers ───────────────────────────────────────────────────────────────────────────────
def test_a_non_reader_is_refused_at_the_bff_with_the_compliant_envelope(world):
    world.user_id = BOB
    r = world.export(BOARD_PLAN)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["refusal"]["policy_id"] == "recipient_readers"
    assert "grantable_by" in detail["refusal"]
    assert world.cost_package_calls == 0 and not world.dist.exists()


def test_the_plan_recipient_is_absent_from_a_non_readers_list(world):
    world.user_id = BOB
    assert PLAN not in [x["value"] for x in world.get("/export/package/recipients")
                        .json()["recipients"]]
    world.user_id = ALICE
    assert PLAN in [x["value"] for x in world.get("/export/package/recipients").json()["recipients"]]


def test_bob_cannot_download_alices_file(world):
    section = _plan_section(world.export(BOARD_PLAN).json())
    uri = section["artifact_uri"]
    world.user_id = BOB
    assert world.get(uri).status_code == 403


def test_the_engine_refuses_a_non_reader_itself(world):
    world.user_id = BOB
    r = world.engine.post("/answers_export", json={
        "recipient_scope": PLAN, "export_id": "x1", "user_email": BOB, "rows": []})
    assert r.status_code == 403
    assert r.json()["detail"]["refusal"]["policy_id"] == "recipient_readers"
    assert not world.dist.exists()  # nothing was written


def test_a_rail_that_cannot_be_asked_is_a_503_never_a_deny(world):
    section = _plan_section(world.export(BOARD_PLAN).json())
    name = section["artifact_filename"]
    world.rail_down = True
    r = world.export(BOARD_PLAN)
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "recipient_readers_unavailable"}
    e = world.engine.post("/answers_export", json={
        "recipient_scope": PLAN, "export_id": "x2", "user_email": ALICE, "rows": []})
    assert e.status_code == 503 and e.json()["detail"] == {"reason": "recipient_readers_unavailable"}
    d = world.get(f"/export/package/artifact/{name}")
    assert d.status_code == 503 and d.json()["detail"] == {"reason": "recipient_readers_unavailable"}
    direct = world.engine.get(f"/artifact/{name}")
    assert direct.status_code == 503


# ── 8. the download ──────────────────────────────────────────────────────────────────────────
def test_alice_downloads_her_file(world):
    section = _plan_section(world.export(BOARD_PLAN).json())
    r = world.get(section["artifact_uri"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "sha256:" + hashlib.sha256(r.content).hexdigest() == section["artifact_sha256"]


def test_a_json_profile_is_served_as_json(world, monkeypatch, tmp_path):
    prof = AE.AnswerExportProfile(
        name="plan_json", format="json", scope="answer", label="J", kinds=("mesh:planSchedule",),
        recipients=("notional-plan-json",), columns=(AE.Column("answer_id", "Answer"),))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", {"plan_json": prof})
    world.readers.add(("plan", "notional-plan-json", ALICE))
    r = world.engine.post("/answers_export", json={
        "recipient_scope": "notional-plan-json", "export_id": "e1", "user_email": ALICE,
        "rows": [{"answer_id": "z"}]})
    assert r.status_code == 200, r.text
    got = world.engine.get(f"/artifact/{r.json()['artifact_filename']}")
    assert got.status_code == 200 and got.headers["content-type"].startswith("application/json")


def test_the_filename_to_scope_match_is_closed_not_a_split_on_dashes():
    profiles = AE.load_answer_export_profiles()
    name = AE.artifact_filename(profiles["plan_answers"], PLAN, "abc123")
    assert AE.match_artifact(profiles, name)[1] == PLAN
    assert AE.match_artifact(profiles, name.replace(PLAN, "notional-plan")) is None
    assert AE.match_artifact(profiles, "ia-answers-plan_answers-" + PLAN + "-../x.csv") is None


# ── 9. nothing else moved ────────────────────────────────────────────────────────────────────
def test_a_cost_only_board_to_alpha_answers_as_it_does_on_master(world):
    world.user_id = ALICE
    r = world.export(BOARD_COST, scope=ALPHA)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "export_id": GOOD, "status": "exists", "recipient_scope": ALPHA, "reason": None,
        "artifact_uri": "/export/package/artifact/cost-validation-x.html",
        "artifact_sha256": GOOD, "artifact_bytes": 1,
        "artifact_filename": "cost-validation-x.html", "algorithm_sha": "x",
        "lots_disclosed": [], "sections": [], "template_id": None}
    assert world.cost_package_calls == 1


def test_a_rail_outage_does_not_take_the_cost_picker_or_a_cost_export_down(world):
    world.rail_down = True
    r = world.get("/export/package/recipients")
    assert r.status_code == 200 and ALPHA in [x["value"] for x in r.json()["recipients"]]
    assert world.export(BOARD_COST, scope=ALPHA).status_code == 200


# ── dark by default, and the image carries it ────────────────────────────────────────────────
def test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark(monkeypatch):
    import yaml
    owners = yaml.safe_load((ROOT / "policy" / "recipient_readers.yaml")
                            .read_text(encoding="utf-8"))["recipient_readers"]
    assert "plan" not in owners
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    monkeypatch.setattr(gateway, "_PLAN_PROFILES", None)
    alice = type("U", (), {"authz_id": ALICE})()
    assert gateway._plan_recipients_for(alice) == []  # the REAL can_read_recipient: deny


def test_the_flattened_image_layout_loads_the_seed_profile(tmp_path):
    """/app/utils/answer_exports.py and /app/policy/exports/ (Dockerfile.agent), no repo around."""
    app = tmp_path / "app"
    (app / "utils").mkdir(parents=True)
    (app / "policy").mkdir()
    (app / "utils" / "answer_exports.py").write_text(
        (ROOT / "agent_fleet" / "utils" / "answer_exports.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    import shutil
    shutil.copytree(ROOT / "policy" / "exports", app / "policy" / "exports")
    out = subprocess.run(
        [sys.executable, "-I", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]);"
         "from utils import answer_exports as a; print(sorted(a.load_answer_export_profiles()))",
         str(app)], capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-600:]
    assert "plan_answers" in out.stdout


def test_the_agent_dockerfile_copies_policy_exports():
    text = (ROOT / ".github" / "docker" / "Dockerfile.agent").read_text(encoding="utf-8")
    assert "COPY policy/exports/ /app/policy/exports/" in text
    assert "agent_fleet/utils/" in text and "/app/utils/" in text


def test_the_gateway_hop_is_sealed_in_the_identity_census():
    src = (ROOT / "tests" / "test_the_person_reaches_the_migrated_route.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    hops = next(n.value for n in tree.body if isinstance(n, ast.AnnAssign)
                and getattr(n.target, "id", "") == "HOPS")
    assert any('"_export_plan_answers"' in ast.get_source_segment(src, e) for e in hops.elts)


# ── ruled 10-29: session/scenario-state answers are not exported to the plan recipient ──────────
def test_session_state_answers_on_a_plan_board_are_refused_and_report_answers_still_export(world):
    body = world.export(BOARD_REPORT_AND_SESSION).json()
    assert _refused_ids(body) == {"a-diff": "not_a_kind_this_recipient_takes",
                                  "a-session": "not_a_kind_this_recipient_takes"}
    assert _plan_section(body)["answers"] == ["a-sched"]
    assert [x["Answer"] for x in _file_rows(world, _plan_section(body))] == ["a-sched"]


def test_a_board_of_only_session_state_answers_is_not_offered_to_the_plan_recipient(world):
    offer = _plan_offer(world, BOARD_SESSION)
    assert offer["offered"] is False and offer["reason_code"] == "takes_none_of_these_answers"
    assert offer["exports"] == []
    assert [i["reason_code"] for i in offer["refused"]] == ["not_a_kind_this_recipient_takes"] * 2
