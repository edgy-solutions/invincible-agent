"""Seal: an engine's flat sibling module (`seed`, `entities`, ...) must not outlive the test that
imported it (plugin `tests/flat_engine_modules.py`).

File A stages finance's flat `seed`/`entities` and leaves `sys.modules` alone; file B, sorted after
it, imports cost's export and needs cost's own `seed`. Both run in a subprocess with the repo's
conftest out of the way, once WITH the plugin (must pass) and once WITHOUT (the control: must fail,
B on the assertion), so the seal is shown able to fire.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_A = f'''
import sys

def test_a_stages_finance_flat():
    d = {str(ROOT / "agent_fleet" / "finance_agent")!r}
    sys.path.insert(0, d)
    try:
        import seed, entities  # noqa: F401
    finally:
        sys.path.remove(d)
'''

_B = f'''
import sys
from pathlib import Path

def test_b_cost_export_binds_cost_seed():
    sys.modules.pop("agent_fleet.cost_agent.export", None)
    sys.modules.pop("agent_fleet.cost_agent.seed", None)
    import agent_fleet.cost_agent.export as export
    assert hasattr(export.seed, "LEARNING_SLOPE"), export.seed
    cost = Path({str(ROOT / "agent_fleet" / "cost_agent")!r}).resolve()
    assert cost in Path(export.seed.__file__).resolve().parents
'''


def _run(tmp_path, *plugin):
    a = tmp_path / "test_a_stage.py"
    b = tmp_path / "test_b_consume.py"
    a.write_text(_A, encoding="utf-8")
    b.write_text(_B, encoding="utf-8")
    # The inner pytest gets its own ini and rootdir. Without them, its rootdir is the common
    # ancestor of the repo and tmp_path (the home directory), and collection walks all of the
    # temp directory, so a temp dir another process removes mid-walk is a random red.
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", str(ini),
         "--rootdir", str(tmp_path), *plugin, str(a), str(b)],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_THE_PLUGIN_KEEPS_A_FLAT_MODULE_FROM_OUTLIVING_ITS_TEST(tmp_path):
    r = _run(tmp_path, "-p", "tests.flat_engine_modules")
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]


def test_CONTROL_WITHOUT_THE_PLUGIN_THE_SAME_FILES_FAIL_ON_THE_ASSERTION(tmp_path):
    r = _run(tmp_path)
    assert r.returncode != 0, "control did not fail: the seal cannot fire\n" + r.stdout[-1500:]
    assert "test_b_consume.py::test_b_cost_export_binds_cost_seed" in r.stdout and "FAILED" in r.stdout, r.stdout[-1500:]
    assert "LEARNING_SLOPE" in r.stdout, r.stdout[-1500:]


def test_THE_DERIVED_SET_IS_REAL():
    from tests.flat_engine_modules import FLAT_NAMES

    assert {"seed", "entities", "measures"} <= FLAT_NAMES
    assert "__init__" not in FLAT_NAMES
    for n in FLAT_NAMES:
        assert list((ROOT / "agent_fleet").glob(f"*/{n}.py")), n
