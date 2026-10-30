"""SEAL (Lane saf's review of PR #154): the review export against three of the architect's seals.

  s2. A batch export is filtered by the caller's cells -- by the REAL `PgDecisionLedger.promoted_between`
      filter, not the `Ledger` double in test_a_review_export_resolves_every_column_or_refuses.py (that
      double reimplements the filter, so mutating the real one stayed green). The cell is the
      persona.domain pair; the shipped rule (architect 2026-10-29, "domain-scoped") reads the DOMAIN of
      each cell and ignores the persona. Mixed cells, the single-vs-batch pair, and an unreadable
      record are all sealed here.
  s3. No profile reaches outside the catalogue. The profile set is DERIVED from the loader
      (`load_profiles()` over the shipped dir, plus a maximal profile that names every catalogue
      source), never typed. Out-of-catalogue sources, store/path-shaped names and traversal names in
      `?profile=` are refused at load time or request time.
  s4. Steward edits and the provenance rung (`obtained_via`, incl. `steward_corrected`) survive every
      profile. TODAY the export does not serve edits at all: a promotion carrying row or header edits
      is refused (single 409 / batch 422 `export_corrections_not_applied`) for EVERY profile, so no
      profile drops them silently (held, below). The seal as worded -- the edits and the rung COME OUT
      -- is a gap: the two strict xfails name it. `obtained_via` is in the catalogue (ROW_SHARED) and
      passes through `render_rows` for every profile that names it; no shipped profile names it.
"""
from __future__ import annotations

import copy
import json
import re

import pytest
import yaml

pytest.importorskip("fastapi")

from src.iagent import export_profiles as ep  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion_stores  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402,F401
    CAP, DOM_A, DOM_B, DROPPER, ROOT, STRANGER, SIMPLE, Ledger, _as, _cleanup, _get, _iid, _install,
    _ms, _review, _use_profiles, _world,
)

DOM_C = "finance"
_RealPg = promotion_stores.PgDecisionLedger     # captured before any test patches the module


def _rec(domain, **inputs):
    audience = f"document_promotion:{domain}" if domain else "garbage"
    return {"checks": [{"name": "human_review", "inputs": {"audience": audience, **inputs}}]}


def _real_ledger(records: dict):
    """The REAL `PgDecisionLedger` (its real `promoted_between`), over a fake connection serving
    `{ingest_id: (acted_at_ms, record)}`; only `record_for` is a double (it is not under test)."""
    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            _dec, lo, hi = params
            self.rows = [(i, a, r) for i, (a, r) in sorted(
                records.items(), key=lambda kv: (kv[1][0], kv[0])) if lo <= a < hi]

        def __iter__(self):
            return iter(self.rows)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cur()

    class _L(_RealPg):
        def __init__(self):
            super().__init__(connect=lambda: _Conn())

        def record_for(self, ingest_id):
            return records[ingest_id][1]

    return _L


# ── s2: the batch is filtered by cells, by the real filter ────────────────────────────────────────

AT = _ms(2026, 10, 1, 6)
RECORDS = {
    _iid(1): (AT + 1, _rec(DOM_A)),
    _iid(2): (AT + 2, _rec(DOM_B)),
    _iid(3): (AT + 3, _rec(DOM_C)),
    _iid(4): (AT + 4, _rec(None)),                      # an audience that names no domain
    _iid(5): (AT + 5, {"checks": []}),                  # no human_review check at all
    _iid(6): (AT + 6, _rec(DOM_A)),
}


def test_s2_the_real_filter_keeps_only_the_wanted_domains_and_counts_the_limit_in_domain():
    led = _real_ledger(RECORDS)()
    ids = lambda hits: [i for i, _ in hits]   # noqa: E731
    assert ids(led.promoted_between(AT, AT + 100, 50, {DOM_A, DOM_B})) == [_iid(1), _iid(2), _iid(6)]
    assert ids(led.promoted_between(AT, AT + 100, 50, {DOM_A})) == [_iid(1), _iid(6)]
    assert ids(led.promoted_between(AT, AT + 100, 50, {DOM_C})) == [_iid(3)]
    # the limit counts IN-DOMAIN promotions: an out-of-domain row before it does not use a slot
    assert ids(led.promoted_between(AT, AT + 100, 1, {DOM_B})) == [_iid(2)]
    assert ids(led.promoted_between(AT, AT + 100, 2, {DOM_A})) == [_iid(1), _iid(6)]
    # no domain, no rows -- and a record with no readable domain is in no domain
    assert led.promoted_between(AT, AT + 100, 50, set()) == []
    assert _iid(4) not in ids(led.promoted_between(AT, AT + 100, 50, {DOM_A, DOM_B, DOM_C, "garbage", ""}))
    assert _iid(5) not in ids(led.promoted_between(AT, AT + 100, 50, {DOM_A, DOM_B, DOM_C}))


