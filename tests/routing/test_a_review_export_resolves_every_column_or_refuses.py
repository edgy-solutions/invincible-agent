"""A review export resolves every column it declares, or refuses -- it never guesses and never drops.

WHAT THIS DEFENDS (the review export: `GET /ingest/{id}/export?profile=`, the batch
`GET /ingest/export?...`, and the profiles in `policy/exports/`, vocabulary = doc-tools 7f's
`batch-column-map.md`, contract_version 1):

  a. the served set `export_profiles` validates against is DERIVED from the models and equals the
     schemas in the committed OpenAPI doc: a field added to the model without a regen reds here.
  b. every validation rule refuses its own profile with its own reason; every shipped profile loads.
  c. rendering: an absent row is an empty cell, an ambiguous or malformed date LANDS verbatim (or is
     blanked, or blocks) and is never guessed -- including `20230512`, which `date.fromisoformat`
     alone would accept on 3.12.
  d. a notice with no parts is ONE row with `no_parts: true`, not zero rows.
  e. `absent_row: block` and two rows for one (part, field) refuse, naming notice, part, column.
  f. the single route: dropper, capability holder, the original 403, 409s, 422s, 503s, headers.
  g. the batch: capability gate (403 policy refusal, 503), inclusive UTC day bounds, 92 days, 500
     notices, loud-not-partial, empty range is 200.
  h. `ROW_FIELDS` (declared in `export_profiles`; no other tuple of the per-part field names exists)
     against an inline review.json double: every member resolves to its value, and the double
     carries nothing the tuple omits. No fixture under `tests/fixtures/` carries review items.
  i. the three paths each reach their own handler.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import export_profiles as ep  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion_stores  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DROPPER = "alice@example.com"
STRANGER = "mallory@example.com"
CAP = "capability_grants:ingest:exportBatch"
DOM_A, DOM_B = "maintenance", "supply"


# ── doubles: the same targets tests/test_ingest_review_card_routes.py patches ────────────────────

class _Body:
    def __init__(self, data):
        self._d, self._p = data, 0

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._d)
        out = self._d[self._p:self._p + n]
        self._p += n
        return out

    def close(self):
        pass


class FakeS3:
    def __init__(self, objects):
        self.objects, self.calls = dict(objects), []

    def get_object(self, Bucket, Key):
        self.calls.append(Key)
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": _Body(self.objects[Key])}


def _item(fp, value):
    return {"field_path": fp, "value": value, "source_snippet": f"snip {value}", "region": "table",
            "page_number": 1, "bboxes": [[1.0, 2.0, 3.0, 4.0]], "page_dims": [612, 792],
            "match_method": "text_layer_cell", "match_confidence": 0.9, "needs_review": False,
            "review_reason": None, "approval_state": "pending",
            "wire_evidence_ref": {"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4]}}


def _review(parts: dict, *, header=True):
    """parts: {i: {field: value}} -> a review.json double (items in file order)."""
    items = [_item("header.mfr", "Acme Semi"), _item("header.pub_date", "2026-03-04")] if header else []
    for i in sorted(parts):
        for f, v in parts[i].items():
            items.append(_item(f"parts[{i}].{f}", v))
    return {"doc_id": "PCN-1", "doc_id_raw": "PCN #1", "notice_identity": {"mfr": "FallbackCo"},
            "pages": [], "stats": {}, "review_items": items}


def _hex(n: int) -> str:
    return f"{n:064x}"


def _iid(n: int) -> str:
    return "sha256:" + _hex(n)


def _world(n: int, review: dict, **row_over):
    """(row, objects) for notice n, shaped like the review-card tests' world."""
    h = _hex(n)
    prefix = f"ingress-user/pdf/{h}/"
    gen = prefix + "generated/PCN-1_pdf/doc-tools@61f74dc/"
    ref = gen + "manifest.json"
    manifest = {"doc_id": "PCN-1", "filename": "PCN-1.pdf", "source_key": prefix + "PCN-1.pdf",
                "text_location": gen + "text.json", "pipeline_version": "doc-tools@61f74dc",
                "provenance": {"standing": "supervised", "ingest_id": _iid(n)}, "ingest_id": _iid(n)}
    row = {"id": _iid(n), "status": ist.PROMOTED, "kind": "pdf", "content_kind": "pcn", "attempt": 1,
           "object_prefix": prefix, "extraction_ref": ref, "submitted_by": DROPPER,
           "on_behalf_of": None, "notice_id": "PCN-1"}
    row.update(row_over)
    return row, {ref: json.dumps(manifest).encode(), gen + "review.json": json.dumps(review).encode()}


