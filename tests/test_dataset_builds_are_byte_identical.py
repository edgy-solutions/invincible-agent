"""The same rows, built again, are the same bytes -- for both .duckdb builders.

MEASURED CAUSE: over IDENTICAL rows duckdb 1.5.2 wrote different bytes build to build, because
its default compression choice varies (2-4 distinct shas per 5 builds). The page embeds this
file's sha256, so one export input gave several pages. `force_compression=uncompressed` gave one
sha over 15 builds in 3 processes. The catalog also stores the file STEM, so every build here
uses the SAME file name in its own directory; a different name is different bytes by design.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb is not installed in this venv: dataset byte-stability is NOT verified (root agent-fleet extra declares it; uv sync --extra agent-fleet)")

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_cost_dataset  # noqa: E402
import build_fin_package  # noqa: E402
from agent_fleet.finance_agent import main as fmain  # noqa: E402
from agent_fleet.finance_agent import state_codec  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402
from iagent.canvas_template import load_template, panel_dispatch  # noqa: E402

ALPHA = "notional-customer-alpha"
COST_NAME = f"cost-{ALPHA}.duckdb"
FIN_NAME = "fin-package.duckdb"

_COST_SUBPROCESS = (
    "import sys, pathlib; sys.path[:0] = [sys.argv[1], sys.argv[1] + '/scripts'];"
    "import build_cost_dataset as D; D.build(sys.argv[2], pathlib.Path(sys.argv[3]), lots=(4,))"
)


def _sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fin_inputs():
    template = load_template("program_finance")
    panels = []
    for i in range(len(template.panels)):
        verb, _subject, params = panel_dispatch(template, i, {"program": "NP-MERIDIAN"})
        fn = fmain.VERB_TO_FN[verb]
        env = fmain._measure_envelope(fn, dict(params))
        panels.append({"panel": i, "verb": verb, "fn": fn, "params": dict(params),
                       "artifact_id": env["artifact_id"], "rows": env["rows"]})
    state_dict = state_codec.state_to_dict(state_codec.narrow(build_seed(), "NP-MERIDIAN"))
    return state_dict, panels


def test_the_cost_dataset_is_byte_identical_in_process_and_across_processes(
        tmp_path, record_property):
    files = []
    for i in range(3):
        out = tmp_path / f"in{i}" / COST_NAME
        build_cost_dataset.build(ALPHA, out, lots=(4,))
        files.append(out)
    for i in range(2):
        out = tmp_path / f"sub{i}" / COST_NAME
        out.parent.mkdir()
        proc = subprocess.run(
            [sys.executable, "-c", _COST_SUBPROCESS, str(ROOT), ALPHA, str(out)],
            capture_output=True, text=True, cwd=ROOT)
        assert proc.returncode == 0, proc.stderr[-800:]
        files.append(out)
    shas = [_sha(f) for f in files]
    record_property("cost_dataset_sha256", shas[0])
    assert files[0].stat().st_size > 0
    assert len(set(shas)) == 1, shas


def test_the_fin_dataset_is_byte_identical_over_a_real_narrowed_state(tmp_path, record_property):
    state_dict, panels = _fin_inputs()
    files = []
    for i in range(3):
        out = tmp_path / f"in{i}" / FIN_NAME
        out.parent.mkdir()
        build_fin_package.build_duckdb(out, state_dict, panels)
        files.append(out)
    shas = [_sha(f) for f in files]
    record_property("fin_dataset_sha256", shas[0])
    assert len(set(shas)) == 1, shas


def _recording_connect(monkeypatch):
    calls = []
    real = duckdb.connect

    def connect(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", connect)
    return calls


def _writes(calls):
    return [k for k in calls if not k.get("read_only")]


def test_the_cost_builder_opens_its_write_connection_uncompressed(tmp_path, monkeypatch):
    calls = _recording_connect(monkeypatch)
    build_cost_dataset.build(ALPHA, tmp_path / COST_NAME, lots=(4,))
    writes = _writes(calls)
    assert writes, "the builder opened no write connection"
    for kw in writes:
        assert kw.get("config", {}).get("force_compression") == "uncompressed", kw


def test_the_fin_builder_opens_its_write_connection_uncompressed(tmp_path, monkeypatch):
    state_dict, panels = _fin_inputs()
    calls = _recording_connect(monkeypatch)
    build_fin_package.build_duckdb(tmp_path / FIN_NAME, state_dict, panels)
    writes = _writes(calls)
    assert writes, "the builder opened no write connection"
    for kw in writes:
        assert kw.get("config", {}).get("force_compression") == "uncompressed", kw


def test_both_builders_say_the_same_thing():
    """No shared module exists for the literal, so the two sources must agree on it."""
    for script in ("build_cost_dataset.py", "build_fin_package.py"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert text.count('config={"force_compression": "uncompressed"}') == 1, script
