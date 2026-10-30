"""The `can_export:<profile>` capability rail: DENY-BY-DEFAULT, unlike `can_drop`.

A profile with no `can_export:<P>` row is exportable by nobody; object existence decides nothing, so
the sync has no existence read and no object prune (deleting a row revokes through the invoker
relation prune). One row gates a single export and a batch alike (ruled 2026-10-29). The defaults are
met by COMPLETENESS: validate_policy refuses ANY known profile that no row decides, and names its
kind's default group -- alert-processors for a review-export profile (policy/exports), and
finance-analysts, the program-finance persona's group, for a fin CDRL profile (ruled 2026-10-29).
A profile can have its grantee ruled by name: plan_answers (fin's #148) goes to portfolio-leads,
not alert-processors -- "AP is notices" (ruled 2026-10-29). The seed ships a row for every profile it
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
    r = {"granted_by": "cnogradi", "reason": "test"}
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

def test_1_the_seed_composition(monkeypatch):
    monkeypatch.delenv("FIN_EXPORT_PROFILE_POLICY_DIR", raising=False)
    monkeypatch.delenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", raising=False)
    profiles, notes = vp.known_export_profiles()
    assert profiles.get(CDRL) == "fin_cdrl", profiles
    stems = {p.stem for p in (ROOT / "policy" / "exports").glob("*.yaml")}
    assert stems, "policy/exports ships no profile"
    assert {n for n, k in profiles.items() if k == "review_export"} == stems, (profiles, stems)
    exports = [n for n in notes if n.startswith((ROOT / "policy" / "exports").as_posix())]
    assert exports and exports[0].endswith(f"({len(stems)} profile(s))"), notes


# -- 2. the join seal with fin's loader ----------------------------------------------------

def test_2_fin_cdrl_names_equal_what_fins_loader_returns(monkeypatch):
    from agent_fleet.finance_agent import export_profiles
    from agent_fleet.finance_agent import main as engine

    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(ROOT / "policy/overlays/sample/measure_verbs"))
    declared = engine._load_declared()
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(SAMPLE))
    monkeypatch.delenv("FIN_EXPORT_PROFILE_POLICY_DIR", raising=False)
    loaded = {p.name for p in export_profiles.load_export_profiles(declared=declared)}
    ours = {n for n, k in vp.known_export_profiles()[0].items() if k == "fin_cdrl"}
    assert loaded and ours == loaded, (ours, loaded)



def test_2_the_fin_env_vars_move_the_seed_and_add_overlays(tmp_path, monkeypatch):
    """The two env vars fin reads, each seen on its own: the seed dir is MOVED (the repo seed's
    names are not read) and each overlay dir is ADDED. The join above sets the overlay var to the
    sample dir, which known_export_profiles also appends unconditionally, so it cannot see the
    var go unread."""
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p_seed"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p_ov"}})
    monkeypatch.setenv("FIN_EXPORT_PROFILE_POLICY_DIR", str(seed))
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(ov))
    profiles, notes = vp.known_export_profiles()
    assert profiles.get("p_seed") == "fin_cdrl", (profiles, notes)
    assert profiles.get("p_ov") == "fin_cdrl", (profiles, notes)
    assert (ROOT / "policy" / "fin_export_profiles").as_posix() not in " ".join(notes), notes


# -- 3. fin's semantics, on tmp dirs -------------------------------------------------------

def _compose(*dirs, kind="fin_cdrl"):
    return vp.known_export_profiles([(d, kind) for d in dirs])


def test_3_an_overlay_replaces_a_same_name_row_and_stays_known_once(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1", "label": "old"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p1", "label": "new"}})
    profiles, notes = _compose(seed, ov)
    assert profiles == {"p1": "fin_cdrl"}
    assert not [n for n in notes if "COLLISION" in n], notes


def test_3_a_tombstone_removes_the_name(tmp_path):
    seed = _profile_dir(tmp_path, "seed", {"a": {"name": "p1"}, "c": {"name": "p2"}})
    ov = _profile_dir(tmp_path, "ov", {"b": {"name": "p1", "deleted": True}})
    profiles, _ = _compose(seed, ov)
    assert profiles == {"p2": "fin_cdrl"}


def test_3_a_later_directory_wins(tmp_path):
    first = _profile_dir(tmp_path, "first", {"a": {"name": "p1", "deleted": True}})
    second = _profile_dir(tmp_path, "second", {"b": {"name": "p1"}})
    assert _compose(first, second)[0] == {"p1": "fin_cdrl"}
    assert _compose(second, first)[0] == {}


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
    """The seed's review-export profiles (policy/exports), read from the loader, not restated."""
    profiles, _ = vp.known_export_profiles()
    return {n: k for n, k in profiles.items() if k == "review_export"}