class Ledger:
    """Stands for `promotion_stores.PgDecisionLedger`: the instance reads share class state."""
    records: dict = {}
    between: list = []          # [(ingest_id, acted_at_ms)]
    calls: list = []            # the params promoted_between received
    fail = False
    domains: dict = {}          # ingest_id -> promotion domain; unlisted notices are in DOM_A

    @staticmethod
    def domain(ingest_id):
        return Ledger.domains.get(ingest_id, DOM_A)

    def record_for(self, ingest_id):
        if Ledger.fail:
            raise RuntimeError("ledger down")
        if ingest_id in Ledger.records:
            return Ledger.records[ingest_id]
        return {"checks": [{"name": "human_review", "inputs": {
            "audience": f"document_promotion:{Ledger.domain(ingest_id)}"}}]}

    def promoted_between(self, start_ms, end_ms, limit, domains):
        if Ledger.fail:
            raise RuntimeError("ledger down")
        Ledger.calls.append((start_ms, end_ms, limit, frozenset(domains)))
        return [(i, at) for i, at in sorted(Ledger.between, key=lambda t: (t[1], t[0]))
                if start_ms <= at < end_ms and Ledger.domain(i) in domains][:limit]


def _install(monkeypatch, worlds, *, topaz=None, holders=()):
    """worlds: [(row, objects)]. topaz: None (untouched) | (status, check) the capability check
    answers | an Exception class to raise from the transport."""
    rows, objs = {}, {}
    for row, o in worlds:
        rows[row["id"]] = row
        objs.update(o)
    fake = FakeS3(objs)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: fake)
    monkeypatch.setattr(ist, "get_row", lambda i: rows.get(i))
    monkeypatch.setattr(ht, "get_task_open_state", lambda t: None)
    monkeypatch.setattr(ht, "can_act_or_unavailable", lambda aud, who: who in holders)
    Ledger.records, Ledger.between, Ledger.calls, Ledger.fail = {}, [], [], False
    Ledger.domains = {}
    monkeypatch.setattr(promotion_stores, "PgDecisionLedger", Ledger)
    asked = []
    # The 2026-10-30 `can_export:<profile>` gate is its own file's subject
    # (test_the_export_door_checks_can_export_per_profile.py): here it is granted, so this file's
    # arms keep defending what they defended and `asked` still records only ingest:exportBatch.
    _real_can_invoke = ht.can_invoke_or_unavailable
    monkeypatch.setattr(
        ht, "can_invoke_or_unavailable",
        lambda cap, who: True if cap.startswith("can_export:") else _real_can_invoke(cap, who))
    if topaz is not None:
        class _Client:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, path, json=None):
                asked.append(json)
                if isinstance(topaz, type) and issubclass(topaz, Exception):
                    raise topaz("transport down")
                status, check = topaz
                return httpx.Response(status, json={"check": check},
                                      request=httpx.Request("POST", "http://topaz" + path))

        monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz")
        monkeypatch.setattr(ht, "httpx", SimpleNamespace(Client=_Client, HTTPError=httpx.HTTPError))
    return fake, asked


def _as(who, domains=(DOM_A,)):
    cells = [SimpleNamespace(persona="p", domain=d) for d in domains]
    user = type("U", (), {"authz_id": who, "id": who, "sub": who, "email": who, "persona": None,
                          "entitled_domains": [], "is_authenticated": True,
                          "entitlements": SimpleNamespace(cells=cells)})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def _cleanup():
    ep.clear_cache()
    yield
    gateway.app.dependency_overrides.clear()
    ep.clear_cache()


def _get(path):
    with TestClient(gateway.app) as c:
        return c.get(path)


