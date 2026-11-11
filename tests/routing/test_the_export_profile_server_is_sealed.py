"""The export-profile server, sealed (architect ruling, Job 24; NOT on 0.4.85). One seal per item,
each with a control that differs from the case only in the thing being decided.

  1. OVERLAY on the review-export loader: add, replace by name (a full replacement), tombstone, a
     tombstone of an unshipped name is that name's ProfileInvalid, a broken sibling never breaks the
     rest; one composed set (no second loader in src/ or agent_fleet/).
  2. FIELDS: `accepts` (kind names, by shape), `grain` (per_notice | per_part; `dedupe`), `version`
     (REQUIRED: a profile with none is a load error, so a record never carries a guessed one).
  3. SERVING: the listing holds only the profiles the caller may use, decided by asking the
     `can_export:<profile>` rail (policy rows), never a group constant; and the PRE-FLIGHT lists
     the unexportable notices with reasons BEFORE any file is built.
  4. ROUTE: POST /ingest/export/notices. The actor is the authenticated principal (a body-supplied
     one is refused); the record carries the notice ids, the profile id and the version USED, and
     the destination when given; a profile the caller may not use is refused at the route.
  5. SAMPLE: the generic `part-list` profile (per_part, one column) lives in the sample overlay.
  7. STATES (architect, Job 25): `exportable_states` is the profile's list of notice states, named
     as the status route serves them; a notice in a state the profile does not list is refused
     naming that state, one in a listed state is admitted; the shipped profiles stay [promoted];
     the record carries each notice's state; the sample gains `part-list-reviewed`.

Doubles are the review-export test file's own. Notice and kind names below are synthetic.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/routing/test_the_export_profile_server_is_sealed.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import export_profiles as ep  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402
    DOM_B, REV_C, ROOT, STRANGER, Ledger, _as, _install, _iid, _world,
)

BATCH = "ingest:exportBatch"
ONE_COL = "  - output: Ingest\n    source: {field: ingest_id}\n"
PART_COL = "  - output: Part\n    source: {field: mpn}\n"
OVERLAY_ENV = ep._OVERLAY_ENV
SAMPLE_DIR = ROOT / "policy" / "overlays" / "sample" / "exports"


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.delenv(ep._DIR_ENV, raising=False)
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    ep.clear_cache()
    yield
    gateway.app.dependency_overrides.clear()
    ep.clear_cache()


def _yaml(name="t", *, version=1, grain="per_part", extra="", columns=ONE_COL, fmt="json",
          label="T", version_line=None) -> str:
    v = f"version: {version}\n" if version_line is None else version_line
    return (f"column_map_version: 1\nname: {name}\nlabel: {label}\nformat: {fmt}\n"
            f"grain: {grain}\n{v}{extra}columns:\n{columns}")


def _dir(base, sub, **files):
    d = base / sub
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.yaml").write_text(text, encoding="utf-8")
    return d


def _compose(monkeypatch, seed, *overlays):
    monkeypatch.setenv(ep._DIR_ENV, str(seed))
    monkeypatch.setenv(OVERLAY_ENV, ":".join(map(str, overlays)) if len(overlays) < 2
                       else __import__("os").pathsep.join(map(str, overlays)))
    ep.clear_cache()
    return ep.load_profiles()


# 1. overlay ----------------------------------------------------------------------------------

def test_1_an_overlay_adds_a_profile_and_the_seed_alone_does_not_have_it(monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", a=_yaml("a"))
    ov = _dir(tmp_path, "ov", b=_yaml("b"))
    assert set(_compose(monkeypatch, seed)) == {"a"}                       # control: no overlay
    got = _compose(monkeypatch, seed, ov)
    assert set(got) == {"a", "b"} and all(isinstance(p, ep.Profile) for p in got.values())


def test_1_an_overlay_row_replaces_by_name_with_no_field_merge(monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", a=_yaml("a", version=1, extra="accepts: [k-one]\n"))
    ov = _dir(tmp_path, "ov", a=_yaml("a", version=2))                    # says nothing of accepts
    assert _compose(monkeypatch, seed)["a"].accepts == ("k-one",)          # control: the seed's
    got = _compose(monkeypatch, seed, ov)["a"]
    assert got.version == 2 and got.accepts is None                        # replaced, not merged


def test_1_a_tombstone_removes_a_seed_profile_and_one_for_an_unshipped_name_is_an_error(
        monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", a=_yaml("a"), keep=_yaml("keep"))
    ov = _dir(tmp_path, "ov", a="name: a\ndeleted: true\n", ghost="name: ghost\ndeleted: true\n")
    got = _compose(monkeypatch, seed, ov)
    assert "a" not in got and isinstance(got["keep"], ep.Profile)
    assert isinstance(got["ghost"], ep.ProfileInvalid) and got["ghost"].reason == "tombstone_unshipped"
    # control: the same tombstone file for a name the seed DOES ship is no error
    assert not [k for k, v in got.items() if k == "a"]


def test_1_a_tombstone_in_the_seed_is_refused_and_a_broken_overlay_row_breaks_no_other(
        monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", a=_yaml("a"), dead="name: dead\ndeleted: true\n")
    ov = _dir(tmp_path, "ov", broken="name: broken\n", good=_yaml("good"))
    got = _compose(monkeypatch, seed, ov)
    assert got["dead"].reason == "tombstone_outside_overlay"
    assert isinstance(got["broken"], ep.ProfileInvalid)
    assert isinstance(got["a"], ep.Profile) and isinstance(got["good"], ep.Profile)


def test_1_later_overlays_win_over_earlier_ones(monkeypatch, tmp_path):
    seed = _dir(tmp_path, "seed", a=_yaml("a", version=1))
    o1 = _dir(tmp_path, "o1", a=_yaml("a", version=2))
    o2 = _dir(tmp_path, "o2", a=_yaml("a", version=3))
    assert _compose(monkeypatch, seed, o1, o2)["a"].version == 3
    assert _compose(monkeypatch, seed, o2, o1)["a"].version == 2          # control: order decides


def test_1_there_is_one_composed_set_no_second_loader_reads_the_variable():
    import subprocess

    out = subprocess.run(
        ["git", "grep", "-l", "-e", "INGEST_EXPORT_PROFILE_OVERLAY_DIRS", "--", "src", "agent_fleet"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split()
    assert out == ["src/iagent/export_profiles.py"], out
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert "load_profiles()" in src and "yaml.safe_load" not in src.split("_EXPORT_BATCH_CAPABILITY")[1][:20000]


# 2. fields -----------------------------------------------------------------------------------

def test_2_version_is_required_and_a_positive_int():
    ep.validate("t", yaml.safe_load(_yaml("t", version=1)))                # control: valid
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate("t", yaml.safe_load(_yaml("t", version_line="")))
    assert (e.value.reason, e.value.detail) == ("missing_key", "version")
    for bad in ("0", "-1", "true", "'1'", "1.5"):
        with pytest.raises(ep.ProfileInvalid) as e:
            ep.validate("t", yaml.safe_load(_yaml("t", version_line=f"version: {bad}\n")))
        assert e.value.reason == "version_invalid", bad


def test_2_the_seed_profiles_all_declare_a_version():
    for p in (ROOT / "policy" / "exports").glob("*.yaml"):
        assert isinstance(ep.validate(p.stem, yaml.safe_load(p.read_text(encoding="utf-8"))).version, int)


def test_2_accepts_is_checked_by_shape_never_against_an_enum():
    ok = ep.validate("t", yaml.safe_load(_yaml("t", extra="accepts: [any-kind_1, other.kind]\n")))
    assert ok.accepts == ("any-kind_1", "other.kind")                     # a name no code lists
    assert ep.validate("t", yaml.safe_load(_yaml("t"))).accepts is None   # control: omitted = any
    for bad in ("accepts: []\n", "accepts: kind\n", "accepts: [Bad]\n", "accepts: [a, a]\n",
                "accepts: [1]\n", "accepts: ['a b']\n"):
        with pytest.raises(ep.ProfileInvalid) as e:
            ep.validate("t", yaml.safe_load(_yaml("t", extra=bad)))
        assert e.value.reason == "accepts_invalid", bad


def test_2_grain_is_a_closed_vocabulary_and_maps_to_the_granularity():
    assert ep.validate("t", yaml.safe_load(_yaml("t", grain="per_part"))).granularity == "notice_part"
    assert ep.validate("t", yaml.safe_load(_yaml("t", grain="per_notice"))).granularity == "notice"
    assert ep.validate("t", yaml.safe_load(_yaml("t", grain="per_part"))).grain == "per_part"
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate("t", yaml.safe_load(_yaml("t", grain="per_page")))
    assert e.value.reason == "grain_invalid"
    with pytest.raises(ep.ProfileInvalid) as e:                           # the two words disagree
        ep.validate("t", yaml.safe_load(_yaml("t", grain="per_part", extra="granularity: notice\n")))
    assert e.value.reason == "grain_granularity_disagree"
    legacy = _yaml("t").replace("grain: per_part\n", "granularity: notice_part\n")  # seeds' own word
    assert ep.validate("t", yaml.safe_load(legacy)).grain == "per_part"


def _two_notices():
    row = lambda i, mpn: {"ingest_id": f"n{i}", "rows": [{"part_index": 0, "mpn": mpn, "field": "x"}]}
    return [row(1, "P-1"), row(2, "P-1"), row(3, "P-2")]


def test_2_dedupe_keeps_the_first_of_each_and_no_dedupe_keeps_all():
    cols = PART_COL
    plain = ep.validate("t", yaml.safe_load(_yaml("t", columns=cols)))
    dd = ep.validate("t", yaml.safe_load(_yaml("t", columns=cols, extra="dedupe: [Part]\n")))
    assert [r["Part"] for r in ep.render_all(plain, _two_notices())] == ["P-1", "P-1", "P-2"]
    assert [r["Part"] for r in ep.render_all(dd, _two_notices())] == ["P-1", "P-2"]
    for bad in ("dedupe: []\n", "dedupe: [Nope]\n", "dedupe: Part\n", "dedupe: [Part, Part]\n"):
        with pytest.raises(ep.ProfileInvalid) as e:
            ep.validate("t", yaml.safe_load(_yaml("t", columns=cols, extra=bad)))
        assert e.value.reason == "dedupe_invalid", bad


# 3. serving ----------------------------------------------------------------------------------

def _door(monkeypatch, tmp_path, *, grants, who=STRANGER, profiles=None, worlds=(), domains=None):
    """Install worlds and the capability double over them. `grants`: capability strings that answer
    True. Returns the list of capabilities asked."""
    d = _dir(tmp_path, f"profiles{len(list(tmp_path.iterdir()))}", **(profiles or {"t": _yaml("t", version=7)}))
    monkeypatch.setenv(ep._DIR_ENV, str(d))
    ep.clear_cache()
    _install(monkeypatch, list(worlds))
    asks: list = []

    def can_invoke(capability, caller):
        asks.append(capability)
        return capability in grants

    monkeypatch.setattr(ht, "can_invoke_or_unavailable", can_invoke)
    _as(who, domains=domains or ("maintenance",))
    return asks


def _list():
    with TestClient(gateway.app) as c:
        return c.get("/ingest/export/profiles")


def test_3_the_listing_holds_only_what_the_rail_grants_the_caller(monkeypatch, tmp_path):
    two = {"a": _yaml("a"), "b": _yaml("b")}
    asks = _door(monkeypatch, tmp_path, grants={"can_export:a"}, profiles=two)
    r = _list()
    assert r.status_code == 200 and [p["name"] for p in r.json()] == ["a"]
    assert sorted(asks) == ["can_export:a", "can_export:b"]               # the rail was ASKED, per row
    _door(monkeypatch, tmp_path, grants={"can_export:zzz"}, profiles=two)
    assert _list().json() == []                                           # control: grants name others
    _door(monkeypatch, tmp_path, grants={"can_export:a", "can_export:b"}, profiles=two)
    assert [p["name"] for p in _list().json()] == ["a", "b"]              # control: both granted


def test_3_the_listing_carries_the_new_fields_and_a_group_name_decides_nothing(monkeypatch, tmp_path):
    _door(monkeypatch, tmp_path, grants={"can_export:t"},
          profiles={"t": _yaml("t", version=7, extra="accepts: [k-one]\n", grain="per_notice")})
    got = _list().json()
    assert got == [{"name": "t", "format": "json", "granularity": "notice", "label": "T",
                    "grain": "per_notice", "version": 7, "accepts": ["k-one"],
                    "exportable_states": list(ep.DEFAULT_EXPORTABLE_STATES), "dedupe": []}]
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    body = src.split("async def ingest_export_profiles_route")[1].split("@app.")[0]
    assert "alert-processors" not in body and "_may_export_profile" in body


def test_3_a_topaz_outage_on_the_listing_is_503_not_an_empty_list(monkeypatch, tmp_path):
    _door(monkeypatch, tmp_path, grants=set())

    def down(capability, caller):
        raise ht.AuthorizationUnavailable("down")

    monkeypatch.setattr(ht, "can_invoke_or_unavailable", down)
    assert _list().status_code == 503


# 3b. pre-flight ------------------------------------------------------------------------------

def _post(body):
    with TestClient(gateway.app) as c:
        return c.post("/ingest/export/notices", json=body)


@pytest.fixture
def built(monkeypatch):
    """Records every build: `_export_render` calls, `to_csv`/`to_json` calls, and `_record_export`."""
    calls = {"render": 0, "records": []}
    real = gateway._export_render

    def render(profile, bodies):
        calls["render"] += 1
        return real(profile, bodies)

    monkeypatch.setattr(gateway, "_export_render", render)
    monkeypatch.setattr(gateway, "_record_export", lambda rec: calls["records"].append(rec))
    return calls


def _mixed_world(monkeypatch, tmp_path, *, with_bad=True, profiles=None):
    good1, good2 = _world(1, REV_C), _world(2, REV_C)
    worlds = [good1, good2]
    if with_bad:
        worlds += [_world(3, REV_C, content_kind="other-kind"),      # kind not accepted
                   _world(4, REV_C, status="in_review"),             # not promoted
                   _world(5, REV_C)]                                 # out of the caller's domain
    asks = _door(monkeypatch, tmp_path, grants={BATCH, "can_export:t"}, worlds=worlds,
                 profiles=profiles or {"t": _yaml("t", version=7, extra="accepts: [pcn]\n")})
    Ledger.domains = {_iid(5): DOM_B}
    return asks


def test_3_the_preflight_lists_every_unexportable_notice_with_its_reason_and_builds_nothing(
        monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path)
    ids = [_iid(i) for i in (1, 2, 3, 4, 5)] + [_iid(99)]
    r = _post({"notice_ids": ids, "profile": "t"})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "export_notices_unexportable"
    assert {(u["notice_id"], u["reason"]) for u in d["unexportable"]} == {
        (_iid(3), "kind_not_accepted"), (_iid(4), "state_not_exportable"),
        (_iid(5), "not_available"), (_iid(99), "not_available")}   # out-of-scope = unknown: no oracle
    assert built["render"] == 0 and built["records"] == []          # NO FILE BUILT, nothing recorded


def test_3_check_only_lists_the_same_and_builds_nothing_even_when_all_are_fine(
        monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path)
    r = _post({"notice_ids": [_iid(1), _iid(3)], "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["unexportable"] == [
        {"notice_id": _iid(3), "reason": "kind_not_accepted"}]
    assert (r.json()["profile"], r.json()["version"]) == ("t", 7)
    r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["unexportable"] == []
    assert built["render"] == 0 and built["records"] == []


def test_3_control_with_every_notice_exportable_the_file_is_built(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t"})
    assert r.status_code == 200, r.text
    assert built["render"] == 1 and len(built["records"]) == 1


def test_3_a_profile_with_no_accepts_takes_any_kind(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, profiles={"t": _yaml("t", version=7)})
    r = _post({"notice_ids": [_iid(3)], "profile": "t", "check_only": True})
    assert r.json()["unexportable"] == []


# 4. route ------------------------------------------------------------------------------------

def test_4_the_record_carries_actor_ids_profile_version_and_destination(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    ids = [_iid(1), _iid(2)]
    r = _post({"notice_ids": ids, "profile": "t", "destination": "outbound-a"})
    assert r.status_code == 200, r.text
    assert built["records"] == [{"actor": STRANGER, "notice_ids": ids,
                                 "notice_states": {i: ist.PROMOTED for i in ids},
                                 "profile": "t", "version": 7, "destination": "outbound-a"}]
    assert r.headers["X-Export-Profile"] == "t" and r.headers["X-Export-Profile-Version"] == "7"
    assert r.json()["destination"] == "outbound-a"


def test_4_without_a_destination_the_record_says_none(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert r.status_code == 200
    assert built["records"][0]["destination"] is None and "destination" in built["records"][0]


def test_4_the_version_recorded_is_the_one_the_composed_profile_carries(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False, profiles={"t": _yaml("t", version=42)})
    assert _post({"notice_ids": [_iid(1)], "profile": "t"}).status_code == 200
    assert built["records"][0]["version"] == 42


def test_4_a_body_supplied_actor_is_refused_and_the_principal_is_the_actor(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    r = _post({"notice_ids": [_iid(1)], "profile": "t", "actor": "someone-else"})
    assert r.status_code == 422 and built["records"] == [] and built["render"] == 0
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})                  # control: same body, no actor
    assert r.status_code == 200 and built["records"][0]["actor"] == STRANGER


def test_4_a_profile_the_caller_may_not_use_is_refused_at_the_route_too(monkeypatch, tmp_path, built):
    asks = _door(monkeypatch, tmp_path, grants={BATCH}, worlds=[_world(1, REV_C)])
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_export"
    assert d["refusal"]["policy_id"] == "capability_grants:can_export:t"
    assert built["render"] == 0 and built["records"] == []
    assert asks == [BATCH, "can_export:t"]
    _door(monkeypatch, tmp_path, grants={BATCH, "can_export:t"},
          worlds=[_world(1, REV_C)], profiles={"t": _yaml("t")})
    assert _post({"notice_ids": [_iid(1)], "profile": "t"}).status_code == 200   # control: granted


def test_4_without_the_batch_capability_the_profile_is_not_even_asked(monkeypatch, tmp_path, built):
    asks = _door(monkeypatch, tmp_path, grants={"can_export:t"}, worlds=[_world(1, REV_C)])
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled_to_export_batch"
    assert asks == [BATCH]


def test_4_an_unknown_profile_is_422_and_an_empty_id_list_is_422(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    r = _post({"notice_ids": [_iid(1)], "profile": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown"
    r = _post({"notice_ids": [], "profile": "t"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_notice_ids_invalid"


# 5. the sample profile -----------------------------------------------------------------------

def test_5_the_sample_overlay_carries_a_generic_one_column_per_part_profile(monkeypatch, tmp_path):
    assert not (ROOT / "policy" / "exports" / "part-list.yaml").exists()  # not in the seed path
    seed = ROOT / "policy" / "exports"
    assert "part-list" not in _compose(monkeypatch, seed)                  # control: seed alone
    got = _compose(monkeypatch, seed, SAMPLE_DIR)["part-list"]
    assert isinstance(got, ep.Profile)
    assert got.grain == "per_part" and len(got.columns) == 1 and got.accepts is None
    assert got.dedupe == (got.columns[0].output,)
    assert [r["Part"] for r in ep.render_all(got, _two_notices())] == ["P-1", "P-2"]
    text = (SAMPLE_DIR / "part-list.yaml").read_text(encoding="utf-8")
    assert text.startswith("# SAMPLE")


def test_5_the_sample_has_a_can_export_row_and_the_registry_row_composes_it():
    rows = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    assert "can_export:part-list" in str(rows)
    src = yaml.safe_load((ROOT / "policy" / "export_profile_sources.yaml").read_text(encoding="utf-8"))
    row = next(r for r in src["sources"] if r["kind"] == "review-export")
    assert row["overlay_env"] == OVERLAY_ENV
    assert "policy/overlays/sample/exports" in row["offline_overlays"]


# 6. the wire says notice_id; the two gates; check_only (architect rulings 2026-11-11) ---------

def _keys(obj, out=None):
    """Every dict key at any depth."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


