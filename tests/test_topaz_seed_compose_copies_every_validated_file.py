"""The topaz-seed CronJob's overlay compose must copy EVERY data file the validator requires.

In `configMap`/`git` mode the CronJob composes `/work/policy` from the overlay with a hand-kept
`for f in ...` loop, then runs `validate_policy.py`, which refuses a missing data file. The two lists
drifted on 2026-10-02 (82ed0b7f added `domain_consumption.yaml` and `program_members.yaml` to the
validator's DATA_FILES, not to the loop). From then on every overlay-mode seed run was REFUSED with
"MISSING", even when the overlay had both files. The sandbox runs `image` mode and never composes,
so only a work deployment could see it.

The expected set is READ from the validator's own `DATA_FILES` (parsed with `ast`; importing it
would drag in every sync module), never restated here. Each mode that composes is rendered.

Run: uv run pytest tests/test_topaz_seed_compose_copies_every_validated_file.py -q
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_CHART = "helm/invincible-agent"
_VALIDATOR = Path("policy/sync/validate_policy.py")

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_MODES = {
    "git": ["--set", "topazSeed.policySource.type=git",
            "--set", "topazSeed.policySource.git.repoUrl=https://example.invalid/policy.git"],
    "configMap": ["--set", "topazSeed.policySource.type=configMap",
                  "--set", "topazSeed.policySource.configMap.name=policy-overlay"],
}


def _validator_data_files() -> set[str]:
    tree = ast.parse(_VALIDATOR.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "DATA_FILES"):
            files = set(ast.literal_eval(node.value))
            assert files, "DATA_FILES parsed empty"
            return files
    raise AssertionError(f"no DATA_FILES assignment in {_VALIDATOR}")


def _cronjob(mode: str) -> str:
    r = subprocess.run(["helm", "template", "t", _CHART, "--set", "topazSeed.enabled=true",
                        *_MODES[mode]], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"helm template failed ({mode}): {r.stderr[-2000:]}"
    docs = [d for d in r.stdout.split("\n---") if re.search(r"^kind: CronJob$", d, re.M)
            and re.search(r"^  name: t-topaz-seed$", d, re.M)]
    assert len(docs) == 1, f"expected one topaz-seed CronJob in {mode} mode, got {len(docs)}"
    return docs[0]


def _compose_loop_files(doc: str) -> set[str]:
    loops = re.findall(r"^\s*for f in ([^;]+); do$", doc, re.M)
    assert len(loops) == 1, f"expected one compose `for f in` loop, got {loops!r}"
    return set(loops[0].split())


def test_the_validator_set_is_the_one_this_seal_reads():
    # Control: the parse reads the real tuple, including the two files that drifted.
    files = _validator_data_files()
    assert {"domain_consumption.yaml", "program_members.yaml", "users.yaml"} <= files


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_the_compose_loop_copies_every_validated_data_file(mode):
    copied = _compose_loop_files(_cronjob(mode))
    missing = _validator_data_files() - copied
    assert not missing, (
        f"{mode} mode: the CronJob composes /work/policy without {sorted(missing)}, which "
        f"validate_policy.py requires, so every run is REFUSED 'MISSING'")


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_the_compose_loop_copies_nothing_the_validator_does_not_name(mode):
    extra = _compose_loop_files(_cronjob(mode)) - _validator_data_files()
    assert not extra, f"{mode} mode: the loop copies {sorted(extra)}, unknown to the validator"
