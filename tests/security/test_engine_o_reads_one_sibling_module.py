"""Engine O reads the sibling module a seal patches, whatever ran first.

Q8 (`test_q8_flips_on_one_precondition.py`) flips `SEED_PROVENANCE_STAMPED` on
`agent_fleet.ontology_service.notice_parts`. When an earlier test had put the engine dir on
`sys.path` and loaded `notice_parts` flat, engine O's flat-first import picked that second module
object, the flip never reached `/resolve_instance`, and two Q8 seals went red by order (11-16).

Each case runs in a fresh interpreter, so the answer does not depend on this suite's order. It
reproduces the polluting order first, then imports engine O in the package form.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

_REPO = Path(__file__).resolve().parents[2]
_OS = _REPO / "agent_fleet" / "ontology_service"
_SIBLINGS = ("notice_parts", "where_used")

_PROBE = r"""
import importlib, json, sys
os_dir, siblings = sys.argv[1], sys.argv[2].split(",")
sys.path.insert(0, os_dir)                      # the polluting order: engine dir on sys.path,
for s in siblings:                              # and each sibling already loaded flat
    importlib.import_module(s)
from agent_fleet.ontology_service import main
out = {}
for s in siblings:
    pkg = importlib.import_module("agent_fleet.ontology_service." + s)
    out[s] = {"flat_loaded": s in sys.modules,
              "engine_reads": getattr(main, "_" + s).__name__,
              "same_object": getattr(main, "_" + s) is pkg}
print(json.dumps(out))
"""


def _probe() -> dict:
    p = subprocess.run([sys.executable, "-c", _PROBE, str(_OS), ",".join(_SIBLINGS)],
                       cwd=str(_REPO), capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def probed() -> dict:
    return _probe()


@pytest.mark.parametrize("sibling", _SIBLINGS)
def test_the_polluting_order_was_reproduced(probed, sibling):
    # The control: without a flat module in sys.modules, the next assertion would pass vacuously.
    assert probed[sibling]["flat_loaded"] is True


@pytest.mark.parametrize("sibling", _SIBLINGS)
def test_engine_o_reads_the_package_module(probed, sibling):
    got = probed[sibling]
    assert got["same_object"] is True, (
        f"engine O reads {got['engine_reads']!r}, not agent_fleet.ontology_service.{sibling}: "
        "a seal patching the package module would miss the code under test")
