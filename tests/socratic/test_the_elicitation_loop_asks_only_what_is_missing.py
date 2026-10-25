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
NAMES = ("pcn_review", "maint_case_release", "training_course_approval")
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
            if gap is not None:
                _seen.append((gap.key, gap.key in [g.key for g in se.gaps(draft)]))
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
