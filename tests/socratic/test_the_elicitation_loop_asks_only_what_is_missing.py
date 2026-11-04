"""ADR-0061 prototype: the socratic loop asks only what the draft does not already answer.

The oracle arm reads each answer's ``facts``; no model runs here. The fixtures are synthetic.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
from pathlib import Path

import pytest
import yaml

from agent_fleet.restate_analyst import socratic_elicitation as se

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "socratic"
NAMES = tuple(sorted(p.name for p in FIXTURES.iterdir() if (p / "transcript.yaml").is_file()))
assert NAMES, f"no fixture with a transcript.yaml under {FIXTURES}"  # an empty bank skips, never passes
FOLDERS = ("triggers", "decisions", "workflows", "task_kinds")


def _yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _expected(name: str) -> dict:
    files = {}
    for folder in FOLDERS:
        for p in sorted((FIXTURES / name / "expected" / folder).glob("*.yaml")):
            files[f"{folder}/{p.name}"] = _yaml(p)
    return files


def _transcript(name: str) -> dict:
    return _yaml(FIXTURES / name / "transcript.yaml")


def _flat(prefix, value, out):
    if isinstance(value, dict) and value:
        for k, v in value.items():
            _flat(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = value


def _diff_paths(a: dict, b: dict) -> list:
    fa, fb = {}, {}
    for f, d in a.items():
        _flat(f, d, fa)
    for f, d in b.items():
        _flat(f, d, fb)
    return sorted(k for k in set(fa) | set(fb) if k not in fa or k not in fb or fa[k] != fb[k])


@pytest.fixture(scope="module")
def oracle_runs():
    runs = {}
    for name in NAMES:
        t = _transcript(name)
        seen = []  # (key, was it a gap of the draft at the moment of asking)

        def extractor(entry, draft, gap, _seen=seen):
            # before the asked-count cut: the loop counts the ask first, and a confirm is asked once
            if gap is not None:
                _seen.append((gap.key, gap.key in [g.key for g in se._all_gaps(draft)]))
            return se.OracleExtractor()(entry, draft, gap)

        runs[name] = (t, se.run(t, extractor), seen)
    return runs


@pytest.mark.parametrize("name", NAMES)
def test_the_expected_bundle_is_runnable_and_has_no_problems(name):
    files = _expected(name)
    assert se.runnable(files) == []
    assert [g.key for g in se.problems(files)] == []


@pytest.mark.parametrize("name", NAMES)
def test_the_oracle_run_completes_and_asks_each_banked_question_once(name, oracle_runs):
    t, r, _ = oracle_runs[name]
    keys = [q["key"] for q in r["questions"]]
    assert r["gaps_left"] == []
    assert r["unanswerable"] == 0
    assert r["unresolved"] == 0
    assert len(keys) == len(set(keys)), "a question was asked twice"
    assert set(keys) == set(t["answers"]), (
        f"asked but not banked: {sorted(set(keys) - set(t['answers']))}; "
        f"banked but never asked: {sorted(set(t['answers']) - set(keys))}")


@pytest.mark.parametrize("name", NAMES)
def test_the_planted_contradictions_are_asked_and_the_planted_deferrals_recorded(name, oracle_runs):
    t, r, _ = oracle_runs[name]
    for k in t["planted"]["contradictions"]:
        assert k in r["contradictions_asked"], k
    for k in t["planted"]["deferrals"]:
        assert k in r["deferrals"], k
    want = _yaml(FIXTURES / name / "expected" / "deferrals.yaml")["deferrals"]
    assert set(r["deferrals"]) == set(want)


@pytest.mark.parametrize("name", NAMES)
def test_the_final_files_equal_the_expected_bundle(name, oracle_runs):
    _, r, _ = oracle_runs[name]
    expected = _expected(name)
    assert r["files"] == expected, f"differing leaves: {_diff_paths(r['files'], expected)[:20]}"


@pytest.mark.parametrize("name", NAMES)
def test_the_final_files_are_runnable(name, oracle_runs):
    _, r, _ = oracle_runs[name]
    assert se.runnable(r["files"]) == []
    assert r["runnable"] == []


@pytest.mark.parametrize("name", NAMES)
def test_no_question_is_asked_about_a_fact_the_draft_already_holds(name, oracle_runs):
    _, r, seen = oracle_runs[name]
    stale = [k for k, was_gap in seen if not was_gap]
    assert stale == [], f"asked while no longer a gap: {stale}"


# ── positive control: the validator accepts what the repo ships ─────────────────────────────

def _bundle_from(*roots_by_folder):
    files = {}
    for folder, root in roots_by_folder:
        d = Path(root) / folder
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            body = _yaml(p)
            if isinstance(body, dict):
                files[f"{folder}/{p.name}"] = body
    return files


@pytest.mark.parametrize("overlay", ["sample", "openddil-lab", "both"])
def test_the_validator_accepts_the_shipped_seed_with_each_overlay(overlay):
    policy = REPO / "policy"
    names = ["sample", "openddil-lab"] if overlay == "both" else [overlay]
    spec = [(f, policy) for f in FOLDERS] + [(f, policy / "overlays" / n) for n in names for f in FOLDERS]
    files = _bundle_from(*spec)
    assert files, "the control built an empty bundle"
    got = [(g.key, g.question) for g in se.problems(files)]
    assert got == [], f"problems on shipped rows ({overlay}): {got}"


# ── negative controls: a defect planted in a good bundle is named ───────────────────────────

IR = "workflows/pcn_impact_review.yaml"
CH = "decisions/pcn_impact_review_chaining.yaml"
SEL = "decisions/pcn_received_selection.yaml"


def _good():
    return copy.deepcopy(_expected("pcn_review"))


def _step(files, wf, sid):
    return next(s for s in files[wf]["steps"] if s["id"] == sid)


def _keys(files):
    return {g.key: g for g in se.problems(files)}


def test_control_a_a_verb_the_step_can_end_with_but_the_table_omits_is_asked():
    f = _good()
    f[CH]["domain"]["outcome"].remove("needs_info")
    f[CH]["rows"] = [r for r in f[CH]["rows"] if r["when"]["outcome"] != "needs_info"]
    assert "approvals.pcn_impact_review.next.needs_info" in _keys(f)


def test_control_b_a_verb_the_step_cannot_end_with_is_a_contradiction():
    f = _good()
    f[CH]["domain"]["outcome"].append("withdrawn")
    f[CH]["rows"].append({"when": {"outcome": "withdrawn"}, "then": "pcn_rejected"})
    g = _keys(f).get("contradiction:chaining.pcn_impact_review_chaining.withdrawn")
    assert g is not None and g.kind == "contradiction"


def test_control_c_two_rows_selecting_the_same_input_is_a_routing_contradiction():
    f = _good()
    f[SEL]["rows"].append({"when": {"change_class": "fff"}, "then": "pcn_acknowledge"})
    assert "contradiction:routing.pcn_received_selection" in _keys(f)


def test_control_d_a_then_that_names_nothing_is_asked():
    f = _good()
    f[CH]["rows"][0]["then"] = "pcn_nowhere"
    assert "steps.pcn_nowhere" in _keys(f)


def test_control_e_a_step_without_an_audience_is_asked_under_actors():
    f = _good()
    del _step(f, IR, "engineering_disposition")["audience"]
    g = _keys(f).get("steps.pcn_impact_review.engineering_disposition.audience")
    assert g is not None and g.facet == "actors" and g.kind == "missing"


def test_control_f_reasons_for_an_answer_the_kind_does_not_accept_is_a_contradiction():
    f = _good()
    f["task_kinds/pcn_program_approval.yaml"]["reason_required"] = ["rejected", "withdrawn"]
    assert "contradiction:task_kind.pcn_program_approval" in _keys(f)


def test_control_g_a_definition_nothing_confirms_is_asked_how_it_ends():
    f = _good()
    f["workflows/pcn_record.yaml"]["steps"] = [
        s for s in f["workflows/pcn_record.yaml"]["steps"] if s["kind"] != "signal_await"]
    assert "outputs.pcn_record.ends" in _keys(f)


def test_control_h_a_routing_input_the_trigger_does_not_require_is_asked():
    f = _good()
    f["triggers/pcn_received.yaml"]["requires"].remove("change_class")
    assert "trigger.requires.change_class" in _keys(f)


def test_control_the_controls_name_nothing_on_the_good_bundle():
    assert _keys(_good()) == {}


def test_overwrite_control_a_different_value_later_is_a_pending_contradiction_and_an_equal_one_is_not():
    d = se.Draft()
    f, p = "workflows/x.yaml", "steps[id=a].deadline_seconds"
    se.apply_patch(d, {"set": [{"file": f, "path": p, "value": 100}]}, 1)
    se.apply_patch(d, {"set": [{"file": f, "path": p, "value": 100}]}, 2)
    assert d.pending == []
    se.apply_patch(d, {"set": [{"file": f, "path": p, "value": 200}]}, 3)
    assert [g.key for g in d.pending] == [f"contradiction:{f}#{p}"]
    assert d.pending[0].proposed == 200
    assert d.files[f]["steps"][0]["deadline_seconds"] == 100
    assert d.set_at[(f, p)] == 1


def _orphan(files):
    files["workflows/orphan_stage.yaml"] = {
        "id": "orphan_stage", "name": "Orphan stage",
        "steps": [{"kind": "human_await", "id": "review", "audience": "pcn_engineering:SUSTAINMENT",
                   "role": "component_engineer", "subject_ref": "{trigger.pcn_id}",
                   "title": "Orphan review", "excludes": [], "deadline_seconds": None}]}


def test_control_reachability_a_definition_no_table_names_is_not_asked_for_its_details():
    f = _good()
    _orphan(f)
    assert [k for k in _keys(f) if "orphan_stage" in k] == []


def test_control_reachability_the_same_definition_named_by_a_row_is_asked_about():
    f = _good()
    _orphan(f)
    for r in f["decisions/pcn_acknowledge_chaining.yaml"]["rows"]:
        if r["when"]["outcome"] == "escalated":
            r["then"] = "orphan_stage"
    keys = _keys(f)
    assert "approvals.orphan_stage.review.task_kind" in keys
    assert "approvals.orphan_stage.next" in keys


# ── the aligning user: a question is understood by what it is about, not by its id ──────────────

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("socratic_measure_under_test", REPO / "scripts" / "socratic_measure.py")
sm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sm)


def _rename(files: dict, mapping: dict) -> dict:
    def walk(v):
        if isinstance(v, dict):
            return {walk(k): walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return mapping.get(v, v)
        return v
    out = {}
    for f, d in files.items():
        folder, _, fname = f.partition("/")
        stem = Path(fname).stem
        out[f"{folder}/{mapping.get(stem, stem)}.yaml" if folder == "workflows" else f] = walk(d)
    return out


def test_the_oracle_through_the_aligning_user_gives_the_identical_table():
    for name in NAMES:
        exact = sm.measure(name, se.OracleExtractor())
        aligned = sm.measure(name, se.OracleExtractor(), aligned=True)
        drop = ("seconds", "aligned_answers", "unaligned", "unbanked")
        assert {k: v for k, v in exact.items() if k not in drop} == {k: v for k, v in aligned.items() if k not in drop}
        assert aligned["aligned_answers"] == [] and aligned["unaligned"] == [] and aligned["unbanked"] == []
        assert exact["deferred_refusals"] == aligned["deferred_refusals"]


def test_a_renamed_definition_and_step_translate_to_the_banks_names():
    expected = _expected("pcn_review")
    draft = _rename(expected, {"pcn_impact_review": "impact_review", "engineering_disposition": "review"})
    assert "workflows/impact_review.yaml" in draft
    user = sm.AligningUser(_transcript("pcn_review"), expected)
    t = user.translate
    assert t("approvals.impact_review.review.deadline", draft) == \
        "approvals.pcn_impact_review.engineering_disposition.deadline"
    assert t("approvals.impact_review.next", draft) == "approvals.pcn_impact_review.next"
    assert t("steps.impact_review", draft) == "steps.pcn_impact_review"
    assert t("contradiction:workflows/impact_review.yaml#steps[id=review].excludes", draft) == \
        "contradiction:workflows/pcn_impact_review.yaml#steps[id=engineering_disposition].excludes"
    assert t("outputs.pcn_record.next", draft) == "outputs.pcn_record.next"


def _without_program_approval() -> dict:
    d = _expected("pcn_review")
    del d["workflows/pcn_program_approval.yaml"]
    del d["decisions/pcn_program_approval_chaining.yaml"]
    return d


def test_a_stage_the_draft_cannot_reach_is_unaligned_not_misaligned():
    user = sm.AligningUser(_transcript("pcn_review"), _expected("pcn_review"))
    draft = _without_program_approval()
    assert user.translate("outputs.pcn_record.next", draft) is None
    assert user.translate("steps.pcn_record", draft) is None
    assert user.translate("steps.pcn_program_approval", draft) == "steps.pcn_program_approval"


class _FileOrderUser(sm.AligningUser):
    """MUTANT: pair definitions by position in file order instead of by the path that reaches them."""

    def _pair_definitions(self, d, e):
        return dict(zip(sorted(d["wfs"]), sorted(e["wfs"])))


def test_the_unaligned_test_fails_if_alignment_falls_back_to_file_order():
    user = _FileOrderUser(_transcript("pcn_review"), _expected("pcn_review"))
    assert user.translate("outputs.pcn_record.next", _without_program_approval()) is not None


class _RenamingExtractor(se.OracleExtractor):
    """The oracle's patches under the model's own names, as runs 7 to 18 drafted them. Only ids
    that are not also a task kind are renamed, so every reference still resolves."""

    MAP = {"pcn_impact_review": "impact_review", "engineering_disposition": "review"}

    def __call__(self, utterance_entry, draft, gap):
        import re
        p, m = super().__call__(utterance_entry, draft, gap), self.MAP

        def walk(v):
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x) for x in v]
            return m.get(v, v) if isinstance(v, str) else v

        def fname(f):
            folder, _, n = f.partition("/")
            return f"{folder}/{m.get(Path(n).stem, Path(n).stem)}.yaml" if folder == "workflows" else f

        return {"set": [{"file": fname(s["file"]),
                         "path": re.sub(r"\[id=([^\]]*)\]",
                                        lambda mo: f"[id={m.get(mo.group(1), mo.group(1))}]", s["path"]),
                         "value": walk(s["value"])} for s in p.get("set") or []],
                "defer": [dict(d, gap=".".join(m.get(x, x) for x in str(d["gap"]).split(".")))
                          for d in p.get("defer") or []]}


def test_a_planted_item_recorded_under_the_drafts_own_names_is_counted():
    """ADR-0061 §10, run 7 and runs 16 to 18: the planted deferral was recorded live under the
    draft's step names and the column read 0/1, because the compare did not translate."""
    row = sm.measure("pcn_review", _RenamingExtractor(), aligned=True)
    assert "workflows/impact_review.yaml" in row["files"]
    assert "approvals.impact_review.review.deadline" in row["deferrals"]
    assert DEADLINE_KEY not in row["deferrals"]
    assert row["deferrals_recorded"] == row["deferrals_planted"] == 1
    assert row["contradictions_detected"] == row["contradictions_planted"] == 1


# ── ADR-0061 rulings: a refusal is never deferred; required slots are asked by name ─────────────

def _run_without(*keys):
    t = copy.deepcopy(_transcript("pcn_review"))
    for k in keys:
        del t["answers"][k]
    return se.run(t, se.OracleExtractor())


NEXT_KEY = "approvals.pcn_impact_review.next"
BARRED_KEY = "actors.pcn_program_approval.program_approval.excludes"
DEADLINE_KEY = "approvals.pcn_impact_review.engineering_disposition.deadline"


def test_t1_an_unanswerable_refusal_is_left_open_never_deferred():
    r = _run_without(NEXT_KEY)
    assert NEXT_KEY in r["missing"]
    assert NEXT_KEY not in r["deferrals"]
    assert r["status"] == "cannot_run"
    assert r["deferred_refusals"] == []
    assert [q["key"] for q in r["questions"]].count(NEXT_KEY) == 2
    assert r["summary"].startswith("cannot run, missing ")


def test_t2_a_model_defer_of_a_refusal_goes_to_open():
    draft = se.Draft(files=_good())
    del draft.files["decisions/pcn_impact_review_chaining.yaml"]
    key = next(g.key for g in se.problems(draft.files) if g.key == NEXT_KEY)
    se.apply_patch(draft, {"defer": [{"gap": key, "reason": "later"}]}, 1)
    assert key in draft.open and key not in draft.deferrals


def test_t3_who_is_barred_is_left_open_never_deferred():
    r = _run_without(BARRED_KEY)
    assert BARRED_KEY in r["open"] and BARRED_KEY not in r["deferrals"]
    assert r["status"] == "cannot_run"


def test_t4_control_a_completeness_gap_is_still_deferred():
    r = _run_without(DEADLINE_KEY)
    assert DEADLINE_KEY in r["deferrals"] and DEADLINE_KEY not in r["open"]
    assert r["status"] == "runnable"


def test_t5_status_is_runnable_only_when_nothing_is_left_open_or_refused():
    assert se._status([], [], []) == "runnable"
    assert se._status([], [], ["x"]) == "cannot_run"
    assert se._status([], ["k"], []) == "cannot_run"
    assert se._status(["g"], [], []) == "cannot_run"


def _maintenance_run3_shape() -> dict:
    return {
        "triggers/t.yaml": {"trigger": "t", "selection": "stage_one"},
        "workflows/stage_one.yaml": {
            "id": "stage_one", "name": "Stage one",
            "steps": [{"kind": "human_await", "id": "look", "audience": "a:B", "role": "r",
                       "subject_ref": "{trigger.x}", "title": "Look"}]},
    }


def test_t6_required_slots_cover_a_definition_no_table_reaches():
    f = _maintenance_run3_shape()
    slots = {g.key: g for g in se.required_slots(f)}
    assert set(slots) == {"approvals.stage_one.look.task_kind", "approvals.stage_one.next",
                          "actors.stage_one.look.excludes", "trigger.stages"}
    named = {g.key: g.question for g in se.gaps(se.Draft(files=f))}
    for k in slots:
        assert named[k].startswith("Required:")
    # control: problems() alone does not see it, the definition being unreachable
    assert "approvals.stage_one.look.task_kind" not in {g.key for g in se.problems(f)}


@pytest.mark.parametrize("name", NAMES)
def test_t7_every_fixture_is_runnable_under_the_oracle_and_the_aligner(name):
    for aligned in (False, True):
        row = sm.measure(name, se.OracleExtractor(), aligned=aligned)
        assert row["status"] == "runnable" and row["missing"]["count"] == 0 and row["open"] == {}
        assert row["exact"] is True and row["deferred_refusals"] == []
        if aligned:
            assert row["answered_by_path"] == []
    # 10-30 turn check: +1, +2, +4 confirms of slots each person stated in passing (ADR-0061 §10)
    # 11-02: +1 "defer this?" for each stated null: one in PCN, one in training, none in maint
    # 11-02: +1 confirm per approval whose reasons were stated in passing: 3, 2, 2 (the content
    # review's reasons are answered in their own contradiction)
    assert sm.measure(name, se.OracleExtractor())["questions"] == {
        "pcn_review": 18, "maint_case_release": 14, "training_course_approval": 18}[name]


def _event_values_unseen(name: str, transcript: dict) -> list:
    shown = {(k, str(v)) for k, vals in (transcript["context"].get("event_values") or {}).items() for v in vals}
    out = []
    for p in sorted((FIXTURES / name / "expected" / "decisions").glob("*.yaml")):
        for row in _yaml(p)["rows"]:
            for k, v in row["when"].items():
                if k != "outcome" and (k, str(v)) not in shown:
                    out.append((k, str(v)))
    return out


def _outcomes_unspoken(name: str, transcript: dict, grammar: str = se._GRAMMAR) -> list:
    # Visible = spoken as a whole word in some `says`, or stated in the extractor's grammar (runner
    # vocabulary such as timed_out, which no user coins).
    import re
    said = " ".join([transcript["opening"]["says"]] + [a["says"] for a in transcript["answers"].values()])
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", said + " " + grammar)}
    out = set()
    for p in sorted((FIXTURES / name / "expected" / "decisions").glob("*.yaml")):
        for row in _yaml(p)["rows"]:
            v = row["when"].get("outcome")
            if v is not None and str(v).lower() not in words:
                out.add(str(v))
    return sorted(out)