def test_s2_a_cell_cannot_carry_no_domain_so_the_route_never_asks_for_none():
    """Why the xfail below is latent, not live: the route's wanted set is `{c.domain for c in cells}`
    and `EntitlementCell.domain` is a required `str`."""
    from pydantic import ValidationError

    from src.iagent.authz.topaz_client import EntitlementCell

    with pytest.raises(ValidationError):
        EntitlementCell(persona="p", domain=None)


@pytest.mark.xfail(strict=True, reason=(
    "LATENT, unreachable today: PgDecisionLedger.promoted_between tests `recorded_domain(rec) in "
    "wanted`, and recorded_domain is None for a record with no readable domain, so a wanted set "
    "containing None would admit every unreadable record. The route cannot build such a set "
    "(EntitlementCell.domain is a str); the filter does not defend itself."))
def test_s2_gap_none_in_the_wanted_set_does_not_match_a_record_with_no_domain():
    led = _real_ledger(RECORDS)()
    got = [i for i, _ in led.promoted_between(AT, AT + 100, 50, {DOM_A, None})]
    assert _iid(4) not in got and _iid(5) not in got


def _world_for(n):
    return _world(n, _review({0: {"affected_mpn": f"M{n}"}}))


def _batch_real(monkeypatch, tmp_path, domains, ns=(1, 2, 3, 4, 5, 6)):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world_for(n) for n in ns], topaz=(200, True))
    monkeypatch.setattr(promotion_stores, "PgDecisionLedger", _real_ledger(RECORDS))
    _as(STRANGER, domains=domains)
    return _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")


@pytest.mark.parametrize("domains,expect", [
    ((DOM_A,), ["M1", "M6"]),
    ((DOM_B,), ["M2"]),
    ((DOM_A, DOM_B), ["M1", "M2", "M6"]),               # mixed cells: the union, nothing else
    ((DOM_A, DOM_B, DOM_C), ["M1", "M2", "M3", "M6"]),  # the control: widen the cells, the row appears
    ((), []),
])
def test_s2_a_batch_through_the_real_filter_exports_only_the_callers_cells(
        monkeypatch, tmp_path, domains, expect):
    r = _batch_real(monkeypatch, tmp_path, domains)
    assert r.status_code == 200, r.text
    assert [x["Affected"] for x in r.json()["rows"]] == expect
    assert r.json()["notices"] == len(expect)


def test_s2_single_and_batch_agree_on_which_notices_a_caller_may_export(monkeypatch, tmp_path):
    cells = (DOM_A, DOM_B)
    batch = _batch_real(monkeypatch, tmp_path, cells)
    in_batch = {x["Affected"] for x in batch.json()["rows"]}
    for n in (1, 2, 3, 4, 5, 6):
        _as(STRANGER, domains=cells)
        s = _get(f"/ingest/{_iid(n)}/export?profile=t")
        assert (s.status_code == 200) == (f"M{n}" in in_batch), (n, s.status_code, s.text[:120])
        if s.status_code != 200:
            assert s.status_code == 403 and s.json()["detail"]["error"] == "not_entitled"


# ── s3: no profile reaches outside the catalogue ──────────────────────────────────────────────────

CATALOGUE_NOTICE = {"attempt", "content_kind", "corrected_by", "ingest_id", "leaf", "leaf_source",
                    "notice.mfr", "notice.mfr_parent", "notice.mfr_source", "notice.notice_date",
                    "notice_id", "part_count"}
