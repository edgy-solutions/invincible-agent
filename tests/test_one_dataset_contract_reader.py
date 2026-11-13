"""The shared dataset-contract reader is one module, and no engine keeps a copy (ruled 2026-11-11).

AST-based: it reads no runtime state. `agent_fleet/utils/dataset_contracts.py` is the only file under
`agent_fleet/` or `src/` that defines the reader's names, and every importer reaches it by the image's
path (`utils.dataset_contracts`) or the repo's (`agent_fleet.utils.dataset_contracts`).
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = "agent_fleet/utils/dataset_contracts.py"
_FUNCTIONS = {"load_contract", "check_contract_rows", "check_contract_schema"}
_CLASSES = {"DatasetContract", "ContractViolation"}


def _files(root: Path):
    for top in ("agent_fleet", "src"):
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root)
            if any(p.startswith(".venv") or p == "__pycache__" for p in rel.parts):
                continue
            yield path, rel.as_posix()


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _definers(root: Path) -> set[str]:
    found = set()
    for path, rel in _files(root):
        for node in _tree(path).body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _FUNCTIONS) or (
                isinstance(node, ast.ClassDef) and node.name in _CLASSES
            ):
                found.add(rel)
    return found


def _importers(root: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path, rel in _files(root):
        names = set()
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names if a.name.split(".")[-1] == "dataset_contracts"}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module.split(".")[-1] == "dataset_contracts":
                    names.add(node.module)
                elif any(a.name == "dataset_contracts" for a in node.names):
                    names.add(f"{node.module}.dataset_contracts")
        if names:
            out[rel] = names
    return out


def test_the_contract_reader_is_defined_once_in_utils():
    assert _definers(ROOT) == {SHARED}


def test_engine_fin_reads_the_shared_module():
    allowed = {"utils.dataset_contracts", "agent_fleet.utils.dataset_contracts"}
    importers = _importers(ROOT)
    for rel, names in importers.items():
        assert names <= allowed, (rel, names)
    assert "agent_fleet/finance_agent/asset_inputs.py" in importers
    assert "agent_fleet/finance_agent/measure_verbs.py" in importers
    assert not (ROOT / "agent_fleet/finance_agent/dataset_contracts.py").exists()


def test_the_exception_is_one_object():
    from agent_fleet.finance_agent import asset_inputs
    from agent_fleet.utils import dataset_contracts

    assert asset_inputs.ContractViolation is dataset_contracts.ContractViolation
    assert asset_inputs.check_contract_rows is dataset_contracts.check_contract_rows


def test_the_detector_finds_a_planted_copy(tmp_path):
    shared = tmp_path / "agent_fleet" / "utils"
    engine = tmp_path / "agent_fleet" / "some_engine"
    shared.mkdir(parents=True)
    engine.mkdir(parents=True)
    shutil.copy(ROOT / SHARED, shared / "dataset_contracts.py")
    shutil.copy(ROOT / SHARED, engine / "dataset_contracts.py")
    assert _definers(tmp_path) >= {SHARED, "agent_fleet/some_engine/dataset_contracts.py"}
    (engine / "reader.py").write_text("from some_engine import dataset_contracts\n", encoding="utf-8")
    assert _importers(tmp_path)["agent_fleet/some_engine/reader.py"] == {"some_engine.dataset_contracts"}
    (engine / "x.py").write_text("class K:\n    def load_contract(self): ...\n", encoding="utf-8")
    (engine / "y.py").write_text("def f():\n    def load_contract(): ...\n", encoding="utf-8")
    assert not {"agent_fleet/some_engine/x.py", "agent_fleet/some_engine/y.py"} & _definers(tmp_path)
