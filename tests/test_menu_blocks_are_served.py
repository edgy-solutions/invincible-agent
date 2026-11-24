"""GET /menu_blocks serves the overlay rows' menu placements (ruling 2026-11-07: the row declares
its placement, the BFF serves it, cortex reads it).

Run: uv run pytest tests/test_menu_blocks_are_served.py -q
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_fleet.utils.mesh_registration import _IRI_PREFIXES
from src.iagent import gateway, menu_blocks

_REPO = Path(__file__).resolve().parents[1]
_SAMPLE = _REPO / "policy" / "overlays" / "sample" / "menu_blocks"
_ENV = "MENU_BLOCK_OVERLAY_DIRS"
_WHERE_USED = _REPO / "agent_fleet" / "ontology_service" / "where_used.py"

_GOOD = {"declared_by": "mesh:someVerb",
         "menu": {"subject": "mesh:SomeSet", "archetype": "mesh:SomeArchetype",
                  "persona_fit": ["SAFETY_ENGINEER"], "domain_fit": ["SUSTAINMENT"]}}
_EXPECTED = {"subject": "mesh:WhereUsedSet", "archetype": "mesh:InstancesByProperty",
             "persona_fit": ["SAFETY_ENGINEER", "SUSTAINMENT_ENGINEER"],
             "domain_fit": ["SUSTAINMENT"], "declared_by": "mesh:whereIsThisPartUsed"}


class _User:
    id = "u"
    email = "u@example.invalid"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    menu_blocks.clear_cache()
    yield
    menu_blocks.clear_cache()


def _get():
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
    try:
        with TestClient(gateway.app) as c:
            r = c.get("/menu_blocks")
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    return r.json()


def _row(**menu):
    m = dict(_GOOD["menu"])
    m.update(menu)
    return {"declared_by": _GOOD["declared_by"], "menu": m}


def _write(d: Path, stem: str, row) -> None:
    (d / f"{stem}.yaml").write_text(yaml.safe_dump(row), encoding="utf-8")


def _serve(monkeypatch, d: Path):
    monkeypatch.setenv(_ENV, str(d))
    menu_blocks.clear_cache()
    return _get()


# 1, 2
def test_unset_is_not_read_and_an_empty_dir_is_read_and_empty(monkeypatch, tmp_path):
    unset = _get()
    assert unset == {"composed": False, "blocks": [], "invalid": []}
    empty = _serve(monkeypatch, tmp_path)
    assert empty == {"composed": True, "blocks": [], "invalid": []}
    assert unset != empty, "control: not-read and read-empty must be told apart"


def test_a_missing_dir_is_not_read(monkeypatch, tmp_path):
    assert _serve(monkeypatch, tmp_path / "nope")["composed"] is False


# 3
def test_the_shipped_row_is_served_with_exactly_five_keys(monkeypatch):
    got = _serve(monkeypatch, _SAMPLE)
    assert got["composed"] is True and got["invalid"] == []
    assert got["blocks"] == [_EXPECTED]
    assert set(got["blocks"][0]) == set(_EXPECTED)


def _compact(iri: str) -> str:
    for pfx, ns in _IRI_PREFIXES.items():
        if iri.startswith(ns):
            return pfx + iri[len(ns):]
    raise AssertionError(f"no registered prefix for {iri}")


# 4
def test_the_subject_is_engine_os_output_class():
    src = _WHERE_USED.read_text(encoding="utf-8")
    uri = re.search(r'^OUTPUT_URI\s*=\s*"([^"]+)"', src, re.M).group(1)
    row = yaml.safe_load((_SAMPLE / "where_used_set.yaml").read_text(encoding="utf-8"))
    assert _compact(uri) == row["menu"]["subject"]
    assert f'"{row["declared_by"]}"' in src


# 5
def _rows_of(caps):
    for v in vars(caps).values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v) \
                and any("subject_uri" in x and "object_uri" in x for x in v):
            return v
    raise AssertionError("presentation capability rows not found")


def test_the_archetype_is_presentations_row_for_the_subject():
    from agent_fleet.presentation_agent import capabilities as caps
    row = yaml.safe_load((_SAMPLE / "where_used_set.yaml").read_text(encoding="utf-8"))
    rows = [r for r in _rows_of(caps) if r.get("subject_uri") == row["menu"]["subject"]]
    assert len(rows) == 1, "positive control: exactly one presentation row for the subject"
    assert rows[0]["object_uri"] == row["menu"]["archetype"]


# 6
def _refusal_cases():
    return {
        "unknown_prefix": _row(subject="zzz:Foo"),
        "full_iri_subject": _row(subject="http://invincible-agent/mesh#Foo"),
        "extra_menu_key": _row(extra="x"),
        "missing_key": {"declared_by": "mesh:v", "menu": {
            k: v for k, v in _GOOD["menu"].items() if k != "domain_fit"}},
        "empty_list": _row(persona_fit=[]),
        "extra_top_level_key": {**_GOOD, "note": "x"},
    }


@pytest.mark.parametrize("stem", sorted(_refusal_cases()))
def test_a_bad_row_is_named_and_left_out_and_a_sibling_is_served(monkeypatch, tmp_path, stem):
    _write(tmp_path, stem, _refusal_cases()[stem])
    _write(tmp_path, "sibling", _row(subject="mesh:Sibling"))
    got = _serve(monkeypatch, tmp_path)
    assert [i["source"] for i in got["invalid"]] == [stem], got
    assert got["invalid"][0]["reason"]
    assert [b["subject"] for b in got["blocks"]] == ["mesh:Sibling"]


def test_an_unknown_prefix_names_the_field(monkeypatch, tmp_path):
    _write(tmp_path, "bad", _row(subject="zzz:Foo"))
    got = _serve(monkeypatch, tmp_path)
    assert "subject must be a compact CURIE with a registered prefix" in got["invalid"][0]["reason"]


def test_two_rows_declaring_the_same_verb_are_both_invalid(monkeypatch, tmp_path):
    _write(tmp_path, "a", _row())
    _write(tmp_path, "b", _row())
    _write(tmp_path, "c", {**_row(subject="mesh:Other"), "declared_by": "mesh:otherVerb"})
    got = _serve(monkeypatch, tmp_path)
    assert [i["source"] for i in got["invalid"]] == ["a", "b"]
    assert all(i["reason"].startswith("ambiguous: ") for i in got["invalid"])
    assert [b["subject"] for b in got["blocks"]] == ["mesh:Other"]


# 7
def test_a_later_dirs_same_stem_row_replaces_the_earlier(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write(a, "x", _row(subject="mesh:First"))
    _write(b, "x", _row(subject="mesh:Second"))
    monkeypatch.setenv(_ENV, f"{a}{os.pathsep}{b}")
    menu_blocks.clear_cache()
    assert [x["subject"] for x in _get()["blocks"]] == ["mesh:Second"]


# 8
def test_the_menu_keys_equal_finances():
    src = (_REPO / "agent_fleet" / "finance_agent" / "measure_verbs.py").read_text(encoding="utf-8")
    m = re.search(r"^_MENU_KEYS\s*=\s*frozenset\(\{([^}]*)\}\)", src, re.M)
    assert m, "finance's _MENU_KEYS not found"
    assert menu_blocks._MENU_KEYS == frozenset(re.findall(r'"(\w+)"', m.group(1)))


# vocabulary: the runtime does not check it (the vocabularies are not in the BFF image)
def _vocab_problems(overlay_root: Path) -> list[str]:
    personas = set(yaml.safe_load((_REPO / "policy" / "personas.yaml").read_text("utf-8"))["personas"])
    domains = set(yaml.safe_load((_REPO / "policy" / "domains.yaml").read_text("utf-8"))["domains"])
    out = []
    for p in sorted(overlay_root.glob("*/menu_blocks/*.yaml")):
        menu = yaml.safe_load(p.read_text("utf-8"))["menu"]
        out += [f"{p.name}: persona {x} not in personas.yaml"
                for x in menu["persona_fit"] if x not in personas]
        out += [f"{p.name}: domain {x} not in domains.yaml"
                for x in menu["domain_fit"] if x not in domains]
    return out


def test_every_shipped_row_uses_declared_personas_and_domains():
    root = _REPO / "policy" / "overlays"
    assert list(root.glob("*/menu_blocks/*.yaml")), "positive control: rows exist to check"
    assert _vocab_problems(root) == []


def test_the_vocabulary_check_reports_an_undeclared_persona(tmp_path):
    d = tmp_path / "ov" / "menu_blocks"
    d.mkdir(parents=True)
    _write(d, "bad", _row(persona_fit=["NOT_A_PERSONA"], domain_fit=["NOT_A_DOMAIN"]))
    got = _vocab_problems(tmp_path)
    assert any("NOT_A_PERSONA" in g for g in got) and any("NOT_A_DOMAIN" in g for g in got)


# 9
def test_the_chart_names_a_dir_that_exists_and_delivers_the_overlay():
    cm = (_REPO / "helm/invincible-agent/templates/configmap.yaml").read_text("utf-8")
    m = re.search(r'^\s*MENU_BLOCK_OVERLAY_DIRS:\s*"([^"]+)"', cm, re.M)
    assert m, "configmap.yaml does not set MENU_BLOCK_OVERLAY_DIRS"
    assert m.group(1).startswith("/app/")
    assert (_REPO / m.group(1)[len("/app/"):]).is_dir()
    vals = yaml.safe_load((_REPO / "helm/invincible-agent/values.yaml").read_text("utf-8"))
    comps = vals["policyOverlay"]["components"]["cortex-bff"]
    assert {"dir": "menu_blocks", "env": "MENU_BLOCK_OVERLAY_DIRS", "optional": True} in comps