@pytest.mark.parametrize("name", NAMES)
def test_every_when_value_is_visible_to_the_model_event_values(name):
    assert _event_values_unseen(name, _transcript(name)) == []


def test_every_when_value_is_visible_to_the_model_control_pcn_without_event_values():
    t = _transcript("pcn_review")
    del t["context"]["event_values"]
    assert ("change_class", "fff") in _event_values_unseen("pcn_review", t)


@pytest.mark.parametrize("name", NAMES)
def test_every_when_value_is_visible_to_the_model_outcomes(name):
    assert _outcomes_unspoken(name, _transcript(name)) == []


def test_every_when_value_is_visible_to_the_model_control_grammar_without_timed_out():
    grammar = se._GRAMMAR.replace("timed_out", "")
    assert _outcomes_unspoken("pcn_review", _transcript("pcn_review"), grammar) == ["timed_out"]


def test_every_when_value_is_visible_to_the_model_control_pcn_without_its_answer_labels():
    t = _transcript("pcn_review")
    for a in t["answers"].values():
        a["says"] = a["says"].replace("The answers are recorded as approved, rejected and needs_info.", "")
    assert _outcomes_unspoken("pcn_review", t) == ["needs_info"]


# ── ADR-0061: the scripted user answers by the path a fact sets; excludes is a required slot ────

_IMPACT = ("workflows/pcn_impact_review.yaml", "steps[id=engineering_disposition].excludes")


def _pcn_user(transcript=None):
    return sm.AligningUser(transcript or _transcript("pcn_review"), _expected("pcn_review"))


def test_an_unbanked_question_is_answered_by_the_entry_that_sets_its_path():
    tr = _transcript("pcn_review")
    bank = tr["answers"]
    u = _pcn_user(tr)
    assert u.entry_for_path("workflows/pcn_acknowledge.yaml", "steps[id=acknowledge].excludes")[0] == "steps.pcn_acknowledge"
    assert u.entry_for_path(*_IMPACT)[0] == "opening"
    prog = ("workflows/pcn_program_approval.yaml", "steps[id=program_approval].excludes")
    assert u.entry_for_path(*prog)[0] == "actors.pcn_program_approval.program_approval.excludes"
    # the rejected file-level rule would differ: the step entry sets that FILE, not that PATH
    step_entry = bank["steps.pcn_program_approval"]
    assert any(f["file"] == prog[0] for f in step_entry["facts"]["set"])
    assert sm._sets_path(step_entry, *prog) is False
    # the rejected precedence (bank first) would pick this entry, not the opening
    assert sm._sets_path(bank["actors.pcn_program_approval.program_approval.excludes"], *_IMPACT) is True
    # without the opening, the bank answers -- and never a contradiction: entry
    tr2 = copy.deepcopy(tr)
    del tr2["opening"]
    got = _pcn_user(tr2).entry_for_path(*_IMPACT)[0]
    assert got == "actors.pcn_program_approval.program_approval.excludes"
    assert not got.startswith("contradiction:")
    # a path no entry sets (the impact review's deadline is deferred in the bank)
    assert u.entry_for_path("workflows/pcn_impact_review.yaml",
                            "steps[id=engineering_disposition].deadline_seconds") is None
    # _fact_target
    assert sm._fact_target("actors.w.s.excludes") == ("workflows/w.yaml", "steps[id=s].excludes")
    assert sm._fact_target("approvals.w.s.deadline") == ("workflows/w.yaml", "steps[id=s].deadline_seconds")
    assert sm._fact_target("approvals.x.next") is None


def test_the_scripted_user_delivers_a_fact_the_bank_has_no_key_for():
    tr = _transcript("pcn_review")
    expected = _expected("pcn_review")
    draft = copy.deepcopy(expected)
    for s in draft["workflows/pcn_acknowledge.yaml"]["steps"]:
        if s.get("id") == "acknowledge":
            del s["excludes"]
    key = "actors.pcn_acknowledge.acknowledge.excludes"
    del tr["answers"][key]  # banked since the turn check (10-30); the seal is about a key with none
    u = sm.AligningUser(tr, expected)
    g = se.Gap(key, "actors", "missing", "q")
    stage = tr["answers"]["steps.pcn_acknowledge"]
    # the person repeats the one fact asked, in the words they first said it
    assert u(g, se.Draft(files=draft)) == {"says": stage["says"], "facts": {"set": [
        {"file": "workflows/pcn_acknowledge.yaml", "path": "steps[id=acknowledge].excludes", "value": []}]}}
    assert u.answered_by_path == [(key, "steps.pcn_acknowledge")]
    assert u.unbanked == []
    # that deadline is banked (as a deferral), so drop the key: no entry sets the path either
    del tr["answers"]["approvals.pcn_impact_review.engineering_disposition.deadline"]
    u = sm.AligningUser(tr, expected)
    g2 = se.Gap("approvals.pcn_impact_review.engineering_disposition.deadline", "approvals", "missing", "q")
    assert u(g2, se.Draft(files=copy.deepcopy(expected))) is None
    assert u.unbanked == [g2.key]


def test_an_explicit_empty_excludes_is_set():
    f = _maintenance_run3_shape()
    f["workflows/stage_one.yaml"]["steps"][0]["excludes"] = []
    assert not [g.key for g in se.required_slots(f) if g.key.endswith(".excludes")]
    assert not [g.key for g in se.gaps(se.Draft(files=f)) if g.key.endswith(".excludes")]


def test_the_grammar_requires_excludes():
    lines = [ln for ln in se._GRAMMAR.replace("\n  ", " ").splitlines() if ln.startswith("- REQUIRED:")]
    assert any("excludes" in ln and "[]" in ln for ln in lines)


def _a_chaining_table() -> dict:
    """A chaining table the shipped policy already composes, so its shape is one the loader takes."""
    tables = se._dt.load_tables()
    return copy.deepcopy(tables[sorted(k for k, v in tables.items() if v.get("after"))[0]])


def test_the_prompt_examples_are_the_deployments_own_rows(tmp_path, monkeypatch):
    """Config names the case: a deployment's rows become the examples, with no code change."""
    table = _a_chaining_table()
    table["decision"] = "aaa_deployment_chaining"
    (tmp_path / "decisions").mkdir()
    (tmp_path / "decisions" / "aaa_deployment_chaining.yaml").write_text(yaml.safe_dump(table), encoding="utf-8")
    (tmp_path / "task_kinds").mkdir()
    (tmp_path / "task_kinds" / "aaa_deployment_kind.yaml").write_text(yaml.safe_dump({
        "kind": "aaa_deployment_kind",
        "renders_as": {"badge": "DEPLOY", "title": "A deployment's kind", "archetype": "APPROVAL_TASK"},
        "accepts": ["approved", "rejected"]}), encoding="utf-8")
    monkeypatch.setenv("DECISION_TABLE_DIR", str(tmp_path / "decisions"))
    monkeypatch.setenv("TASK_KIND_OVERLAY_DIRS", str(tmp_path / "task_kinds"))
    chain, kind = se.served_examples()
    assert yaml.safe_load(chain)["decision"] == "aaa_deployment_chaining"
    assert yaml.safe_load(kind)["kind"] == "aaa_deployment_kind"


def test_no_example_to_show_is_a_refusal_not_an_empty_prompt(tmp_path, monkeypatch):
    (tmp_path / "decisions").mkdir()
    monkeypatch.setenv("DECISION_TABLE_DIR", str(tmp_path / "decisions"))
    with pytest.raises(ValueError, match="no chaining table"):
        se.served_examples()


def test_the_model_extractor_names_no_policy_file():
    src = Path(se.__file__).read_text(encoding="utf-8")
    assert "policy/overlays/" not in src


# ── a patch the loop cannot apply is a model error charged to its turn (architect, 2026-10-30) ──

GOOD = {"file": "decisions/probe.yaml", "path": "note", "value": "kept"}
POSITIONAL = {"file": "decisions/probe.yaml", "path": "steps[0].deadline_seconds", "value": 60}


class _Restating:
    """Sends a positional path first; sends ``GOOD`` once it is told the patch was refused."""

    def __init__(self):
        self.calls = []

    def __call__(self, entry, draft, gap):
        self.calls.append(dict(entry))
        return {"set": [GOOD] if entry.get("refused") else [POSITIONAL]}


def test_an_unparseable_path_is_charged_to_its_turn_and_the_restatement_lands():
    ex = _Restating()
    r = se.run({"opening": {"says": "probe"}}, ex)
    assert [e["turn"] for e in r["model_errors"]] == [0]
    assert "steps[0]" in r["model_errors"][0]["error"]
    assert len(ex.calls) == 2 and "refused" not in ex.calls[0]
    assert "steps[0]" in ex.calls[1]["refused"]
    assert r["files"]["decisions/probe.yaml"]["note"] == "kept"


def test_a_refused_patch_lands_nothing_and_the_run_continues():
    calls = []

    def stubborn(entry, draft, gap):
        calls.append(entry)
        return {"set": [GOOD, POSITIONAL]}

    r = se.run({"opening": {"says": "probe"}}, stubborn)
    assert len(calls) == 1 + se.PATCH_RESTATES
    assert [e["turn"] for e in r["model_errors"]] == [0] * (1 + se.PATCH_RESTATES)
    assert "decisions/probe.yaml" not in r["files"]
    assert r["status"] in ("runnable", "cannot_run")


# ── a chaining table's values and rows are required slots asked by name (architect, 2026-10-30) ──

VALUES_KEY = "approvals.pcn_impact_review.next.domain.outcome"


def _slots(files):
    return {g.key: g for g in se.required_slots(files)}


def test_a_chaining_table_with_no_values_is_a_required_slot_for_its_input():
    f = _good()
    del f[CH]["domain"]["outcome"]
    g = _slots(f).get(VALUES_KEY)
    assert g is not None and g.question.startswith("Required:")
    assert "approved, rejected, needs_info" in g.question
    assert (CH, "domain.outcome") in g.revises and (CH, "rows") in g.revises
    assert se.non_deferrable(se.Draft(files=f), VALUES_KEY) is not None
    # the vague whole-table contradiction is not asked while a slot names what is missing
    assert "contradiction:chaining.pcn_impact_review_chaining" not in _keys(f)


def test_a_value_with_no_row_is_a_required_slot_for_that_value_only():
    f = _good()
    f[CH]["rows"] = [r for r in f[CH]["rows"] if r["when"]["outcome"] != "approved"]
    rows = [k for k in _slots(f) if k.startswith("approvals.pcn_impact_review.next.")]
    assert rows == ["approvals.pcn_impact_review.next.approved"]


def test_the_slot_names_the_input_the_table_declares():
    f = _good()
    f[CH]["matches"] = ["verdict"]
    f[CH]["domain"] = {"verdict": []}
    assert "approvals.pcn_impact_review.next.domain.verdict" in _slots(f)
    assert VALUES_KEY not in _slots(f)


def test_control_two_rows_for_one_value_stay_a_contradiction_not_a_slot():
    f = _good()
    f[CH]["rows"].append({"when": {"outcome": "approved"}, "then": "pcn_rejected"})
    assert not [k for k in _slots(f) if k.startswith("approvals.pcn_impact_review.next.")]
    assert "contradiction:chaining.pcn_impact_review_chaining" in _keys(f)


def test_control_the_good_bundle_has_no_chaining_slot():
    assert not [k for k in _slots(_good()) if ".next." in k]


def test_the_scripted_user_answers_a_chaining_slot_from_the_entry_that_sets_the_table():
    exp = _expected("pcn_review")
    assert sm._chain_target(VALUES_KEY, exp) == (CH, "domain.outcome")
    assert sm._chain_target("approvals.pcn_impact_review.next.approved", exp) == (CH, "rows")
    assert sm._chain_target("approvals.pcn_impact_review.next", exp) is None
    f = _good()
    del f[CH]["domain"]["outcome"]
    u = _pcn_user()
    got = u(_slots(f)[VALUES_KEY], se.Draft(files=f))
    assert got == {"says": _transcript("pcn_review")["answers"]["approvals.pcn_impact_review.next"]["says"],
                   "facts": {"set": [{"file": CH, "path": "domain.outcome",
                                      "value": exp[CH]["domain"]["outcome"]}]}}
    assert u.answered_by_path == [(VALUES_KEY, "approvals.pcn_impact_review.next")]


# ── 10-30: a chaining slot binds to its table; the trigger declares its stages ──────────────────

ACK = "workflows/pcn_acknowledge.yaml"
ACK_CH = "decisions/pcn_acknowledge_chaining.yaml"
TRIG = "triggers/pcn_received.yaml"
STAGES = ["pcn_impact_review", "pcn_acknowledge", "pcn_program_approval", "pcn_record"]


def _run15_shape():
    """Run 15 (ADR-0061 §10): a stage with no disposing step, and an empty routing table after it."""
    f = _good()
    f[ACK]["steps"] = [{"kind": "render", "id": "note", "template": {"pcn": "{trigger.pcn_id}"}}]
    f[ACK_CH] = {"decision": "pcn_acknowledge_chaining", "after": "pcn_acknowledge"}
    return f


def test_a_routing_table_after_a_stage_that_cannot_end_is_asked_its_values():
    f = _run15_shape()
    g = _slots(f).get("outputs.pcn_acknowledge.next.domain.outcome")
    assert g is not None and g.question.startswith("Required:")
    assert se.non_deferrable(se.Draft(files=f), g.key) is not None


def test_a_trigger_that_declares_no_stages_is_a_required_slot():
    g = _slots(_good()).get("trigger.stages")
    assert g is not None and g.question.startswith("Required:")
    assert se.non_deferrable(se.Draft(files=_good()), "trigger.stages") is not None


def test_each_declared_stage_not_drafted_is_a_required_slot_and_only_those():
    f = _good()
    f[TRIG]["stages"] = STAGES + ["pcn_supplier_query"]
    named = lambda: sorted(k for k in _slots(f) if k.startswith(("trigger.", "steps.")))  # noqa: E731
    assert named() == ["steps.pcn_supplier_query"]
    del f["workflows/pcn_record.yaml"]
    assert named() == ["steps.pcn_record", "steps.pcn_supplier_query"]
    assert _slots(f)["steps.pcn_record"].question.startswith("Required:")


def test_the_stages_are_draft_only_the_served_trigger_drops_them():
    f = _good()
    f[TRIG]["stages"] = list(STAGES)
    assert se.runnable(f) == []
    assert "stages" not in se.finalize(f)[TRIG]
    assert "contradiction:trigger" not in _keys(f)
    # control: the runner's own Trigger refuses the field, so the drop is what makes it runnable
    with pytest.raises(Exception, match="stages"):
        se._cr.Trigger.model_validate(f[TRIG])


def test_a_declared_stage_no_row_names_yet_is_paired_by_its_place_in_the_list():
    u = _pcn_user()
    assert u.stages == STAGES
    draft = _rename(_good(), {"pcn_program_approval": "program_approval_stage"})
    del draft[CH]  # nothing routes to the program approval yet
    draft[TRIG]["stages"] = ["pcn_impact_review", "pcn_acknowledge", "program_approval_stage", "pcn_record"]
    key = "actors.program_approval_stage.program_approval.excludes"
    assert u.translate(key, draft) == BARRED_KEY
    # control: a list of another length pairs nothing by place
    draft[TRIG]["stages"] = draft[TRIG]["stages"][:3]
    assert u.translate(key, draft) is None


# ── 10-30: the turn check; a stalled question; a terminal is what a row points to ──────────────

PROGRAM = "workflows/pcn_program_approval.yaml"
PLANTED = "contradiction:workflows/pcn_impact_review.yaml#steps[id=engineering_disposition].excludes"
CONFIRMED = {  # the slots each fixture's person stated in passing, so the turn check asks them
    "pcn_review": ["actors.pcn_acknowledge.acknowledge.excludes",
                   "approvals.pcn_impact_review.engineering_disposition.reason_required",
                   "approvals.pcn_acknowledge.acknowledge.reason_required",
                   "approvals.pcn_program_approval.program_approval.reason_required"],
    "maint_case_release": ["actors.maint_case_inspection.inspection.excludes",
                           "actors.maint_case_supervisor_release.supervisor.excludes",
                           "approvals.maint_case_inspection.inspection.reason_required",
                           "approvals.maint_case_supervisor_release.supervisor.reason_required"],
    "training_course_approval": ["actors.course_content_review.content.excludes",
                                 "actors.course_security_review.security.excludes",
                                 "actors.course_accreditation.accreditation.excludes",
                                 "approvals.course_content_review.content.task_kind",
                                 "approvals.course_security_review.security.reason_required",
                                 "approvals.course_accreditation.accreditation.reason_required"],
}


@pytest.mark.parametrize("name", NAMES)
def test_the_turn_check_confirms_exactly_the_slots_no_turn_asked(name, oracle_runs):
    _, r, _ = oracle_runs[name]
    assert [q["key"] for q in r["questions"] if q["kind"] == "confirm"] == CONFIRMED[name]


def _unasked_excludes(transcript):
    """Runs 10 to 18 (ADR-0061 §10): the model writes `excludes: []` on the program approval while
    answering the stage question, which says nothing about who may answer."""
    def extractor(entry, draft, gap):
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == "steps.pcn_program_approval":
            patch = {**patch, "set": list(patch.get("set") or []) + [
                {"file": PROGRAM, "path": "steps[id=program_approval].excludes", "value": []}]}
        return patch
    return extractor


def test_a_slot_the_model_filled_unasked_is_confirmed_and_reaches_the_planted_contradiction():
    t = _transcript("pcn_review")
    r = se.run(t, _unasked_excludes(t))
    assert {"key": BARRED_KEY, "kind": "confirm", "facet": "actors"} in r["questions"]
    assert PLANTED in r["contradictions_asked"]
    assert r["status"] == "runnable" and r["files"] == _expected("pcn_review")


def test_control_a_slot_answered_in_its_own_turn_is_not_confirmed():
    t = _transcript("pcn_review")
    r = se.run(t, se.OracleExtractor())
    assert [q["kind"] for q in r["questions"] if q["key"] == BARRED_KEY] == ["missing"]
    assert PLANTED in r["contradictions_asked"]


@pytest.mark.parametrize("name,key", [
    ("pcn_review", "actors.pcn_acknowledge.acknowledge.excludes"),
    # a task kind is deferrable as a plain question: only the confirm rule keeps it open
    ("training_course_approval", "approvals.course_content_review.content.task_kind")])
def test_an_unanswered_confirm_is_asked_once_and_left_open_never_deferred(name, key):
    t = _transcript(name)
    del t["answers"][key]
    r = se.run(t, se.OracleExtractor())
    assert [q["key"] for q in r["questions"]].count(key) == 1
    assert key in r["open"] and key not in r["deferrals"]
    assert r["status"] == "cannot_run"


def test_the_opening_attributes_nothing():
    d = se.Draft()
    se.apply_patch(d, _transcript("pcn_review")["opening"]["facts"], 0)
    keys = {g.key for g in se.confirms(d)}
    assert "actors.pcn_impact_review.engineering_disposition.excludes" in keys
    # control: a question about the slot, answered after the opening, attributes it
    d.answered["actors.pcn_impact_review.engineering_disposition.excludes"] = 1
    assert "actors.pcn_impact_review.engineering_disposition.excludes" not in {g.key for g in se.confirms(d)}


def _silent_on(key, second=None):
    def extractor(entry, draft, gap):
        if gap is not None and gap.key == key:
            return second if (second is not None and draft.asked[key] > 1) else {}
        return se.OracleExtractor()(entry, draft, gap)
    return extractor


def test_a_repeated_question_whose_answer_changes_nothing_is_stalled():
    t = _transcript("pcn_review")
    r = se.run(t, _silent_on("trigger.stages"))
    assert [q["key"] for q in r["questions"]].count("trigger.stages") == 2
    assert r["stalled"] == ["trigger.stages"]
    assert "stalled" in r["open"]["trigger.stages"]


def test_control_a_repeated_question_whose_answer_changed_something_is_not_stalled():
    t = _transcript("pcn_review")
    note = {"set": [{"file": TRIG, "path": "note", "value": "changed"}]}
    r = se.run(t, _silent_on("trigger.stages", second=note))
    assert [q["key"] for q in r["questions"]].count("trigger.stages") == 2
    assert r["stalled"] == []
    assert "did not settle" in r["open"]["trigger.stages"]