def _use_profiles(monkeypatch, tmp_path, **files: str):
    for name, text in files.items():
        (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("INGEST_EXPORT_PROFILE_DIR", str(tmp_path))
    ep.clear_cache()


def _profile_yaml(name="t", fmt="json", columns="", gran="notice_part"):
    return (f"column_map_version: 1\nname: {name}\nlabel: T\nformat: {fmt}\n"
            f"granularity: {gran}\ncolumns:\n{columns}")


ROWSEL = "field: extracted_value, row_field: {rf}"
COLS = f"""  - output: Ingest
    source: {{field: ingest_id}}
  - output: Part
    source: {{field: part_index}}
  - output: Affected
    source: {{field: extracted_value, row_field: affected_mpn}}
  - output: Replacement
    source: {{field: extracted_value, row_field: replacement_mpn}}
  - output: LTB
    source: {{field: extracted_value, row_field: ltb_date}}
    format: iso8601
    on_unresolvable: {{onu}}
{{landing}}  - output: ltb_amb
  - output: no_parts
"""
LAND = COLS.replace("{onu}", "land").replace("{landing}", "    landing: ltb_amb\n")
BLANK_COLS = (COLS.replace("{onu}", "blank").replace("{landing}", "")
              .replace("  - output: ltb_amb\n", ""))
BLOCK_COLS = (COLS.replace("{onu}", "block").replace("{landing}", "")
              .replace("  - output: ltb_amb\n", ""))


# ── a. the served set is the schema ─────────────────────────────────────────────────────────────

def test_a_the_served_set_equals_the_committed_openapi_schemas():
    schemas = json.loads((ROOT / "docs/api/cortex-bff.openapi.json").read_text(encoding="utf-8")
                         )["components"]["schemas"]
    ext, notice, row = (set(schemas[k]["properties"]) for k in ("Extraction", "Notice", "ExtractionRow"))
    declared = (ep.NOTICE_FIELDS | ep.ROW_UNSHARED | ep.ROW_SHARED | {ep.ROW_DISCRIMINATOR}
                | ep.EXCLUDED)
    assert declared == ext | {f"notice.{p}" for p in notice} | row
    # the partition: nothing is both a notice-level and a row-level source
    assert not (ep.NOTICE_FIELDS & (ep.ROW_UNSHARED | ep.ROW_SHARED))
    assert not (ep.ROW_UNSHARED & ep.ROW_SHARED)
    assert ep.ROW_DISCRIMINATOR not in ep.ROW_SHARED | ep.ROW_UNSHARED


# ── b. validation: one refused profile per rule ─────────────────────────────────────────────────

def _base(**over):
    d = {"column_map_version": 1, "name": "t", "label": "T", "format": "json",
         "granularity": "notice_part", "columns": [{"output": "Ingest", "source": {"field": "ingest_id"}}]}
    d.update(over)
    return d


def _cols(*cols, **over):
    return _base(columns=list(cols), **over)


LTB = {"output": "LTB", "source": {"field": "extracted_value", "row_field": "ltb_date"},
       "format": "iso8601", "on_unresolvable": "land", "landing": "amb"}
AMB = {"output": "amb"}

REFUSED = [
    ("version_unsupported", _base(column_map_version=2)),
    ("unknown_key", _base(scope="row")),
    ("unknown_key", _cols({"output": "I", "source": {"field": "ingest_id"}, "extra": 1})),
    ("missing_key", {k: v for k, v in _base().items() if k != "label"}),
    ("name_invalid", _base(name="Bad_Name")),
    ("label_blank", _base(label="  ")),
    ("format_invalid", _base(format="xml")),
    ("granularity_invalid", _base(granularity="scope")),
    ("columns_empty", _base(columns=[])),
    ("output_blank", _cols({"output": " ", "source": {"field": "ingest_id"}})),
    ("output_duplicate", _cols({"output": "I", "source": {"field": "ingest_id"}},
                               {"output": "I", "source": {"field": "notice_id"}})),
    ("field_not_served", _cols({"output": "D", "source": {"field": "header.doc_level_ltb_date"}})),
    ("field_not_served", _cols({"output": "D", "source": {"field": "field"}})),  # the discriminator
    ("row_field_required", _cols({"output": "V", "source": {"field": "extracted_value"}})),
    ("row_field_refused", _cols({"output": "I", "source": {"field": "ingest_id", "row_field": "ltb_date"}})),
    ("row_field_unknown", _cols({"output": "V", "source": {"field": "extracted_value",
                                                           "row_field": "not_a_field"}})),
    ("absent_row_refused", _cols({"output": "I", "source": {"field": "ingest_id",
                                                            "absent_row": "block"}})),
    ("absent_row_invalid", _cols({"output": "V", "source": {"field": "extracted_value",
                                                            "row_field": "ltb_date",
                                                            "absent_row": "null"}})),
    ("row_source_at_notice_granularity",
     _cols({"output": "P", "source": {"field": "part_index"}}, granularity="notice")),
    ("row_source_at_notice_granularity",
     _cols({"output": "I", "source": {"field": "ingest_id"}}, {"output": "no_parts"},
           granularity="notice")),
    ("row_source_at_notice_granularity",
     _cols({"output": "R", "source": {"field": "row_index"}}, granularity="notice")),
    ("derived_column_unbound", _cols({"output": "I", "source": {"field": "ingest_id"}}, {"output": "Orphan"})),
    ("derived_column_has_key", _cols({"output": "no_parts", "format": "iso8601"})),
    ("landing_undeclared", _cols(LTB)),
    ("landing_shared", _cols(LTB, {**LTB, "output": "LTB2"}, AMB)),
    ("landing_not_derived", _cols(LTB, {"output": "amb", "source": {"field": "ingest_id"}})),
    ("format_unsupported", _cols({**LTB, "format": "dmy"}, AMB)),
    ("on_unresolvable_required", _cols({k: v for k, v in LTB.items()
                                        if k not in ("on_unresolvable", "landing")}, AMB)),
    ("on_unresolvable_refused", _cols({"output": "I", "source": {"field": "ingest_id"},
                                       "on_unresolvable": "blank"})),
    ("landing_required", _cols({k: v for k, v in LTB.items() if k != "landing"}, AMB)),
    ("landing_refused", _cols({**LTB, "on_unresolvable": "blank"}, AMB)),
    ("transform_unknown", _cols({"output": "I", "source": {"field": "ingest_id"}, "transforms": ["rot13"]})),
]


@pytest.mark.parametrize("reason,raw", REFUSED, ids=[f"{r}-{i}" for i, (r, _) in enumerate(REFUSED)])
def test_b_each_rule_refuses_with_its_own_reason(reason, raw):
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate(raw.get("name", "t") if isinstance(raw.get("name"), str) else "t", raw)
    assert e.value.reason == reason


def test_b_the_name_must_equal_the_file_stem():
    with pytest.raises(ep.ProfileInvalid) as e:
        ep.validate("other", _base())
    assert e.value.reason == "name_stem_mismatch"


def test_b_a_legal_profile_with_a_landing_and_no_parts_validates():
    p = ep.validate("t", _cols({"output": "I", "source": {"field": "ingest_id"}}, LTB, AMB,
                               {"output": "no_parts"}))
    assert p.outputs == ["I", "LTB", "amb", "no_parts"]


def test_b_every_shipped_profile_validates(monkeypatch):
    monkeypatch.delenv("INGEST_EXPORT_PROFILE_DIR", raising=False)
    ep.clear_cache()
    loaded = ep.load_profiles()
    shipped = sorted(p.stem for p in (ROOT / "policy/exports").glob("*.yaml"))
    assert shipped and sorted(loaded) == shipped
    bad = {k: str(v) for k, v in loaded.items() if not isinstance(v, ep.Profile)}
    assert bad == {}


# ── c. render, notice_part ──────────────────────────────────────────────────────────────────────

REV_C = _review({
    0: {"affected_mpn": "A0", "replacement_mpn": "R0", "ltb_date": "2024-01-31"},
    1: {"affected_mpn": "A1"},
    2: {"affected_mpn": "A2", "ltb_date": "05/12/2023"},
    3: {"affected_mpn": "A3", "ltb_date": "2024-02-30"},
    4: {"affected_mpn": "A4", "ltb_date": "20230512"},        # date.fromisoformat alone takes this
})


def _single(monkeypatch, tmp_path, review, profile_text, *, who=DROPPER, status=ist.PROMOTED, **kw):
    _use_profiles(monkeypatch, tmp_path, t=profile_text)
    _install(monkeypatch, [_world(1, review, status=status)], **kw)
    _as(who)
    return _get(f"/ingest/{_iid(1)}/export?profile=t")


def test_c_an_absent_row_is_an_empty_cell_and_an_ambiguous_date_lands_verbatim(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, _profile_yaml(columns=LAND))
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert [x["Part"] for x in rows] == [0, 1, 2, 3, 4]
    assert rows[0] | {} == {"Ingest": _iid(1), "Part": 0, "Affected": "A0", "Replacement": "R0",
                            "LTB": "2024-01-31", "ltb_amb": None, "no_parts": False}
    assert rows[1]["Replacement"] is None and rows[1]["LTB"] is None and rows[1]["ltb_amb"] is None
    assert rows[2]["LTB"] is None and rows[2]["ltb_amb"] == "05/12/2023"
    assert rows[3]["LTB"] is None and rows[3]["ltb_amb"] == "2024-02-30"
    assert rows[4]["LTB"] is None and rows[4]["ltb_amb"] == "20230512"


def test_c_blank_drops_the_value_and_declares_no_landing(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, _profile_yaml(columns=BLANK_COLS))
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert [x["LTB"] for x in rows] == ["2024-01-31", None, None, None, None]
    assert all("ltb_amb" not in x for x in rows)


def test_c_block_fails_naming_the_notice_part_and_column(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, _profile_yaml(columns=BLOCK_COLS))
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d == {"error": "export_blocked", "reason": "date_unresolvable", "notice": _iid(1),
                 "part": 2, "column": "LTB"}


def test_c_transforms_apply_in_order_to_strings_only(monkeypatch, tmp_path):
    cols = (f"  - output: Affected\n    source: {{field: extracted_value, row_field: affected_mpn}}\n"
            "    transforms: [trim, lower]\n"
            "  - output: Conf\n    source: {field: match_confidence, row_field: affected_mpn}\n"
            "    transforms: [upper]\n")
    rev = _review({0: {"affected_mpn": "  ABC-1 "}})
    r = _single(monkeypatch, tmp_path, rev, _profile_yaml(columns=cols))
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{"Affected": "abc-1", "Conf": 0.9}]


