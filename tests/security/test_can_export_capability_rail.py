"""The `can_export:<profile>` capability rail: DENY-BY-DEFAULT, unlike `can_drop`.

A profile with no `can_export:<P>` row is exportable by nobody; object existence decides nothing, so
the sync has no existence read and no object prune (deleting a row revokes through the invoker
relation prune). One row gates a single export and a batch alike (ruled 2026-10-29). The defaults are
met by COMPLETENESS: validate_policy refuses ANY known profile that no row decides, and names its
kind's default group -- alert-processors for a review-export profile (policy/exports), and
finance-analysts, the program-finance persona's group, for a fin CDRL profile (ruled 2026-10-29).
An answer-export profile (fin's #148, policy/exports/answers) needs its row too (ruled 2026-10-30);
that kind has no default, so its refusal says none is ruled. A profile can have its grantee ruled by
name: plan-answers goes to portfolio-leads, not alert-processors -- "AP is notices" (ruled
2026-10-29, re-keyed to the moved profile 2026-10-30). The seed ships a row for every profile it
knows: one per policy/exports profile at its group, and the CDRL row.

Run:  uv run python -m pytest tests/security/test_can_export_capability_rail.py -q
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "policy" / "sync"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import capability_grant_sync as cgs  # noqa: E402
import validate_policy as vp  # noqa: E402
from topaz_sync import DirObject, DirRelation  # noqa: E402

SAMPLE = ROOT / "policy" / "overlays" / "sample" / "fin_export_profiles"
CDRL = "cdrl_a001_ev_summary"
GROUP = "alert-processors"
FIN_GROUP = "finance-analysts"


def _row(group=(GROUP,), users=()):
    r = {"granted_by": "seed", "reason": "test"}
    if group:
        r["grant_to_groups"] = list(group)
    if users:
        r["grant_to"] = list(users)
    return r


def _profile_dir(base: Path, name: str, rows: dict[str, dict]) -> Path:
    d = base / name
    d.mkdir(parents=True)
    for fname, body in rows.items():
        (d / f"{fname}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return d


# -- 1. the seed composition ---------------------------------------------------------------

_ENV = ("INGEST_EXPORT_PROFILE_DIR", "EXPORT_PROFILE_POLICY_DIR", "EXPORT_PROFILE_OVERLAY_DIRS",
        "FIN_EXPORT_PROFILE_POLICY_DIR", "FIN_EXPORT_PROFILE_OVERLAY_DIRS")
ANSWERS = ROOT / "policy" / "exports" / "answers"


def test_1_the_seed_composition(monkeypatch):
    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    profiles, notes = vp.known_export_profiles()
    assert profiles.get(CDRL) == "fin-cdrl", profiles
    stems = {p.stem for p in (ROOT / "policy" / "exports").glob("*.yaml")}
    assert stems, "policy/exports ships no profile"
    # the review seed, then the sample overlay the registry row names (offline_overlays).
    sample = {p.stem for p in (ROOT / "policy" / "overlays" / "sample" / "exports").glob("*.yaml")}
    assert sample, "the sample overlay ships no review profile"
    assert {n for n, k in profiles.items() if k == "review-export"} == stems | sample, (profiles, stems)
    review = (ROOT / "policy" / "exports").as_posix()
    assert [n for n in notes if n.startswith(f"review-export: {review}")
            and f"-> {len(stems | sample)} profile(s)" in n], notes
    # policy/exports/answers is its own kind; the review seed's glob is not recursive.
    answers = {p.stem for p in ANSWERS.glob("*.yaml")}
    assert {n for n, k in profiles.items() if k == "answer-export"} == answers, (profiles, answers)
    assert [n for n in notes if n.startswith(f"answer-export: {ANSWERS.as_posix()} ")], notes
    # the fin seed ships no profile; the sandbox overlay the chart sets is composed after it.
    fin = [n for n in notes if n.startswith("fin-cdrl: ")]
    assert len(fin) == 1 and SAMPLE.as_posix() in fin[0], notes
    assert not [n for n in notes if n.startswith(("REFUSED:", "COLLISION:"))], notes


def test_1_the_source_rows_are_the_sdks_shape_one_per_kind():
    """policy/export_profile_sources.yaml is what both sides read (architect 2026-10-30): each row
    is an iagent_mesh ExportProfileSource, and no kind is declared twice."""
    from iagent_mesh import ExportProfileSource

    rows = yaml.safe_load((ROOT / "policy" / vp.EXPORT_PROFILE_SOURCES).read_text(encoding="utf-8"))["sources"]
    kinds = [ExportProfileSource.model_validate({**r, "overlay_env": r["overlay_env"] or ""}).kind
             for r in rows]
    assert len(kinds) == len(set(kinds)) == 3, kinds


def test_1_the_source_rows_name_the_variables_each_loader_reads():
    """Until the engines read policy/export_profile_sources.yaml (01M6A9QDN1GQ20347W16EM0D3X), the
    rows restate each loader's variables. This goes red when a loader renames one and the row is not
    re-read. Each row names the overlay variable its loader reads."""
    from agent_fleet.finance_agent import export_profiles as fin
    from agent_fleet.utils import answer_exports as ans
    from iagent import export_profiles as rev

    rows = {r["kind"]: r for r in yaml.safe_load(
        (ROOT / "policy" / vp.EXPORT_PROFILE_SOURCES).read_text(encoding="utf-8"))["sources"]}
    got = {k: (r["seed_env"], r["overlay_env"]) for k, r in rows.items()}
    assert got == {"review-export": (rev._DIR_ENV, rev._OVERLAY_ENV),
                   "answer-export": (ans._SEED_ENV, ans._OVERLAY_ENV),
                   "fin-cdrl": (fin._SEED_ENV, fin._OVERLAY_ENV)}, got


# -- 2. the join seal with fin's loader ----------------------------------------------------

def test_2_fin_cdrl_names_equal_what_fins_loader_returns(monkeypatch):
    from agent_fleet.finance_agent import export_profiles
    from agent_fleet.finance_agent import main as engine

    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(ROOT / "policy/overlays/sample/measure_verbs"))
    declared = engine._load_declared()
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(SAMPLE))
    monkeypatch.delenv("FIN_EXPORT_PROFILE_POLICY_DIR", raising=False)
    loaded = {p.name for p in export_profiles.load_export_profiles(declared=declared)}
    ours = {n for n, k in vp.known_export_profiles()[0].items() if k == "fin-cdrl"}
    assert loaded and ours == loaded, (ours, loaded)



def test_2_the_fin_env_vars_move_the_seed_and_add_overlays(tmp_path, monkeypatch):
    """The two env vars fin reads, each seen on its own: the seed dir is MOVED (the repo seed's
    names are not read) and each overlay dir is ADDED. The join above sets the overlay var to the
    sample dir, which the fin row's offline_overlays also names, so it cannot see the var go
    unread."""
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p_seed"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p_ov"}})
    monkeypatch.setenv("FIN_EXPORT_PROFILE_POLICY_DIR", str(seed))
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(ov))
    profiles, notes = vp.known_export_profiles()
    assert profiles.get("p_seed") == "fin-cdrl", (profiles, notes)
    assert profiles.get("p_ov") == "fin-cdrl", (profiles, notes)
    assert (ROOT / "policy" / "fin_export_profiles").as_posix() not in " ".join(notes), notes


def test_2_answer_export_names_equal_what_fins_answer_loader_returns(monkeypatch):
    """The join seal with #148's loader: the answer-export names this gate demands a row for are
    the ones the BFF and engine-cost load. Skipped on a tree without #148's loader."""
    if not (ROOT / "agent_fleet" / "utils" / "answer_exports.py").is_file():
        pytest.skip("fin's answer-export loader (#148) is not on this tree")
    from agent_fleet.utils import answer_exports

    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    loaded = set(answer_exports.load_answer_export_profiles())
    ours = {n for n, k in vp.known_export_profiles()[0].items() if k == "answer-export"}
    assert loaded and ours == loaded, (ours, loaded)