CATALOGUE_UNSHARED = {"part_index", "mpn", "row_index"}
CATALOGUE_SHARED = {"evidence_ref", "extracted_value", "match_confidence", "needs_review",
                    "obtained_via", "review_reason", "source_snippet"}


def _maximal() -> dict:
    """A profile naming EVERY catalogue source (and every row_field for the shared ones)."""
    cols = [{"output": f, "source": {"field": f}} for f in sorted(ep.NOTICE_FIELDS)]
    cols += [{"output": f, "source": {"field": f}} for f in sorted(ep.ROW_UNSHARED)]
    cols += [{"output": f"{f}@{rf}", "source": {"field": f, "row_field": rf}}
             for f in sorted(ep.ROW_SHARED) for rf in ep.ROW_FIELDS]
    return {"column_map_version": 1, "name": "maximal", "label": "every catalogue source",
            "format": "json", "granularity": "notice_part", "columns": cols}


def _profile_dir(monkeypatch, tmp_path):
    """The shipped profiles + the maximal one, in a throwaway dir the loader reads."""
    for p in sorted((ROOT / "policy" / "exports").glob("*.yaml")):
        (tmp_path / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "maximal.yaml").write_text(yaml.safe_dump(_maximal(), sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("INGEST_EXPORT_PROFILE_DIR", str(tmp_path))
    ep.clear_cache()
    return tmp_path


def _valid_profiles(monkeypatch, tmp_path) -> dict:
    _profile_dir(monkeypatch, tmp_path)
    loaded = ep.load_profiles()
    valid = {k: v for k, v in loaded.items() if isinstance(v, ep.Profile)}
    assert {"default-csv", "default-json", "maximal"} <= set(valid), {k: str(v) for k, v in loaded.items()}
    assert set(loaded) == set(valid), {k: str(v) for k, v in loaded.items() if k not in valid}
    return valid


def test_s3_the_catalogue_is_the_reviewed_list():
    """Widening the catalogue is a deliberate act: it edits this list. (test_a pins the sets to the
    OpenAPI schemas; this pins them to what was reviewed, so a new model field cannot become a
    servable source -- say a store key or a path -- by being added to the model.)"""
    assert set(ep.NOTICE_FIELDS) == CATALOGUE_NOTICE
    assert set(ep.ROW_UNSHARED) == CATALOGUE_UNSHARED
    assert set(ep.ROW_SHARED) == CATALOGUE_SHARED
    assert ep.ROW_FIELDS == ("affected_mpn", "replacement_mpn", "ltb_date")
    pathish = re.compile(r"(prefix|bucket|path|uri|url|key|s3|object|manifest|relocat)", re.I)
    assert [f for f in CATALOGUE_NOTICE | CATALOGUE_UNSHARED | CATALOGUE_SHARED if pathish.search(f)] == []


def test_s3_every_profile_the_loader_accepts_names_only_catalogue_sources(monkeypatch, tmp_path):
    served = ep.NOTICE_FIELDS | ep.ROW_UNSHARED | ep.ROW_SHARED
    for name, prof in _valid_profiles(monkeypatch, tmp_path).items():
        seen = 0
        for c in prof.columns:
            if c.derived:
                assert c.source is None, (name, c.output)
                continue
            seen += 1
            assert c.source["field"] in served, (name, c.output, c.source)
            assert c.source["row_field"] is None or c.source["row_field"] in ep.ROW_FIELDS, (name, c.output)
        assert seen, f"{name}: a control profile with no sourced column proves nothing"


def test_s3_the_rendered_cells_are_exactly_the_declared_outputs(monkeypatch, tmp_path):
    ext = {"ingest_id": _iid(1), "notice_id": "PCN-1", "leaf": "pcn", "extraction_ref": "SECRET/KEY",
           "object_prefix": "ingress-user/pdf/x/", "review_ref": "k", "relocated_to": "q",
           "notice": {"mfr": "Acme", "notice_date": "2026-03-04", "object_key": "SECRET"},
           "rows": [{"part_index": 0, "field": "affected_mpn", "extracted_value": "A0",
                     "obtained_via": "text_layer", "object_key": "SECRET", "row_index": 0}]}
    for name, prof in _valid_profiles(monkeypatch, tmp_path).items():
        for cells in ep.render_rows(prof, ext):
            assert list(cells) == prof.outputs, name
            assert "SECRET" not in json.dumps(cells, default=str), name
            assert "ingress-user" not in json.dumps(cells, default=str), name


OUT_OF_CATALOGUE = [
    "extraction_ref", "object_prefix", "status", "submitted_by", "on_behalf_of", "relocated_to",
    "review_ref", "rows", "rows_without_evidence", "notice", "run_id", "bucket", "object_key",
    "../etc/passwd", "s3://bucket/key", "/abs/path", "notice.", "notice.unknown", "notice.__class__",
    "INGEST_ID", "ingest_id ", "", "field", "header.mfr", "parts[0].affected_mpn",
]


@pytest.mark.parametrize("fld", OUT_OF_CATALOGUE)
def test_s3_a_source_outside_the_catalogue_is_refused_at_load_time(fld):
    raw = {"column_map_version": 1, "name": "t", "label": "T", "format": "json",
           "granularity": "notice_part", "columns": [{"output": "X", "source": {"field": fld}}]}
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate("t", raw)
    assert e.value.reason == "field_not_served", f"{fld!r}: {e.value}"


@pytest.mark.parametrize("rf", ["field_path", "wire_evidence_ref", "../x", "s3://b/k", "", "AFFECTED_MPN"])
def test_s3_a_row_field_outside_the_declared_three_is_refused(rf):
    raw = {"column_map_version": 1, "name": "t", "label": "T", "format": "json",
           "granularity": "notice_part", "columns": [
               {"output": "X", "source": {"field": "extracted_value", "row_field": rf}}]}
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate("t", raw)
    assert e.value.reason == "row_field_unknown", f"{rf!r}: {e.value}"


def test_s3_a_file_in_the_dir_that_leaves_the_catalogue_is_invalid_and_422_while_its_neighbour_serves(
        monkeypatch, tmp_path):
    bad = _maximal() | {"name": "leaky"}
    bad["columns"] = bad["columns"] + [{"output": "Key", "source": {"field": "extraction_ref"}}]
    _profile_dir(monkeypatch, tmp_path)
    (tmp_path / "leaky.yaml").write_text(yaml.safe_dump(bad, sort_keys=False), encoding="utf-8")
    ep.clear_cache()
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))])
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=leaky")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_invalid", r.text
    assert r.json()["detail"]["reason"] == "field_not_served"
    ok = _get(f"/ingest/{_iid(1)}/export?profile=default-json")                      # the control
    assert ok.status_code == 200 and "extraction_ref" not in ok.text, ok.text[:200]