# ── d. no parts ─────────────────────────────────────────────────────────────────────────────────

def test_d_a_notice_with_no_parts_is_one_row_flagged_not_zero_rows(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, _review({}), _profile_yaml(columns=LAND))
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{"Ingest": _iid(1), "Part": None, "Affected": None,
                                 "Replacement": None, "LTB": None, "ltb_amb": None,
                                 "no_parts": True}]


# ── e. block and ambiguous ──────────────────────────────────────────────────────────────────────

def test_e_absent_row_block_refuses_naming_the_part(monkeypatch, tmp_path):
    cols = ("  - output: Replacement\n"
            "    source: {field: extracted_value, row_field: replacement_mpn, absent_row: block}\n")
    rev = _review({0: {"affected_mpn": "A0", "replacement_mpn": "R0"}, 1: {"affected_mpn": "A1"}})
    r = _single(monkeypatch, tmp_path, rev, _profile_yaml(columns=cols))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {"error": "export_blocked", "reason": "absent_row",
                                  "notice": _iid(1), "part": 1, "column": "Replacement"}


def test_e_absent_row_empty_cell_is_the_default_and_does_not_refuse(monkeypatch, tmp_path):
    cols = ("  - output: Replacement\n"
            "    source: {field: extracted_value, row_field: replacement_mpn}\n")
    rev = _review({0: {"affected_mpn": "A0", "replacement_mpn": "R0"}, 1: {"affected_mpn": "A1"}})
    r = _single(monkeypatch, tmp_path, rev, _profile_yaml(columns=cols))
    assert r.status_code == 200 and [x["Replacement"] for x in r.json()["rows"]] == ["R0", None]