def _known(monkeypatch, profiles, notes=("n (1 profile(s))",)):
    """Fake the profile set as the seed's review-export profiles plus `profiles`: the seed ships a
    row for each of those, and a row naming an unknown profile is refused."""
    merged = {**_seed_review(), **profiles}
    monkeypatch.setattr(vp, "known_export_profiles", lambda sources=None: (dict(merged), list(notes)))


def test_4_baseline_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl"})
    assert vp.validate(pol, pol) == []


def test_4_an_unknown_can_export_name_is_refused(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl"})
    _add(pol, "can_export:nosuch", _row())
    errs = vp.validate(pol, pol)
    assert any("can_export:nosuch" in e and "NOT a known export profile" in e for e in errs), errs


def test_4_a_known_cdrl_name_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl"})
    _add(pol, f"can_export:{CDRL}", _row())
    assert vp.validate(pol, pol) == []


def test_4_a_known_review_export_name_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl", "ingest_review": "review_export"})
    _add(pol, "can_export:ingest_review", _row())
    assert vp.validate(pol, pol) == []


# -- 5. completeness -----------------------------------------------------------------------

def _no_row(errs, name):
    return [e for e in errs if f"profile {name!r} has no" in e and "NOBODY could export it" in e]


def test_5_a_review_export_profile_with_no_row_is_refused(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl", "ingest_review": "review_export"})
    hit = _no_row(vp.validate(pol, pol), "ingest_review")
    assert len(hit) == 1 and "review-export profile" in hit[0], hit
    assert f"grant_to_groups: [{GROUP}]" in hit[0] and FIN_GROUP not in hit[0], hit


def test_5_with_the_row_present_it_passes(pol, monkeypatch):
    _known(monkeypatch, {CDRL: "fin_cdrl", "ingest_review": "review_export"})
    _add(pol, "can_export:ingest_review", _row())
    assert vp.validate(pol, pol) == []


def test_5_a_cdrl_profile_with_no_row_is_refused_and_names_the_finance_group(pol, monkeypatch):
    """Ruled 2026-10-29: completeness covers CDRL profiles too, and their default is the
    program-finance persona's group, NOT alert-processors (the rejected single default)."""
    _known(monkeypatch, {CDRL: "fin_cdrl", "cdrl_b": "fin_cdrl"})
    hit = _no_row(vp.validate(pol, pol), "cdrl_b")
    assert len(hit) == 1 and "fin CDRL profile" in hit[0], hit
    assert f"grant_to_groups: [{FIN_GROUP}]" in hit[0] and GROUP not in hit[0], hit


def test_5_the_seed_cdrl_row_is_what_keeps_the_seed_green(pol, monkeypatch):
    """CONTROL for the arm above on the real seed: delete the shipped row and the seed's own
    profile is refused."""
    _known(monkeypatch, {CDRL: "fin_cdrl"})
    p = pol / "capability_grants.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    del data["capabilities"][f"can_export:{CDRL}"]
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert len(_no_row(vp.validate(pol, pol), CDRL)) == 1


def test_5_the_seed_ships_the_cdrl_row_to_the_finance_group():
    caps = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    row = caps["capabilities"][f"can_export:{CDRL}"]
    assert row.get("grant_to_groups") == [FIN_GROUP] and not row.get("grant_to"), row


def test_5_the_seed_ships_a_review_export_row_per_profile_to_the_default_group():
    """Every policy/exports profile ships its row at the review-export default, or at the group
    ruled for it by name (plan_answers: portfolio-leads, once fin's #148 ships the profile)."""
    caps = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    review = _seed_review()
    assert review, "no review-export profile in the seed"
    for name in sorted(review):
        row = caps["capabilities"].get(f"can_export:{name}")
        assert row is not None, name
        want = vp.EXPORT_PROFILE_GROUPS.get(name, vp.EXPORT_DEFAULT_GROUPS["review_export"])
        assert row.get("grant_to_groups") == [want] and not row.get("grant_to"), (name, row)


def test_5_plan_answers_with_no_row_names_portfolio_leads_not_the_kind_default(pol, monkeypatch):
    """Ruled 2026-10-29: plan_answers sits in policy/exports (review-export kind) but goes to
    portfolio-leads; "AP is notices". The refusal names the ruled group, not the kind's default."""
    _known(monkeypatch, {CDRL: "fin_cdrl", "plan_answers": "review_export"})
    hit = _no_row(vp.validate(pol, pol), "plan_answers")
    assert len(hit) == 1 and "review-export profile" in hit[0], hit
    assert "grant_to_groups: [portfolio-leads]" in hit[0] and GROUP not in hit[0], hit


def test_5_each_ruled_profile_group_is_a_group_and_plan_answers_is_the_portfolio_lead_cell():
    """Derive, don't restate: plan_answers' group is the one whose grants carry PORTFOLIO_LEAD, and
    alice holds it in the sandbox (the ruling's "alice in sandbox")."""
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    for name, g in vp.EXPORT_PROFILE_GROUPS.items():
        assert g in groups and g not in vp.EXPORT_DEFAULT_GROUPS.values(), (name, g)
    lead = {name for name, body in groups.items()
            if any(isinstance(x, dict) and x.get("persona") == "PORTFOLIO_LEAD"
                   for x in ((body or {}).get("grants") or []))}
    assert lead == {vp.EXPORT_PROFILE_GROUPS["plan_answers"]}, lead
    users = yaml.safe_load((ROOT / "policy" / "users.yaml").read_text(encoding="utf-8"))["users"]
    alice = [u for u in users if u.get("id") == "alice@example.com"]
    assert len(alice) == 1 and vp.EXPORT_PROFILE_GROUPS["plan_answers"] in (alice[0].get("groups") or [])


def test_5_each_default_group_is_a_group_and_the_cdrl_one_is_program_finance():
    """Derive, don't restate: the CDRL default is the group whose grants carry the
    PROGRAM_FINANCE_ANALYST persona, read from groups.yaml."""
    groups = yaml.safe_load((ROOT / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    assert set(vp.EXPORT_DEFAULT_GROUPS) == {"review_export", "fin_cdrl"}
    for kind, g in vp.EXPORT_DEFAULT_GROUPS.items():
        assert g in groups, (kind, g)
    fin = {name for name, body in groups.items()
           if any(isinstance(x, dict) and x.get("persona") == "PROGRAM_FINANCE_ANALYST"
                  for x in ((body or {}).get("grants") or []))}
    assert fin == {vp.EXPORT_DEFAULT_GROUPS["fin_cdrl"]}, fin


# -- 6. a collision ------------------------------------------------------------------------

def test_6_the_same_name_in_both_kinds_is_a_collision(tmp_path):
    a = _profile_dir(tmp_path, "rev", {"a": {"name": "dup"}})
    b = _profile_dir(tmp_path, "cdrl", {"b": {"name": "dup"}})
    _, notes = vp.known_export_profiles([(a, "review_export"), (b, "fin_cdrl")])
    assert any(n.startswith("COLLISION:") and "'dup'" in n for n in notes), notes


def test_6_validate_turns_a_collision_into_an_error(pol, monkeypatch):
    monkeypatch.setattr(vp, "known_export_profiles", lambda sources=None: (
        {"dup": "fin_cdrl"}, ["COLLISION: 'dup' is a review_export profile and a fin_cdrl profile"]))
    errs = vp.validate(pol, pol)
    assert any("export profile COLLISION" in e and "'dup'" in e for e in errs), errs


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