_BANNED = {"ingest_id", "ingest_ids"}


def test_6_the_seal_for_the_wire_key_can_go_red():
    assert _keys({"unexportable": [{"ingest_id": "x"}]}) & _BANNED          # the control: it sees one
    assert not (_keys({"unexportable": [{"notice_id": "x"}]}) & _BANNED)


def test_6_no_response_or_record_key_is_ingest_id(monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path)
    ids = [_iid(i) for i in (1, 3, 4, 5, 99)]
    seen = set()
    seen |= _keys(_post({"notice_ids": ids, "profile": "t"}).json())              # 422 list
    seen |= _keys(_post({"notice_ids": ids, "profile": "t", "check_only": True}).json())
    ok = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t", "destination": "d"})
    assert ok.status_code == 200
    seen |= _keys(ok.json()) | set(ok.headers)
    for rec in built["records"]:
        seen |= _keys(rec)
    assert built["records"], "the record was not seen"
    assert "notice_id" in seen and "notice_ids" in seen
    assert not (seen & _BANNED), seen & _BANNED


def test_6_each_gate_alone_is_refused_and_both_together_admit(monkeypatch, tmp_path, built):
    for grants, want in (({BATCH}, "not_entitled_to_export"),
                         ({"can_export:t"}, "not_entitled_to_export_batch")):
        _door(monkeypatch, tmp_path, grants=grants, worlds=[_world(1, REV_C)])
        for body in ({"notice_ids": [_iid(1)], "profile": "t"},
                     {"notice_ids": [_iid(1)], "profile": "t", "check_only": True}):
            r = _post(body)
            assert r.status_code == 403 and r.json()["detail"]["error"] == want, (grants, body)
    assert built["render"] == 0 and built["records"] == []
    _door(monkeypatch, tmp_path, grants={BATCH, "can_export:t"}, worlds=[_world(1, REV_C)])
    assert _post({"notice_ids": [_iid(1)], "profile": "t"}).status_code == 200      # control