def test_e_two_rows_for_one_part_and_field_is_ambiguous_never_picked(monkeypatch, tmp_path):
    rev = _review({0: {"affected_mpn": "A0"}})
    rev["review_items"].append(_item("parts[0].affected_mpn", "A0-again"))
    cols = "  - output: Affected\n    source: {field: extracted_value, row_field: affected_mpn}\n"
    r = _single(monkeypatch, tmp_path, rev, _profile_yaml(columns=cols))
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {"error": "export_blocked", "reason": "row_ambiguous",
                                  "notice": _iid(1), "part": 0, "column": "Affected"}


# ── f. the single route ─────────────────────────────────────────────────────────────────────────

SIMPLE = _profile_yaml(columns=LAND)


def test_f_the_dropper_is_allowed_and_json_has_its_shape_and_headers(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, SIMPLE)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["profile"], b["column_map_version"], b["granularity"]) == ("t", 1, "notice_part")
    assert b["columns"] == ["Ingest", "Part", "Affected", "Replacement", "LTB", "ltb_amb", "no_parts"]
    assert len(b["rows"]) == 5 and "notices" not in b
    assert r.headers["content-disposition"] == f'attachment; filename="{_iid(1)}.t.json"'
    assert r.headers["content-type"].startswith("application/json")


def test_f_csv_has_its_content_type_disposition_and_literal_cells(monkeypatch, tmp_path):
    prof = _profile_yaml(fmt="csv", columns=LAND)
    r = _single(monkeypatch, tmp_path, REV_C, prof)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="{_iid(1)}.t.csv"'
    got = list(csv.reader(io.StringIO(r.text)))
    assert got[0] == ["Ingest", "Part", "Affected", "Replacement", "LTB", "ltb_amb", "no_parts"]
    assert got[1] == [_iid(1), "0", "A0", "R0", "2024-01-31", "", "false"]
    assert got[3] == [_iid(1), "2", "A2", "", "", "05/12/2023", "false"]


def test_f_a_non_dropper_without_the_capability_gets_the_original_403(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, SIMPLE, who=STRANGER, topaz=(200, False))
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"


def test_f_a_non_dropper_with_the_capability_gets_200_and_it_is_audited(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="iagent.audit.ingest_access")
    r, asked = None, None
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _, asked = _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    _as(STRANGER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 200, r.text
    assert asked == [{"object_type": "capability", "object_id": "ingest:exportBatch",
                      "relation": "can_invoke", "subject_type": "user", "subject_id": STRANGER}]
    assert any("route=export" in m and "reason=export_capability" in m and "decision=allow" in m
               for m in caplog.messages)


def test_f_the_gates_404_is_not_rescued_by_the_capability(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [], topaz=(200, True))
    _as(STRANGER)
    r = _get(f"/ingest/{_iid(9)}/export?profile=t")
    assert r.status_code == 404 and r.json()["detail"]["error"] == "ingest_not_found"


@pytest.mark.parametrize("topaz,code,err", [
    ((500, False), 503, "authorization_unavailable"),
    (httpx.ConnectError, 503, "authorization_unavailable"),
])
def test_f_topaz_down_when_the_capability_is_consulted_is_503_not_403(
        monkeypatch, tmp_path, topaz, code, err):
    r = _single(monkeypatch, tmp_path, REV_C, SIMPLE, who=STRANGER, topaz=topaz)
    assert r.status_code == code and r.json()["detail"]["error"] == err


def test_f_an_unset_topaz_url_is_503_unconfigured(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)])
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "")
    _as(STRANGER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unconfigured"


def test_f_a_notice_not_promoted_is_409_and_names_its_status(monkeypatch, tmp_path):
    r = _single(monkeypatch, tmp_path, REV_C, SIMPLE, status=ist.REVIEW)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "ingest_not_promoted" and d["status"] == ist.REVIEW


@pytest.mark.parametrize("edit", [
    {"op": "row_corrected", "field_path": "parts[0].affected_mpn", "value": "FIXED"},
    {"op": "header_corrected", "field": "mfr", "value": "Fixed Co"},
])
def test_f_a_promotion_with_corrections_is_409_not_exported_uncorrected(monkeypatch, tmp_path, edit):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)])
    Ledger.records[_iid(1)] = {"checks": [{"name": "human_review",
                                           "inputs": {"row_edits": [edit]}}]}
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 409 and r.json()["detail"]["error"] == "export_corrections_not_applied"


