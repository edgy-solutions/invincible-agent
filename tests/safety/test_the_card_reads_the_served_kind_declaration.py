"""The draft card's task kind and `reason_required` are READ from the served declarations.

Standing rule (architect, 2026-10-30): config names the case, code implements the mechanism.
Before this, `measures.py` built the kind as an f-string over the level and carried a copy of the
reason verbs. Now:

  * the KIND is the head of the matrix's own `acceptanceAudience` (`<task_kind>:<compartment>`);
  * `reason_required` is that kind's composed task-kind row.

WHAT IS PINNED HERE IS THE RELATION, NOT A VALUE. Every expectation is read from the SERVER's
composition (`human_tasks._declared_kinds()` over the chart's overlay list) and from the matrix.
The controls change the row, or the matrix and the row together, and watch the card follow: a card
that still carried a copied verb list or an f-string kind would pass a seal that compared it with
those same values, and fails these.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
from pathlib import Path

import pytest

from ._engine_extra import requires_rdflib
from .conftest import served_overlay_dirs

_REPO = Path(__file__).resolve().parents[2]
_ENV = "TASK_KIND_OVERLAY_DIRS"


def _server_rows():
    """Rows exactly as the gateway reads them: seed + the chart's overlay list."""
    pytest.importorskip("iagent_mesh.task_kinds",
                        reason="iagent-mesh SDK not installed -- this seal is VOID, not green")
    from iagent import human_tasks as ht
    prev = os.environ.get(_ENV)
    os.environ[_ENV] = served_overlay_dirs()
    ht._DECLARED_KINDS_CACHE = None
    try:
        assert ht._declared_kinds() is not None
        return dict(ht._DECLARED_ROWS)
    finally:
        if prev is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = prev
        ht._DECLARED_KINDS_CACHE = None
        ht._DECLARED_ROWS.clear()


def _cards_by_level():
    """level -> (hazard_id, review_request), found by drafting every fixture hazard."""
    from agent_fleet.safety_agent import measures
    seen = {}
    for n in range(1000, 1100):
        try:
            d = measures.draft_risk_assessment(hazard_id=f"HAZ-{n}")
        except Exception:
            continue
        if "review_request" in d:
            seen.setdefault(d["risk_level"], (f"HAZ-{n}", d["review_request"]))
    return seen


@requires_rdflib
def test_every_level_card_carries_the_kind_and_reason_verbs_the_server_serves():
    from agent_fleet.safety_agent import matrix
    rows = _server_rows()
    cards = _cards_by_level()
    labels = {lbl for lbl, _a in matrix.known_cells().values()}
    assert cards and set(cards) <= labels, "instrument failure: no level reached a card"
    for level, (_hid, rr) in sorted(cards.items()):
        head = rr["audience"].partition(":")[0]
        assert rr["kind"] == head, (level, rr["kind"], rr["audience"])
        assert head in rows, f"{head} (from the matrix) is not a kind the server serves"
        row = rows[head]
        want = [v for v in row.accepts if v in set(row.reason_required)]
        assert want, f"{head} declares no reason verb -- nothing to compare"
        assert rr["payload"]["reason_required"] == want, (
            level, rr["payload"]["reason_required"], want)


def _overlay_with(tmp_path, *, reason, rename=None):
    """A copy of the served sample overlay's task kinds with `risk_acceptance_medium` changed."""
    dst = tmp_path / "task_kinds"
    shutil.copytree(_REPO / "policy" / "overlays" / "sample" / "task_kinds", dst)
    f = dst / "risk_acceptance_medium.yaml"
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^reason_required:.*?(?=^\S|\Z)", text, flags=re.M | re.S)
    assert m, "instrument failure: the row has no reason_required block to change"
    text = text.replace(m.group(0), f"reason_required: [{reason}]\n")
    if rename:
        text = text.replace("kind: risk_acceptance_medium", f"kind: {rename}")
        f.unlink()
        f = dst / f"{rename}.yaml"
    f.write_text(text, encoding="utf-8")
    return dst