def test_the_grammar_says_a_terminal_is_what_a_row_points_to():
    assert "A terminal is what a row points to" in se._GRAMMAR


def test_a_row_slot_for_an_outcome_listed_as_terminal_says_the_row_still_names_it():
    f = _good()
    f[CH]["terminals"] = f[CH]["terminals"] + ["rejected"]
    f[CH]["rows"] = [r for r in f[CH]["rows"] if r["when"]["outcome"] == "approved"]
    q = _slots(f)
    assert "'rejected' is listed as a final state" in q["approvals.pcn_impact_review.next.rejected"].question
    # control: an outcome not listed as terminal gets no such line
    assert "final state" not in q["approvals.pcn_impact_review.next.needs_info"].question


# ── 10-30: a confirm may be answered "that is not right" ────────────────────────────────────────

REC = "workflows/pcn_record.yaml"
FILING = "task_kinds/pcn_filing.yaml"
REJECTED_KEY = "actors.pcn_record.filed.excludes"
NO = "No, that is not right."


def _record_as_approval(redraft=True):
    """Runs 19 to 21 (ADR-0061 §10): the model drafts the record's wait as a human approval. With
    ``redraft``, the extractor applies the rejection's correction as given, as the grammar asks;
    without it, the correction is dropped."""
    def extractor(entry, draft, gap):
        if not redraft and entry.get("corrects"):
            return {"set": [], "unset": [], "defer": []}
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == "steps.pcn_record":
            for fact in patch["set"]:
                if fact["file"] == REC and fact["path"] == "":
                    fact["value"]["steps"][1] = {"kind": "human_await", "id": "filed",
                                                 "audience": "pcn_records:SUSTAINMENT",
                                                 "task_kind": "pcn_filing", "excludes": []}
            patch["set"].append({"file": FILING, "path": "",
                                 "value": {"kind": "pcn_filing", "accepts": ["filed"]}})
        return patch
    return extractor


def test_a_confirm_of_a_step_the_process_does_not_have_is_rejected_and_its_correction_alone_redrafts_it():
    t, exp = _transcript("pcn_review"), _expected("pcn_review")
    u = sm.AligningUser(t, exp)
    r = se.run(t, _record_as_approval(), answer=u)
    assert u.rejected == [REJECTED_KEY]
    said = [m["user"] for m in r["messages"] if (m["user"] or "").startswith(NO)]
    assert len(said) == 1
    said = said[0]
    assert said == NO + " " + t["answers"]["steps.pcn_record"]["says"]  # the stage, in their words
    assert PLANTED in r["contradictions_asked"]
    assert r["status"] == "runnable" and r["files"] == exp


def test_control_a_rejection_the_model_does_not_act_on_leaves_the_draft_cannot_run():
    t, exp = _transcript("pcn_review"), _expected("pcn_review")
    u = sm.AligningUser(t, exp)
    r = se.run(t, _record_as_approval(redraft=False), answer=u)
    assert u.rejected == [REJECTED_KEY]
    assert r["status"] == "cannot_run" and r["files"] != exp
    # the correction was offered, and logged with the turn that dropped it
    assert [m["key"] for m in r["messages"] if m.get("correction")] == [REJECTED_KEY]


def _confirm_draft():
    d = se.Draft(files=_expected("pcn_review"))
    d.files[REC]["steps"][1] = {"kind": "human_await", "id": "filed", "audience": "pcn_records:SUSTAINMENT",
                                "task_kind": "pcn_filing", "excludes": []}
    d.files[FILING] = {"kind": "pcn_filing", "accepts": ["filed"]}
    d.set_at[(REC, "steps")] = 1  # drafted in a turn that asked something else
    g = next(x for x in se.confirms(d) if x.key == REJECTED_KEY)
    return d, g


def test_a_confirm_may_rewrite_its_step_and_remove_the_task_kind_only_that_step_names():
    d, g = _confirm_draft()
    assert set(g.rewrites) == {(REC, "steps[id=filed]"), (FILING, "")}
    d.set_at[(FILING, "accepts")] = 1
    d.set_at[(REC, "steps[id=filed].task_kind")] = 1
    se.apply_patch(d, {"unset": [{"file": FILING, "path": ""}, {"file": REC, "path": "steps[id=filed].task_kind"}],
                       "set": [{"file": REC, "path": "steps[id=filed].kind", "value": "signal_await"}]},
                   1, answering=g)
    assert FILING not in d.files and "task_kind" not in d.files[REC]["steps"][1]
    assert d.files[REC]["steps"][1]["kind"] == "signal_await" and not d.pending
    # what was removed forgets the turns that set it; the turn that drafted the whole list stays
    assert (FILING, "accepts") not in d.set_at and (REC, "steps[id=filed].task_kind") not in d.set_at
    assert d.set_at[(REC, "steps")] == 1


def test_control_outside_its_step_a_confirm_answer_is_an_overwrite_contradiction():
    d, g = _confirm_draft()
    se.apply_patch(d, {"set": [{"file": REC, "path": "steps[id=disposition].channel", "value": "x"}]},
                   1, answering=g)
    assert [p.key for p in d.pending] == [f"contradiction:{REC}#steps[id=disposition].channel"]


@pytest.mark.parametrize("unset", [
    {"file": REC, "path": "steps[id=disposition].channel"},       # outside the step
    {"file": FILING, "path": "accepts"},                         # the kind file: whole or nothing
    {"file": "task_kinds/pcn_acknowledgement.yaml", "path": ""},  # a kind another step names
])
def test_an_unset_outside_the_confirms_scope_is_refused(unset):
    d, g = _confirm_draft()
    with pytest.raises(se.PatchError):
        se.apply_patch(d, {"unset": [unset]}, 1, answering=g)


def test_an_unset_is_refused_outside_a_confirm():
    d, _ = _confirm_draft()
    missing = se.Gap(REJECTED_KEY, "actors", "missing", "q", revises=((REC, "steps[id=filed].excludes"),),
                     rewrites=((REC, "steps[id=filed]"),))
    with pytest.raises(se.PatchError):
        se.apply_patch(d, {"unset": [{"file": REC, "path": "steps[id=filed].excludes"}]}, 1, answering=missing)


def test_the_scripted_user_never_denies_a_value_the_expected_bundle_holds():
    t, exp = _transcript("pcn_review"), _expected("pcn_review")
    key = "actors.pcn_acknowledge.acknowledge.excludes"
    del t["answers"][key]
    t["answers"]["steps.pcn_acknowledge"]["facts"]["set"] = []  # no entry states it either
    u = sm.AligningUser(t, exp)
    g = se.Gap(key, "actors", "confirm", "q")
    assert u(g, se.Draft(files=exp)) is None and u.rejected == [] and u.unbanked == [key]


def test_control_the_scripted_user_rejects_only_a_confirm():
    _, g = _confirm_draft()
    d, _ = _confirm_draft()
    u = sm.AligningUser(_transcript("pcn_review"), _expected("pcn_review"))
    missing = se.Gap(g.key, g.facet, "missing", g.question)
    assert u(missing, d) is None and u.rejected == []
    assert u(g, d)["says"].startswith(NO) and u.rejected == [REJECTED_KEY]


def test_the_grammar_and_the_parser_carry_unset():
    assert '"unset": [...]' in se._GRAMMAR and "UNSET the fields" in se._GRAMMAR
    m = se.ModelExtractor.__new__(se.ModelExtractor)
    m.errors = 0
    got = m._parse('{"set": [], "unset": [{"file": "a/b.yaml", "path": "x"}], "defer": []}')
    assert got["unset"] == [{"file": "a/b.yaml", "path": "x"}] and m.errors == 0


# ── 10-31: each turn's reply is logged; the confirm names its step; the rejection carries facts ──

def test_the_correction_is_the_stage_in_the_drafts_own_names():
    d, g = _confirm_draft()
    u = sm.AligningUser(_transcript("pcn_review"), _expected("pcn_review"))
    a = u(g, d)
    assert a["corrects"] == REJECTED_KEY
    assert sorted((f["file"], f["path"], f["value"]) for f in a["facts"].get("set", [])) == sorted([
        (REC, "steps[id=filed].kind", "signal_await"),
        (REC, "steps[id=filed].signal", "pcn_filed"),
        (REC, "steps[id=filed].accepts", ["filed"])])  # the audience is the same, so it is not set
    assert sorted((f["file"], f["path"]) for f in a["facts"].get("unset", [])) == sorted([
        (REC, "steps[id=filed].task_kind"), (REC, "steps[id=filed].excludes"), (FILING, "")])


def test_a_step_confirm_names_its_step_and_no_other_confirm_does():
    d, g = _confirm_draft()
    assert "It is about step `filed` of workflows/pcn_record.yaml." in g.question
    # control: the stage list is a slot of the trigger, not of a step
    d.files["triggers/pcn_received.yaml"][se._STAGES] = ["pcn_impact_review", "pcn_record"]
    d.set_at[("triggers/pcn_received.yaml", se._STAGES)] = 1
    other = [x for x in se.confirms(d) if not any(p.startswith("steps[id=") for _, p in x.rewrites)]
    assert [x.key for x in other] == [f"trigger.{se._STAGES}"] and "It is about" not in other[0].question


def test_the_model_is_shown_a_correction_only_for_a_rejection():
    d, g = _confirm_draft()
    u = sm.AligningUser(_transcript("pcn_review"), _expected("pcn_review"))
    a = u(g, d)
    m = se.ModelExtractor.__new__(se.ModelExtractor)
    m.context = {}
    shown = m._user_message(a, d, g)
    assert "\nCORRECTION\n" in shown and json.dumps(a["facts"]) in shown
    # control: an answer by path carries facts too, and they reach the model as words only
    path = {"says": "Yes.", "facts": a["facts"]}
    assert "CORRECTION" not in m._user_message(path, d, g)


def test_the_grammar_says_a_correction_is_applied_as_given():
    assert "CORRECTION" in se._GRAMMAR and "apply them as given" in se._GRAMMAR


def test_each_turn_logs_its_question_answer_and_every_reply_including_a_refused_one():
    t = _transcript("pcn_review")
    refused = []

    def extractor(entry, draft, gap):
        if gap is not None and gap.kind != "confirm" and not refused:
            refused.append(gap.key)
            return {"set": [], "unset": [{"file": REC, "path": "steps"}], "defer": []}
        return se.OracleExtractor()(entry, draft, gap)

    r = se.run(t, extractor)
    log = r["messages"]
    assert log[0]["kind"] == "opening" and log[0]["key"] is None
    assert log[0]["user"] == t["opening"]["says"] and len(log[0]["replies"]) == 1
    assert [m["key"] for m in log[1:]] == [q["key"] for q in r["questions"]]
    assert [m["kind"] for m in log[1:]] == [q["kind"] for q in r["questions"]]
    turn = next(m for m in log if m["key"] == refused[0])
    first, second = turn["replies"]
    assert first["patch"]["unset"] == [{"file": REC, "path": "steps"}] and first.get("refused")
    assert "refused" not in second and "patch" in second
    assert all(len(m["replies"]) == 1 for m in log if m is not turn and m["user"] is not None)


def test_the_measure_row_carries_every_turn():
    row = sm.measure("pcn_review", se.OracleExtractor())
    assert len(row["turns"]) == row["questions"] + 1 and row["turns"][0]["kind"] == "opening"


def test_a_selection_table_that_names_the_trigger_by_after_is_the_trigger_stage():
    # run 23: the trigger's `selection` named a field, not a table
    files = {"triggers/pcn.yaml": {"trigger": "pcn_received", "selection": "change_class"},
             "decisions/sel.yaml": {"decision": "pcn_sel", "after": "pcn_received"}}
    assert sm._index(files)["sel_name"] == "pcn_sel"


def test_control_two_tables_naming_the_trigger_by_after_choose_neither():
    files = {"triggers/pcn.yaml": {"trigger": "pcn_received", "selection": "change_class"},
             "decisions/a.yaml": {"decision": "a", "after": "pcn_received"},
             "decisions/b.yaml": {"decision": "b", "after": "pcn_received"}}
    i = sm._index(files)
    assert i["sel_name"] == "change_class" and i["sel"] is None


def test_a_reply_logs_the_models_own_text_when_the_extractor_keeps_it():
    class Raw:
        last_raw = None

        def __call__(self, entry, draft, gap):
            self.last_raw = f"text for {gap.key if gap else 'opening'}"
            return se.OracleExtractor()(entry, draft, gap)

    r = se.run(_transcript("pcn_review"), Raw())
    replies = [(m["key"], x) for m in r["messages"] for x in m["replies"]]
    assert replies and all(x.get("raw") == f"text for {k or 'opening'}" for k, x in replies)
    # control: an extractor that keeps no text logs none
    assert all("raw" not in x for m in se.run(_transcript("pcn_review"), se.OracleExtractor())["messages"]
               for x in m["replies"])


# ── 2026-11-02: a row for an outcome the stage lacks; rendering; a null is not a deferral ───────

CHAIN = "decisions/pcn_acknowledge_chaining.yaml"
CHAIN_NAME = "pcn_acknowledge_chaining"


def _with_stray_row(outcome):
    files = _expected("pcn_review")
    t = files[CHAIN]
    t["domain"]["outcome"] = list(t["domain"]["outcome"]) + [outcome]
    t["rows"] = list(t["rows"]) + [{"when": {"outcome": outcome}, "then": t["rows"][0]["then"]}]
    return files


def _gap_of(files, key):
    return next(g for g in se.problems(files) if g.key == key)


def test_the_scripted_user_says_no_to_a_row_for_an_outcome_the_stage_lacks_and_the_row_goes():
    exp = _expected("pcn_review")
    files = _with_stray_row("timed_out")
    key = f"contradiction:chaining.{CHAIN_NAME}.timed_out"
    u = sm.AligningUser(_transcript("pcn_review"), exp)
    entry = u(_gap_of(files, key), se.Draft(files=files)) or {}
    assert entry.get("says", "").startswith("No") and entry.get("corrects") == key and u.denied_rows == [key]
    assert u.rejected == [] and u.unbanked == []
    by_path = {x["path"]: x["value"] for x in (entry.get("facts") or {}).get("set", [])}
    assert by_path == {"domain.outcome": exp[CHAIN]["domain"]["outcome"], "rows": exp[CHAIN]["rows"]}
    # applied as the answer to that question, it is what the question may revise, and the gap is gone
    d = se.Draft(files=files)
    se.apply_patch(d, entry["facts"], 1, answering=_gap_of(files, key))
    assert d.pending == [] and d.files[CHAIN] == exp[CHAIN]
    assert key not in [g.key for g in se.problems(d.files)]


def test_control_an_outcome_the_expected_table_routes_is_never_denied():
    t, exp = _transcript("pcn_review"), _expected("pcn_review")
    files = copy.deepcopy(exp)
    # the draft's task kind has lost an outcome the expected table still routes
    routed = exp[CHAIN]["domain"]["outcome"][0]
    files["task_kinds/pcn_acknowledgement.yaml"]["accepts"] = [
        v for v in files["task_kinds/pcn_acknowledgement.yaml"]["accepts"] if v != routed]
    key = f"contradiction:chaining.{CHAIN_NAME}.{routed}"
    u = sm.AligningUser(t, exp)
    entry = u(_gap_of(files, key), se.Draft(files=files))
    assert entry["says"].startswith(f"Yes, it can end '{routed}'") and "facts" not in entry
    assert u.denied_rows == [] and u.unbanked == [] and u.answered_contradictions == [key]


def test_control_a_table_that_does_not_align_is_not_answered():
    files = _with_stray_row("timed_out")
    key = f"contradiction:chaining.{CHAIN_NAME}.timed_out"
    g = _gap_of(files, key)
    # nothing reaches the stage in this expected bundle, so the table has no counterpart
    exp = _expected("pcn_review")
    del exp[CHAIN]
    u = sm.AligningUser(_transcript("pcn_review"), exp)
    assert u(g, se.Draft(files=files)) is None and u.denied_rows == []
    # and when the key translates to a table the expected bundle does not hold
    assert u._no_such_outcome(g, files, "contradiction:chaining.not_expected.timed_out") is None
    assert u.denied_rows == []


def test_control_a_planted_row_contradiction_is_answered_from_the_bank():
    t = _transcript("training_course_approval")
    key = "contradiction:chaining.course_content_review_chaining.deferred"
    assert key in t["planted"]["contradictions"]
    u = sm.AligningUser(t, _expected("training_course_approval"))
    g = se.Gap(key, "approvals", "contradiction", "q",
               revises=(("decisions/course_content_review_chaining.yaml", "rows"),))
    assert u(g, se.Draft(files=_expected("training_course_approval"))) == t["answers"][key]
    assert u.denied_rows == []


def test_the_model_is_shown_a_row_denials_correction():
    entry = {"says": "No", "corrects": "contradiction:chaining.t.v", "facts": {"set": [{"file": "f", "path": "rows", "value": []}]}}
    assert "CORRECTION" in se.ModelExtractor("http://model.invalid", "m")._user_message(entry, se.Draft(), None)


def test_the_grammar_applies_a_correction_outside_the_confirm_rule():
    assert any(ln.startswith("- When the answer carries a CORRECTION") for ln in se._GRAMMAR.splitlines())


KIND = "task_kinds/k.yaml"


@pytest.mark.parametrize("entry", [
    {"file": KIND, "path": "", "value": {"kind": "k", "accepts": ["approved"], "renders_as": {"title": "T"}}},
    {"file": KIND, "path": "kind", "value": "k"},
])
def test_a_rendering_field_written_by_the_model_is_never_held(entry):
    d = se.Draft()
    se.apply_patch(d, {"set": [entry, {"file": KIND, "path": "renders_as", "value": {"title": "T"}},
                               {"file": KIND, "path": "renders_as.badge", "value": "B"}]}, 1)
    assert "renders_as" not in d.files[KIND]
    assert not [k for k in d.set_at if "renders_as" in k[1]]


def test_a_second_rendering_value_raises_no_contradiction_and_an_unset_is_not_refused():
    d = se.Draft(files={KIND: {"kind": "k", "accepts": ["approved"]}})
    se.apply_patch(d, {"set": [{"file": KIND, "path": "renders_as.title", "value": "one"}]}, 1)
    se.apply_patch(d, {"set": [{"file": KIND, "path": "renders_as.title", "value": "two"}],
                       "unset": [{"file": KIND, "path": "renders_as"}]}, 2)
    assert d.pending == [] and "renders_as" not in d.files[KIND]


def test_a_rendering_only_patch_declares_no_task_kind():
    d = se.Draft()
    se.apply_patch(d, {"set": [{"file": KIND, "path": "renders_as", "value": {"title": "T"}}]}, 1)
    assert KIND not in d.files


def test_the_rendering_comes_from_the_declaration_default_and_the_bundle_runs():
    # run 25: two kinds with a `renders_as` holding only a title, and the runtime refused them
    exp = _expected("pcn_review")
    files = copy.deepcopy(exp)
    kind_file = "task_kinds/pcn_acknowledgement.yaml"
    d = se.Draft(files={f: b for f, b in files.items() if f != kind_file})
    body = {k: v for k, v in files[kind_file].items() if k != "renders_as"}
    se.apply_patch(d, {"set": [{"file": kind_file, "path": "", "value": {**body, "renders_as": {"title": "T"}}}]}, 1)
    assert not [g.key for g in se.problems(d.files) if "task_kind" in g.key]
    fin = se.finalize(d.files)
    assert fin[kind_file]["renders_as"] == exp[kind_file]["renders_as"]
    assert se.runnable(fin) == []


def test_control_a_shipped_kinds_own_rendering_is_kept():
    # the drop is at the dialogue's door: finalize does not overwrite a declared rendering
    files = {KIND: {"kind": "k", "accepts": ["approved"],
                    "renders_as": {"badge": "OWN", "title": "Own", "archetype": "TRIAGE_TASK"}}}
    assert se.finalize(files)[KIND]["renders_as"]["badge"] == "OWN"


def test_control_only_a_task_kinds_rendering_is_dropped():
    d = se.Draft()
    se.apply_patch(d, {"set": [{"file": "workflows/w.yaml", "path": "renders_as", "value": "kept"}]}, 1)
    assert d.files.get("workflows/w.yaml", {}).get("renders_as") == "kept"