def test_2_the_answer_and_review_env_vars_are_read_as_their_loaders_read_them(tmp_path, monkeypatch):
    """#148's two variables: EXPORT_PROFILE_POLICY_DIR MOVES the answer seed and each
    EXPORT_PROFILE_OVERLAY_DIRS dir is ADDED. lane/01's INGEST_EXPORT_PROFILE_DIR MOVES the review
    directory. Each kind is read from where its own loader reads it."""
    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    seed = _profile_dir(tmp_path, "aseed", {"a": {"name": "a-seed"}})
    ov = _profile_dir(tmp_path, "aov", {"b": {"name": "a-ov"}})
    rev = _profile_dir(tmp_path, "rev", {"c": {"name": "r-moved"}})
    monkeypatch.setenv("EXPORT_PROFILE_POLICY_DIR", str(seed))
    monkeypatch.setenv("EXPORT_PROFILE_OVERLAY_DIRS", str(ov))
    monkeypatch.setenv("INGEST_EXPORT_PROFILE_DIR", str(rev))
    profiles, notes = vp.known_export_profiles()
    assert profiles.get("a-seed") == "answer-export", (profiles, notes)
    assert profiles.get("a-ov") == "answer-export", (profiles, notes)
    sample = {p.stem for p in (ROOT / "policy" / "overlays" / "sample" / "exports").glob("*.yaml")}
    assert {n for n, k in profiles.items() if k == "review-export"} == {"r-moved"} | sample, (profiles, notes)
    joined = " ".join(notes)
    assert ANSWERS.as_posix() + " " not in joined, notes
    assert (ROOT / "policy" / "exports").as_posix() + " " not in joined, notes