def test_f_an_uncorrected_promotion_record_exports(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)])
    Ledger.records[_iid(1)] = {"checks": [{"name": "human_review", "inputs": {"comment": ""}}]}
    _as(DROPPER)
    assert _get(f"/ingest/{_iid(1)}/export?profile=t").status_code == 200


def test_f_a_ledger_fault_is_503(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)])
    Ledger.fail = True
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "decision_ledger_unreachable"


def test_f_an_unknown_and_an_invalid_profile_are_422(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE, broken=_profile_yaml(name="broken", columns="  - output: I\n    source: {field: ingest_id}\n").replace("version: 1", "version: 9"))
    _install(monkeypatch, [_world(1, REV_C)])
    _as(DROPPER)
    r = _get(f"/ingest/{_iid(1)}/export?profile=nope")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown"
    r = _get(f"/ingest/{_iid(1)}/export")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown"
    r = _get(f"/ingest/{_iid(1)}/export?profile=broken")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_invalid"
    assert r.json()["detail"]["reason"] == "version_unsupported"


# ── g. the batch ────────────────────────────────────────────────────────────────────────────────

def _ms(y, mo, d, h=0, mi=0, s=0, ms=0):
    return int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp() * 1000) + ms


def _batch(monkeypatch, tmp_path, worlds, between, *, q="from=2026-10-01&to=2026-10-02",
           topaz=(200, True), prof=SIMPLE, who=STRANGER):
    _use_profiles(monkeypatch, tmp_path, t=prof)
    _install(monkeypatch, worlds, topaz=topaz)
    Ledger.between = list(between)
    _as(who)
    return _get(f"/ingest/export?profile=t&{q}")


def test_g_no_capability_is_a_403_policy_refusal_and_the_ledger_is_not_read(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], topaz=(200, False))
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "not_entitled_to_export_batch"
    assert d["refusal"]["policy_id"] == CAP
    assert d["refusal"]["missing_binding"] == "can_invoke ingest:exportBatch"
    assert d["refusal"]["grantable_by"]
    assert Ledger.calls == []


def test_g_a_topaz_404_is_an_ungranted_capability_not_an_outage(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], topaz=(404, False))
    assert r.status_code == 403 and r.json()["detail"]["refusal"]["policy_id"] == CAP


@pytest.mark.parametrize("topaz", [(500, False), (503, False), httpx.ConnectError])
def test_g_a_topaz_failure_is_503_not_403(monkeypatch, tmp_path, topaz):
    r = _batch(monkeypatch, tmp_path, [], [], topaz=topaz)
    assert r.status_code == 503 and r.json()["detail"]["error"] == "authorization_unavailable"


def test_g_the_range_is_utc_days_inclusive_at_both_ends(monkeypatch, tmp_path):
    ins = {1: _ms(2026, 10, 1), 2: _ms(2026, 10, 2, 23, 59, 59, 999),   # in: first and last ms
           3: _ms(2026, 10, 3), 4: _ms(2026, 9, 30, 23, 59, 59, 999)}   # out: one ms either side
    worlds = [_world(n, _review({0: {"affected_mpn": f"M{n}"}})) for n in ins]
    r = _batch(monkeypatch, tmp_path, worlds, [(_iid(n), at) for n, at in ins.items()])
    assert r.status_code == 200, r.text
    assert Ledger.calls == [(_ms(2026, 10, 1), _ms(2026, 10, 3), 501, frozenset({DOM_A}))]
    b = r.json()
    assert (b["from"], b["to"], b["notices"]) == ("2026-10-01", "2026-10-02", 2)
    assert [x["Affected"] for x in b["rows"]] == ["M1", "M2"]            # acted_at order
    assert r.headers["content-disposition"] == \
        'attachment; filename="ingest-export.t.2026-10-01_2026-10-02.json"'


def test_g_an_empty_range_is_200_with_a_header_only_csv(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], prof=_profile_yaml(fmt="csv", columns=LAND))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert list(csv.reader(io.StringIO(r.text))) == [
        ["Ingest", "Part", "Affected", "Replacement", "LTB", "ltb_amb", "no_parts"]]
    assert r.headers["content-disposition"].endswith('.t.2026-10-01_2026-10-02.csv"')