def test_6_check_only_records_nothing_and_the_same_call_without_it_records_once(
        monkeypatch, tmp_path, built):
    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    body = {"notice_ids": [_iid(1), _iid(2)], "profile": "t", "destination": "d"}
    assert _post({**body, "check_only": True}).status_code == 200
    assert built["records"] == [] and built["render"] == 0
    assert _post(body).status_code == 200
    assert len(built["records"]) == 1 and built["render"] == 1                      # control


def test_6_there_is_one_notice_route_and_no_resolve_route():
    paths = {(m, r.path) for r in gateway.app.routes if hasattr(r, "methods")
             for m in r.methods if r.path.startswith("/ingest") and "/export" in r.path}
    assert ("POST", "/ingest/export/notices") in paths
    assert not [p for p in paths if "resolve" in p[1]], paths
    assert [p for p in paths if p[0] == "POST"] == [("POST", "/ingest/export/notices")], paths


def test_6_the_record_LINE_that_arrives_carries_notice_ids_and_no_ingest_key(
        monkeypatch, tmp_path, caplog):
    import json as _json
    import logging

    _mixed_world(monkeypatch, tmp_path, with_bad=False)
    with caplog.at_level(logging.INFO, logger="iagent.audit.ingest_export"):
        r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t", "destination": "d"})
    assert r.status_code == 200
    lines = [m for m in caplog.messages if m.startswith("ingest_export ")]
    assert len(lines) == 1, caplog.messages
    rec = _json.loads(lines[0].split(" ", 1)[1])
    assert rec == {"actor": STRANGER, "notice_ids": [_iid(1), _iid(2)],
                   "notice_states": {_iid(1): ist.PROMOTED, _iid(2): ist.PROMOTED},
                   "profile": "t", "version": 7, "destination": "d"}
    assert not (_keys(rec) & _BANNED)


