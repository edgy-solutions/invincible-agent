"""Every finance loader that resolves a seed directory from `__file__` must import, and find
its seed, in the FLATTENED engine-fin image.

`Dockerfile.agent` does `COPY ${AGENT_DIR}/ /app/`, so `measure_verbs.py` is `/app/measure_verbs.py`
there, its `Path(...).parents` is `('/app', '/')`, and the policy directories sit at `/app/policy/`.
A fixed `parents[2]` raises IndexError AT IMPORT -- the pod would crash-loop, and no test run from
a checkout can see it, because a checkout has the extra levels.

THE SET IS DERIVED, NOT TYPED: every `agent_fleet/finance_agent/*.py` that names `__file__` and
spells a `"policy" / "<dir>"` path. A new loader of that shape is covered the day it lands.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_FIN = Path(__file__).resolve().parents[2] / "agent_fleet" / "finance_agent"
_SEED = re.compile(r'"policy"\s*/\s*"(\w+)"')


def _loaders() -> list[tuple[str, str]]:
    out = []
    for path in sorted(_FIN.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "__file__" not in text:
            continue
        m = _SEED.search(text)
        if m:
            out.append((path.stem, m.group(1)))
    return out


_LOADERS = _loaders()


def _seed_defaults(module, seed_dir: Path) -> list[str]:
    """Names of the module's Path attributes equal to `seed_dir`."""
    return [k for k, v in vars(module).items() if isinstance(v, Path) and v == seed_dir]


def test_the_derivation_finds_the_loaders_it_is_meant_to():
    names = {n for n, _ in _LOADERS}
    assert {"measure_verbs", "method_registry"} <= names, _LOADERS


@pytest.mark.parametrize("module_name,seed", _LOADERS, ids=[n for n, _ in _LOADERS])
def test_the_loader_imports_and_finds_its_seed_in_the_flattened_layout(
    module_name, seed, tmp_path, monkeypatch
):
    app = tmp_path / "app"
    (app / "policy" / seed).mkdir(parents=True)
    copy = app / f"{module_name}.py"
    copy.write_bytes((_FIN / f"{module_name}.py").read_bytes())
    for sib in _FIN.glob("*.py"):  # siblings, so a flat `import measures` resolves as in /app
        if sib.stem != module_name:
            (app / sib.name).write_bytes(sib.read_bytes())
    monkeypatch.syspath_prepend(str(app))
    for env in ("MEASURE_POLICY_DIR", "MEASURE_VERB_POLICY_DIR", "FIN_EXPORT_PROFILE_POLICY_DIR"):
        monkeypatch.delenv(env, raising=False)

    unique = f"_flat_image_{module_name}"
    spec = importlib.util.spec_from_file_location(unique, copy)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, unique, module)  # restored: gov's ratchet reds a bare write
    spec.loader.exec_module(module)  # an IndexError here IS the defect

    found = _seed_defaults(module, (app / "policy" / seed).resolve())
    assert found, f"{module_name}: no default equals {app / 'policy' / seed}"


@pytest.mark.parametrize("module_name,seed", _LOADERS, ids=[n for n, _ in _LOADERS])
def test_the_loader_imports_when_its_file_sits_two_levels_deep_as_at_slash_app(
    module_name, seed, tmp_path, monkeypatch
):
    """The faithful `/app/<module>.py`: `parents` has only TWO entries, so `parents[2]` raises
    IndexError. A tmp dir is too deep to show that, so the module is run as if its file were at
    the filesystem root's `app/`, and must land on the image's `/app/policy/<dir>` fallback."""
    anchor = Path(tmp_path.anchor)
    fake = anchor / "app" / f"{module_name}.py"
    if (anchor / "app" / "policy").exists():
        pytest.skip("a real /app/policy exists on this machine")
    assert len(fake.resolve().parents) == 2, fake
    monkeypatch.syspath_prepend(str(_FIN))
    for env in ("MEASURE_POLICY_DIR", "MEASURE_VERB_POLICY_DIR", "FIN_EXPORT_PROFILE_POLICY_DIR"):
        monkeypatch.delenv(env, raising=False)

    unique = f"_flat_root_{module_name}"
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(unique, loader=None))
    module.__file__ = str(fake)
    monkeypatch.setitem(sys.modules, unique, module)
    source = (_FIN / f"{module_name}.py").read_text(encoding="utf-8")
    exec(compile(source, str(fake), "exec"), module.__dict__)  # IndexError IS the defect

    assert _seed_defaults(module, Path("/app/policy") / seed), (
        f"{module_name}: no default equals /app/policy/{seed}"
    )