# -- 3. fin's semantics, on tmp dirs -------------------------------------------------------

def _src(kind, seed, *overlays):
    """A source row for tmp dirs: the seed is `seed_default` (its variable is never set) and the
    overlays ride as offline_overlays, an absolute path under the root being itself."""
    return {"kind": kind, "seed_env": "IAGENT_TEST_UNSET_EXPORT_SEED", "seed_default": str(seed),
            "overlay_env": None, "offline_overlays": [str(o) for o in overlays]}


def _compose(*dirs, kind="fin-cdrl"):
    return vp.known_export_profiles([_src(kind, *dirs)])


def test_3_an_overlay_replaces_a_same_name_row_and_stays_known_once(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1", "label": "old"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p1", "label": "new"}})
    profiles, notes = _compose(seed, ov)
    assert profiles == {"p1": "fin-cdrl"}
    assert not [n for n in notes if "COLLISION" in n], notes


def test_3_a_tombstone_removes_the_name(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1"}, "c": {"name": "p2"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p1", "deleted": True}})
    profiles, _ = _compose(seed, ov)
    assert profiles == {"p2": "fin-cdrl"}


def test_3_a_later_directory_wins(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1"}})
    gone = _profile_dir(tmp_path, "gone", {"a": {"name": "p1", "deleted": True}})
    back = _profile_dir(tmp_path, "back", {"b": {"name": "p1"}})
    assert _compose(seed, gone, back)[0] == {"p1": "fin-cdrl"}
    assert _compose(seed, back, gone)[0] == {}


# The SDK refuses what the old copy skipped (v0.9.13's compose_rows; ruled 10-30: one function).

@pytest.mark.parametrize("rows, why", [
    ({"a": {"label": "no name"}}, "has no name"),
    ({"a": {"name": "p1"}, "b": {"name": "p1"}}, "both declare name 'p1'"),
], ids=["nameless", "two-files-one-name"])
def test_3_a_bad_profile_file_refuses_its_kind(tmp_path, rows, why):
    profiles, notes = _compose(_profile_dir(tmp_path, "seed", rows))
    assert profiles == {}, profiles
    assert [n for n in notes if n.startswith("REFUSED: fin-cdrl: ") and why in n], notes


def test_3_a_tombstone_for_a_name_nothing_ships_is_refused(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p2", "deleted": True}})
    assert [n for n in _compose(seed, ov)[1] if n.startswith("REFUSED: fin-cdrl: ") and "'p2'" in n]


def test_3_a_dir_both_in_the_variable_and_offline_is_composed_once(tmp_path, monkeypatch):
    """The sandbox sets FIN_EXPORT_PROFILE_OVERLAY_DIRS to the dir the fin row names offline. Read
    twice, a tombstone in it would delete a name the first read already removed: a refusal."""
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1"}, "c": {"name": "p2"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p1", "deleted": True}})
    monkeypatch.setenv("IAGENT_TEST_EXPORT_OVERLAYS", str(ov))
    row = {**_src("fin-cdrl", seed, ov), "overlay_env": "IAGENT_TEST_EXPORT_OVERLAYS"}
    profiles, notes = vp.known_export_profiles([row])
    assert profiles == {"p2": "fin-cdrl"}, (profiles, notes)