# 7. exportable_states (architect, Job 25) ----------------------------------------------------
# The vocabulary is SERVED, not typed here: `ingest_status.ALL_STATUSES` is what the status route's
# `stage` carries, and every state name below is read from that module's own constants.

REVIEW = ist.REVIEW
SEED = ROOT / "policy" / "exports"


def _states_line(*names):
    return "exportable_states: [" + ", ".join(names) + "]\n"


def _open_review_world(monkeypatch, tmp_path, *, extra, statuses, domain=None):
    """Notices 1..n at `statuses`. A notice that is not promoted has NO decision record, and its
    domain is the one its open `document_promotion:<domain>` task names (what the review page's
    steward acts on)."""
    worlds = [_world(i + 1, REV_C, status=st) for i, st in enumerate(statuses)]
    _door(monkeypatch, tmp_path, grants={BATCH, "can_export:t"}, worlds=worlds,
          profiles={"t": _yaml("t", version=7, extra=extra)})
    for i, st in enumerate(statuses):
        if st != ist.PROMOTED:
            Ledger.records[_iid(i + 1)] = None
    audience = f"document_promotion:{domain or 'maintenance'}"
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: {"audience": audience, "open": True})


def _unexportable(r):
    return r.json()["detail"]["unexportable"]


def test_7_a_notice_below_the_profiles_states_is_refused_naming_its_state(
        monkeypatch, tmp_path, built):
    _open_review_world(monkeypatch, tmp_path, extra="", statuses=[ist.PROMOTED, REVIEW])
    r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "export_notices_unexportable"
    assert _unexportable(r) == [
        {"notice_id": _iid(2), "reason": "state_not_exportable", "state": REVIEW}]
    assert built["render"] == 0 and built["records"] == []
    c = _post({"notice_ids": [_iid(2)], "profile": "t", "check_only": True})
    assert c.status_code == 200 and c.json()["unexportable"] == [
        {"notice_id": _iid(2), "reason": "state_not_exportable", "state": REVIEW}]