WF = "workflows/pcn_program_approval.yaml"
NULL_STEP = "steps[id=program_approval].deadline_seconds"
NULL_KEY = "approvals.pcn_program_approval.program_approval.deadline"


def _null_draft(turn=3):
    files = _expected("pcn_review")
    step = next(s for s in files[WF]["steps"] if s["id"] == "program_approval")
    step["deadline_seconds"] = None
    d = se.Draft(files=files)
    d.set_at[(WF, NULL_STEP)] = turn
    return d


def _null_gap(d):
    return next(g for g in se.gaps(d) if g.key == NULL_KEY)


def test_a_null_written_for_a_required_value_is_asked_defer_this():
    d = _null_draft()
    g = _null_gap(d)
    assert g.kind == "null" and "Defer this?" in g.question and g.revises == ((WF, NULL_STEP),)
    assert se.non_deferrable(d, NULL_KEY) is None


def test_null_is_not_a_deferral():
    d = _null_draft()
    assert d.deferrals == {} and NULL_KEY in [g.key for g in se.gaps(d)]


def test_a_deferral_removes_the_null_and_settles_the_key():
    d = _null_draft()
    se.apply_patch(d, {"defer": [{"gap": NULL_KEY, "reason": "not agreed"}]}, 4, answering=_null_gap(d))
    step = next(s for s in d.files[WF]["steps"] if s["id"] == "program_approval")
    assert d.deferrals == {NULL_KEY: "not agreed"} and "deadline_seconds" not in step
    assert NULL_KEY not in [g.key for g in se.gaps(d)]


def test_a_value_replaces_the_null_without_a_contradiction():
    d = _null_draft()
    se.apply_patch(d, {"set": [{"file": WF, "path": NULL_STEP, "value": 3600}]}, 4, answering=_null_gap(d))
    assert d.pending == [] and NULL_KEY not in [g.key for g in se.gaps(d)]


def test_control_a_null_the_person_was_asked_about_stands():
    d = _null_draft()
    d.vouched[(WF, NULL_STEP)] = 4
    assert NULL_KEY not in [g.key for g in se.gaps(d)]
    step = next(s for s in d.files[WF]["steps"] if s["id"] == "program_approval")
    assert step["deadline_seconds"] is None
    # a null written after that answer is asked again: the vouching does not outlive the value
    d.set_at[(WF, NULL_STEP)] = 5
    assert NULL_KEY in [g.key for g in se.gaps(d)]


def test_control_a_value_is_not_asked_and_an_absent_slot_is_asked_as_missing():
    assert NULL_KEY not in [g.key for g in se.gaps(se.Draft(files=_expected("pcn_review")))]
    files = _expected("pcn_review")
    step = next(s for s in files[WF]["steps"] if s["id"] == "program_approval")
    del step["deadline_seconds"]
    assert [g.kind for g in se.gaps(se.Draft(files=files)) if g.key == NULL_KEY] == ["missing"]


def test_control_a_null_on_a_definition_no_table_names_is_not_asked():
    f = _good()
    _orphan(f)
    assert [g for g in se.null_values(se.Draft(files=f)) if "orphan_stage" in g.key] == []


def test_a_null_is_asked_once_even_when_the_slot_was_asked_twice_before():
    d = _null_draft()
    d.asked[NULL_KEY] = 2
    assert NULL_KEY in [g.key for g in se.gaps(d)]
    d.null_asked.add(NULL_KEY)
    assert NULL_KEY not in [g.key for g in se.gaps(d)]


@pytest.mark.parametrize("file,leaf,key", [
    ("triggers/pcn_received.yaml", "requires", "trigger.requires"),
])
def test_every_slot_asked_while_absent_asks_its_null_too(file, leaf, key):
    files = _expected("pcn_review")
    if file not in files:
        file = next(f for f in files if f.startswith("triggers/"))
    files[file][leaf] = None
    d = se.Draft(files=files)
    assert [g.kind for g in se.gaps(d) if g.key == key] == ["null"]
    assert not [g.key for g in se.problems(files) if g.key.startswith("contradiction:")]
    se.apply_patch(d, {"defer": [{"gap": key, "reason": "not decided"}]}, 1)
    assert leaf not in d.files[file]


def test_a_null_for_who_is_barred_is_not_nobody_and_may_not_be_deferred():
    files = _expected("pcn_review")
    step = next(s for s in files[WF]["steps"] if s["id"] == "program_approval")
    step["excludes"] = None
    key = "actors.pcn_program_approval.program_approval.excludes"
    d = se.Draft(files=files)
    assert [g.kind for g in se.gaps(d) if g.key == key] == ["missing"]
    assert se.non_deferrable(d, key) is not None
    assert not [s for s in se._value_slots(files) if s[0] == key]  # not read as "nobody is barred"
    g = next(g for g in se.gaps(d) if g.key == key)
    se.apply_patch(d, {"set": [{"file": WF, "path": "steps[id=program_approval].excludes", "value": []}]}, 1, answering=g)
    assert d.pending == [] and key not in [g.key for g in se.gaps(d) if g.kind == "missing"]


def test_the_loop_defers_a_null_the_person_says_is_not_decided():
    t = _transcript("pcn_review")
    calls = []

    def extractor(entry, draft, gap):
        if gap is not None and gap.key == DEADLINE_KEY and gap.kind == "missing":
            calls.append(gap.kind)  # the model reads "not agreed" as null, as in runs 28 to 30
            f = "workflows/pcn_impact_review.yaml"
            return {"set": [{"file": f, "path": "steps[id=engineering_disposition].deadline_seconds",
                             "value": None}], "unset": [], "defer": []}
        return se.OracleExtractor()(entry, draft, gap)

    r = se.run(t, extractor)
    assert calls == ["missing"]
    assert [q["kind"] for q in r["questions"] if q["key"] == DEADLINE_KEY] == ["missing", "null"]
    assert DEADLINE_KEY in r["deferrals"] and r["status"] == "runnable"
    assert r["files"] == _expected("pcn_review")


def test_a_stated_no_deadline_survives_the_question():
    r = se.run(_transcript("pcn_review"), se.OracleExtractor())
    key = "approvals.pcn_acknowledge.acknowledge.deadline"
    assert [q["kind"] for q in r["questions"] if q["key"] == key] == ["null"]
    assert key not in r["deferrals"]
    step = next(s for s in r["files"]["workflows/pcn_acknowledge.yaml"]["steps"] if s["id"] == "acknowledge")
    assert step["deadline_seconds"] is None


def test_the_measure_row_names_nulls_and_denials():
    row = sm.measure("pcn_review", se.OracleExtractor(), aligned=True)
    assert row["nulls_asked"] == ["approvals.pcn_acknowledge.acknowledge.deadline"]
    assert row["denied_rows"] == []


def test_the_grammar_says_null_is_not_a_deferral_and_never_set_renders_as():
    grammar = " ".join(se._GRAMMAR.split())
    assert "null is not a deferral" in grammar and "Never set `renders_as`" in grammar


# ── an emit that declares its disposition: the runner's rule, read the same here ─────────

REC_CH = "decisions/pcn_record_chaining.yaml"


def _record_only_emits(disposes=None):
    f = _good()
    f[REC]["steps"] = [s for s in f[REC]["steps"] if s["kind"] == "emit"]
    if disposes:
        f[REC]["steps"][0]["disposes"] = disposes
    return f


def test_an_emit_that_declares_its_disposition_ends_its_definition():
    f = _record_only_emits("filed")
    assert "outputs.pcn_record.ends" not in _keys(f)
    assert se.problems(f) == [] and se.runnable(f) == []


def test_control_an_emit_that_declares_nothing_still_disposes_nothing():
    assert "outputs.pcn_record.ends" in _keys(_record_only_emits())


def test_the_table_is_held_to_what_the_emit_declares_not_to_elapsed():
    keys = _keys(_record_only_emits("sent"))
    assert "outputs.pcn_record.next.sent" in keys
    assert "contradiction:chaining.pcn_record_chaining.filed" in keys
    assert "outputs.pcn_record.next.elapsed" not in keys


def test_a_definition_whose_emit_disposes_needs_a_table_after_it():
    f = _record_only_emits("filed")
    del f[REC_CH]
    assert any("no table declares `after: pcn_record`" in e for e in se.runnable(f))


def test_control_an_emit_that_disposes_nothing_needs_no_table_after_it():
    f = _record_only_emits()
    del f[REC_CH]
    assert not any("no table declares `after: pcn_record`" in e for e in se.runnable(f))


# ── runnable refuses a definition no table routes to (architect, 2026-11-02) ─────────────────

PROGRAM_CH = "decisions/pcn_program_approval_chaining.yaml"
PROGRAM_NEXT = "approvals.pcn_program_approval.next"
ROUTED = "steps.pcn_record.routed"
REFUSED = "definition pcn_record: no table routes to it from the trigger"


def _cut(files, stage, terminal):
    """Every row that routes to ``stage`` ends the case at ``terminal`` instead: run 33's table."""
    for name, d in files.items():
        if not name.startswith("decisions/"):
            continue
        for row in d.get("rows") or []:
            if row.get("then") == stage:
                row["then"] = terminal
                if terminal not in d["terminals"]:
                    d["terminals"].append(terminal)


def _staged(files):
    """``files`` as a draft holds them: ``finalize`` drops the trigger's stages from a bundle, and
    the routing question waits for them."""
    trigger = next(d for f, d in files.items() if f.startswith("triggers/"))
    trigger[se._STAGES] = sorted(d["id"] for f, d in files.items() if f.startswith("workflows/"))
    return files


def test_runnable_refuses_a_definition_no_table_routes_to():
    f = _good()
    _cut(f, "pcn_record", "pcn_rejected")
    assert se.runnable(f) == [REFUSED]


def test_runnable_refuses_everything_downstream_of_the_cut():
    """Run 32's shape: the record has a table after it and a row into it, from a stage no case
    reaches. Only a walk from the trigger says so."""
    f = _good()
    _cut(f, "pcn_program_approval", "pcn_rejected")
    assert sorted(se.runnable(f)) == [
        "definition pcn_program_approval: no table routes to it from the trigger", REFUSED]


def test_runnable_refuses_a_definition_with_no_table_at_all():
    f = _good()
    _orphan(f)
    assert "definition orphan_stage: no table routes to it from the trigger" in se.runnable(f)


@pytest.mark.parametrize("name", NAMES)
def test_control_every_stage_of_each_expected_bundle_is_reached(name):
    assert se.runnable(_expected(name)) == []
    assert se.required_slots(_staged(_expected(name))) == []


def test_a_terminal_is_read_in_its_own_table():
    """Another table's terminal of that name does not stop this table's row: ``runnable`` reads a
    row's ``then`` against its own table, so a walk with one list of terminals refuses a bundle the
    runner runs."""
    f = _good()
    f["decisions/pcn_acknowledge_chaining.yaml"]["terminals"].append("pcn_record")
    assert "pcn_record" in se._reachable(f)
    assert REFUSED not in se.runnable(f)


def test_the_person_is_asked_about_the_refusal_and_may_not_defer_it():
    f = _staged(_good())
    _cut(f, "pcn_record", "pcn_rejected")
    g = _slots(f)[ROUTED]
    assert g.kind == "missing" and "pcn record" in g.question
    assert (PROGRAM_CH, "rows") in g.revises and (PROGRAM_CH, "terminals") in g.revises
    assert se.non_deferrable(se.Draft(files=f), ROUTED)


def test_control_the_routing_question_waits_for_the_tables_being_drafted():
    """A stage the draft has not routed yet is asked for by its table, not reported as lost."""
    f = _staged(_good())
    _cut(f, "pcn_record", "pcn_rejected")
    del f[CH]
    slots = _slots(f)
    assert "approvals.pcn_impact_review.next" in slots and ROUTED not in slots


def _routes_to_a_terminal(entry, draft, gap):
    patch = se.OracleExtractor()(entry, draft, gap)
    if gap is not None and gap.key == PROGRAM_NEXT:
        return json.loads(json.dumps(patch).replace(
            '"then": "pcn_record"', '"then": "pcn_rejected"'))
    return patch


def test_a_person_who_hears_the_refusal_can_route_the_stage():
    t = _transcript("pcn_review")
    r = se.run(t, _routes_to_a_terminal, answer=sm.AligningUser(t, _expected("pcn_review")))
    assert ROUTED in [q["key"] for q in r["questions"]]
    assert not any("rows" in c for c in r["contradictions_asked"])
    assert r["status"] == "runnable" and r["files"] == _expected("pcn_review")


def test_a_refusal_left_unanswered_is_open_and_cannot_run():
    r = se.run(_transcript("pcn_review"), _routes_to_a_terminal)
    assert ROUTED in r["open"] and ROUTED not in r["deferrals"]
    assert REFUSED in r["runnable"] and r["status"] == "cannot_run"


def test_the_measure_row_names_what_is_unreachable():
    row = sm.measure("pcn_review", _routes_to_a_terminal)
    assert row["unreachable"] == ["pcn_record"]
    assert sm.measure("pcn_review", se.OracleExtractor())["unreachable"] == []


# ── which outcomes need a reason: a required slot per approval step (architect, 2026-11-02) ───

REASON_KIND = "task_kinds/pcn_engineering_disposition.yaml"
REASON_KEY = "approvals.pcn_impact_review.engineering_disposition.reason_required"
KIND_ENTRY = "approvals.pcn_impact_review.engineering_disposition.task_kind"


def _set_reasons(value):
    """An extractor that writes ``value`` (or nothing, for None) as the reasons in the turn that
    drafts the kind, as a model does while answering a question that did not ask."""
    def extractor(entry, draft, gap):
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == KIND_ENTRY:
            patch = copy.deepcopy(patch)
            for fact in patch["set"]:
                if fact["file"] == REASON_KIND:
                    del fact["value"]["reason_required"]
                    if value is not None:
                        fact["value"]["reason_required"] = value
        return patch
    return extractor


@pytest.mark.parametrize("held", ["absent", "null"])
def test_every_approval_step_is_asked_which_outcomes_need_a_reason(held):
    f = _good()
    del f[REASON_KIND]["reason_required"]
    if held == "null":  # as excludes: a null has said nothing, so it is not "defer this?"
        f[REASON_KIND]["reason_required"] = None
    g = _slots(f)[REASON_KEY]
    assert g.kind == "missing" and g.facet == "approvals"
    assert "need a reason" in g.question and "needs_info" in g.question
    assert g.revises == ((REASON_KIND, "reason_required"),)
    assert [x.kind for x in se.gaps(se.Draft(files=f)) if x.key == REASON_KEY] == ["missing"]


def test_control_a_held_value_and_a_signal_step_are_not_asked():
    """pcn_record's signal_await declares no reasons and is not an approval step."""
    assert [k for k in _slots(_good()) if k.endswith("reason_required")] == []


def test_each_step_naming_a_kind_is_asked_for_itself():
    f = _good()
    del f[REASON_KIND]["reason_required"]
    _step(f, PROGRAM, "program_approval")["task_kind"] = "pcn_engineering_disposition"
    keys = [k for k in _slots(f) if k.endswith("reason_required")]
    assert keys == [REASON_KEY, "approvals.pcn_program_approval.program_approval.reason_required"]


def test_the_per_kind_question_is_gone():
    f = _good()
    del f[REASON_KIND]["reason_required"]
    keys = [g.key for g in se._completeness(f)]
    assert "approvals.pcn_engineering_disposition.reason_required" not in keys
    _step(f, IR, "engineering_disposition").pop("deadline_seconds", None)  # the control: it still asks
    assert "approvals.pcn_impact_review.engineering_disposition.deadline" in \
        [g.key for g in se._completeness(f)]


def test_the_reasons_may_not_be_deferred():
    t = _transcript("pcn_review")
    del t["answers"][REASON_KEY]
    r = se.run(t, _set_reasons(None))
    assert REASON_KEY in r["open"] and REASON_KEY not in r["deferrals"]
    assert r["status"] == "cannot_run"


def test_an_empty_list_nobody_stated_is_replaced_by_the_stated_reasons():
    """Runs 31 to 33 lost the reasons: an unasked `[]`, and a later statement charged as an overwrite
    with nobody to answer it (ADR-0061 §10). The confirm's answer may replace the value."""
    t = _transcript("pcn_review")
    r = se.run(t, _set_reasons([]))
    assert {"key": REASON_KEY, "kind": "confirm", "facet": "approvals"} in r["questions"]
    assert not any("reason_required" in c for c in r["contradictions_asked"])
    assert r["files"] == _expected("pcn_review") and r["status"] == "runnable"


def test_the_grammar_requires_the_reasons_and_says_what_empty_means():
    grammar = " ".join(se._GRAMMAR.split())
    assert "every task kind sets reason_required" in grammar
    assert "[] only when the user says none do" in grammar


def test_a_reason_confirm_on_a_step_the_process_does_not_have_is_rejected():
    d, _ = _confirm_draft()
    d.files[FILING]["reason_required"] = []
    d.set_at[(FILING, "reason_required")] = 1
    key = "approvals.pcn_record.filed.reason_required"
    g = next(x for x in se.confirms(d) if x.key == key)
    assert (REC, "steps[id=filed]") in g.rewrites
    u = sm.AligningUser(_transcript("pcn_review"), _expected("pcn_review"))
    said = u(g, d)
    assert said is not None and said["says"].startswith(NO) and u.rejected == [key]


def test_control_reasons_the_person_was_asked_for_are_not_confirmed():
    r = se.run(_transcript("pcn_review"), _set_reasons(None))
    assert [q["kind"] for q in r["questions"] if q["key"] == REASON_KEY] == ["missing"]
    assert r["files"] == _expected("pcn_review")


def test_the_confirm_says_what_the_draft_holds():
    f = _good()
    d = se.Draft(files=f)
    d.set_at[(REASON_KIND, "reason_required")] = 1
    g = next(x for x in se.confirms(d) if x.key == REASON_KEY)
    assert "rejected" in g.question and "needs_info" in g.question and g.revises == ((REASON_KIND, "reason_required"),)
    f[REASON_KIND]["reason_required"] = []
    g = next(x for x in se.confirms(d) if x.key == REASON_KEY)
    assert "no outcome needs a reason" in g.question


def test_the_scripted_user_finds_where_each_new_slot_is_stated():
    e = _expected("pcn_review")
    assert sm._slot_target(REASON_KEY, e) == (REASON_KIND, "reason_required")
    assert sm._slot_target(ROUTED, e) == (PROGRAM_CH, "rows")
    assert sm._slot_target("steps.pcn_acknowledge.routed", e) == (SEL, "rows")
    assert sm._slot_target("outputs.pcn_record.ends", e) == (REC, "steps[id=filed].kind")
    assert sm._slot_target("approvals.no_such.step.reason_required", e) is None
    assert sm._slot_target("steps.no_such.routed", e) is None
    assert sm._slot_target("approvals.x.next", e) is None


# ── run 34: a value of the wrong shape is refused, never a crash ──────────────────────────────

def _wrong_shape(file, *path, value):
    """The whole of ``file`` with one node replaced, and a draft that does not hold it yet, so the
    patch lands rather than charging an overwrite."""
    f = _good()
    doc = copy.deepcopy(f.pop(file))
    node = doc
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    return se.Draft(files=f), {"set": [{"file": file, "path": "", "value": doc}]}


@pytest.mark.parametrize("file,path,value", [
    (CH, ("rows", 0, "when"), "approved"),  # run 34's own
    (CH, ("rows", 0), "approved"),
    (CH, ("rows", 0, "then"), {"a": 1}),
    (CH, ("rows",), 1),
    (CH, ("matches",), 1),
    (CH, ("matches", 0), {"a": 1}),
    (CH, ("domain",), "x"),
    (CH, ("domain", "outcome"), 1),
    (CH, ("terminals",), 1),
    (CH, ("terminals", 0), {"a": 1}),
    (CH, ("after",), {"a": 1}),
    (REASON_KIND, ("accepts", 0), {"a": 1}),
    (IR, ("steps", 0, "kind"), ["x"]),
    (TRIG, ("requires",), 1),
])
def test_a_value_of_the_wrong_shape_is_refused_and_the_draft_keeps_what_it_had(file, path, value):
    draft, patch = _wrong_shape(file, *path, value=value)
    before = copy.deepcopy(draft.files)
    charged, log = [], []
    se._apply_or_charge(draft, lambda *_: patch, {"says": "x"}, None, 1, charged, log)
    assert draft.files == before
    assert len(charged) == 1 + se.PATCH_RESTATES and "wrong shape" in charged[0]["error"]
    assert "{when: {input: value}, then: name}" in log[0]["refused"]