def test_3_a_bad_source_row_is_refused(tmp_path):
    bad = {"kind": "x", "seed_default": str(tmp_path)}  # no seed_env
    _, notes = vp.known_export_profiles([bad, _src("x", tmp_path), _src("x", tmp_path)])
    assert [n for n in notes if n.startswith("REFUSED:") and "row 0" in n and "seed_env" in n], notes
    assert [n for n in notes if n.startswith("REFUSED:") and "kind 'x' twice" in n], notes


# -- validate(): a policy dir with the repo's own files, mutated in one thing ---------------

@pytest.fixture
def pol(tmp_path):
    d = tmp_path / "policy"
    shutil.copytree(ROOT / "policy", d, ignore=shutil.ignore_patterns("__pycache__", "overlays"))
    return d


def _add(d, key, row):
    p = d / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["capabilities"][key] = row
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _seed_review() -> dict[str, str]:
    """The seed's review-, answer-export and fin CDRL profiles, read from the loader, not restated:
    the seed ships a row for each, so a fin profile left out here (a second format, #144) reads
    as a row naming an unknown profile."""
    profiles, _ = vp.known_export_profiles()
    return {n: k for n, k in profiles.items() if k in ("review-export", "answer-export", "fin-cdrl")}


def _known(monkeypatch, profiles, notes=("n (1 profile(s))",)):
    """Fake the profile set as the seed's review- and answer-export profiles plus `profiles`: the
    seed ships a row for each of those, and a row naming an unknown profile is refused."""
    merged = {**_seed_review(), **profiles}
    monkeypatch.setattr(vp, "known_export_profiles", lambda rows=None: (dict(merged), list(notes)))


def test_4_baseline_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl"})
    assert vp.validate(pol, pol) == []