def test_g_an_empty_range_is_200_with_no_rows_in_json(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [])
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["notices"] == 0


def test_g_501_notices_is_too_large_not_a_truncated_export(monkeypatch, tmp_path):
    many = [(_iid(n), _ms(2026, 10, 1) + n) for n in range(1, 502)]
    r = _batch(monkeypatch, tmp_path, [], many)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_too_large"
    assert Ledger.calls == [(_ms(2026, 10, 1), _ms(2026, 10, 3), 501, frozenset({DOM_A}))]


def test_g_a_notice_that_is_no_longer_promoted_refuses_the_whole_export(monkeypatch, tmp_path):
    good = _world(1, _review({0: {"affected_mpn": "M1"}}))
    bad = _world(2, _review({0: {"affected_mpn": "M2"}}), status=ist.REVIEW)
    r = _batch(monkeypatch, tmp_path, [good, bad],
               [(_iid(1), _ms(2026, 10, 1, 1)), (_iid(2), _ms(2026, 10, 1, 2))])
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "export_notice_unreadable" and d["ingest_id"] == _iid(2)
    assert d["reason"] == "ingest_not_promoted"


def test_g_a_missing_row_and_a_corrected_promotion_refuse_the_export(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [(_iid(7), _ms(2026, 10, 1, 1))])
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_notice_unreadable"
    assert r.json()["detail"]["reason"] == "ingest_not_found"
    w = _world(1, _review({0: {"affected_mpn": "M1"}}))
    r = _batch(monkeypatch, tmp_path, [w], [(_iid(1), _ms(2026, 10, 1, 1))])
    assert r.status_code == 200
    Ledger.records[_iid(1)] = {"checks": [{"name": "human_review", "inputs": {
        "row_edits": [{"op": "row_corrected"}]}}]}
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "export_corrections_not_applied"


def test_g_a_blocked_cell_in_any_notice_refuses_the_export(monkeypatch, tmp_path):
    w = _world(1, REV_C)
    r = _batch(monkeypatch, tmp_path, [w], [(_iid(1), _ms(2026, 10, 1, 1))],
               prof=_profile_yaml(columns=BLOCK_COLS))
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_blocked"


def test_g_a_ledger_fault_is_503(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [], topaz=(200, True))
    Ledger.fail = True
    _as(STRANGER)
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "decision_ledger_unreachable"


@pytest.mark.parametrize("q", [
    "from=2026-10-03&to=2026-10-02", "from=2026-10-01", "to=2026-10-01", "from=2026-1-1&to=2026-10-02",
    "from=20261001&to=20261002", "from=2026-02-30&to=2026-03-01", "from=2026-10-01&to=2026-10-02T00:00",
])
def test_g_a_bad_or_reversed_range_is_422_invalid(monkeypatch, tmp_path, q):
    r = _batch(monkeypatch, tmp_path, [], [], q=q)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_invalid"
    assert Ledger.calls == []


def test_g_93_days_is_too_large_and_92_is_not(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], q="from=2026-01-01&to=2026-04-03")   # 93 days counted
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_too_large"
    r = _get("/ingest/export?profile=t&from=2026-01-01&to=2026-04-02")             # 92 days
    assert r.status_code == 200


def test_g_the_profile_is_checked_after_the_capability_and_before_the_range(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [], topaz=(200, True))
    _as(STRANGER)
    r = _get("/ingest/export?profile=nope&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_profile_unknown"


# ── h. ROW_FIELDS against an inline review.json ─────────────────────────────────────────────────

def test_h_row_fields_are_exactly_the_per_part_names_a_review_json_carries(monkeypatch, tmp_path):
    part = {f: f"v-{f}" for f in ep.ROW_FIELDS}
    rev = _review({0: part, 1: part})
    names = {it["field_path"].split(".", 1)[1] for it in rev["review_items"]
             if it["field_path"].startswith("parts[")}
    assert names == set(ep.ROW_FIELDS)
    cols = "".join(f"  - output: {f}\n    source: {{field: extracted_value, row_field: {f}}}\n"
                   for f in ep.ROW_FIELDS)
    r = _single(monkeypatch, tmp_path, rev, _profile_yaml(columns=cols))
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [{f: f"v-{f}" for f in ep.ROW_FIELDS}] * 2


def test_h_row_index_is_a_per_part_value_and_needs_no_row_field():
    assert "row_index" in ep.ROW_UNSHARED and "row_index" not in ep.ROW_SHARED
    ep.validate("t", _cols({"output": "R", "source": {"field": "row_index"}}))


# ── i. routing ──────────────────────────────────────────────────────────────────────────────────

def test_i_each_path_reaches_its_own_handler(monkeypatch, tmp_path, caplog):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE, broken="name: broken\n")
    _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    _as(DROPPER)
    with caplog.at_level(logging.ERROR, logger="cortex"):
        r = _get("/ingest/export/profiles")
    # only the profiles handler answers a bare list of {name, format, granularity, label}
    assert r.status_code == 200 and r.json() == [
        {"name": "t", "format": "json", "granularity": "notice_part", "label": "T"}]
    assert any("broken" in m for m in caplog.messages)         # the invalid one is logged, not served
    # only the batch handler answers with `notices`
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 200 and r.json()["notices"] == 0
    # only the single handler answers with the id-named attachment
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 200 and "notices" not in r.json()
    assert r.headers["content-disposition"] == f'attachment; filename="{_iid(1)}.t.json"'


