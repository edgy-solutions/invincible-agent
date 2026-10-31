"""ADR-0061 prototype: the socratic loop asks only what the draft does not already answer.

The oracle arm reads each answer's ``facts``; no model runs here. The fixtures are synthetic.
"""
from __future__ import annotations

import copy
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


def test_control_reachability_a_definition_no_table_names_is_not_asked_about():
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
    assert sm.measure(name, se.OracleExtractor())["questions"] == {
        "pcn_review": 14, "maint_case_release": 12, "training_course_approval": 15}[name]


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
    assert sm._fact_target("approvals.k.reason_required") == ("task_kinds/k.yaml", "reason_required")
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
    "pcn_review": ["actors.pcn_acknowledge.acknowledge.excludes"],
    "maint_case_release": ["actors.maint_case_inspection.inspection.excludes",
                           "actors.maint_case_supervisor_release.supervisor.excludes"],
    "training_course_approval": ["actors.course_content_review.content.excludes",
                                 "actors.course_security_review.security.excludes",
                                 "actors.course_accreditation.accreditation.excludes",
                                 "approvals.course_content_review.content.task_kind"],
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
    ``redraft``, the extractor rewrites the step from the person's rejection, as the grammar asks."""
    def extractor(entry, draft, gap):
        patch = se.OracleExtractor()(entry, draft, gap)
        if gap is not None and gap.key == "steps.pcn_record":
            for fact in patch["set"]:
                if fact["file"] == REC and fact["path"] == "":
                    fact["value"]["steps"][1] = {"kind": "human_await", "id": "filed",
                                                 "audience": "pcn_records:SUSTAINMENT",
                                                 "task_kind": "pcn_filing", "excludes": []}
            patch["set"].append({"file": FILING, "path": "",
                                 "value": {"kind": "pcn_filing", "accepts": ["filed"]}})
        if redraft and gap is not None and gap.kind == "confirm" and str(entry.get("says", "")).startswith(NO):
            patch = {"unset": [{"file": REC, "path": "steps[id=filed].task_kind"},
                               {"file": REC, "path": "steps[id=filed].excludes"},
                               {"file": FILING, "path": ""}],
                     "set": [{"file": REC, "path": "steps[id=filed].kind", "value": "signal_await"},
                             {"file": REC, "path": "steps[id=filed].signal", "value": "pcn_filed"},
                             {"file": REC, "path": "steps[id=filed].accepts", "value": ["filed"]}]}
        return patch
    return extractor


def test_a_confirm_of_a_step_the_process_does_not_have_is_rejected_and_the_redraft_runs():
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
