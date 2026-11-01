"""A Portfolio board exports to a plan recipient through a `policy/exports/answers` profile.

A plan recipient is named by an answer-export profile (`agent_fleet/utils/answer_exports.py`, seed
`policy/exports/answers/plan-answers.yaml`): the profile declares the verbs ("kinds") it takes and the
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
from tests.recipient_rail_double import rail_rows  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAN = "notional-plan-office"
ALPHA = "notional-customer-alpha"
ALICE, BOB = "alice@example.com", "bob@example.com"
GOOD = "sha256:" + "a" * 64


# ── the board ────────────────────────────────────────────────────────────────────────────────
def _rec(aid, *, intent=None, routing=None, question="q?", summary="s", program="PGM-1",
         status="SUCCESS", valid="2026-10-01T00:00:00+00:00", rendered=None):
    return {
        "id": aid, "is_owner": True, "question_text": question, "summary": summary,
        "status": status, "valid_as_of": valid, "origin_program": program,
        "resolved_intent": None if intent is None else json.dumps(intent),
        "routing_inline": None if routing is None else json.dumps(routing),
        "rendered_output": rendered,
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
        self.answers_export_calls = 0
        self.rail_down = False
        # (owner, scope, caller) triples the fake rail admits
        # the plan row is this test's own; cost's and finance's rows are the SHIPPED rail's (read
        # through the sync's loader), since the cost doors ask the rail for them too
        self.readers = {("plan", PLAN, ALICE)} | {
            (o, s, r) for (o, s), rs in rail_rows().items() if o != "plan" for r in rs}
        self.rail_calls: list[tuple] = []
        # can_export (profile name, caller) pairs the fake rail admits; the name is READ from the
        # loaded profile, never typed
        self.profile_name = AE.profile_for_recipient(
            AE.load_answer_export_profiles(), PLAN).name
        self.exporters = {(self.profile_name, ALICE)}
        self.export_down = False
        self.export_calls: list[tuple] = []
        # the BFF reads the profile set engine-cost SERVES: "ok" asks cost's real app; "down" is a
        # transport error; "bad" is a 200 whose set does not validate; "500" a non-2xx
        self.profiles_mode = "ok"
        self.profiles_calls = 0


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

    def fake_can_export(profile_name, caller_id, **_k):
        w.export_calls.append((profile_name, caller_id))
        if w.export_down:
            raise ConnectionError("topaz is down")
        return (profile_name, caller_id) in w.exporters

    # the BFF imports the module function at call time; cost bound the name at import
    monkeypatch.setattr("agent_fleet.utils.export_capability.can_export", fake_can_export)
    monkeypatch.setattr(cost_main, "can_export", fake_can_export)
    monkeypatch.setattr(cost_main, "_current_caller", lambda: _Caller(w.user_id))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", None)

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
                w.answers_export_calls += 1
                return engine.post("/answers_export", json=json)

            async def get(self, url, headers=None, **k):
                return engine.get(url[url.index("/artifact/"):])

        monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

        def profiles_get(url):
            import httpx
            w.profiles_calls += 1
            assert url.endswith("/answers_export/profiles"), url
            if w.profiles_mode == "down":
                raise ConnectionError("engine-cost is down")
            if w.profiles_mode == "500":
                return httpx.Response(500, json={"detail": "boom"})
            if w.profiles_mode == "bad":
                return httpx.Response(200, json={"profiles": [{"name": "x"}]})
            return engine.get("/answers_export/profiles")

        monkeypatch.setattr(gateway, "_cost_profiles_get", profiles_get)

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
    p = profiles["plan-answers"]
    assert p.recipients == (PLAN,) and p.format == "csv" and p.granularity == "answer"
    assert [c.output for c in p.columns][0] == "Answer"
    assert p.header() == {"name": "plan-answers", "format": "csv", "granularity": "answer",
                          "label": p.label}


def _col(output, field):
    return {"output": output, "source": {"field": field}}


_GOOD = {
    "column_map_version": 1, "name": "p", "format": "csv", "granularity": "answer", "label": "P",
    "kinds": ["mesh:planSchedule"], "recipients": ["r-1"],
    "columns": [{"output": "Answer", "source": {"field": "answer_id"}}],
}


def _load(tmp_path, *rows, overlay=()):
    import yaml
    seed = tmp_path / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    for r in rows:
        r = dict(r)
        stem = r.pop("_stem", r.get("name"))  # `_stem` writes the file under another name
        (seed / f"{stem}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    ov = []
    for j, r in enumerate(overlay):
        d = tmp_path / f"ov{j}"
        d.mkdir(exist_ok=True)
        (d / f"{r['name']}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
        ov.append(d)
    return AE.load_answer_export_profiles(seed, ov)


@pytest.mark.parametrize("label,edit,fragment", [
    ("unknown key", lambda r: r.update(color="red"), "unknown key"),
    ("missing kinds", lambda r: r.pop("kinds"), "missing required key 'kinds'"),
    ("empty recipients", lambda r: r.update(recipients=[]), "missing required key 'recipients'"),
    ("duplicate output", lambda r: r.update(columns=[_col("X", "answer_id"), _col("X", "summary")]),
     "used twice"),
    ("blank output", lambda r: r.update(columns=[_col("  ", "answer_id")]), "non-blank 'output'"),
    ("unknown field", lambda r: r.update(columns=[_col("X", "nope")]),
     "outside the answer fields"),
    ("the old `as` key", lambda r: r.update(columns=[{"field": "answer_id", "as": "X"}]),
     "columns entry carries"),
    ("bad format", lambda r: r.update(format="xlsx"), "format 'xlsx'"),
    ("scope given (the old header key)", lambda r: r.update(scope="answer"), "unknown key"),
    ("granularity notice_part", lambda r: r.update(granularity="notice_part"),
     "granularity 'notice_part'"),
    ("granularity row", lambda r: r.update(granularity="row"), "granularity 'row'"),
    ("column_map_version 2", lambda r: r.update(column_map_version=2), "column_map_version 2"),
    ("name that is not a stem", lambda r: r.update(_stem="other"), "is not the file stem"),
    ("name outside lane/01's rule", lambda r: r.update(name="Plan_Answers", _stem="Plan_Answers"),
     "does not match"),
    ("column key: format", lambda r: r.update(columns=[{**_col("X", "answer_id"), "format": "iso"}]),
     "source.field only"),
    ("column key: on_unresolvable",
     lambda r: r.update(columns=[{**_col("X", "answer_id"), "on_unresolvable": "blank"}]),
     "source.field only"),
    ("column key: landing", lambda r: r.update(columns=[{**_col("X", "answer_id"), "landing": "Y"}]),
     "source.field only"),
    ("column key: transforms",
     lambda r: r.update(columns=[{**_col("X", "answer_id"), "transforms": ["trim"]}]),
     "source.field only"),
    ("source key: row_field",
     lambda r: r.update(columns=[{"output": "X", "source": {"row_field": "affected_mpn"}}]),
     "source.field only"),
    ("source key: absent_row",
     lambda r: r.update(columns=[{"output": "X",
                                  "source": {"field": "answer_id", "absent_row": "empty_cell"}}]),
     "source.field only"),
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
        "as REPORT or SESSION_STATE here (and added to plan-answers.yaml if REPORT): "
        f"{sorted((REPORT | SESSION_STATE) ^ declared)}")


def test_a_writing_verb_is_never_classified_as_a_report():
    planning = _engine_p()
    verb_of = {v["fn"]: v["verb"] for v in planning.VERBS}
    mutating = {verb_of[fn] for fn in planning.MUTATING_VERBS}
    assert mutating and mutating <= SESSION_STATE, sorted(mutating - SESSION_STATE)


def test_plan_answers_kinds_are_exactly_the_report_verbs():
    kinds = set(AE.load_answer_export_profiles()["plan-answers"].kinds)
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
        name="p", format=fmt, granularity="answer", label="P", kinds=("mesh:planSchedule",),
        recipients=("r",), columns=(AE.Column("answer_id", "Answer"), AE.Column("summary", "Sum"),
                                    AE.Column("subject", "Subj")))


ROWS = [{"answer_id": "1", "summary": "é, \"q\"", "subject": None},
        {"answer_id": "2", "summary": "x", "subject": "mesh:S"}]


def test_csv_is_crlf_without_bom_and_the_header_is_the_output_list():
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
        name="plan-json", format="json", granularity="answer", label="J",
        kinds=("mesh:planSchedule",),
        recipients=("notional-plan-json",), columns=(AE.Column("answer_id", "Answer"),))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", {"plan-json": prof})
    world.readers.add(("plan", "notional-plan-json", ALICE))
    world.exporters.add(("plan-json", ALICE))
    r = world.engine.post("/answers_export", json={
        "recipient_scope": "notional-plan-json", "export_id": "e1", "user_email": ALICE,
        "rows": [{"answer_id": "z"}]})
    assert r.status_code == 200, r.text
    got = world.engine.get(f"/artifact/{r.json()['artifact_filename']}")
    assert got.status_code == 200 and got.headers["content-type"].startswith("application/json")


def test_the_filename_to_scope_match_is_closed_not_a_split_on_dashes():
    profiles = AE.load_answer_export_profiles()
    name = AE.artifact_filename(profiles["plan-answers"], PLAN, "abc123")
    assert AE.match_artifact(profiles, name)[1] == PLAN
    assert AE.match_artifact(profiles, name.replace(PLAN, "notional-plan")) is None
    assert AE.match_artifact(profiles, "ia-answers-plan-answers-" + PLAN + "-../x.csv") is None


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


def test_a_rail_outage_takes_the_cost_door_and_the_picker_down_as_a_503(world):
    """Cost's readers ride the rail now (they were a code table when this test said the opposite):
    a rail that cannot be asked is a 503 at the door, never a 403, and (ruled 10-31, was: omitted)
    at the picker too, which names the owner it was asking."""
    world.rail_down = True
    r = world.get("/export/package/recipients")
    assert r.status_code == 503 and r.json()["detail"] == {
        "reason": "recipient_readers_unavailable", "owner": "cost"}
    got = world.export(BOARD_COST, scope=ALPHA)
    assert got.status_code == 503 and got.json()["detail"] == {
        "reason": "recipient_readers_unavailable"}

# ── the plan owner ships (ruled 2026-10-30), and the image carries it ─────────────────────────
def test_the_shipped_plan_owner_is_seed_granted_for_scopes_the_plan_path_offers_and_denies_without_topaz(
        monkeypatch):
    """The plan owner SHIPS (ruled 2026-10-30; this test said the opposite before the row was
    ruled). What stays true, read through the sync's own loader: every shipped plan row is granted
    by `seed` (a shipped row's grantor is the seed, never a person), and every plan scope is one
    the plan path offers -- a recipient of a served answer-export profile, read from the profile
    loader, not typed. And with no Topaz to ask, the REAL can_read_recipient still denies."""
    import yaml
    sys.path.insert(0, str(ROOT / "policy" / "sync"))
    import recipient_reader_sync as rrs
    raw = yaml.safe_load((ROOT / "policy" / "recipient_readers.yaml")
                         .read_text(encoding="utf-8"))
    rows, errors = rrs.load_readers(raw)
    assert errors == [], errors
    plan_rows = [r for r in rows if r.owner == "plan"]
    assert plan_rows, "the plan owner ships a row (ruled 2026-10-30)"
    assert {r.granted_by for r in plan_rows} == {"seed"}
    offered = {s for p in AE.load_answer_export_profiles().values() for s in p.recipients}
    assert {r.scope for r in plan_rows} <= offered
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", None)
    with TestClient(cost_main.app) as engine:
        monkeypatch.setattr(gateway, "_cost_profiles_get",
                            lambda url: engine.get("/answers_export/profiles"))
        alice = type("U", (), {"authz_id": ALICE})()
        assert gateway._plan_recipients_for(alice) == []  # the REAL can_read_recipient: deny


def test_the_flattened_image_layout_loads_the_seed_profile(tmp_path):
    """/app/utils/answer_exports.py and /app/policy/exports/answers/ (Dockerfile.agent copies
    policy/exports/ whole, the subdirectory with it), no repo around."""
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
    assert "plan-answers" in out.stdout


def test_the_agent_dockerfile_copies_policy_exports():
    text = (ROOT / ".github" / "docker" / "Dockerfile.agent").read_text(encoding="utf-8")
    assert "COPY policy/exports/ /app/policy/exports/" in text
    # the COPY is of the directory, so `answers/` lands at the loader's default fallback
    assert (ROOT / "policy" / "exports" / "answers").is_dir()
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


# ── ruled 10-29: only baseline answers export; a scenario-computed one is refused ────────────────
def _scen(aid, *refs, verb="mesh:planCostCurve", raw=None):
    comps = [{"type": "card", **({} if r is None else {"state_ref": r})} for r in refs]
    return _rec(aid, intent={"verb_iri": verb, "subject_uri": "mesh:Portfolio/PGM-1"},
                rendered=raw if raw is not None else json.dumps({"components": comps}))


def _refused_items(w, cards):
    return {i["answer_id"]: i for i in _plan_offer(w, cards)["refused"]}


def test_a_scenario_computed_answer_is_refused_naming_the_scenario(world):
    scen = _scen("a-scen", "SC-ALPHA")
    body = world.export([SCHEDULE, scen]).json()
    assert _refused_ids(body) == {"a-scen": "scenario_answer"}
    entry = next(d for d in body["documents"] if d["status"] == "failed")
    assert entry["scenario_id"] == "SC-ALPHA" and "SC-ALPHA" in entry["reason"]
    item = _refused_items(world, [SCHEDULE, scen])["a-scen"]
    assert item["reason_code"] == "scenario_answer" and item["scenario_id"] == "SC-ALPHA"
    assert "SC-ALPHA" in item["reason"]
    assert [x["Answer"] for x in _file_rows(world, _plan_section(body))] == ["a-sched"]


def test_the_same_verb_against_baseline_exports(world):
    base = _scen("a-base", "baseline")
    body = world.export([_scen("a-scen", "SC-ALPHA"), base]).json()
    assert _plan_section(body)["answers"] == ["a-base"]
    assert [x["Answer"] for x in _file_rows(world, _plan_section(body))] == ["a-base"]


@pytest.mark.parametrize("card", [
    _scen("a-null", raw="null"),
    _scen("a-nokey", None, None),
    _scen("a-junk", raw="{not json"),
], ids=["null", "no_state_ref", "unparseable"])
def test_an_absent_state_reads_as_baseline(world, card):
    body = world.export([card]).json()
    assert _plan_section(body)["answers"] == [card["id"]]
    assert _refused_ids(body) == {}


def test_the_kind_refusal_precedes_the_scenario_refusal(world):
    diff = _scen("a-sdiff", "SC-ALPHA", verb="mesh:planDiff")
    body = world.export([SCHEDULE, diff]).json()
    assert _refused_ids(body) == {"a-sdiff": "not_a_kind_this_recipient_takes"}
    assert "scenario_id" not in _refused_items(world, [SCHEDULE, diff])["a-sdiff"]


def test_the_offer_agrees_on_scenario_answers(world):
    only = [_scen("s1", "SC-A"), _scen("s2", "SC-B")]
    offer = _plan_offer(world, only)
    assert offer["offered"] is False and offer["reason_code"] == "takes_none_of_these_answers"
    assert [i["reason_code"] for i in offer["refused"]] == ["scenario_answer"] * 2
    mixed = [_scen("s1", "SC-A"), _scen("b1", "baseline")]
    offer = _plan_offer(world, mixed)
    assert offer["offered"] is True and offer["exports"] == ["b1"]
    assert [i["answer_id"] for i in offer["refused"]] == ["s1"]


def test_two_scenarios_on_one_answer_are_both_named_sorted(world):
    two = _scen("a-two", "SC-B", "SC-A")
    item = _refused_items(world, [two])["a-two"]
    assert item["scenario_id"] == "SC-A, SC-B" and "SC-A, SC-B" in item["reason"]


def test_state_refs_never_reach_an_engine_payload():
    resolved = [gateway._resolve_export_record(c) for c in
                (COST, _scen("a-scen", "SC-ALPHA", verb="mesh:costTrendAnalysis"))]
    assert resolved[1]["state_refs"] == ["SC-ALPHA"]
    for _engine, answers in gateway._partition_export_answers(resolved):
        assert all("state_refs" not in a for a in answers)


# ── 5. the two loaders are apart (the join seal) ─────────────────────────────────────────────
#: Fin's `answer_exports` and lane/01's `src/iagent/export_profiles.py` each refuse the other's
#: files, so they are kept apart by a SUBDIRECTORY until the SDK's export-profile header type
#: lands (iagent-mesh v0.9.12) and one loader reads both. This arm runs on the REAL tree.
def _lane01():
    from src.iagent import export_profiles as EP
    return EP


def test_the_two_loaders_are_apart_on_the_real_tree(monkeypatch):
    EP = _lane01()
    for var in ("INGEST_EXPORT_PROFILE_DIR", "EXPORT_PROFILE_POLICY_DIR",
                "EXPORT_PROFILE_OVERLAY_DIRS"):
        monkeypatch.delenv(var, raising=False)
    EP.clear_cache()
    try:
        theirs = EP.load_profiles()
        ours = AE.load_answer_export_profiles()
    finally:
        EP.clear_cache()
    assert ours, "fin's loader found nothing on the real tree"
    assert theirs, "lane/01's loader found nothing on the real tree"
    assert not (set(ours) & set(theirs)), sorted(set(ours) & set(theirs))
    assert all(isinstance(v, EP.Profile) for v in theirs.values()), {
        k: v for k, v in theirs.items() if not isinstance(v, EP.Profile)}
    assert all(isinstance(v, AE.AnswerExportProfile) for v in ours.values())
    # the shared header vocabulary: lane/01's keys are READ from its module, never typed
    shared = {"name", "label", "format", "granularity", "column_map_version"}
    assert shared <= set(EP._TOP_KEYS) and shared <= set(AE._TOP_KEYS)
    assert AE.COLUMN_MAP_VERSION == EP.COLUMN_MAP_VERSION
    assert AE._NAME_RE.pattern == EP._NAME_RE.pattern
    assert set(AE.MEDIA_TYPES) == set(EP.FORMATS)
    assert AE._COLUMN_KEYS <= set(EP._COL_KEYS)
    assert AE._SOURCE_KEYS <= set(EP._SRC_KEYS)


def test_the_join_seal_can_fire_each_loader_refuses_the_others_file(monkeypatch, tmp_path):
    """POSITIVE CONTROL: fin's yaml beside lane/01's default-csv.yaml in one directory."""
    EP = _lane01()
    both = tmp_path / "both"
    both.mkdir()
    exports = ROOT / "policy" / "exports"
    (both / "plan-answers.yaml").write_bytes(
        (exports / "answers" / "plan-answers.yaml").read_bytes())
    (both / "default-csv.yaml").write_bytes((exports / "default-csv.yaml").read_bytes())
    monkeypatch.delenv("EXPORT_PROFILE_OVERLAY_DIRS", raising=False)
    monkeypatch.setenv("INGEST_EXPORT_PROFILE_DIR", str(both))
    monkeypatch.setenv("EXPORT_PROFILE_POLICY_DIR", str(both))
    EP.clear_cache()
    try:
        theirs = EP.load_profiles()
    finally:
        EP.clear_cache()
    assert isinstance(theirs["plan-answers"], EP.ProfileInvalid)
    assert isinstance(theirs["default-csv"], EP.Profile)
    with pytest.raises(AE.AnswerExportError) as exc:
        AE.load_answer_export_profiles()
    assert "default-csv" in str(exc.value)


# ── can_export gates both doors (ruled (b) 10-30) ────────────────────────────────────────────
def _no_file(w):
    return not w.dist.exists() or not any(w.dist.iterdir())


def test_can_export_gates_both_doors_bff_refuses_a_reader_without_it(world):
    world.exporters = set()
    r = world.export(BOARD_PLAN)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "not_entitled_to_export"
    assert detail["refusal"]["policy_id"] == f"capability_grants:can_export:{world.profile_name}"
    assert detail["refusal"]["missing_binding"] == f"can_invoke can_export:{world.profile_name}"
    # engine-cost was not called, on either of its routes
    assert world.cost_package_calls == 0 and world.answers_export_calls == 0 and _no_file(world)


def test_can_export_gates_both_doors_bff_503_when_the_check_raises(world):
    world.export_down = True
    r = world.export(BOARD_PLAN)
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "can_export_unavailable"}
    assert world.answers_export_calls == 0 and _no_file(world)


def test_can_export_gates_both_doors_cost_refuses_a_reader_without_it(world):
    world.exporters = set()
    r = world.engine.post("/answers_export", json={
        "recipient_scope": PLAN, "export_id": "c1", "user_email": ALICE, "rows": []})
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "not_entitled_to_export"
    assert detail["refusal"] == {
        "policy_id": f"capability_grants:can_export:{world.profile_name}",
        "missing_binding": f"can_invoke can_export:{world.profile_name}", "candidates": []}
    assert detail["message"]
    assert _no_file(world)


def test_can_export_gates_both_doors_cost_503_when_the_check_raises(world):
    world.export_down = True
    r = world.engine.post("/answers_export", json={
        "recipient_scope": PLAN, "export_id": "c2", "user_email": ALICE, "rows": []})
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "can_export_unavailable"}
    assert _no_file(world)


def test_can_export_gates_both_doors_picker_and_offer_list_only_what_would_export(world):
    def picker():
        return [x["value"] for x in world.get("/export/package/recipients").json()["recipients"]]

    assert PLAN in picker()
    assert PLAN in [x["value"] for x in world.offer(BOARD_PLAN).json()["recipients"]]
    world.exporters = set()
    assert PLAN not in picker()
    assert PLAN not in [x["value"] for x in world.offer(BOARD_PLAN).json()["recipients"]]
    # the 409 options do not list it either
    r = world.export(BOARD_PLAN, scope="")
    assert r.status_code == 409
    assert PLAN not in [o["value"] for o in r.json()["detail"]["options"]]


def test_can_export_gates_both_doors_the_download_stays_reader_only(world):
    section = _plan_section(world.export(BOARD_PLAN).json())
    world.exporters = set()
    r = world.get(section["artifact_uri"])
    assert r.status_code == 200
    assert world.engine.get(f"/artifact/{section['artifact_filename']}").status_code == 200


# ── the check asks the right question ────────────────────────────────────────────────────────
def _run(handler):
    import httpx
    from agent_fleet.utils import export_capability as EC
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    real = httpx.Client
    mp = pytest.MonkeyPatch()
    mp.setattr(EC.httpx, "Client", lambda **k: real(transport=httpx.MockTransport(wrapped), **k))
    try:
        return seen, EC.can_export("some-profile", ALICE, directory_url="http://topaz.test")
    finally:
        mp.undo()


def test_export_capability_asks_the_right_question():
    import httpx
    seen, got = _run(lambda req: httpx.Response(200, json={"check": True}))
    assert got is True and len(seen) == 1
    assert seen[0].url.path == "/api/v3/directory/check"
    assert json.loads(seen[0].content) == {
        "object_type": "capability", "object_id": "can_export:some-profile",
        "relation": "can_invoke", "subject_type": "user", "subject_id": ALICE}
    assert _run(lambda req: httpx.Response(200, json={"check": False}))[1] is False
    assert _run(lambda req: httpx.Response(404, json={"msg": "object not found"}))[1] is False
    with pytest.raises(httpx.HTTPStatusError):
        _run(lambda req: httpx.Response(500, json={}))
    with pytest.raises(ValueError):
        _run(lambda req: httpx.Response(200, content=b"not json"))
    with pytest.raises(httpx.TransportError):
        def boom(req):
            raise httpx.ConnectError("down")
        _run(boom)


def test_export_capability_without_a_url_is_false_and_sends_nothing(monkeypatch):
    import httpx
    from agent_fleet.utils import export_capability as EC
    sent = []
    real = httpx.Client
    monkeypatch.setattr(EC.httpx, "Client", lambda **k: real(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={"check": True})),
        **k))
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    assert EC.can_export("p", ALICE) is False
    assert EC.can_export("p", ALICE, directory_url="  ") is False
    assert EC.can_export("", ALICE, directory_url="http://t") is False
    assert EC.can_export("p", "", directory_url="http://t") is False
    assert sent == []


# ── E6. the BFF reads the profile set engine-cost SERVES, not its own copy ───────────────────────
# The rule: the registry your code reads is the one the server serves. Cost loads seed + overlays;
# the BFF asks it (`GET /answers_export/profiles`) and validates with the loader's own validator.
def _wire(profiles):
    return {"profiles": [AE.profile_to_wire(profiles[n]) for n in sorted(profiles)]}


def test_the_wire_round_trip_is_the_loaded_set():
    loaded = AE.load_answer_export_profiles()
    assert loaded
    assert AE.profiles_from_wire(_wire(loaded)) == loaded


def test_a_wire_profile_is_the_profile_files_vocabulary_with_nothing_extra():
    p = AE.load_answer_export_profiles()["plan-answers"]
    wire = AE.profile_to_wire(p)
    assert set(wire) == set(AE._TOP_KEYS)
    assert all(set(c) == set(AE._COLUMN_KEYS) and set(c["source"]) == set(AE._SOURCE_KEYS)
               for c in wire["columns"])
    assert wire["kinds"] == list(p.kinds)  # the verbs a profile takes travel


def test_the_wire_reader_runs_the_loaders_validator_and_set_rule():
    good = AE.profile_to_wire(AE.load_answer_export_profiles()["plan-answers"])
    for bad_doc, fragment in (
        ({"profiles": [dict(good, format="xml")]}, "format"),
        ({"profiles": [dict(good, surprise=1)]}, "unknown key"),
        ({"profiles": [good, dict(good, name="other")]}, "exactly one profile"),
        ({"nope": []}, "profiles"),
    ):
        with pytest.raises(AE.AnswerExportError) as exc:
            AE.profiles_from_wire(bad_doc)
        assert fragment in str(exc.value)


def _cost_serves(monkeypatch, tmp_path, *rows, overlay=()):
    """Point COST's loader at tmp dirs through the environment (the BFF is never told)."""
    import os
    import yaml
    seed = tmp_path / "cost-seed"
    seed.mkdir(parents=True, exist_ok=True)
    for r in rows:
        r = dict(r)
        stem = r.pop("_stem", r.get("name"))
        (seed / f"{stem}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    ov = []
    for j, r in enumerate(overlay):
        d = tmp_path / f"cost-ov{j}"
        d.mkdir(exist_ok=True)
        (d / f"{r['name']}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
        ov.append(str(d))
    monkeypatch.setenv(AE._SEED_ENV, str(seed))
    monkeypatch.setenv(AE._OVERLAY_ENV, os.pathsep.join(ov))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", None)


def _picker(w):
    r = w.get("/export/package/recipients")
    assert r.status_code == 200, r.text
    return [x["value"] for x in r.json()["recipients"]]


def test_cost_serves_its_set_sorted_and_a_failed_load_is_a_503_that_is_not_cached(
        world, monkeypatch, tmp_path):
    doc = world.engine.get("/answers_export/profiles").json()
    names = [p["name"] for p in doc["profiles"]]
    assert names and names == sorted(names)
    assert AE.profiles_from_wire(doc) == AE.load_answer_export_profiles()
    _cost_serves(monkeypatch, tmp_path, dict(_GOOD, _stem="not-the-name"))
    r = world.engine.get("/answers_export/profiles")
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "answer_profiles_unavailable"}
    _cost_serves(monkeypatch, tmp_path / "fixed", _GOOD)
    assert world.engine.get("/answers_export/profiles").status_code == 200


def test_the_bff_reads_what_engine_cost_serves_not_the_repo_seed(world, monkeypatch, tmp_path):
    """Test 4a. Cost's profile dir holds a recipient the repo seed does not name."""
    other = dict(_GOOD, name="elsewhere", recipients=["notional-elsewhere"])
    # set on COST's module, not through the environment: the BFF shares this process and would
    # see an env var, which is exactly the copy this arm exists to catch
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", _load(tmp_path, other))
    world.readers.add(("plan", "notional-elsewhere", ALICE))
    world.exporters.add(("elsewhere", ALICE))
    got = _picker(world)
    assert "notional-elsewhere" in got
    assert PLAN not in got  # the repo seed's recipient is not in what cost serves


def _hits(path, tree=None):
    """Every way a module reaches the profile loader or its two environment variables. The names
    are read from `answer_exports`, never typed here."""
    fn = {AE.load_answer_export_profiles.__name__}
    fns = fn | {AE.EXPORT_PROFILE_POLICY_DIR.__name__, AE.EXPORT_PROFILE_OVERLAY_DIRS.__name__}
    envs = {AE._SEED_ENV, AE._OVERLAY_ENV}
    tree = tree or ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in fns:
            found.append((n.lineno, n.id))
        elif isinstance(n, ast.Attribute) and n.attr in fns:
            found.append((n.lineno, n.attr))
        elif isinstance(n, ast.alias) and n.name in fns:
            found.append((0, n.name))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in envs:
            found.append((n.lineno, n.value))
    return found


def test_the_gateway_never_loads_a_profile_nor_reads_the_loaders_env():
    """Test 4b, with its controls: the same census FINDS the call in engine-cost and the env
    names in the loader, so a silent census cannot pass for a clean gateway."""
    assert _hits(ROOT / "src" / "iagent" / "gateway.py") == []
    cost = _hits(ROOT / "agent_fleet" / "cost_agent" / "main.py")
    assert any(name == AE.load_answer_export_profiles.__name__ for _, name in cost), cost
    loader = _hits(ROOT / "agent_fleet" / "utils" / "answer_exports.py")
    assert {AE._SEED_ENV, AE._OVERLAY_ENV} <= {name for _, name in loader}, loader


def test_an_overlay_set_on_cost_alone_reaches_the_offer_with_no_code_change(
        world, monkeypatch, tmp_path):
    """Test 3. The overlay dir is set ONLY on cost's side (the BFF has no such setting)."""
    import os
    extra = dict(_GOOD, name="overlay-plan", recipients=["notional-overlay"])
    d = tmp_path / "only-on-cost"
    d.mkdir()
    import yaml
    (d / "overlay-plan.yaml").write_text(yaml.safe_dump(extra), encoding="utf-8")
    monkeypatch.setenv(AE._OVERLAY_ENV, str(d))
    monkeypatch.setattr(cost_main, "_ANSWER_PROFILES", None)
    world.readers.add(("plan", "notional-overlay", ALICE))
    world.exporters.add(("overlay-plan", ALICE))
    r = world.offer(BOARD_PLAN)
    assert r.status_code == 200, r.text
    offered = {x["value"]: x for x in r.json()["recipients"]}
    assert "notional-overlay" in offered and offered["notional-overlay"]["offered"] is True
    assert PLAN in offered  # the seed rides along
    assert os.environ[AE._OVERLAY_ENV] == str(d)


# ── cost unreachable: omit at the pickers, 503 at the doors, never a 403 ─────────────────────────
def _down(world, mode="down"):
    world.profiles_mode = mode


@pytest.mark.parametrize("mode", ["down", "500", "bad"])
def test_without_the_served_set_the_pickers_are_a_503_and_the_409_listing_omits_plan(world, mode):
    """Was `..._the_pickers_omit_plan_and_keep_cost`: ruled 10-31, a profile-set outage at a picker
    is a 503 `answer_profiles_unavailable` (never an omission, never a 403), cost non-empty or not.
    The 409 listing INSIDE the export door is a door's error listing, and still omits."""
    assert PLAN in _picker(world)
    _down(world, mode)
    for got in (world.get("/export/package/recipients"), world.offer(BOARD_COST)):
        assert got.status_code == 503, got.text
        assert got.json()["detail"] == {"reason": "answer_profiles_unavailable"}
    r = world.export(BOARD_PLAN, scope="")
    assert r.status_code == 409
    options = [o["value"] for o in r.json()["detail"]["options"]]
    assert PLAN not in options and ALPHA in options


@pytest.mark.parametrize("mode", ["down", "500", "bad"])
def test_without_the_served_set_a_plan_export_is_a_503_never_a_403(world, mode):
    _down(world, mode)
    r = world.export(BOARD_PLAN)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == {"reason": "answer_profiles_unavailable"}
    assert world.answers_export_calls == 0 and world.cost_package_calls == 0


def test_without_the_served_set_a_cost_export_is_unaffected(world):
    _down(world)
    assert world.export(BOARD_COST, scope=ALPHA).status_code == 200
    assert world.cost_package_calls == 1


@pytest.mark.parametrize("mode", ["down", "500", "bad"])
def test_without_the_served_set_an_answers_download_is_a_503_and_other_names_stay_404(
        world, mode):
    name = _plan_section(world.export(BOARD_PLAN).json())["artifact_filename"]
    assert name.startswith(AE.ARTIFACT_PREFIX)
    _down(world, mode)
    r = world.get(f"/export/package/artifact/{name}")
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "answer_profiles_unavailable"}
    assert world.get("/export/package/artifact/not-an-export.csv").status_code == 404