# ── s. a service caller is never admitted by the export capability ──────────────────────────────

SERVICE = "svc:doc-tools"      # `svc:` namespace, and not a declared seeding delegate


def test_s1_a_service_holding_the_capability_gets_the_original_403_on_the_single_export(
        monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _, asked = _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    _as(SERVICE)
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"
    assert asked == []


def test_s2_a_service_holding_the_capability_gets_the_batch_403_and_topaz_is_not_asked(
        monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], who=SERVICE, topaz=(200, True))
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "not_entitled_to_export_batch"
    assert r.json()["detail"]["refusal"]["policy_id"] == CAP
    assert Ledger.calls == []
    assert gateway._is_service_caller(SERVICE)


def test_s3_control_a_human_with_the_capability_is_admitted_on_both_routes(monkeypatch, tmp_path):
    r = _batch(monkeypatch, tmp_path, [], [], who=STRANGER, topaz=(200, True))
    assert r.status_code == 200, r.text
    _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    _as(STRANGER)
    assert not gateway._is_service_caller(STRANGER)
    assert _get(f"/ingest/{_iid(1)}/export?profile=t").status_code == 200


# ── d. the capability is domain-scoped (architect 2026-10-29) ───────────────────────────────────

def test_d1_a_granted_human_exports_an_in_domain_notice_it_did_not_drop_and_not_another_domains(
        monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _, asked = _install(monkeypatch, [_world(1, REV_C), _world(2, REV_C)], topaz=(200, True))
    Ledger.domains = {_iid(1): DOM_A, _iid(2): DOM_B}
    _as(STRANGER, domains=(DOM_A,))
    assert _get(f"/ingest/{_iid(1)}/export?profile=t").status_code == 200
    r = _get(f"/ingest/{_iid(2)}/export?profile=t")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"
    assert len(asked) == 2           # the capability WAS consulted; the domain decided


def test_d1_a_record_with_no_readable_domain_is_out_of_domain(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    for rec in ({"checks": []}, {"checks": [{"name": "human_review", "inputs": {"audience": "x"}}]}):
        Ledger.records[_iid(1)] = rec
        _as(STRANGER)
        assert _get(f"/ingest/{_iid(1)}/export?profile=t").status_code == 403


def test_d2_the_batch_exports_only_the_callers_domains_and_reports_no_failure(monkeypatch, tmp_path):
    worlds = [_world(n, _review({0: {"affected_mpn": f"M{n}"}})) for n in (1, 2, 3)]
    # notice 2 (domain B) is not promoted any more: out of the caller's set, so NOT a failure
    worlds[1][0]["status"] = ist.REVIEW
    between = [(_iid(n), _ms(2026, 10, 1, n)) for n in (1, 2, 3)]
    Ledger.domains = {_iid(2): DOM_B}
    r = _batch(monkeypatch, tmp_path, worlds, between)
    Ledger.domains = {_iid(2): DOM_B}
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 200, r.text
    assert [x["Affected"] for x in r.json()["rows"]] == ["M1", "M3"] and r.json()["notices"] == 2


def test_d3_a_granted_caller_with_no_cells_gets_a_single_403_and_an_empty_batch(monkeypatch, tmp_path):
    _use_profiles(monkeypatch, tmp_path, t=SIMPLE)
    _install(monkeypatch, [_world(1, REV_C)], topaz=(200, True))
    Ledger.between = [(_iid(1), _ms(2026, 10, 1, 1))]
    _as(STRANGER, domains=())
    r = _get(f"/ingest/{_iid(1)}/export?profile=t")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["notices"] == 0


def test_d4_the_cap_counts_in_domain_notices_only(monkeypatch, tmp_path):
    ins = [_iid(n) for n in range(1, 502)]                 # 501 in total, one over the cap
    Ledger.domains = {ins[0]: DOM_B}                       # ... of which 500 are in the caller's
    worlds = [_world(n, _review({0: {"affected_mpn": f"M{n}"}})) for n in range(2, 502)]
    r = _batch(monkeypatch, tmp_path, worlds,
               [(i, _ms(2026, 10, 1) + k) for k, i in enumerate(ins)])
    Ledger.domains = {ins[0]: DOM_B}
    r = _get("/ingest/export?profile=t&from=2026-10-01&to=2026-10-02")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["notices"] == 500