def test_4_an_unknown_can_export_name_is_refused(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl"})
    _add(pol, "can_export:nosuch", _row())
    errs = vp.validate(pol, pol)
    assert any("can_export:nosuch" in e and "NOT a known export profile" in e for e in errs), errs


def test_4_a_known_cdrl_name_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl"})
    _add(pol, f"can_export:{CDRL}", _row())
    assert vp.validate(pol, pol) == []


def test_4_a_known_review_export_name_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl", "ingest_review": "review-export"})
    _add(pol, "can_export:ingest_review", _row())
    assert vp.validate(pol, pol) == []


# -- 5. completeness -----------------------------------------------------------------------

def _no_row(errs, name):
    return [e for e in errs if f"profile {name!r} has no" in e and "NOBODY could export it" in e]


def test_5_a_review_export_profile_with_no_row_is_refused(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl", "ingest_review": "review-export"})
    hit = _no_row(vp.validate(pol, pol), "ingest_review")
    assert len(hit) == 1 and "review-export profile" in hit[0], hit
    assert f"grant_to_groups: [{GROUP}]" in hit[0] and FIN_GROUP not in hit[0], hit


def test_5_with_the_row_present_it_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin-cdrl", "ingest_review": "review-export"})
    _add(pol, "can_export:ingest_review", _row())
    assert vp.validate(pol, pol) == []


def _drop_row(pol, name):
    p = pol / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if data["capabilities"].pop(f"can_export:{name}", None) is not None:
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_5_a_cdrl_profile_with_no_row_is_refused_and_names_the_finance_group(pol, monkeypatch):
    """Ruled 2026-10-29: completeness covers CDRL profiles too. The advice is the group the seed's
    CDRL row grants (the program-finance persona's group), drawn from that ROW, never the
    review-export rows' alert-processors (the rejected single default)."""
    _known(monkeypatch, {CDRL: "fin-cdrl", "cdrl_b": "fin-cdrl"})
    hit = _no_row(vp.validate(pol, pol), "cdrl_b")
    assert len(hit) == 1 and "fin-cdrl profile" in hit[0], hit
    assert f"grant_to_groups: [{FIN_GROUP}]" in hit[0] and GROUP not in hit[0], hit


def test_5_the_seed_cdrl_row_is_what_keeps_the_seed_green(pol, monkeypatch):
    """CONTROL for the arm above on the real seed: delete the shipped row and the seed's own
    profile is refused."""
    _known(monkeypatch, {CDRL: "fin-cdrl"})
    _drop_row(pol, CDRL)
    assert len(_no_row(vp.validate(pol, pol), CDRL)) == 1


def _set_groups(pol, names, groups):
    p = pol / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    for n in names:
        data["capabilities"][f"can_export:{n}"]["grant_to_groups"] = list(groups)
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_5_the_advice_follows_the_rows_not_a_constant(pol, monkeypatch):
    """Standing rule (2026-10-30): no grantee is held in code. Re-grant every seed review-export
    row to another real group and the refusal's advice for a new review profile moves with them."""
    seed = [n for n, k in _seed_review().items() if k == "review-export"]
    assert seed, "no review-export profile in the seed"
    _set_groups(pol, seed, ["portfolio-leads"])
    _known(monkeypatch, {CDRL: "fin-cdrl", "ingest_review": "review-export"})
    hit = _no_row(vp.validate(pol, pol), "ingest_review")
    assert len(hit) == 1 and "grant_to_groups: [portfolio-leads]" in hit[0], hit
    assert GROUP not in hit[0], hit


def test_5_a_lone_kind_profile_with_no_row_is_refused_and_names_no_group(pol, monkeypatch):
    """Ruled 2026-10-30: answer-export profiles need a row. With no other answer-export row to
    follow, the refusal invents no group -- neither another kind's group nor a ruled one held in
    code; the ruled grantee arrives as the first ROW."""
    _known(monkeypatch, {CDRL: "fin-cdrl", "plan-answers": "answer-export"})
    _drop_row(pol, "plan-answers")
    hit = _no_row(vp.validate(pol, pol), "plan-answers")
    assert len(hit) == 1 and "answer-export profile" in hit[0], hit
    assert "no other answer-export profile has a row" in hit[0] and "grant_to_groups" not in hit[0], hit
    assert GROUP not in hit[0] and FIN_GROUP not in hit[0] and "portfolio-leads" not in hit[0], hit


def test_5_the_ruled_plan_answers_row_is_what_the_next_answer_profile_is_told(pol, monkeypatch):
    """Ruled 2026-10-29/30: `can_export:plan-answers` -> [portfolio-leads] is a ROW (it ships with
    whichever of #148 and #151 merges second). Once it is there, another answer-export profile with
    no row is pointed at portfolio-leads -- by the row, not by code."""
    _known(monkeypatch, {CDRL: "fin-cdrl", "plan-answers": "answer-export",
                         "other-answers": "answer-export"})
    _drop_row(pol, "plan-answers")
    _add(pol, "can_export:plan-answers", _row(group=("portfolio-leads",)))
    errs = vp.validate(pol, pol)
    assert _no_row(errs, "plan-answers") == [], errs
    hit = _no_row(errs, "other-answers")
    assert len(hit) == 1 and "grant_to_groups: [portfolio-leads]" in hit[0], hit
    assert GROUP not in hit[0] and FIN_GROUP not in hit[0], hit


def test_5_no_grantee_is_held_in_code():
    """Standing rule (2026-10-30): the validator names no group. The retired constants are gone,
    and no group policy/groups.yaml declares appears as a quoted literal in validate_policy.py."""
    assert not hasattr(vp, "EXPORT_DEFAULT_GROUPS") and not hasattr(vp, "EXPORT_PROFILE_GROUPS")
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    src = Path(vp.__file__).read_text(encoding="utf-8")
    held = sorted(g for g in groups if f'"{g}"' in src or f"'{g}'" in src)
    assert held == [], held


def _persona_groups(persona):
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    return {name for name, body in groups.items()
            if any(isinstance(x, dict) and x.get("persona") == persona
                   for x in ((body or {}).get("grants") or []))}


def test_5_the_seed_ships_the_cdrl_row_to_the_program_finance_group():
    """Ruled 2026-10-29, carried by the ROW: the seed CDRL row grants the group whose grants carry
    the PROGRAM_FINANCE_ANALYST persona (read from groups.yaml, not restated)."""
    caps = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    row = caps["capabilities"][f"can_export:{CDRL}"]
    assert row.get("grant_to_groups") == [FIN_GROUP] and not row.get("grant_to"), row
    assert _persona_groups("PROGRAM_FINANCE_ANALYST") == {FIN_GROUP}


def test_5_the_seed_ships_a_row_per_review_and_answer_profile():
    """Every policy/exports and policy/exports/answers profile ships its row. The ruled grantees are
    those rows: review-export to alert-processors (2026-10-29); plan-answers, when #148's profile is
    on the tree, to the PORTFOLIO_LEAD group (2026-10-29/30)."""
    caps = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    review = _seed_review()
    assert "review-export" in review.values(), "no review-export profile in the seed"
    lead = _persona_groups("PORTFOLIO_LEAD")
    for name, kind in sorted(review.items()):
        row = caps["capabilities"].get(f"can_export:{name}")
        assert row is not None, name
        assert not row.get("grant_to"), (name, row)
        if kind == "review-export":
            assert row.get("grant_to_groups") == [GROUP], (name, row)
        elif name == "plan-answers":
            assert set(row.get("grant_to_groups") or []) == lead and len(lead) == 1, (name, row, lead)


def test_5_the_plan_answers_group_is_the_portfolio_lead_cell_and_alice_holds_it():
    """The ruling's precondition, read from config: exactly one group carries PORTFOLIO_LEAD, it is
    the group the plan-answers row names, and alice holds it in the sandbox (no topaz_sync owed)."""
    lead = _persona_groups("PORTFOLIO_LEAD")
    assert lead == {"portfolio-leads"}, lead
    users = yaml.safe_load((ROOT / "policy" / "users.yaml").read_text(encoding="utf-8"))["users"]
    alice = [u for u in users if u.get("id") == "alice@example.com"]
    assert len(alice) == 1 and "portfolio-leads" in (alice[0].get("groups") or []), alice


# -- 6. a collision ------------------------------------------------------------------------

def test_6_the_same_name_in_both_kinds_is_a_collision(tmp_path):
    a = _profile_dir(tmp_path, "rev", {"a": {"name": "dup"}})
    b = _profile_dir(tmp_path, "cdrl", {"b": {"name": "dup"}})
    _, notes = vp.known_export_profiles([_src("review-export", a), _src("fin-cdrl", b)])
    assert any(n.startswith("COLLISION:") and "'dup'" in n for n in notes), notes


def test_6_a_review_and_an_answer_profile_of_one_name_collide(tmp_path):
    """One `can_export:<P>` namespace for every kind: the subdirectory keeps the LOADERS apart, not
    the capability keys."""
    a = _profile_dir(tmp_path, "rev", {"a": {"name": "dup"}})
    b = _profile_dir(tmp_path, "ans", {"b": {"name": "dup"}})
    _, notes = vp.known_export_profiles([_src("review-export", a), _src("answer-export", b)])
    assert any(n.startswith("COLLISION:") and "'dup'" in n for n in notes), notes


def test_6_validate_turns_a_collision_into_an_error(pol, monkeypatch):
    monkeypatch.setattr(vp, "known_export_profiles", lambda rows=None: (
        {"dup": "fin-cdrl"}, ["COLLISION: 'dup' is a review-export profile and a fin-cdrl profile"]))
    errs = vp.validate(pol, pol)
    assert any("export profile COLLISION" in e and "'dup'" in e for e in errs), errs


def test_6_validate_turns_a_refusal_into_one_error_not_a_misspelt_key_per_row(pol, monkeypatch):
    """A refused kind composed no names. validate() reports the refusal, and does not then call
    every can_export row a misspelt key."""
    monkeypatch.setattr(vp, "known_export_profiles", lambda rows=None: (
        {}, ["REFUSED: fin-cdrl: ExportProfileError: a.yaml has no name"]))
    errs = vp.validate(pol, pol)
    assert [e for e in errs if e.startswith("export profiles: REFUSED: fin-cdrl:")], errs
    assert not [e for e in errs if "NOT a known export profile" in e], errs


# -- 7. grantees ---------------------------------------------------------------------------

def test_7_a_can_export_row_with_no_grantees_is_refused_by_load_capabilities():
    # Already true for ALL capability rows (load_capabilities); no can_export-specific check exists.
    _, errors = cgs.load_capabilities({"capabilities": {"can_export:x": _row(group=())}})
    assert errors and "grant_to or grant_to_groups" in errors[0], errors


# -- 8. the sync ---------------------------------------------------------------------------

class _Fake:
    def __init__(self, objects=(), relations=()):
        self.objects = set(objects)
        self.relations = set(relations)
        self.writes: list = []

    def object_exists(self, t, i):
        return DirObject(t, i) in self.objects

    def set_object(self, obj, display_name=""):
        self.writes.append(("set_object", obj))
        self.objects.add(obj)

    def set_relation(self, rel):
        self.writes.append(("set_relation", rel))
        self.relations.add(rel)

    def delete_relation(self, rel):
        self.writes.append(("delete_relation", rel))
        self.relations.discard(rel)

    def delete_object(self, obj, with_relations=True):
        self.writes.append(("delete_object", obj))
        self.objects.discard(obj)

    def list_objects(self, t):
        return sorted((o for o in self.objects if o.type == t), key=lambda o: o.id)

    def list_relations(self, object_type="", relation=""):
        return [r for r in self.relations
                if (not object_type or r.object_type == object_type)
                and (not relation or r.relation == relation)]

    def check(self, *a, **k):
        return True


MEMBER = DirRelation("capability", "can_export:x", "invoker", "group", GROUP, "member")
OBJ = DirObject("capability", "can_export:x")


def _caps(raw):
    caps, errors = cgs.load_capabilities({"capabilities": raw})
    assert not errors, errors
    return caps


def _after_row_then_deleted(prune):
    c = _Fake(objects=[DirObject("group", GROUP)])
    cgs.sync_capabilities(c, _caps({"can_export:x": _row()}), prune=prune)
    assert MEMBER in c.relations and OBJ in c.objects, "the row must land first"
    c.writes.clear()
    cgs.sync_capabilities(c, [], prune=prune)
    return c


def test_8_prune_true_revokes_the_invoker_relation_but_never_deletes_the_object():
    c = _after_row_then_deleted(prune=True)
    assert MEMBER not in c.relations
    assert ("delete_relation", MEMBER) in c.writes
    assert not [w for w in c.writes if w[0] == "delete_object"], c.writes
    assert OBJ in c.objects


def test_8_prune_false_keeps_the_relation_and_the_object():
    c = _after_row_then_deleted(prune=False)
    assert MEMBER in c.relations and OBJ in c.objects
    assert not [w for w in c.writes if w[0] in ("delete_relation", "delete_object")], c.writes


# -- 9. the CLI ----------------------------------------------------------------------------

def test_9_the_validate_policy_cli_is_green():
    r = subprocess.run([sys.executable, str(ROOT / "policy" / "sync" / "validate_policy.py")],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])