def test_control_the_same_file_of_the_right_shape_lands():
    file = CH
    draft, patch = _wrong_shape(file, "after", value=_good()[file]["after"])
    charged = []
    se._apply_or_charge(draft, lambda *_: patch, {"says": "x"}, None, 1, charged)
    assert charged == [] and draft.files[file] == _good()[file]


@pytest.mark.parametrize("value", [[1], 1])
def test_the_instrument_records_a_shape_the_loop_tolerates(value):
    f = _good()
    f[IR]["steps"] = value
    assert len(sm.semantic_diffs(f, _good())) == 1
    assert sm._steps_of(f[IR]) == []


def test_a_run_restates_a_row_of_the_wrong_shape_and_finishes():
    """Run 34 lost everything: the crash came before the row was written out."""
    def once_wrong(entry, draft, gap):
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == PROGRAM_NEXT and not entry.get("refused"):
            patch = copy.deepcopy(patch)
            for fact in patch["set"]:
                if fact["file"] == PROGRAM_CH:
                    fact["value"]["rows"][0]["when"] = "approved"
        return patch
    r = se.run(_transcript("pcn_review"), once_wrong)
    assert len(r["model_errors"]) == 1 and "wrong shape" in r["model_errors"][0]["error"]
    assert r["status"] == "runnable" and r["files"] == _expected("pcn_review")


# ── an emit may dispose: in the grammar, asked only for emit steps (architect, 2026-11-02) ────


def test_the_grammar_says_only_an_emit_disposes():
    assert "Only an emit step has disposes" in se._GRAMMAR


def test_a_definition_that_only_sends_is_asked_whether_sending_settles_it():
    q = _keys(_record_only_emits())["outputs.pcn_record.ends"].question
    assert "sending disposition" in q and "with what outcome" in q


def test_control_a_definition_with_no_emit_is_not_asked_about_sending():
    f = _good()
    f[REC]["steps"] = [{"kind": "render", "id": "page", "template": "x"}]
    q = _keys(f)["outputs.pcn_record.ends"].question
    assert "who or what confirms it" in q and "sending" not in q


def test_a_disposition_on_any_other_step_is_refused_and_not_confirmed():
    f = _good()
    _step(f, IR, "engineering_disposition")["disposes"] = "approved"
    assert not [s for s in se._value_slots(f) if s[0] == "outputs.pcn_impact_review.ends"]


def test_only_an_emit_step_may_declare_it():
    f = _good()
    _step(f, IR, "engineering_disposition")["disposes"] = "approved"
    assert se.runnable(f) != []


def _sends_and_guesses(entry, draft, gap):
    patch = se.OracleExtractor()(entry, draft, gap)
    if gap is not None and gap.key == "steps.pcn_record":
        patch = {**patch, "set": list(patch.get("set") or []) + [
            {"file": REC, "path": "steps[id=disposition].disposes", "value": "filed"}]}
    return patch


def test_a_disposition_nobody_stated_is_confirmed():
    t = _transcript("pcn_review")
    r = se.run(t, _sends_and_guesses, answer=sm.AligningUser(t, _expected("pcn_review")))
    assert {"key": "outputs.pcn_record.ends", "kind": "confirm", "facet": "outputs"} in r["questions"]
    assert "outputs.pcn_record.ends" not in r["open"]


def test_control_a_disposition_the_person_was_asked_about_is_not_confirmed():
    d = se.Draft(files=_record_only_emits("filed"))
    d.set_at[(REC, "steps[id=disposition].disposes")] = 2
    assert "outputs.pcn_record.ends" in [g.key for g in se.confirms(d)]
    d.answered["outputs.pcn_record.ends"] = 2
    assert "outputs.pcn_record.ends" not in [g.key for g in se.confirms(d)]


# ── a value nobody stated, corrected at its own confirm (architect, 2026-11-02) ───────────────

ACK_KIND = "task_kinds/pcn_acknowledgement.yaml"
ACK_ENDS = "outputs.pcn_acknowledge.ends"


def _acknowledge_guessed():
    """Runs 35 and 36: the opening guessed the stage as a send, and a table for that send."""
    f = _good()
    emit = next(s for s in f[REC]["steps"] if s["kind"] == "emit")
    f[ACK]["steps"] = [{**copy.deepcopy(emit), "id": "notify", "disposes": "sent"}]
    del f[ACK_KIND]
    f[ACK_CH]["domain"]["outcome"] = ["sent"]
    f[ACK_CH]["rows"] = [{"when": {"outcome": "sent"}, "then": "pcn_acknowledged"}]
    d = se.Draft(files=f)
    d.set_at[(ACK, "steps[id=notify].disposes")] = 0
    for leaf in ("matches", "domain.outcome", "rows", "terminals"):
        d.set_at[(ACK_CH, leaf)] = 0
    return d, next(g for g in se.confirms(d) if g.key == ACK_ENDS)


def _the_stage_as_described():
    good = _good()
    return {"set": [{"file": ACK, "path": "steps", "value": good[ACK]["steps"]},
                    {"file": ACK_KIND, "path": "", "value": good[ACK_KIND]},
                    {"file": ACK_CH, "path": "domain.outcome", "value": good[ACK_CH]["domain"]["outcome"]},
                    {"file": ACK_CH, "path": "rows", "value": good[ACK_CH]["rows"]}]}


def test_a_confirm_replaces_the_guessed_step_and_its_table_with_nothing_to_contradict():
    d, g = _acknowledge_guessed()
    charged = []
    se._apply_or_charge(d, lambda *_: _the_stage_as_described(), {"says": "x"}, g, 3, charged)
    assert charged == [] and d.pending == [] and se.finalize(d.files) == _good()


@pytest.mark.parametrize("asked", ["approvals.pcn_acknowledge.next", "outputs.pcn_acknowledge.next"])
def test_control_a_table_the_person_was_asked_about_still_pends_and_the_step_still_lands(asked):
    d, g = _acknowledge_guessed()
    guess = copy.deepcopy(d.files[ACK_CH]["rows"])
    d.answered[asked] = 1
    se.apply_patch(d, _the_stage_as_described(), 3, answering=g)
    assert d.files[ACK_CH]["rows"] == guess and d.files[ACK]["steps"] == _good()[ACK]["steps"]
    assert f"contradiction:{ACK_CH}#rows" in [p.key for p in d.pending]


@pytest.mark.parametrize("outside", ["a contradiction", "no question"])
def test_control_the_same_patch_outside_a_confirm_pends(outside):
    d, g = _acknowledge_guessed()
    guess = copy.deepcopy(d.files)
    gap = dataclasses.replace(g, kind="contradiction") if outside == "a contradiction" else None
    se.apply_patch(d, _the_stage_as_described(), 3, answering=gap)
    assert d.files[ACK]["steps"] == guess[ACK]["steps"] and d.files[ACK_CH]["rows"] == guess[ACK_CH]["rows"]
    assert {f"contradiction:{ACK}#steps", f"contradiction:{ACK_CH}#rows"} <= {p.key for p in d.pending}


def test_control_a_correction_of_one_step_may_not_change_another_in_the_whole_list():
    d, g = _confirm_draft()
    other, filed = copy.deepcopy(d.files[REC]["steps"])
    corrected = {**filed, "excludes": ["someone"]}
    se.apply_patch(d, {"set": [{"file": REC, "path": "steps", "value": [other, corrected]}]}, 3, answering=g)
    assert d.pending == [] and d.files[REC]["steps"] == [other, corrected]

    d, g = _confirm_draft()
    se.apply_patch(d, {"set": [{"file": REC, "path": "steps", "value": [{**other, "id": "x"}, corrected]}]}, 3, answering=g)
    assert f"contradiction:{REC}#steps" in [p.key for p in d.pending]
    d, g = _confirm_draft()
    se.apply_patch(d, {"set": [{"file": REC, "path": "steps", "value": [corrected]}]}, 3, answering=g)
    assert f"contradiction:{REC}#steps" in [p.key for p in d.pending]


def _kind_guessed():
    d = se.Draft(files=_good())
    for leaf in ((IR, "steps[id=engineering_disposition].task_kind"), (REASON_KIND, "accepts"),
                 (REASON_KIND, "reason_required")):
        d.set_at[leaf] = 0
    return d


NO_REASON = {"set": [{"file": REASON_KIND, "path": "reason_required", "value": []}]}


def test_a_task_kind_confirm_replaces_which_outcomes_need_a_reason_when_nobody_stated_it():
    d = _kind_guessed()
    g = next(x for x in se.confirms(d) if x.key == KIND_ENTRY)
    se.apply_patch(d, NO_REASON, 3, answering=g)
    assert d.pending == [] and d.files[REASON_KIND]["reason_required"] == []


def test_control_a_reason_the_person_was_asked_about_pends_at_a_task_kind_confirm():
    d = _kind_guessed()
    g = next(x for x in se.confirms(d) if x.key == KIND_ENTRY)
    d.answered[REASON_KEY] = 1
    se.apply_patch(d, NO_REASON, 3, answering=g)
    assert f"contradiction:{REASON_KIND}#reason_required" in [p.key for p in d.pending]


def test_control_a_reason_stated_for_another_step_of_that_kind_pends():
    d = _kind_guessed()
    kind = d.files[REASON_KIND]["kind"]
    step = next(s for s in d.files[PROGRAM]["steps"] if s["id"] == "program_approval")
    step["task_kind"] = kind
    g = next(x for x in se.confirms(d) if x.key == KIND_ENTRY)
    d.answered["approvals.pcn_program_approval.program_approval.reason_required"] = 1
    se.apply_patch(d, NO_REASON, 3, answering=g)
    assert f"contradiction:{REASON_KIND}#reason_required" in [p.key for p in d.pending]


def test_a_kind_with_no_answers_yet_is_asked_for_them_not_whether_a_stage_can_end_a_way():
    f = _good()
    f[ACK_KIND]["accepts"] = []
    assert not [g.key for g in se.problems(f) if g.key.startswith(f"contradiction:chaining.{CHAIN_NAME}.")]
    assert "contradiction:task_kind.pcn_acknowledgement" in _keys(f)


def test_control_a_kind_that_has_answers_and_lost_one_is_still_a_contradiction():
    f = _good()
    f[ACK_KIND]["accepts"] = ["escalated"]
    gap = _gap_of(f, f"contradiction:chaining.{CHAIN_NAME}.acknowledged")
    assert "answers are escalated" in gap.question


# ── a structural error the person can't answer goes back to the model (architect, 2026-11-02) ─

def _table_not_yet_drafted(file, **changes):
    f = _good()
    doc = f.pop(file)
    doc.update(changes)
    return se.Draft(files=f), {"set": [{"file": file, "path": "", "value": doc}]}


STRUCTURE_CASES = [
    (CH, {"terminals": ["pcn_rejected", "pcn_acknowledge"]}, "pcn_acknowledge, which is also a stage"),
    (SEL, {"after": "pcn_received"}, "a selection table has no `after`"),
]


@pytest.mark.parametrize("file,changes,cause", STRUCTURE_CASES)
def test_a_structural_error_is_refused_naming_its_cause_and_the_draft_keeps_what_it_had(file, changes, cause):
    draft, patch = _table_not_yet_drafted(file, **changes)
    before = copy.deepcopy(draft.files)
    charged, log = [], []
    se._apply_or_charge(draft, lambda *_: patch, {"says": "x"}, None, 1, charged, log)
    assert draft.files == before
    assert len(charged) == 1 + se.PATCH_RESTATES and cause in charged[0]["error"] and cause in log[0]["refused"]


@pytest.mark.parametrize("file,changes,cause", STRUCTURE_CASES)
def test_the_restatement_of_a_structural_error_lands(file, changes, cause):
    draft, wrong = _table_not_yet_drafted(file, **changes)
    right = {"set": [{"file": file, "path": "", "value": _good()[file]}]}
    asked = []

    def model(entry, *_):
        asked.append(entry)
        return right if entry.get("refused") else wrong
    charged = []
    se._apply_or_charge(draft, model, {"says": "x"}, None, 1, charged)
    assert cause in asked[1]["refused"] and len(charged) == 1
    assert draft.pending == [] and draft.files[file] == _good()[file]


def test_a_stage_that_an_old_terminal_names_may_rewrite_that_terminal_in_the_restatement():
    good = _good()
    f = _good()
    stage = f.pop(ACK)
    f[CH]["terminals"] = list(f[CH]["terminals"]) + ["pcn_acknowledge"]
    d = se.Draft(files=f)
    d.set_at[(CH, "terminals")] = 1
    d.answered["approvals.pcn_impact_review.next"] = 1
    add = {"file": ACK, "path": "", "value": stage}

    def model(entry, *_):
        return ({"set": [add, {"file": CH, "path": "terminals", "value": good[CH]["terminals"]}]}
                if entry.get("refused") else {"set": [add]})
    charged = []
    se._apply_or_charge(d, model, {"says": "x"}, None, 2, charged)
    assert len(charged) == 1 and "also a stage" in charged[0]["error"]
    assert d.pending == [] and d.files == good


def test_control_an_error_the_draft_already_held_does_not_block_a_later_patch():
    f = _good()
    kind = f.pop(ACK_KIND)
    f[CH]["terminals"] = list(f[CH]["terminals"]) + ["pcn_acknowledge"]
    d = se.Draft(files=f)
    assert se._structure_errors(d.files)
    charged = []
    se._apply_or_charge(d, lambda *_: {"set": [{"file": ACK_KIND, "path": "", "value": kind}]},
                        {"says": "x"}, None, 2, charged)
    assert charged == [] and d.files[ACK_KIND]["accepts"] == kind["accepts"]


def test_a_stage_the_trigger_lists_counts_before_its_definition_is_drafted():
    f = _good()
    del f[ACK]
    f[TRIG]["stages"] = STAGES
    f[CH]["terminals"] = ["pcn_acknowledge"]
    assert [c for c in se._structure_errors(f) if "pcn_acknowledge, which is also a stage" in c]


@pytest.mark.parametrize("name", NAMES)
def test_no_expected_bundle_holds_a_structural_error(name):
    f = _expected(name)
    trig = next(k for k in f if k.startswith("triggers/"))
    f[trig]["stages"] = sorted(se._workflows(f))
    assert se._structure_errors(f) == {}


def test_the_grammar_says_both():
    assert "a stage is named by a row's `then` and never listed in `terminals`" in se._GRAMMAR
    assert "A selection table has no `after`" in se._GRAMMAR


def test_a_run_restates_a_table_that_lists_a_stage_as_a_terminal_and_finishes():
    def once_wrong(entry, draft, gap):
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == PROGRAM_NEXT and not entry.get("refused"):
            patch = copy.deepcopy(patch)
            for fact in patch["set"]:
                if fact["file"] == PROGRAM_CH:
                    fact["value"]["terminals"].append("pcn_record")
        return patch
    r = se.run(_transcript("pcn_review"), once_wrong)
    assert len(r["model_errors"]) == 1 and "pcn_record, which is also a stage" in r["model_errors"][0]["error"]
    assert r["status"] == "runnable" and r["files"] == _expected("pcn_review")


# ── the scripted user answers a contradiction the loop raised (architect, 2026-11-02) ─────────

def _raised(key, *revises):
    return se.Gap(key, "approvals", "contradiction", "Which holds?", revises=tuple(revises))


def _bank_says(key):
    return _transcript("pcn_review")["answers"][key]["says"]


@pytest.mark.parametrize("key", [f"contradiction:{ACK_KIND}#accepts", "contradiction:task_kind.pcn_acknowledgement"])
def test_the_scripted_user_answers_a_contradiction_the_loop_raised_in_words_only(key):
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=_good())) == {"says": "It is acknowledged, escalated."}
    assert u.answered_contradictions == [key] and u.unbanked == []


@pytest.mark.parametrize("key", [f"contradiction:{ACK}#steps", "contradiction:workflow.pcn_acknowledge"])
def test_the_scripted_user_says_a_contradiction_about_steps_as_the_person_described_them(key):
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=_good())) == {"says": _bank_says("steps.pcn_acknowledge")}
    assert u.answered_contradictions == [key]


@pytest.mark.parametrize("key", [f"contradiction:{ACK_CH}#rows", f"contradiction:chaining.{CHAIN_NAME}"])
def test_the_scripted_user_says_a_routing_contradiction_as_the_person_described_it(key):
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=_good())) == {"says": _bank_says("approvals.pcn_acknowledge.next")}
    assert u.answered_contradictions == [key]


def test_the_scripted_user_says_none_for_an_empty_value():
    exp = _expected("pcn_review")
    exp[ACK_KIND]["reason_required"] = []
    u = sm.AligningUser(_transcript("pcn_review"), exp)
    key = f"contradiction:{ACK_KIND}#reason_required"
    assert u(_raised(key), se.Draft(files=exp)) == {"says": "It is none."}


@pytest.mark.parametrize("key", [
    f"contradiction:{ACK_KIND}#no_such_field",  # the expected bundle holds no value
    f"contradiction:{SEL}#rows",  # a structure no entry describes
    "contradiction:trigger.pcn_received.requires",  # a form with no one value
])
def test_control_a_contradiction_with_nothing_to_say_stays_unanswered(key):
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=_good())) is None
    assert u.answered_contradictions == [] and u.unbanked == [key]


def test_control_a_planted_contradiction_comes_from_the_bank():
    tr = _transcript("pcn_review")
    u = _pcn_user(tr)
    assert u(_raised(PLANTED), se.Draft(files=_good())) == tr["answers"][PLANTED]
    assert u.answered_contradictions == []


def test_control_an_outcome_the_table_does_not_route_is_never_answered_yes():
    files = _with_stray_row("timed_out")
    key = f"contradiction:chaining.{CHAIN_NAME}.timed_out"
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=files)) is None  # no `rows` to revise, so no denial either
    assert u.denied_rows == [] and u.answered_contradictions == []


# ── the bar: each stage has the steps the person described (architect, 2026-11-02) ────────────

SAME = {w: w for w in STAGES}


def test_a_runnable_spec_that_drops_a_step_has_dropped_it():
    assert sm.dropped_steps(_record_only_emits("filed"), _good(), SAME) == [
        {"stage": "pcn_record", "draft": "pcn_record", "described": ["emit", "signal_await"], "drafted": ["emit"]}]


def test_control_a_step_the_draft_added_is_not_a_dropped_one():
    f = _good()
    f[IR]["steps"] = [{"kind": "emit", "id": "extra"}] + f[IR]["steps"]
    assert sm.dropped_steps(f, _good(), SAME) == []


def test_steps_out_of_order_are_not_the_steps_described():
    f = _good()
    f[REC]["steps"] = list(reversed(f[REC]["steps"]))
    assert [x["stage"] for x in sm.dropped_steps(f, _good(), SAME)] == ["pcn_record"]


def test_a_stage_nothing_pairs_with_has_dropped_its_steps():
    out = sm.dropped_steps(_good(), _good(), {w: w for w in STAGES if w != "pcn_acknowledge"})
    assert out == [{"stage": "pcn_acknowledge", "draft": None, "described": ["human_await"], "drafted": []}]


@pytest.mark.parametrize("name", NAMES)
def test_the_oracle_meets_the_bar_on_every_fixture(name):
    row = sm.measure(name, se.OracleExtractor(), aligned=True)
    assert row["bar_met"] is True and row["dropped_steps"] == [] and row["answered_contradictions"] == []
    assert row["dropped_routes"] == []


@pytest.mark.parametrize("edit", ["drop", "route", "unreachable", "cannot_run"])
def test_the_bar_needs_all_four(monkeypatch, edit):
    real = se.run

    def result(*a, **k):
        r = real(*a, **k)
        if edit == "drop":
            r["files"] = _record_only_emits("filed")
        elif edit == "route":
            r["files"] = copy.deepcopy(r["files"])
            r["files"][ACK_CH]["rows"] = [{**x, "then": "elsewhere"} if x["when"]["outcome"] == "escalated" else x
                                          for x in r["files"][ACK_CH]["rows"]]
        elif edit == "unreachable":
            r["files"] = {**r["files"], "workflows/orphan.yaml": {"id": "orphan", "steps": []}}
        else:
            r["status"] = "cannot_run"
        return r
    monkeypatch.setattr(sm.se, "run", result)
    row = sm.measure("pcn_review", se.OracleExtractor())
    assert row["bar_met"] is False
    assert bool(row["dropped_steps"]) is (edit == "drop") and bool(row["unreachable"]) is (edit == "unreachable")
    assert bool(row["dropped_routes"]) is (edit == "route")