def test_7_control_the_same_notice_at_a_listed_state_is_admitted(monkeypatch, tmp_path, built):
    # differs from the case above ONLY in the profile's list: the notice is the same `review` one
    _open_review_world(monkeypatch, tmp_path, extra=_states_line(REVIEW, ist.PROMOTED),
                       statuses=[ist.PROMOTED, REVIEW])
    r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t"})
    assert r.status_code == 200, r.text
    assert built["render"] == 1 and len(built["records"]) == 1


def test_7_a_state_the_profile_does_not_list_is_refused_though_another_is_listed(
        monkeypatch, tmp_path, built):
    # the profile lists review; a notice at `received` (the only difference) is refused by name
    _open_review_world(monkeypatch, tmp_path, extra=_states_line(REVIEW),
                       statuses=[REVIEW, ist.RECEIVED])
    r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t"})
    assert r.status_code == 422
    assert _unexportable(r) == [
        {"notice_id": _iid(2), "reason": "state_not_exportable", "state": ist.RECEIVED}]
    ok = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert ok.status_code == 200, ok.text


def test_7_the_wire_key_of_a_state_refusal_is_still_notice_id(monkeypatch, tmp_path, built):
    _open_review_world(monkeypatch, tmp_path, extra="", statuses=[REVIEW])
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert _keys(r.json()) & {"notice_id", "state"} == {"notice_id", "state"}
    assert not (_keys(r.json()) & _BANNED)