@requires_rdflib
def test_the_card_follows_the_row_not_a_copy_of_it(tmp_path, monkeypatch):
    """CONTROL. Change what the row declares and the card changes with it; no code edit."""
    from agent_fleet.safety_agent import measures
    hid, _rr = _cards_by_level()["Medium"]
    monkeypatch.setenv(_ENV, str(_overlay_with(tmp_path, reason="rejected")))
    rr = measures.draft_risk_assessment(hazard_id=hid)["review_request"]
    assert rr["payload"]["reason_required"] == ["rejected"], rr["payload"]["reason_required"]


@requires_rdflib
def test_a_new_kind_is_a_row_and_an_audience_not_a_branch(tmp_path, monkeypatch):
    """CONTROL. The matrix names a different kind and an overlay declares it: the card carries it.
    No `risk_acceptance_` prefix is known to the engine."""
    from agent_fleet.safety_agent import matrix, measures
    hid, _rr = _cards_by_level()["Medium"]
    ttl = (_REPO / "setup" / "ontologies" / "safety_risk_matrix.ttl").read_text(encoding="utf-8")
    ttl2 = ttl.replace('"risk_acceptance_medium:SUSTAINMENT"', '"sample_other_kind:SUSTAINMENT"')
    assert ttl2 != ttl
    p = tmp_path / "m.ttl"
    p.write_text(ttl2, encoding="utf-8")
    monkeypatch.setenv("SAFETY_RISK_MATRIX_TTL", str(p))
    monkeypatch.setenv(_ENV, str(_overlay_with(tmp_path, reason="accepted",
                                               rename="sample_other_kind")))
    matrix.reset_cache()
    try:
        rr = measures.draft_risk_assessment(hazard_id=hid)["review_request"]
    finally:
        monkeypatch.delenv("SAFETY_RISK_MATRIX_TTL")
        matrix.reset_cache()
    assert rr["kind"] == "sample_other_kind"
    assert rr["payload"]["reason_required"] == ["accepted"]


@requires_rdflib
def test_an_unreadable_declaration_refuses_naming_the_variable(tmp_path, monkeypatch):
    from agent_fleet.safety_agent import measures
    hid, _rr = _cards_by_level()["Medium"]
    monkeypatch.delenv(_ENV, raising=False)
    unset = measures.draft_risk_assessment(hazard_id=hid)
    assert unset.get("refused") is True and _ENV in unset["reason"], unset
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv(_ENV, str(empty))
    undeclared = measures.draft_risk_assessment(hazard_id=hid)
    assert undeclared.get("refused") is True and "not declared" in undeclared["reason"], undeclared
    monkeypatch.setenv(_ENV, str(tmp_path / "typo"))
    missing = measures.draft_risk_assessment(hazard_id=hid)
    assert missing.get("refused") is True and "not directories" in missing["reason"], missing
    assert "review_request" not in unset and "review_request" not in missing


def test_the_engine_reads_only_what_its_image_carries():
    """IMAGE REACHABILITY. The engine image flattens `agent_fleet/safety_agent` into /app and has
    no `src/iagent`. So `served_kinds` may import nothing from `iagent`, the Dockerfile must bake
    the overlays, and the chart's list must name overlay directories."""
    src = (_REPO / "agent_fleet" / "safety_agent" / "served_kinds.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        for m in mods:
            assert m.split(".")[0] not in {"iagent", "iagent_pure"}, m
    dockerfile = (_REPO / ".github" / "docker" / "Dockerfile.agent").read_text(encoding="utf-8")
    assert re.search(r"^COPY policy/overlays/ /app/policy/overlays/\s*$", dockerfile, flags=re.M)
    for d in served_overlay_dirs().split(os.pathsep):
        assert Path(d).is_dir() and "overlays" in Path(d).parts, d


def test_measures_names_no_kind_template_and_no_reason_verb_list():
    """THE FORM, not the name: no f-string under a `kind` key, and no list literal of verb strings
    under `reason_required`."""
    path = _REPO / "agent_fleet" / "safety_agent" / "measures.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if k.value == "kind" and isinstance(v, ast.JoinedStr):
                bad.append(f"{path.name}:{v.lineno} f-string kind")
            if k.value == "reason_required" and isinstance(v, (ast.List, ast.Tuple)) \
                    and any(isinstance(e, ast.Constant) for e in v.elts):
                bad.append(f"{path.name}:{v.lineno} literal reason_required")
    assert not bad, bad