# ── an ending the person names keeps their word (architect, 2026-11-03) ───────────────────────

def test_the_grammar_says_endings_named_apart_stay_apart():
    line = next((x for x in se._GRAMMAR.split("\n- ") if x.startswith("An ending the user names")), None)
    assert line is not None
    said = " ".join(line.split())
    for word in ("keeps the user's word", "name differently", "two terminals", "never one word of your own"):
        assert word in said


def test_the_grammar_says_two_acts_in_a_row_are_two_steps():
    line = next((x for x in se._GRAMMAR.split("\n- ") if x.startswith("Two acts the user describes")), None)
    assert line is not None
    said = " ".join(line.split())
    for word in ("two steps of one stage", "in the same statement", "never draft the first act alone",
                 "an emit followed by a signal_await", "not a human_await", "the emit has no disposes",
                 "the user's word for what was done"):
        assert word in said


# ── a render step is what someone looks at before an approval (architect, 2026-11-02) ─────────

def test_the_grammar_says_what_someone_looks_at_before_an_approval_is_a_render_step():
    line = next(x for x in se._GRAMMAR.split("\n- ") if x.startswith("When the user says someone looks at"))
    for word in ("looks at", "reviews", "sees", "named fields", "before an approval", "render step",
                 "template", "{trigger.<field>}"):
        assert word in " ".join(line.split())


def test_the_render_form_the_grammar_names_is_the_one_the_fixture_runs():
    render = next(s for s in _good()[IR]["steps"] if s["kind"] == "render")
    assert set(render) == {"kind", "id", "template"}
    assert all(v.startswith("{trigger.") for v in render["template"].values())
    assert se.runnable(_good()) == []


def test_the_loop_inserts_no_render_step_a_draft_without_one_has_dropped_it():
    f = _good()
    f[IR]["steps"] = [s for s in f[IR]["steps"] if s["kind"] != "render"]
    assert se.runnable(f) == [] and not any(g.key.startswith("steps.pcn_impact_review") for g in se.problems(f))
    out = sm.dropped_steps(f, _good(), {w: w for w in STAGES})
    assert [x["stage"] for x in out] == ["pcn_impact_review"]


# ── a person says no when sending does not settle the stage (architect, 2026-11-02) ───────────

ENDS = "outputs.pcn_record.ends"


def _ends_gap(files):
    d = se.Draft(files=files)
    d.set_at[(REC, "steps[id=disposition].disposes")] = 0
    return d, next(g for g in se.confirms(d) if g.key == ENDS)


def test_the_scripted_user_rejects_ends_when_the_expected_emit_has_no_disposes():
    d, g = _ends_gap(_record_only_emits("filed"))
    u = _pcn_user()
    entry = u(g, d)
    assert entry["says"] == f"{NO} {_bank_says('steps.pcn_record')}"
    assert entry["facts"] == {"unset": [{"file": REC, "path": "steps[id=disposition].disposes"}]}
    assert entry["corrects"] == ENDS and u.rejected == [ENDS] and u.answered_by_path == []


def test_rejecting_ends_is_shown_to_the_model_as_a_correction_and_applies():
    d, g = _ends_gap(_record_only_emits("filed"))
    entry = _pcn_user()(g, d)
    assert "CORRECTION" in se.ModelExtractor("http://model.example", "m")._user_message(entry, d, g)
    se.apply_patch(d, entry["facts"], 3, answering=g)
    assert "disposes" not in d.files[REC]["steps"][0] and d.pending == []
    assert ENDS in _keys(d.files)  # nothing settles the stage now: the loop asks what does


def test_control_an_expected_emit_that_disposes_is_never_denied():
    exp = _expected("pcn_review")
    exp[REC]["steps"] = [s for s in exp[REC]["steps"] if s["kind"] == "emit"]
    exp[REC]["steps"][0]["disposes"] = "filed"
    d, g = _ends_gap(copy.deepcopy(exp))
    u = sm.AligningUser(_transcript("pcn_review"), exp)
    assert u._settled_by_sending(g, d.files, ENDS) is None
    assert u.rejected == []


def test_control_an_emit_with_no_expected_emit_to_pair_with_is_not_rejected():
    d, g = _ends_gap(_record_only_emits("filed"))
    exp = _expected("pcn_review")
    emit = next(s for s in exp[REC]["steps"] if s["kind"] == "emit")
    emit["kind"] = "not_an_emit"
    u = sm.AligningUser(_transcript("pcn_review"), exp)
    assert u._settled_by_sending(g, d.files, ENDS) is None and u.rejected == []


def test_control_only_a_confirm_of_ends_is_rejected():
    d, g = _ends_gap(_record_only_emits("filed"))
    u = _pcn_user()
    assert u._settled_by_sending(dataclasses.replace(g, kind="missing"), d.files, ENDS) is None
    assert u._settled_by_sending(g, d.files, "outputs.pcn_record.next") is None
    assert u.rejected == []


def test_a_whole_run_loses_the_guessed_disposes_and_keeps_the_filing_step():
    t = _transcript("pcn_review")
    u = sm.AligningUser(t, _expected("pcn_review"))
    r = se.run(t, _sends_and_guesses, answer=u)
    assert ENDS in u.rejected and r["files"] == _expected("pcn_review") and r["status"] == "runnable"


# ── an unstated empty requires is confirmed once (architect, 2026-11-02) ──────────────────────

REQUIRES = "trigger.requires"


def _requires_guessed(value):
    f = _good()
    f[TRIG]["requires"] = value
    d = se.Draft(files=f)
    d.set_at[(TRIG, "requires")] = 0
    return d


def test_an_unstated_empty_requires_is_confirmed():
    g = next(x for x in se.confirms(_requires_guessed([])) if x.key == REQUIRES)
    assert g.kind == "confirm" and g.revises == ((TRIG, "requires"),) and g.rewrites == ((TRIG, "requires"),)
    assert "never asked" in g.question


def test_an_answer_to_the_empty_requires_replaces_it_with_nothing_to_contradict():
    d = _requires_guessed([])
    g = next(x for x in se.confirms(d) if x.key == REQUIRES)
    se.apply_patch(d, {"set": [{"file": TRIG, "path": "requires", "value": ["kind"]}]}, 3, answering=g)
    assert d.files[TRIG]["requires"] == ["kind"] and d.pending == []


def test_the_empty_requires_is_asked_once():
    d = _requires_guessed([])
    assert REQUIRES in [g.key for g in se.gaps(d)]
    d.asked[REQUIRES] += 1
    assert REQUIRES not in [g.key for g in se.gaps(d)]


def test_control_a_requires_with_values_or_one_the_person_answered_is_not_confirmed():
    assert REQUIRES not in [g.key for g in se.confirms(_requires_guessed(["kind"]))]
    d = _requires_guessed([])
    d.answered[REQUIRES] = 1
    assert REQUIRES not in [g.key for g in se.confirms(d)]


def test_an_unanswered_empty_requires_is_left_open_never_deferred():
    assert se.non_deferrable(_requires_guessed([]), REQUIRES) is not None


# ── a deferral whose slot no longer exists is dropped and recorded (architect, 2026-11-02) ────

FILED_DEADLINE = "approvals.pcn_record.file.deadline"
STALE = "approvals.pcn_impact_review.gone.deadline"


def _record_with(step):
    f = _good()
    f[REC]["steps"] = [s for s in f[REC]["steps"] if s["kind"] == "emit"] + [step]
    return f


@pytest.mark.parametrize("key,exists", [
    (DEADLINE_KEY, True),
    ("approvals.pcn_impact_review.gone.deadline", False),  # the step went
    ("approvals.gone.engineering_disposition.deadline", False),  # the definition went
    ("actors.pcn_impact_review.gone.excludes", False),
    (PLANTED, True),
    (f"contradiction:{IR}#steps[id=gone].excludes", False),  # the leaf went
    ("contradiction:workflows/gone.yaml#steps", False),
    (f"contradiction:{IR}#steps[", True),  # a string nothing parses names nothing
    ("approvals.pcn_impact_review.next", True),
    ("approvals.gone.next", False),
    ("approvals.gone.next.approved", False),
    ("outputs.gone.ends", False),
    ("approvals.pcn_acknowledgement.accepts", True),
    ("approvals.gone.accepts", False),
    ("outputs.record", True),  # no definition in the key: nothing the draft could have lost
    (REQUIRES, True),
    ("timed_out", True),
])
def test_a_slot_exists_while_the_draft_holds_what_its_key_names(key, exists):
    assert se._slot_exists(_good(), key) is exists


def test_a_deferred_deadline_on_a_step_now_another_kind_is_dropped_and_recorded():
    d = se.Draft(files=_record_with({"kind": "signal_await", "id": "file", "signal": "s", "audience": "a"}))
    d.deferrals[FILED_DEADLINE] = "not agreed"
    se._drop_stale_deferrals(d, 7)
    assert d.deferrals == {}
    assert d.dropped_deferrals == [{"key": FILED_DEADLINE, "reason": "not agreed", "turn": 7}]


def test_control_a_deferred_deadline_on_a_step_still_there_stands():
    d = se.Draft(files=_record_with({"kind": "human_await", "id": "file", "task_kind": "k"}))
    d.deferrals[FILED_DEADLINE] = "not agreed"
    se._drop_stale_deferrals(d, 7)
    assert d.deferrals == {FILED_DEADLINE: "not agreed"} and d.dropped_deferrals == []


def _defers_a_slot_of_no_step():
    """An oracle whose first answer also defers a deadline on a step the draft does not have, as run
    40's did once its confirm had replaced that step."""
    state = {"seeded": False}

    def extractor(entry, draft, gap):
        patch = copy.deepcopy(se.OracleExtractor()(entry, draft, gap) or {})
        if gap is not None and not state["seeded"]:
            state["seeded"] = True
            patch["defer"] = list(patch.get("defer") or []) + [{"gap": STALE, "reason": "later"}]
        return patch
    return extractor


def test_the_run_drops_a_stale_deferral_and_carries_the_drop():
    r = se.run(_transcript("pcn_review"), _defers_a_slot_of_no_step())
    assert [(x["key"], x["reason"]) for x in r["dropped_deferrals"]] == [(STALE, "later")]
    assert STALE not in r["deferrals"]
    assert 0 < r["dropped_deferrals"][0]["turn"] < r["turns"]  # at the next turn, not only at the end


def test_the_last_turn_can_leave_a_stale_deferral_and_it_is_still_dropped():
    t = {"opening": {"says": "x", "facts": {"defer": [{"gap": "approvals.gone.x.deadline", "reason": "later"}]}},
         "answers": {}}
    r = se.run(t, se.OracleExtractor(), max_turns=0)
    assert r["deferrals"] == {} and [x["key"] for x in r["dropped_deferrals"]] == ["approvals.gone.x.deadline"]


def test_the_measure_records_the_drop():
    row = sm.measure("pcn_review", _defers_a_slot_of_no_step(), aligned=True)
    assert [x["key"] for x in row["dropped_deferrals"]] == [STALE]


def test_control_the_planted_deferrals_are_not_dropped_on_a_clean_run():
    for name in NAMES:
        row = sm.measure(name, se.OracleExtractor(), aligned=True)
        assert row["dropped_deferrals"] == [] and row["deferrals_recorded"] == row["deferrals_planted"]


# ── "can it end?" vouches only for what it asks: the false "earlier you said" of runs 39, 40 ──

STRAY = "contradiction:chaining.pcn_impact_review_chaining.stray"


def _guessed_at_the_opening(answer_by_key):
    """A run replaying runs 39 and 40: the opening drafts the whole bundle, guessing the reasons as
    [] and a row for an outcome the stage lacks, so nothing has been asked when the contradiction
    is answered, and the kind's confirm comes next."""
    files = _expected("pcn_review")
    files[REASON_KIND]["reason_required"] = []
    files[CH]["domain"]["outcome"] = list(files[CH]["domain"]["outcome"]) + ["stray"]
    files[CH]["rows"] = list(files[CH]["rows"]) + [{"when": {"outcome": "stray"}, "then": files[CH]["rows"][0]["then"]}]
    files[TRIG]["stages"] = list(STAGES)
    t = {"opening": {"says": "x", "facts": {"set": [{"file": f, "path": "", "value": v} for f, v in files.items()]}},
         "answers": {}}

    def answer(g, d):
        return answer_by_key.get(g.key) or {"says": "Yes."}
    return se.run(t, se.OracleExtractor(), answer=answer)


def _no_stray():
    good = _good()
    return {"says": "No.", "facts": {"set": [
        {"file": CH, "path": "domain.outcome", "value": good[CH]["domain"]["outcome"]},
        {"file": CH, "path": "rows", "value": good[CH]["rows"]}]}}


REASONS_NOW = {"says": "They do.", "facts": {"set": [{"file": REASON_KIND, "path": "reason_required",
                                                      "value": _expected("pcn_review")[REASON_KIND]["reason_required"]}]}}


def test_answering_can_it_end_leaves_the_guessed_reasons_a_guess():
    r = _guessed_at_the_opening({STRAY: _no_stray(), KIND_ENTRY: REASONS_NOW})
    keys = [q["key"] for q in r["questions"]]
    assert keys.index(STRAY) < keys.index(KIND_ENTRY)  # the order of runs 39 and 40
    assert f"contradiction:{REASON_KIND}#reason_required" not in r["contradictions_asked"]
    assert r["files"][REASON_KIND]["reason_required"] == _expected("pcn_review")[REASON_KIND]["reason_required"]


def test_can_it_end_asks_the_row_and_the_answers_and_may_still_revise_the_reasons():
    g = _gap_of(_with_stray_row("stray"), f"contradiction:chaining.{CHAIN_NAME}.stray")
    assert set(g.asks) == {(CHAIN, "domain.outcome"), (CHAIN, "rows"), (ACK_KIND, "accepts")}
    assert {(ACK_KIND, "reason_required"), (CHAIN, "terminals")} <= set(g.revises)


def test_control_what_can_it_end_asked_is_vouched():
    r_keys = []

    def answer(g, d):
        r_keys.append((g.key, dict(d.vouched)))
        return {STRAY: _no_stray()}.get(g.key) or {"says": "Yes."}
    files = _expected("pcn_review")
    files[CH]["domain"]["outcome"] = list(files[CH]["domain"]["outcome"]) + ["stray"]
    files[CH]["rows"] = list(files[CH]["rows"]) + [{"when": {"outcome": "stray"}, "then": files[CH]["rows"][0]["then"]}]
    files[TRIG]["stages"] = list(STAGES)
    t = {"opening": {"says": "x", "facts": {"set": [{"file": f, "path": "", "value": v} for f, v in files.items()]}},
         "answers": {}}
    se.run(t, se.OracleExtractor(), answer=answer)
    after = next(v for k, v in r_keys[r_keys.index(next(x for x in r_keys if x[0] == STRAY)) + 1:])
    assert (CH, "rows") in after and (REASON_KIND, "accepts") in after
    assert (REASON_KIND, "reason_required") not in after


def test_can_it_end_after_a_signal_asks_the_signal_s_answers_and_not_its_reasons():
    files = _expected("pcn_review")
    table = files[REC_CH]
    table["domain"]["outcome"] = list(table["domain"]["outcome"]) + ["stray"]
    table["rows"] = list(table["rows"]) + [{"when": {"outcome": "stray"}, "then": table["rows"][0]["then"]}]
    g = _gap_of(files, "contradiction:chaining.pcn_record_chaining.stray")
    assert set(g.asks) == {(REC_CH, "domain.outcome"), (REC_CH, "rows"), (REC, "steps[id=filed].accepts")}
    assert (REC, "steps[id=filed].reason_required") in g.revises


def _vouched_by(g, before, after):
    d = se.Draft(files=after)
    se._vouch(d, g, before, 5)
    return d.vouched


def test_a_reason_the_answer_wrote_is_vouched_and_one_it_left_is_not():
    """The training fixture's answer says "they must say why", and writes the reasons: the person
    spoke of them. Runs 39 and 40 left them: nobody did."""
    good = _good()
    g = se.Gap("k", "approvals", "contradiction", "q", revises=((REASON_KIND, "reason_required"), (CH, "rows")),
               asks=((CH, "rows"),))
    left = _vouched_by(g, good, copy.deepcopy(good))
    assert left == {(CH, "rows"): 5}
    wrote = copy.deepcopy(good)
    wrote[REASON_KIND]["reason_required"] = ["something_new"]
    assert _vouched_by(g, good, wrote) == {(CH, "rows"): 5, (REASON_KIND, "reason_required"): 5}


def test_control_a_gap_with_no_asks_vouches_everything_it_revises():
    g = se.Gap("k", "approvals", "contradiction", "q", revises=((CH, "rows"), (REASON_KIND, "reason_required")))
    assert set(_vouched_by(g, _good(), _good())) == {(CH, "rows"), (REASON_KIND, "reason_required")}


def test_control_a_missing_gap_vouches_nothing():
    g = se.Gap("k", "approvals", "missing", "q", revises=((CH, "rows"),))
    assert _vouched_by(g, _good(), _good()) == {}


# ── the scripted user says what the draft calls it: run 39's terminals ────────────────────────

def _named_as_the_model_named_them():
    """Run 39: the stage's rows name its own terminals, and the expected bundle names others."""
    f = _good()
    for r in f[PROGRAM_CH]["rows"]:
        if r["then"] in f[PROGRAM_CH]["terminals"]:
            r["then"] = "my_" + r["then"]
    f[PROGRAM_CH]["terminals"] = ["completed"]
    return f


def test_the_scripted_user_answers_terminals_in_the_draft_s_names():
    f = _named_as_the_model_named_them()
    key = f"contradiction:{PROGRAM_CH}#terminals"
    expected = _expected("pcn_review")[PROGRAM_CH]["terminals"]
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=f)) == {"says": "It is " + ", ".join("my_" + x for x in expected) + "."}
    assert u.answered_contradictions == [key]


def test_control_a_terminal_no_row_of_the_draft_reaches_stays_unanswered():
    f = _named_as_the_model_named_them()
    terminal = _expected("pcn_review")[PROGRAM_CH]["terminals"][0]
    f[PROGRAM_CH]["rows"] = [r for r in f[PROGRAM_CH]["rows"] if r["then"] != "my_" + terminal]
    key = f"contradiction:{PROGRAM_CH}#terminals"
    u = _pcn_user()
    assert u(_raised(key), se.Draft(files=f)) is None
    assert u.answered_contradictions == [] and key in u.unbanked


def test_a_stage_or_task_kind_is_said_in_the_draft_s_name_and_a_verb_stays_literal():
    u = _pcn_user()
    f = _rename(_good(), {"pcn_acknowledge": "ack"})
    assert u._in_draft_names(["pcn_acknowledge", "approved"], f, PROGRAM_CH) == ["ack", "approved"]
    assert u._in_draft_names("pcn_acknowledge", f, PROGRAM_CH) == "ack"
    assert u._in_draft_names("approved", f, PROGRAM_CH) == "approved"


def test_two_terminals_the_draft_names_alike_are_said_once():
    f = _good()
    for r in f[PROGRAM_CH]["rows"]:
        if r["then"] in f[PROGRAM_CH]["terminals"]:
            r["then"] = "over"
    u = _pcn_user()
    assert u._in_draft_names(_expected("pcn_review")[PROGRAM_CH]["terminals"], f, PROGRAM_CH) == ["over"]


def test_control_nothing_is_said_of_an_empty_value_but_that_it_is_none():
    f = _good()
    f[PROGRAM_CH]["terminals"] = []
    exp = _expected("pcn_review")
    exp[PROGRAM_CH]["terminals"] = []
    key = f"contradiction:{PROGRAM_CH}#terminals"
    assert sm.AligningUser(_transcript("pcn_review"), exp)(_raised(key), se.Draft(files=f)) == {"says": "It is none."}