def test_7_an_unpromoted_notice_is_scoped_to_the_domain_its_open_task_names(
        monkeypatch, tmp_path, built):
    states = _states_line(REVIEW)
    _open_review_world(monkeypatch, tmp_path, extra=states, statuses=[REVIEW])
    assert _post({"notice_ids": [_iid(1)], "profile": "t", "check_only": True}
                 ).json()["unexportable"] == []                     # control: the caller's domain
    _open_review_world(monkeypatch, tmp_path, extra=states, statuses=[REVIEW], domain=DOM_B)
    got = _post({"notice_ids": [_iid(1)], "profile": "t", "check_only": True}).json()
    assert got["unexportable"] == [{"notice_id": _iid(1), "reason": "not_available"}]
    _open_review_world(monkeypatch, tmp_path, extra=states, statuses=[REVIEW])
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: {"audience": "x", "open": False})
    got = _post({"notice_ids": [_iid(1)], "profile": "t", "check_only": True}).json()
    assert got["unexportable"] == [{"notice_id": _iid(1), "reason": "not_available"}]


def test_7_a_review_task_store_fault_is_503_not_a_reason(monkeypatch, tmp_path, built):
    _open_review_world(monkeypatch, tmp_path, extra=_states_line(REVIEW), statuses=[REVIEW])

    def boom(t):
        raise RuntimeError("task store down")

    monkeypatch.setattr(ht, "get_task_open_state", boom)
    r = _post({"notice_ids": [_iid(1)], "profile": "t"})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "review_task_unreachable"