@pytest.mark.parametrize("name", ["../default-json", "default-json.yaml", "/etc/passwd", "..\\x",
                                  "default-json/../default-csv", "DEFAULT-JSON", ""])
def test_s3_a_profile_name_that_is_not_a_loaded_stem_is_422_never_a_path_read(monkeypatch, tmp_path, name):
    _profile_dir(monkeypatch, tmp_path)
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))])
    _as(DROPPER)
    from urllib.parse import quote
    r = _get(f"/ingest/{_iid(1)}/export?profile={quote(name, safe='')}")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown", r.text


# ── s4: steward edits and the provenance rung ─────────────────────────────────────────────────────

ROW_EDIT = {"op": "row_corrected", "field_path": "parts[0].affected_mpn", "value": "FIXED"}
HEADER_EDIT = {"op": "header_corrected", "field": "mfr", "value": "Fixed Co"}
CORRECTED = [pytest.param(ROW_EDIT, id="row_edit"), pytest.param(HEADER_EDIT, id="header_edit")]


def _corrected_rec(*edits):
    return {"checks": [{"name": "human_review", "inputs": {
        "audience": f"document_promotion:{DOM_A}", "row_edits": list(edits)}}]}


@pytest.mark.parametrize("edit", CORRECTED)
def test_s4_a_corrected_promotion_is_refused_for_every_profile_never_served_uncorrected(
        monkeypatch, tmp_path, edit):
    profiles = _valid_profiles(monkeypatch, tmp_path)
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))], topaz=(200, True))
    for name in sorted(profiles):
        Ledger.records = {_iid(1): _corrected_rec(edit)}
        _as(DROPPER)
        s = _get(f"/ingest/{_iid(1)}/export?profile={name}")
        assert s.status_code == 409, (name, s.status_code, s.text[:200])
        assert s.json()["detail"]["error"] == "export_corrections_not_applied", (name, s.text[:200])
        Ledger.between = [(_iid(1), _ms(2026, 10, 1, 6))]
        _as(STRANGER, domains=(DOM_A,))
        b = _get(f"/ingest/export?profile={name}&from=2026-10-01&to=2026-10-02")
        assert b.status_code == 422, (name, b.status_code, b.text[:200])
        d = b.json()["detail"]
        assert d["error"] == "export_notice_unreadable" and d["reason"] == "export_corrections_not_applied", d
        assert "FIXED" not in s.text + b.text and "Fixed Co" not in s.text + b.text