def test_a_terminal_is_said_as_the_table_asked_about_names_it():
    f = _named_as_the_model_named_them()
    terminal = _expected("pcn_review")[PROGRAM_CH]["terminals"][0]
    u = _pcn_user()
    assert u._in_draft_names(terminal, f, PROGRAM_CH) == "my_" + terminal
    assert u._in_draft_names(terminal, f, CH) != "my_" + terminal


# ── a value the person rejected is a constraint on the next patch (architect, 2026-11-03) ─────

SENT = _record_only_emits()[REC]["steps"][0]["id"]
DISPOSES = f"steps[id={SENT}].disposes"


def _writes_back(value, then=None):
    """Says "filed" on the send, unsets it at the confirm, writes ``value`` back at the ``missing``
    gap on the same key, and answers a refusal with ``then``, or with the same patch again."""
    def ex(entry, draft, gap):
        if gap is None:
            return {"set": [{"file": f, "path": "", "value": v} for f, v in _record_only_emits("filed").items()]}
        if gap.key != ENDS:
            return {}
        if gap.kind == "confirm":
            return {"unset": [{"file": REC, "path": DISPOSES}]}
        if entry.get("refused") and then is not None:
            return then
        return {"set": [{"file": REC, "path": DISPOSES, "value": value}]}
    return ex


def _run_rejected(ex):
    return se.run({"opening": {"says": "x"}}, ex, answer=lambda g, d: {"says": NO})


@pytest.mark.parametrize("value", ["filed", "something_else"])
def test_a_rejected_leaf_written_back_is_refused_whatever_its_value(value):
    # run 43 wrote back the value it was told no about, and run 42 a different one
    r = _run_rejected(_writes_back(value))
    assert [m["error"] for m in r["model_errors"]][:1] and "was rejected at turn" in r["model_errors"][0]["error"]
    assert not any("disposes" in s for s in r["files"][REC]["steps"])
    assert r["status"] == "cannot_run"


def test_the_refusal_names_the_gap_the_turn_and_the_forms_that_fill_it():
    r = _run_rejected(_writes_back("filed"))
    said = r["model_errors"][0]["error"]
    turn = next(q for q, m in enumerate(r["questions"], 1) if m["key"] == ENDS and m["kind"] == "confirm")
    assert f"disposes was rejected at turn {turn}" in said
    assert "pcn record still has no step that settles it" in said
    assert "signal_await or wait" in said


def test_the_forms_a_refusal_names_are_forms_that_settle_a_stage():
    assert set(se._SETTLES_AFTER_A_SEND) <= se._DISPOSING
    assert "human_await" not in se._SETTLES_AFTER_A_SEND


def test_a_patch_that_takes_the_named_form_lands_on_the_restatement():
    # the list of steps is one leaf: the restatement may rewrite it whole
    fixed = {"set": [{"file": REC, "path": "steps", "value": _good()[REC]["steps"]}]}
    r = _run_rejected(_writes_back("filed", then=fixed))
    assert len(r["model_errors"]) == 1
    assert r["files"][REC]["steps"] == _good()[REC]["steps"]
    assert ENDS not in r["gaps_left"]


def _after_the_no():
    draft = se.Draft(files=_record_only_emits())
    draft.rejected[(REC, DISPOSES)] = 7
    return draft


def _asked(*revises, kind="contradiction", asks=()):
    return se.Gap(key="k", facet="outputs", kind=kind, question="what now?", revises=tuple(revises), asks=tuple(asks))


def _with_disposes(sid=SENT):
    trial = copy.deepcopy(_after_the_no())
    trial.files[REC]["steps"][0].update(id=sid, disposes="filed")
    return trial


def test_a_renamed_step_does_not_carry_the_rejected_leaf_past_the_refusal():
    with pytest.raises(se.StructureError, match="was rejected at turn 7"):
        se._refuse_rejected(_after_the_no(), _with_disposes("renamed"), _asked())


def test_control_a_step_already_there_that_holds_the_same_key_is_not_a_restoration():
    draft = _after_the_no()
    draft.files[REC]["steps"].append({"kind": "emit", "id": "other", "disposes": "other"})
    se._refuse_rejected(draft, copy.deepcopy(draft), _asked())


def test_control_a_patch_that_leaves_the_leaf_alone_is_not_refused():
    draft = _after_the_no()
    trial = copy.deepcopy(draft)
    trial.files[REC]["note"] = "kept"
    se._refuse_rejected(draft, trial, _asked())


def test_a_turn_that_asks_the_leaf_may_state_it_again_and_that_ends_the_refusal():
    draft, trial = _after_the_no(), _with_disposes()
    g = _asked((REC, DISPOSES))
    se._refuse_rejected(draft, trial, g)
    se._note_rejected(trial, g, draft.files, 9)
    assert trial.rejected == {}
    se._refuse_rejected(trial, copy.deepcopy(trial), _asked())


def test_control_asked_and_left_unset_it_stays_rejected():
    draft = _after_the_no()
    se._note_rejected(draft, _asked((REC, DISPOSES)), _record_only_emits("filed"), 9)
    assert draft.rejected == {(REC, DISPOSES): 9}


@pytest.mark.parametrize("g", [
    _asked((REC, DISPOSES), kind="missing"),  # a `missing` gap on the same key asks how
    _asked((REC, DISPOSES), (REC, "other"), asks=((REC, "other"),)),  # may revise it, and asks another
    _asked((REC, "other")),
    None,
])
def test_a_turn_that_does_not_ask_the_leaf_does_not_lift_the_refusal(g):
    with pytest.raises(se.StructureError):
        se._refuse_rejected(_after_the_no(), _with_disposes(), g)


def test_control_only_what_the_answer_took_out_is_rejected():
    files = _record_only_emits("filed")
    draft = se.Draft(files=copy.deepcopy(files))
    se._note_rejected(draft, _asked((REC, DISPOSES), kind="confirm"), files, 3)
    assert draft.rejected == {}


def test_control_what_a_missing_gap_took_out_is_not_a_rejection():
    draft = se.Draft(files=_record_only_emits())
    se._note_rejected(draft, _asked((REC, DISPOSES), kind="missing"), _record_only_emits("filed"), 3)
    assert draft.rejected == {}


def test_a_leaf_that_settles_nothing_is_refused_with_the_question_still_open():
    draft = se.Draft(files=_good())
    draft.rejected[(REC, "note")] = 4
    trial = copy.deepcopy(draft)
    trial.files[REC]["note"] = "back"
    with pytest.raises(se.StructureError) as e:
        se._refuse_rejected(draft, trial, se.Gap(key="k", facet="outputs", kind="missing", question="what now?"))
    assert "note was rejected at turn 4" in str(e.value) and "still needed: what now?" in str(e.value)
    assert "signal_await" not in str(e.value)


def test_a_refusal_names_the_draft_s_own_stage():
    draft = se.Draft(files={"workflows/q.yaml": {"id": "some_stage", "steps": []}})
    draft.rejected[("workflows/q.yaml", "steps[id=a].disposes")] = 2
    trial = copy.deepcopy(draft)
    trial.files["workflows/q.yaml"]["steps"] = [{"kind": "emit", "id": "a", "disposes": "x"}]
    with pytest.raises(se.StructureError, match="some stage still has no step"):
        se._refuse_rejected(draft, trial, None)


# ── a refused path names the forms the loop accepts, and no new form (architect, 2026-11-03) ──

@pytest.mark.parametrize("path", ["steps[0].excludes", "rows[when.outcome=escalated].then"])
def test_a_refused_path_names_the_forms_and_stays_refused(path):
    with pytest.raises(se.PatchError) as e:
        se.parse_path(path)
    assert "steps[id=a].excludes" in str(e.value) and "set whole" in str(e.value)


# ── the walk pairs a table's rows by what they route to (architect, 2026-11-03, instrument v2) ──

def _verbs(files, table, **said):
    for r in files[table]["rows"]:
        r["when"]["outcome"] = said.get(r["when"]["outcome"], r["when"]["outcome"])
    return files


def _final(files):
    files[TRIG].pop("stages", None)  # the served draft has none, so the walk stands alone
    return files


def _pairs(files):
    return _pcn_user()._pair_definitions(sm._index(files), sm._index(_good()))


def _route(files, table, verb, then):
    t = files[table]
    next(r for r in t["rows"] if r["when"]["outcome"] == verb)["then"] = then
    t["terminals"] = sorted({r["then"] for r in t["rows"] if r["then"] not in STAGES})
    return files


def test_control_rows_that_spell_their_outcome_alike_pair_as_they_did():
    assert _pairs(_final(_good())) == SAME


def test_a_person_s_own_verb_does_not_lose_the_stage_behind_it():
    assert _pairs(_final(_verbs(_good(), PROGRAM_CH, approved="approve", rejected="reject"))) == SAME


def test_an_outcome_that_goes_on_never_pairs_with_one_that_ends():
    f = _final(_verbs(_good(), PROGRAM_CH, approved="approve"))
    _route(f, PROGRAM_CH, "approve", "somewhere_it_ends")
    assert "pcn_record" not in _pairs(f).values()


def test_two_outcomes_left_on_a_side_pair_nothing():
    f = _final(_verbs(_good(), CH, rejected="refuse", needs_info="ask"))
    assert sm._paired_rows(f[CH]["rows"], _good()[CH]["rows"], sm._index(f), sm._index(_good())) == [
        (f[CH]["rows"][0], _good()[CH]["rows"][0])]


def test_two_outcomes_that_go_on_pair_nothing():
    f = _final(_good())
    f[PROGRAM_CH]["rows"] = [{"when": {"outcome": "a"}, "then": "pcn_record"},
                             {"when": {"outcome": "b"}, "then": "pcn_record"}]
    assert "pcn_record" not in _pairs(f).values()


def test_a_selection_s_value_is_not_a_verb_and_stays_literal():
    f = _final(_good())
    next(r for r in f[SEL]["rows"] if r["then"] == "pcn_acknowledge")["when"] = {"change_class": "other"}
    assert "pcn_acknowledge" not in _pairs(f).values()


def test_a_terminal_a_person_names_pairs_by_the_row_that_reaches_it_whatever_its_verb():
    f = _final(_verbs(_good(), PROGRAM_CH, rejected="reject"))
    _route(f, PROGRAM_CH, "reject", "my_end")
    assert _pcn_user()._in_draft_names("pcn_rejected", f, PROGRAM_CH) == "my_end"


# ── the bar reads routing as well as steps (architect, 2026-11-03) ────────────────────────────

def _drafted(files, pairs=SAME):
    return sorted((x["table"], x["when"]["outcome"] if "outcome" in x["when"] else str(x["when"]))
                  for x in sm.dropped_routes(files, _good(), pairs))


def test_control_the_expected_bundle_routes_as_expected():
    assert _drafted(_good()) == []


def test_two_ends_of_a_table_on_one_end_of_the_draft_are_dropped_routes():
    f = _route(_route(_good(), CH, "rejected", "done"), CH, "needs_info", "done")
    assert _drafted(f) == [(CH[len("decisions/"):-len(".yaml")], "needs_info"),
                           (CH[len("decisions/"):-len(".yaml")], "rejected")]


def test_a_rejected_notice_that_ends_where_a_filed_one_ends_reads_on_both_rows():
    f = _route(_good(), PROGRAM_CH, "rejected", "pcn_dispositioned")
    assert _drafted(f) == [("pcn_program_approval_chaining", "rejected"), ("pcn_record_chaining", "filed")]


def test_control_an_end_s_name_is_the_model_s_own():
    f = _route(_route(_good(), CH, "rejected", "refused"), PROGRAM_CH, "rejected", "refused")
    assert _drafted(f) == []


def test_control_one_end_named_twice_loses_nothing_the_person_described():
    f = _route(_route(_good(), CH, "rejected", "refused_early"), PROGRAM_CH, "rejected", "refused_late")
    assert _drafted(f) == []


def test_an_outcome_that_goes_on_to_the_wrong_stage_is_a_dropped_route():
    assert _drafted(_route(_good(), ACK_CH, "escalated", "pcn_record")) == [("pcn_acknowledge_chaining", "escalated")]


def test_an_outcome_that_goes_on_and_now_ends_is_a_dropped_route():
    # run 42 lost the escalation this way
    assert _drafted(_route(_good(), ACK_CH, "escalated", "elsewhere")) == [("pcn_acknowledge_chaining", "escalated")]


def test_an_outcome_that_ends_and_now_goes_on_is_a_dropped_route():
    assert _drafted(_route(_good(), CH, "rejected", "pcn_record")) == [("pcn_impact_review_chaining", "rejected")]


def test_a_selection_that_routes_a_value_elsewhere_is_a_dropped_route():
    f = _good()
    for r in f[SEL]["rows"]:
        r["then"] = "pcn_acknowledge" if r["then"] == "pcn_impact_review" else "pcn_impact_review"
    assert [x[0] for x in _drafted(f)] == ["pcn_received_selection"] * 2


def test_a_stage_nothing_pairs_with_has_no_row_to_route_by():
    out = _drafted(_good(), {w: w for w in STAGES if w != "pcn_acknowledge"})
    assert out == [("pcn_acknowledge_chaining", "acknowledged"), ("pcn_acknowledge_chaining", "escalated"),
                   ("pcn_received_selection", str({"change_class": "minor"}))]


def test_control_a_row_the_draft_added_is_not_a_dropped_route():
    f = _good()
    f[PROGRAM_CH]["rows"].append({"when": {"outcome": "extra"}, "then": "pcn_rejected"})
    assert _drafted(f) == []


def test_every_step_present_and_every_end_on_one_name_is_not_the_workflow():
    # run 41's shape: the walk reaches each stage, and the bar still reads no for what it reaches
    f = _final(_verbs(_good(), PROGRAM_CH, approved="approve", rejected="reject"))
    for table, verb in ((CH, "rejected"), (CH, "needs_info"), (ACK_CH, "acknowledged"),
                        (PROGRAM_CH, "reject"), (REC_CH, "filed")):
        _route(f, table, verb, "completed")
    pairs = _pairs(f)
    assert pairs == SAME and sm.dropped_steps(f, _good(), pairs) == []
    assert len(sm.dropped_routes(f, _good(), pairs)) == 5


# ── a stated value is not rewritten, and the bar reads routes and slots apart (architect, 2026-11-03) ─

_TBL = "decisions/some_stage_chaining.yaml"
_OUT, _ROWS, _ACC = "domain.outcome", "rows", "steps[id=wait].accepts"
_WF = "workflows/some_stage.yaml"
_MISSING = se.Gap("next.other", "outputs", "missing", "When it ends 'other', what happens next?",
                  revises=((_TBL, _OUT), (_TBL, _ROWS), (_WF, _ACC)))
_CONFIRM = se.Gap("confirm.table", "outputs", "confirm", "Is that right?", revises=((_TBL, _OUT), (_TBL, _ROWS)))


def _row(v, then="done"):
    return {"when": {"outcome": v}, "then": then}


def _table(*values):
    return {_TBL: {"decision": "some_stage_chaining", "domain": {"outcome": list(values)},
                   "rows": [_row(v) for v in values], "terminals": ["done"]},
            _WF: {"id": "some_stage", "steps": [{"kind": "signal_await", "id": "wait", "accepts": ["other"]}]}}


def _stated(*values):
    draft = se.Draft(files=_table(*values))
    draft.stated[(_TBL, _OUT)] = (5, list(values))
    return draft


def _rewritten(*values):
    return se.Draft(files=_table(*values))


def test_a_stated_value_rewritten_at_a_missing_gap_is_refused_and_says_what_may_change():
    with pytest.raises(se.RewriteError) as e:
        se._refuse_rewrite(_stated("said"), _rewritten("other"), _MISSING)
    said = str(e.value)
    assert '["said"]' in said and "turn 5" in said and _MISSING.question in said
    assert se._describe(_WF, _ACC) in said and se._describe(_TBL, _OUT) in said


def test_the_refusal_is_a_model_error_and_not_a_structure_refusal():
    assert issubclass(se.RewriteError, se.PatchError) and not issubclass(se.RewriteError, se.StructureError)


@pytest.mark.parametrize("kind", ["confirm", "contradiction", "null"])
def test_control_a_turn_that_puts_the_leaf_to_the_person_may_rewrite_it(kind):
    g = se.Gap("k", "outputs", kind, "q", revises=((_TBL, _OUT),))
    se._refuse_rewrite(_stated("said"), _rewritten("other"), g)


def test_control_a_turn_that_puts_another_leaf_to_the_person_may_not():
    g = se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, _ROWS),))
    with pytest.raises(se.RewriteError):
        se._refuse_rewrite(_stated("said"), _rewritten("other"), g)


def test_a_confirm_may_rewrite_what_its_rewrite_scope_names():
    g = se.Gap("k", "outputs", "confirm", "q", rewrites=((_TBL, ""),))
    se._refuse_rewrite(_stated("said"), _rewritten("other"), g)


def test_control_adding_to_a_stated_leaf_takes_nothing_out():
    se._refuse_rewrite(_stated("said"), _rewritten("said", "other"), _MISSING)


def test_control_a_value_nobody_stated_may_be_replaced_at_a_missing_gap():
    se._refuse_rewrite(_rewritten("guess"), _rewritten("other"), _MISSING)


def test_control_a_structural_fix_the_refusal_named_may_rewrite():
    se._refuse_rewrite(_stated("said"), _rewritten("other"), _MISSING, fixing=((_TBL, "domain"),))


def test_taking_the_stated_leaf_away_is_a_rewrite():
    trial = _rewritten("said")
    del trial.files[_TBL]["domain"]["outcome"]
    with pytest.raises(se.RewriteError):
        se._refuse_rewrite(_stated("said"), trial, _MISSING)


def test_a_rewrite_by_a_whole_list_reads_on_the_leaf_inside_it():
    draft = se.Draft(files=_table("said"))
    draft.stated[(_WF, _ACC)] = (5, ["other"])
    trial = copy.deepcopy(draft)
    trial.files[_WF]["steps"] = [{"kind": "signal_await", "id": "wait", "accepts": ["changed"]}]
    with pytest.raises(se.RewriteError):
        se._refuse_rewrite(draft, trial, se.Gap("k", "outputs", "missing", "q", revises=((_WF, "steps"),)))


def test_a_rewrite_refusal_names_no_case():
    table = "decisions/any_name_chaining.yaml"
    draft = se.Draft(files={table: {"domain": {"outcome": ["said"]}}})
    draft.stated[(table, _OUT)] = (2, ["said"])
    trial = se.Draft(files={table: {"domain": {"outcome": ["other"]}}})
    g = se.Gap("k", "outputs", "missing", "what next?", revises=((table, _OUT),))
    with pytest.raises(se.RewriteError) as e:
        se._refuse_rewrite(draft, trial, g)
    assert not re.search(r"pcn|record|filed|notice", str(e.value), re.I)


def test_what_an_answer_wrote_at_a_confirm_is_stated_and_a_leaf_it_left_alone_is_not():
    g = se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, _OUT), (_TBL, _ROWS)), asks=((_TBL, _OUT),))
    draft = se.Draft(files=_table("said"))
    se._note_stated(draft, g, _table("said"), 7)
    assert draft.stated == {(_TBL, _OUT): (7, ["said"])}


def test_a_contradiction_over_one_value_states_what_it_wrote_and_not_the_rest_of_the_leaf():
    g = se.Gap("contradiction:chaining.some_stage_chaining.new", "outputs", "contradiction", "q",
               revises=((_TBL, _ROWS),), asks=((_TBL, _ROWS),))
    draft = se.Draft(files=_table("guess", "new"))
    se._note_stated(draft, g, _table("guess"), 7)
    assert draft.stated == {(_TBL, _ROWS): (7, [_row("new")])}
    se._refuse_rewrite(draft, _rewritten("other", "new"), _MISSING)


def test_control_an_overwrite_contradiction_states_the_whole_of_what_it_asks():
    g = se.Gap(f"contradiction:{_TBL}#{_OUT}", "outputs", "contradiction", "q", revises=((_TBL, _OUT),))
    draft = se.Draft(files=_table("kept", "other"))
    se._note_stated(draft, g, _table("kept", "other"), 7)
    assert draft.stated == {(_TBL, _OUT): (7, ["kept", "other"])}