def test_7_the_record_carries_each_notices_state_on_the_line_that_arrives(
        monkeypatch, tmp_path, caplog):
    import json as _json
    import logging

    _open_review_world(monkeypatch, tmp_path, extra=_states_line(REVIEW, ist.PROMOTED),
                       statuses=[ist.PROMOTED, REVIEW])
    with caplog.at_level(logging.INFO, logger="iagent.audit.ingest_export"):
        r = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t"})
    assert r.status_code == 200, r.text
    lines = [m for m in caplog.messages if m.startswith("ingest_export ")]
    assert len(lines) == 1
    rec = _json.loads(lines[0].split(" ", 1)[1])
    assert rec["notice_states"] == {_iid(1): ist.PROMOTED, _iid(2): REVIEW}


def test_7_the_state_list_is_validated_against_the_served_set_by_name():
    ok = ep.validate("t", yaml.safe_load(_yaml("t", extra=_states_line(REVIEW, ist.PROMOTED))))
    assert ok.exportable_states == (REVIEW, ist.PROMOTED)
    assert set(ok.exportable_states) <= set(ist.ALL_STATUSES)
    for bad, why in (("exportable_states: [reviewed]\n", "exportable_states_unserved"),
                     ("exportable_states: []\n", "exportable_states_invalid"),
                     ("exportable_states: promoted\n", "exportable_states_invalid"),
                     ("exportable_states: [review, review]\n", "exportable_states_invalid"),
                     ("exportable_states: [1]\n", "exportable_states_invalid")):
        with pytest.raises(ep.ProfileInvalid) as e:
            ep.validate("t", yaml.safe_load(_yaml("t", extra=bad)))
        assert e.value.reason == why, bad