def test_s4_control_the_same_profiles_export_the_same_notice_when_it_is_uncorrected(monkeypatch, tmp_path):
    profiles = _valid_profiles(monkeypatch, tmp_path)
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))], topaz=(200, True))
    for name in sorted(profiles):
        Ledger.records = {_iid(1): _corrected_rec()}              # a review with no edits
        _as(DROPPER)
        s = _get(f"/ingest/{_iid(1)}/export?profile={name}")
        assert s.status_code == 200, (name, s.status_code, s.text[:200])


RUNGS = ["text_layer", "ocr", "llm_extracted", "steward_corrected", None]


def _extraction_with_rungs():
    rows = []
    for i, rung in enumerate(RUNGS):
        for f in ep.ROW_FIELDS:
            rows.append({"part_index": i, "field": f, "extracted_value": f"{f}{i}",
                         "obtained_via": rung, "row_index": len(rows)})
    return {"ingest_id": _iid(1), "notice_id": "PCN-1", "leaf": "pcn", "rows": rows,
            "notice": {"mfr": "Acme"}}


def test_s4_obtained_via_passes_through_render_rows_for_every_profile_that_names_it(monkeypatch, tmp_path):
    profiles = _valid_profiles(monkeypatch, tmp_path)
    naming = {n: p for n, p in profiles.items()
              if any((c.source or {}).get("field") == "obtained_via" for c in p.columns)}
    assert "maximal" in naming                                   # the control: the check is not vacuous
    for name, prof in naming.items():
        cols = [c.output for c in prof.columns if (c.source or {}).get("field") == "obtained_via"]
        cells = ep.render_rows(prof, _extraction_with_rungs())
        assert [c[cols[0]] for c in cells] == RUNGS, name
        assert "steward_corrected" in [c[col] for c in cells for col in cols], name


# The seal as worded: the stewards' edits and the rung COME OUT. They do not yet: the export refuses
# a corrected promotion (above), so these two are the strict xfails that name the gap. They go green
# (and the strict xfail goes red, forcing the marker off) the day the export applies corrections.

_GAP = ("the review export refuses a corrected promotion (409/422 export_corrections_not_applied) "
        "instead of serving the stewards' edits with obtained_via=steward_corrected")


@pytest.mark.xfail(strict=True, reason=_GAP)
def test_s4_gap_a_row_edit_comes_out_with_the_steward_corrected_rung(monkeypatch, tmp_path):
    _valid_profiles(monkeypatch, tmp_path)
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))])
    Ledger.records = {_iid(1): _corrected_rec(ROW_EDIT)}
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=maximal")
    assert r.status_code == 200, r.text[:200]
    row = r.json()["rows"][0]
    assert row["extracted_value@affected_mpn"] == "FIXED"
    assert row["obtained_via@affected_mpn"] == "steward_corrected"


@pytest.mark.xfail(strict=True, reason=_GAP)
def test_s4_gap_a_header_edit_comes_out(monkeypatch, tmp_path):
    _valid_profiles(monkeypatch, tmp_path)
    _install(monkeypatch, [_world(1, _review({0: {"affected_mpn": "A0"}}))])
    Ledger.records = {_iid(1): _corrected_rec(HEADER_EDIT)}
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=maximal")
    assert r.status_code == 200, r.text[:200]
    assert r.json()["rows"][0]["notice.mfr"] == "Fixed Co"
