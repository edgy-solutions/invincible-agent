"""/menu_blocks is keyed by verb (architect ruling 2026-11-22), and finance's declared measures
are served from it. Expectations are read from the loader, never typed.

Run: uv run pytest tests/test_menu_blocks_are_keyed_by_verb.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_fleet.finance_agent import measure_verbs
from src.iagent import gateway, menu_blocks

_REPO = Path(__file__).resolve().parents[1]
_SAMPLE = _REPO / "policy" / "overlays" / "sample"
_MENU_SAMPLE = _SAMPLE / "menu_blocks"
_MEASURE_SAMPLE = _SAMPLE / "measure_verbs"
_MENU_ENV = "MENU_BLOCK_OVERLAY_DIRS"
_MEASURE_ENV = "MEASURE_VERB_OVERLAY_DIRS"
_SEED_ENV = "MEASURE_VERB_POLICY_DIR"


class _User:
    id = "u"
    email = "u@example.invalid"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for e in (_MENU_ENV, _MEASURE_ENV, _SEED_ENV):
        monkeypatch.delenv(e, raising=False)
    menu_blocks.clear_cache()
    yield
    menu_blocks.clear_cache()


def _row(verb, subject="mesh:SomeSet", archetype="mesh:SomeArchetype"):
    return {"declared_by": verb,
            "menu": {"subject": subject, "archetype": archetype,
                     "persona_fit": ["SAFETY_ENGINEER"], "domain_fit": ["SUSTAINMENT"]}}


def _write(d: Path, stem: str, row) -> None:
    (d / f"{stem}.yaml").write_text(yaml.safe_dump(row), encoding="utf-8")


def _sample_rows():
    return measure_verbs.load_measure_verbs(overlay_dirs=[_MEASURE_SAMPLE])


def _verb(r) -> str:
    return "mesh:" + r.verb


def _get():
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
    try:
        with TestClient(gateway.app) as c:
            r = c.get("/menu_blocks")
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    return r.json()


def _env(monkeypatch, menu=None, measure=None):
    for name, v in ((_MENU_ENV, menu), (_MEASURE_ENV, measure)):
        if v is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, str(v))
    menu_blocks.clear_cache()


# 1
def test_distinct_verbs_sharing_subject_and_archetype_are_all_served(monkeypatch, tmp_path):
    _write(tmp_path, "a", _row("mesh:verbA"))
    _write(tmp_path, "b", _row("mesh:verbB"))
    _env(monkeypatch, menu=tmp_path)
    got = menu_blocks.compose()
    assert [b["declared_by"] for b in got.blocks] == ["mesh:verbA", "mesh:verbB"]
    assert got.invalid == []


# 2
def test_one_verb_declared_twice_leaves_both_out_and_names_the_other(monkeypatch, tmp_path):
    _write(tmp_path, "a", _row("mesh:verbA"))
    _write(tmp_path, "b", _row("mesh:verbA", subject="mesh:Other"))
    _env(monkeypatch, menu=tmp_path)
    got = menu_blocks.compose()
    assert got.blocks == []
    by = {i["source"]: i["reason"] for i in got.invalid}
    assert set(by) == {"a", "b"}
    assert "declares the same verb" in by["a"] and "b" in by["a"]
    assert "declares the same verb" in by["b"] and "a" in by["b"]


# 3
def test_declared_measure_menus_are_served(monkeypatch):
    rows = _sample_rows()
    with_menu = [r for r in rows if r.menu]
    assert with_menu, "positive control: the sample declares menu placements"
    assert any(not r.menu for r in rows), "control: the sample has rows without a menu"
    _env(monkeypatch, measure=_MEASURE_SAMPLE)
    got = menu_blocks.compose()
    assert got.composed is True
    assert {b["declared_by"] for b in got.blocks} == {_verb(r) for r in with_menu}
    assert len(got.blocks) == len(with_menu)
    by_verb = {b["declared_by"]: b for b in got.blocks}
    for r in with_menu:
        b = by_verb[_verb(r)]
        assert {k: b[k] for k in ("subject", "archetype", "persona_fit", "domain_fit")} == {
            k: r.menu[k] for k in ("subject", "archetype", "persona_fit", "domain_fit")}


# 4  the join seal
def test_the_served_verb_is_the_verb_the_engine_reports(monkeypatch):
    from agent_fleet.finance_agent import main as fin
    rows = _sample_rows()
    monkeypatch.setattr(fin, "DECLARED", {r.measure_id: r for r in rows})
    reported = {v["fn"]: v["verb"] for v in fin.list_verbs()["verbs"]}
    _env(monkeypatch, measure=_MEASURE_SAMPLE)
    got = menu_blocks.compose()
    served = {b["declared_by"] for b in got.blocks}
    expected = {reported[r.measure_id] for r in rows if r.menu}
    assert served and served == expected


# 5
def test_a_menu_file_and_a_measure_row_sharing_a_verb_are_both_left_out(monkeypatch, tmp_path):
    victim = next(r for r in _sample_rows() if r.menu)
    _write(tmp_path, "clash", _row(_verb(victim)))
    _env(monkeypatch, menu=tmp_path, measure=_MEASURE_SAMPLE)
    got = menu_blocks.compose()
    assert _verb(victim) not in {b["declared_by"] for b in got.blocks}
    by = {i["source"]: i["reason"] for i in got.invalid}
    src = f"measure_verbs/{victim.measure_id}"
    assert set(by) == {"clash", src}
    assert "declares the same verb" in by["clash"] and src in by["clash"]
    assert "clash" in by[src]


# 6
def test_malformed_measure_rows_are_unreadable_and_never_raise(monkeypatch, tmp_path):
    (tmp_path / "bad.yaml").write_text("measure_id: [unterminated\n", encoding="utf-8")
    _env(monkeypatch, measure=tmp_path)
    got = menu_blocks.compose()
    assert got.composed is False and got.blocks == []
    assert len(got.invalid) == 1
    assert got.invalid[0]["source"] == "measure_verbs"
    assert got.invalid[0]["reason"].startswith("unreadable: ")


# 7
def test_the_cache_follows_the_measure_env(monkeypatch, tmp_path):
    _env(monkeypatch, measure=_MEASURE_SAMPLE)
    assert menu_blocks.compose().blocks, "positive control"
    monkeypatch.setenv(_MEASURE_ENV, str(tmp_path))  # no clear_cache()
    second = menu_blocks.compose()
    assert second.composed is True and second.blocks == []


# 8
def test_the_route_serves_both_sources_sorted(monkeypatch):
    _env(monkeypatch, menu=_MENU_SAMPLE, measure=_MEASURE_SAMPLE)
    got = _get()
    assert got["composed"] is True
    where_used = {yaml.safe_load(p.read_text("utf-8"))["declared_by"]
                  for p in _MENU_SAMPLE.glob("*.yaml")}
    measure = {_verb(r) for r in _sample_rows() if r.menu}
    assert where_used and measure
    assert {b["declared_by"] for b in got["blocks"]} == where_used | measure
    keys = [(b["subject"], b["archetype"], b["declared_by"]) for b in got["blocks"]]
    assert keys == sorted(keys)


# 9
def test_neither_env_set_is_not_read():
    assert _get() == {"composed": False, "blocks": [], "invalid": []}