def test_7_a_profile_with_no_states_takes_the_default_read_from_the_code():
    p = ep.validate("t", yaml.safe_load(_yaml("t")))
    assert p.exportable_states == ep.DEFAULT_EXPORTABLE_STATES == (ist.PROMOTED,)


def test_7_the_shipped_profiles_are_unchanged_they_admit_promoted_only(monkeypatch):
    monkeypatch.setenv(ep._DIR_ENV, str(SEED))
    ep.clear_cache()
    shipped = ep.load_profiles()
    assert set(shipped) == {"default-csv", "default-json"}, "a profile was added to the seed"
    for name, prof in shipped.items():
        raw = yaml.safe_load((SEED / f"{name}.yaml").read_text(encoding="utf-8"))
        assert raw["exportable_states"] == list(ep.DEFAULT_EXPORTABLE_STATES), name   # declared
        assert prof.exportable_states == ep.DEFAULT_EXPORTABLE_STATES, name


def test_7_a_shipped_profile_refuses_a_review_notice_and_admits_the_promoted_one(
        monkeypatch, tmp_path, built):
    text = (SEED / "default-json.yaml").read_text(encoding="utf-8")
    worlds = [_world(1, REV_C, status=ist.PROMOTED), _world(2, REV_C, status=REVIEW)]
    _door(monkeypatch, tmp_path, grants={BATCH, "can_export:default-json"}, worlds=worlds,
          profiles={"default-json": text})
    Ledger.records[_iid(2)] = None
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: {"audience": "document_promotion:maintenance", "open": True})
    r = _post({"notice_ids": [_iid(2)], "profile": "default-json"})
    assert r.status_code == 422
    assert _unexportable(r) == [
        {"notice_id": _iid(2), "reason": "state_not_exportable", "state": REVIEW}]
    ok = _post({"notice_ids": [_iid(1)], "profile": "default-json"})       # control: promoted
    assert ok.status_code == 200, ok.text


def test_7_the_sample_overlay_gains_part_list_reviewed_naming_a_served_state(monkeypatch):
    assert "part-list-reviewed" not in _compose(monkeypatch, SEED)           # control: seed alone
    composed = _compose(monkeypatch, SEED, SAMPLE_DIR)
    got = composed["part-list-reviewed"]
    assert isinstance(got, ep.Profile) and got.label == "Part list (reviewed)"
    assert got.exportable_states == (REVIEW, ist.PROMOTED)
    assert set(got.exportable_states) <= set(ist.ALL_STATUSES)
    assert composed["part-list"].exportable_states == ep.DEFAULT_EXPORTABLE_STATES  # unchanged
    rows = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))
    assert "can_export:part-list-reviewed" in str(rows)
