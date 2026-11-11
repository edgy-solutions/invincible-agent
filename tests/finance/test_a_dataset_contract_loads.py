"""A dataset contract is read by name, validated whole, and refused naming its file when it is not one.

`dataset_contracts.load_contract` is what a dataset measure row's `inputs.dataset.contract` joins at
load; `asset_inputs` then enforces what it returns on every read. ev_fixture is read as shipped, and
each way a contract can be malformed is planted on a copy of it.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_dataset_contract_loads.py
"""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import dataset_contracts

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "contracts" / "ev_fixture.yaml"
DOCKERFILE = ROOT / ".github" / "docker" / "Dockerfile.agent"
RAW = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))


def write(tmp_path, raw, name="ev_fixture"):
    (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp_path


def test_the_shipped_contract_loads_with_its_key_scope_and_dependencies():
    c = dataset_contracts.load_contract("ev_fixture", SHIPPED.parent)
    assert c.key == tuple(RAW["grain"]) and c.scope == RAW["scope"]
    assert c.types == {col["name"]: col["type"] for col in RAW["columns"]}
    assert c.required == tuple(col["name"] for col in RAW["columns"] if col["required"])
    assert c.dependencies == tuple((d["by"], tuple(d["determines"])) for d in RAW["dependencies"])
    assert "program_id" in c.determined_by("program_name") and c.determined_by("program_id") == frozenset()


def test_the_default_directory_is_the_repos_and_the_env_overrides_it(tmp_path, monkeypatch):
    monkeypatch.delenv("DATASET_CONTRACT_DIR", raising=False)
    assert dataset_contracts.contract_dir() == SHIPPED.parent
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(write(tmp_path, RAW)))
    assert dataset_contracts.contract_dir() == tmp_path
    assert dataset_contracts.load_contract("ev_fixture").contract_id == "ev_fixture"


def test_only_the_named_file_is_read(tmp_path):
    write(tmp_path, RAW)
    (tmp_path / "another_lanes_contract.yaml").write_text("{not: [a contract", encoding="utf-8")
    assert dataset_contracts.load_contract("ev_fixture", tmp_path).contract_id == "ev_fixture"


def _edit(path, value):
    def edit(raw):
        *head, last = path
        cur = raw
        for p in head:
            cur = cur[p]
        if value is None:
            del cur[last]
        else:
            cur[last] = value
    return edit


REFUSED = {
    "id_mismatch": (_edit(["contract_id"], "other"), "declares contract_id 'other'"),
    "unknown_type": (_edit(["columns", 0, "type"], "date"), "has type 'date'"),
    "column_twice": (lambda r: r["columns"].append(copy.deepcopy(r["columns"][0])), "declared twice"),
    "grain_undeclared": (_edit(["grain"], ["work_package", "pv"]), r"\['pv'\]"),
    "scope_undeclared": (_edit(["scope"], "programme"), r"\['programme'\]"),
    "dependency_undeclared": (lambda r: r["dependencies"].append({"by": "program_id", "determines": ["pv"]}),
                              r"\['pv'\]"),
    "dependency_empty": (lambda r: r["dependencies"].append({"by": "program_id", "determines": []}),
                         "at least one column other than itself"),
    "dependency_on_itself": (lambda r: r["dependencies"].append({"by": "work_package", "determines": ["work_package"]}),
                             "at least one column other than itself"),
    "by_optional": (lambda r: r["dependencies"].append({"by": "eac_reported", "determines": ["eac"]}),
                    "must be required columns"),
    "no_columns": (_edit(["columns"], None), "not a dataset contract"),
    "no_grain": (_edit(["grain"], None), "not a dataset contract"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_each_malformed_contract_is_refused_naming_its_file(case, tmp_path):
    edit, match = REFUSED[case]
    raw = copy.deepcopy(RAW)
    edit(raw)
    with pytest.raises(ValueError, match=match) as e:
        dataset_contracts.load_contract("ev_fixture", write(tmp_path, raw))
    assert "ev_fixture.yaml" in str(e.value)


@pytest.mark.parametrize("cid", ["../ev_fixture", "a/b", "a\\b", "", "  "])
def test_a_contract_id_that_is_a_path_or_blank_is_refused(cid, tmp_path):
    with pytest.raises(ValueError, match="not a path"):
        dataset_contracts.load_contract(cid, write(tmp_path, RAW))


def test_a_contract_with_no_file_is_refused_naming_it(tmp_path):
    with pytest.raises(ValueError, match="has no file absent.yaml"):
        dataset_contracts.load_contract("absent", tmp_path)


# ── the image ─────────────────────────────────────────────────────────────────────────────────

def test_the_image_carries_the_contracts_beside_the_flattened_loader():
    lines = [ln.strip() for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines()]
    assert "COPY contracts/ /app/contracts/" in lines


def test_the_flattened_loader_finds_the_contracts_at_app(tmp_path, monkeypatch):
    """`COPY ${AGENT_DIR}/ /app/` puts the module at /app/dataset_contracts.py; the walk-up must land
    on /app/contracts, which the COPY above provides."""
    app = tmp_path / "app"
    (app / "contracts").mkdir(parents=True)
    (app / "contracts" / "ev_fixture.yaml").write_bytes(SHIPPED.read_bytes())
    src = Path(dataset_contracts.__file__)
    (app / src.name).write_bytes(src.read_bytes())
    monkeypatch.delenv("DATASET_CONTRACT_DIR", raising=False)
    unique = "_flat_image_dataset_contracts"
    spec = importlib.util.spec_from_file_location(unique, app / src.name)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, unique, module)  # restored: gov's ratchet reds a bare write
    spec.loader.exec_module(module)
    assert module.contract_dir() == (app / "contracts").resolve()
    assert module.load_contract("ev_fixture").key == tuple(RAW["grain"])