def test_a_missing_gap_states_nothing():
    draft = se.Draft(files=_table("said"))
    se._note_stated(draft, _MISSING, {}, 7)
    assert draft.stated == {}


def test_a_value_the_answer_took_out_is_no_longer_stated():
    draft = _stated("said", "gone")
    draft.files = _table("said")
    se._note_stated(draft, se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, _OUT),)), _table("said", "gone"), 7)
    assert draft.stated == {(_TBL, _OUT): (7, ["said"])}


def test_a_stated_dict_reads_one_leaf_at_a_time_so_growing_it_is_not_a_rewrite():
    g = se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, "domain"),))
    draft = se.Draft(files=_table("said"))
    se._note_stated(draft, g, _table("said"), 7)
    assert draft.stated == {(_TBL, _OUT): (7, ["said"])}
    se._refuse_rewrite(draft, _rewritten("said", "other"), _MISSING)
    with pytest.raises(se.RewriteError):
        se._refuse_rewrite(draft, _rewritten("other"), _MISSING)


def test_an_empty_dict_states_nothing_so_filling_it_is_not_a_rewrite():
    empty = _table("said")
    empty[_TBL]["domain"] = {}
    g = se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, "domain"),))
    draft = se.Draft(files=empty)
    se._note_stated(draft, g, copy.deepcopy(empty), 7)
    assert draft.stated == {}


def test_a_value_changed_on_a_turn_that_put_it_to_the_person_is_not_held_against_a_later_turn():
    g = se.Gap("k", "outputs", "confirm", "q", rewrites=((_TBL, ""),))
    draft = _stated("said")
    draft.files = _table("other")
    se._note_stated(draft, g, _table("said"), 7)
    assert draft.stated == {}
    se._refuse_rewrite(draft, _rewritten("elsewhere"), _MISSING)


def test_control_a_stated_value_a_turn_did_not_put_to_the_person_stays_stated():
    draft = _stated("said")
    se._note_stated(draft, se.Gap("k", "outputs", "confirm", "q", revises=((_TBL, _ROWS),)), _table("said"), 7)
    assert draft.stated[(_TBL, _OUT)] == (5, ["said"])


def test_a_value_left_standing_keeps_the_turn_that_stated_it():
    g = se.Gap("contradiction:chaining.some_stage_chaining.new", "outputs", "contradiction", "q", revises=((_TBL, _OUT),))
    draft = _stated("said")
    se._note_stated(draft, g, _table("said"), 7)
    assert draft.stated[(_TBL, _OUT)] == (5, ["said"])


def test_a_leaf_that_no_longer_reads_holds_nothing_and_does_not_raise():
    assert se._held(_table("said"), _WF, "steps[id=wait]") == {}
    assert se._held(_table("said"), _WF, "steps[id=gone].accepts") == {}
    assert se._held(_table("said"), "nowhere.yaml", _OUT) == {}
    assert se._held(_table("said"), _TBL, "domain") == {_OUT: ["said"]}


def _one_rewrite(restate=None):
    """Writes ``said`` at the confirm, then rewrites it at the missing gap; ``restate`` answers the refusal."""
    def ex(entry, draft, gap):
        if gap is None:
            return {"set": [{"file": f, "path": "", "value": v} for f, v in _table("guess").items()]}
        if gap.kind == "confirm":
            return {"set": [{"file": _TBL, "path": _OUT, "value": ["said"]}]}
        if entry.get("refused") and restate is not None:
            return restate
        return {"set": [{"file": _TBL, "path": _OUT, "value": ["other"]}]}
    return ex


def _script(monkeypatch):
    """Two turns, the confirm and then the gap, whose gap stays live until nothing reads ``other``."""
    def live(draft):
        wait = draft.files[_WF]["steps"][0]["accepts"] if _WF in draft.files else []
        return [_CONFIRM] + ([_MISSING] if "other" in wait else [])
    monkeypatch.setattr(se, "_all_gaps", live)
    monkeypatch.setattr(se, "gaps", lambda d: [g for g in live(d) if d.asked[g.key] < (1 if g.kind == "confirm" else 2)])


def test_a_rewrite_refused_on_both_tries_leaves_the_gap_open_and_never_deferred(monkeypatch):
    _script(monkeypatch)
    r = se.run({"opening": {"says": "x"}}, _one_rewrite(), answer=lambda g, d: {"says": "it is said"})
    assert r["files"][_TBL]["domain"]["outcome"] == ["said"]
    assert _MISSING.key in r["open"] and "rewriting a stated value" in r["open"][_MISSING.key]
    assert _MISSING.key not in r["deferrals"] and r["status"] == "cannot_run"
    assert {m["fault"] for m in r["model_errors"]} == {"rewrite"}
    assert sum(1 for t in r["messages"] for x in t["replies"] if x.get("refused")) == 4


def test_control_a_restatement_that_changes_what_the_turn_may_change_closes_the_gap(monkeypatch):
    _script(monkeypatch)
    moved = {"set": [{"file": _WF, "path": _ACC, "value": ["said"]}]}
    r = se.run({"opening": {"says": "x"}}, _one_rewrite(moved), answer=lambda g, d: {"says": "it is said"})
    assert r["files"][_TBL]["domain"]["outcome"] == ["said"] and r["open"] == {}
    assert r["files"][_WF]["steps"][0]["accepts"] == ["said"]
    assert [m.get("fault") for m in r["model_errors"]] == ["rewrite"]


def test_a_turn_that_ends_refused_states_nothing(monkeypatch):
    def ex(entry, draft, gap):
        if gap is None:
            return {"set": [{"file": f, "path": "", "value": v} for f, v in _table("guess").items()]}
        return {"set": "not a list of entries"}
    monkeypatch.setattr(se, "_all_gaps", lambda d: [_CONFIRM])
    monkeypatch.setattr(se, "gaps", lambda d: [_CONFIRM] if d.asked[_CONFIRM.key] < 1 else [])
    seen = {}
    real = se._note_stated
    monkeypatch.setattr(se, "_note_stated", lambda *a: seen.setdefault("called", True) and real(*a))
    se.run({"opening": {"says": "x"}}, ex, answer=lambda g, d: {"says": "no, it is something else"})
    assert "called" not in seen


def _t(turn, kind, key, *sets, refused=False):
    reply = {"patch": {"set": [{"file": _TBL, "path": p, "value": v} for p, v in sets]}}
    return {"turn": turn, "kind": kind, "key": key, "replies": [{**reply, "refused": "no"} if refused else reply]}


_OPEN = _t(0, "opening", None, (_OUT, ["guess"]))


def test_the_instrument_reads_a_stated_value_rewritten_on_a_missing_turn():
    out = sm.rewritten_slots([_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])), _t(2, "missing", "m", (_OUT, ["other"]))])
    assert [(x["turn"], x["path"], x["stated_at"], x["gone"]) for x in out] == [(2, _OUT, 1, ["said"])]


@pytest.mark.parametrize("kind", ["confirm", "contradiction", "null"])
def test_control_the_instrument_passes_a_rewrite_on_a_turn_that_asks(kind):
    assert sm.rewritten_slots([_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])), _t(2, kind, "k", (_OUT, ["other"]))]) == []


def test_control_the_instrument_passes_a_guess_replaced_and_a_leaf_added_to():
    assert sm.rewritten_slots([_OPEN, _t(1, "missing", "m", (_OUT, ["other"]))]) == []
    assert sm.rewritten_slots([_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])), _t(2, "missing", "m", (_OUT, ["said", "x"]))]) == []


def test_control_the_instrument_passes_a_write_that_pended_and_was_then_asked():
    asked = f"contradiction:{_TBL}#{_OUT}"
    out = sm.rewritten_slots([_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])), _t(2, "missing", "m", (_OUT, ["other"])),
                              _t(3, "contradiction", asked, (_OUT, ["said"]))])
    assert out == []


def test_control_the_instrument_passes_a_refused_reply():
    assert sm.rewritten_slots([_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])),
                               _t(2, "missing", "m", (_OUT, ["other"]), refused=True)]) == []


def test_the_instrument_reads_a_stated_value_inside_a_whole_list_rewrite():
    leaf = "steps[id=wait].excludes"
    steps = [{"kind": "human_await", "id": "wait", "excludes": ["said"]}]
    turns = [_t(0, "opening", None, ("steps", copy.deepcopy(steps))), _t(1, "confirm", "c", (leaf, ["said", "more"])),
             _t(2, "missing", "m", ("steps", [{"kind": "human_await", "id": "wait", "excludes": []}]))]
    assert [x["gone"] for x in sm.rewritten_slots(turns)] == [["more"]]


def test_a_wrong_field_in_excludes_reads_though_there_is_still_a_bar():
    f = _good()
    _step(f, IR, "engineering_disposition")["excludes"] = ["{trigger.someone_else}"]
    assert [x["stage"] for x in sm.wrong_excludes(f, _good(), SAME)] == ["pcn_impact_review"]
    assert sm.canonical(f) == sm.canonical(_good())


def test_a_bar_lost_from_one_review_reads_on_that_review_alone():
    f = _good()
    _step(f, IR, "engineering_disposition")["excludes"] = []
    assert [x["stage"] for x in sm.wrong_excludes(f, _good(), SAME)] == ["pcn_impact_review"]


def test_a_bar_nobody_described_reads_too():
    f = _good()
    _step(f, ACK, next(s["id"] for s in f[ACK]["steps"] if s["kind"] == "human_await"))["excludes"] = ["{trigger.x}"]
    assert [x["stage"] for x in sm.wrong_excludes(f, _good(), SAME)] == ["pcn_acknowledge"]


def test_control_excludes_in_another_order_and_an_absent_empty_read_the_same():
    f = _good()
    del _step(f, ACK, next(s["id"] for s in f[ACK]["steps"] if s["kind"] == "human_await"))["excludes"]
    assert sm.wrong_excludes(f, _good(), SAME) == [] and sm.wrong_excludes(_good(), _good(), SAME) == []


def test_a_stage_nothing_pairs_with_reads_its_bars():
    out = sm.wrong_excludes(_good(), _good(), {w: w for w in STAGES if w != "pcn_impact_review"})
    assert [(x["stage"], x["drafted"]) for x in out] == [("pcn_impact_review", None)]


def test_required_details_gone_or_changed_read_and_their_order_does_not():
    f = _good()
    named = list(f[TRIG]["requires"])
    assert sm.wrong_requires(f, _good()) == []
    f[TRIG]["requires"] = list(reversed(named))
    assert sm.wrong_requires(f, _good()) == []
    f[TRIG]["requires"] = named[:-1]
    assert sm.wrong_requires(f, _good()) == [{"expected": named, "drafted": named[:-1]}]
    del f[TRIG]["requires"]
    assert sm.wrong_requires(f, _good()) == [{"expected": named, "drafted": None}]


_REWROTE = [_OPEN, _t(1, "confirm", "c", (_OUT, ["said"])), _t(2, "missing", "m", (_OUT, ["other"]))]


@pytest.mark.parametrize("edit,route,slot", [
    ("none", True, True), ("excludes", True, False), ("requires", True, False), ("rewrite", True, False),
    ("drop", False, True), ("route", False, True), ("cannot_run", False, True)])
def test_the_two_bars_read_apart_and_the_bar_needs_both(monkeypatch, edit, route, slot):
    real = se.run

    def result(*a, **k):
        r = real(*a, **k)
        r["files"] = copy.deepcopy(r["files"])
        if edit == "excludes":
            _step(r["files"], IR, "engineering_disposition")["excludes"] = []
        elif edit == "requires":
            r["files"][TRIG]["requires"] = r["files"][TRIG]["requires"][:-1]
        elif edit == "rewrite":
            r["messages"] = _REWROTE
        elif edit == "drop":
            r["files"] = {**r["files"], **_record_only_emits("filed")}
        elif edit == "route":
            r["files"][ACK_CH]["rows"] = [{**x, "then": "elsewhere"} if x["when"]["outcome"] == "escalated" else x
                                          for x in r["files"][ACK_CH]["rows"]]
        elif edit == "cannot_run":
            r["status"] = "cannot_run"
        return r
    monkeypatch.setattr(sm.se, "run", result)
    row = sm.measure("pcn_review", se.OracleExtractor(), aligned=True)
    assert row["route_bar"] is route and row["slot_bar"] is slot
    assert row["bar_met"] is (route and slot)


@pytest.mark.parametrize("name", NAMES)
def test_the_oracle_meets_both_bars_with_nothing_refused_on_every_fixture(name):
    row = sm.measure(name, se.OracleExtractor(), aligned=True)
    assert row["route_bar"] is True and row["slot_bar"] is True
    assert row["wrong_excludes"] == [] and row["wrong_requires"] == []
    assert row["rewritten_slots"] == [] and row["rewrites_refused"] == []


# ── an approval step names who approves and in what role (architect, 2026-11-04) ─────────────

def _await(files, wf):
    return next(s for s in files[wf]["steps"] if s["kind"] == "human_await")


def test_the_grammar_says_an_approval_step_names_who_approves_and_in_what_role():
    line = next((x for x in se._GRAMMAR.split("\n- ") if x.startswith("An approval step names")), None)
    assert line is not None
    said = " ".join(line.split())
    for word in ("names who approves and in what role", "lists those answers in approves",
                 "its role is the approver's capacity in the user's words", "has no approves"):
        assert word in said


def test_an_approval_step_with_no_approves_reads_and_canonical_cannot_see_it():
    f = _good()
    del _step(f, IR, "engineering_disposition")["approves"]
    assert [(x["stage"], x["drafted"]["approves"]) for x in sm.wrong_approvals(f, _good(), SAME)] == [("pcn_impact_review", [])]
    assert sm.canonical(f) == sm.canonical(_good())


def test_a_role_absent_or_another_one_reads():
    f = _good()
    del _await(f, PROGRAM)["role"]
    _await(f, ACK)["role"] = "engineer"
    out = {x["stage"]: x["drafted"]["role"] for x in sm.wrong_approvals(f, _good(), SAME)}
    assert out == {"pcn_program_approval": None, "pcn_acknowledge": "engineer"}


def test_an_answer_counted_as_approval_that_the_person_did_not_count_reads():
    f = _good()
    _step(f, IR, "engineering_disposition")["approves"] = ["approved", "needs_info"]
    assert [x["stage"] for x in sm.wrong_approvals(f, _good(), SAME)] == ["pcn_impact_review"]


def test_an_approval_nobody_described_reads_too():
    e = _good()
    del _await(e, ACK)["approves"], _await(e, ACK)["role"]
    assert [x["stage"] for x in sm.wrong_approvals(_good(), e, SAME)] == ["pcn_acknowledge"]
    assert sm.wrong_approvals(e, e, SAME) == []


def test_control_a_role_in_the_persons_spelling_and_verbs_in_another_order_read_the_same():
    f, e = _good(), _good()
    _await(f, PROGRAM)["role"] = "Program Manager"
    _step(e, IR, "engineering_disposition")["approves"] = ["approved", "needs_info"]
    _step(f, IR, "engineering_disposition")["approves"] = ["needs_info", "approved"]
    assert sm.wrong_approvals(f, e, SAME) == []


def test_an_approval_step_nothing_pairs_with_reads():
    out = sm.wrong_approvals(_good(), _good(), {w: w for w in STAGES if w != "pcn_program_approval"})
    assert [(x["stage"], x["drafted"]) for x in out] == [("pcn_program_approval", None)]


def test_an_approval_step_the_draft_lacks_reads_and_a_render_before_it_does_not_shift_the_pairing():
    f = _good()
    f[IR]["steps"] = [s for s in f[IR]["steps"] if s["kind"] != "render"]
    assert sm.wrong_approvals(f, _good(), SAME) == []
    f[IR]["steps"] = [s for s in f[IR]["steps"] if s["kind"] != "human_await"]
    assert [(x["stage"], x["drafted"]) for x in sm.wrong_approvals(f, _good(), SAME)] == [("pcn_impact_review", None)]


@pytest.mark.parametrize("edit,route,slot,approval", [
    ("none", True, True, True), ("approves", True, True, False), ("role", True, True, False),
    ("excludes", True, False, True), ("drop", False, True, True)])
def test_the_three_bars_read_apart_and_the_bar_needs_all_three(monkeypatch, edit, route, slot, approval):
    real = se.run

    def result(*a, **k):
        r = real(*a, **k)
        r["files"] = copy.deepcopy(r["files"])
        if edit == "approves":
            del _step(r["files"], IR, "engineering_disposition")["approves"]
        elif edit == "role":
            _await(r["files"], PROGRAM)["role"] = "someone_else"
        elif edit == "excludes":
            _step(r["files"], IR, "engineering_disposition")["excludes"] = []
        elif edit == "drop":
            r["files"] = {**r["files"], **_record_only_emits("filed")}
        return r
    monkeypatch.setattr(sm.se, "run", result)
    row = sm.measure("pcn_review", se.OracleExtractor(), aligned=True)
    assert (row["route_bar"], row["slot_bar"], row["approval_bar"]) == (route, slot, approval)
    assert row["bar_met"] is (route and slot and approval)


@pytest.mark.parametrize("name", NAMES)
def test_the_oracle_meets_the_approval_bar_on_every_fixture(name):
    row = sm.measure(name, se.OracleExtractor(), aligned=True)
    assert row["approval_bar"] is True and row["wrong_approvals"] == [] and row["bar_met"] is True


# ── a refusal one field clears is asked on that field (architect, 2026-11-04, on runs 53 to 55) ──

_ROLE = "steps[id=engineering_disposition].role"
_ROLE_KEY = f"contradiction:{IR}#{_ROLE}"


def _roleless():
    f = _good()
    del _step(f, IR, "engineering_disposition")["role"]
    return f


def test_a_refusal_one_unset_field_clears_is_asked_on_that_field():
    gaps = se.problems(_roleless())
    assert [(g.key, g.kind, g.facet, g.revises) for g in gaps] == [(_ROLE_KEY, "contradiction", "approvals", ((IR, _ROLE),))]
    said = gaps[0].question
    assert said.startswith("What is the role of engineering disposition in pcn impact review?")
    assert "`approves` requires a `role`" in said and "Value error" not in said


def test_control_a_refusal_no_single_field_clears_stays_on_the_workflow():
    f = _good()
    _step(f, IR, "engineering_disposition")["completion"] = {"mode": "grouped"}
    gaps = se.problems(f)
    assert [g.key for g in gaps] == ["contradiction:workflow.pcn_impact_review"]
    assert "grouped await" in gaps[0].question


def test_the_field_question_may_not_be_deferred():
    assert se.non_deferrable(se.Draft(files=_roleless()), _ROLE_KEY) == "a runtime refusal may not be deferred"


def test_the_person_answers_the_field_question_from_what_they_meant_and_not_the_opening():
    f = _roleless()
    g = se.problems(f)[0]
    says = _pcn_user()(g, se.Draft(files=f))["says"]
    assert says == "It is component_engineer." and "whoever logged" not in says


def test_an_answer_to_the_field_question_clears_the_refusal():
    d = se.Draft(files=_roleless())
    g = se.problems(d.files)[0]
    se.apply_patch(d, {"set": [{"file": IR, "path": _ROLE, "value": "component_engineer"}]}, 1, answering=g)
    assert se.problems(d.files) == [] and d.files == _good()


def test_a_refusal_two_fields_would_each_clear_names_neither_and_one_field_names_it(monkeypatch):
    # No executor refusal today is cleared by either of two fields, so this reads the counting on a stub.
    from typing import Literal, Optional as Opt
    from pydantic import BaseModel, model_validator

    class _EitherStep(BaseModel):
        kind: Literal["either"]
        id: str
        a: Opt[str] = None
        b: Opt[str] = None
        n: Opt[int] = None

        @model_validator(mode="after")
        def _one(self):
            if not (self.a or self.b):
                raise ValueError("needs a or b")
            return self

    monkeypatch.setitem(se._STEP_MODELS, "either", _EitherStep)
    assert se._field_it_needs({"kind": "either", "id": "s"}, "Value error, needs a or b") is None
    assert se._field_it_needs({"kind": "either", "id": "s", "b": ""}, "Value error, needs a or b") is None
    monkeypatch.setattr(_EitherStep, "model_fields", {k: v for k, v in _EitherStep.model_fields.items() if k != "b"})
    assert se._field_it_needs({"kind": "either", "id": "s"}, "Value error, needs a or b") == "a"
