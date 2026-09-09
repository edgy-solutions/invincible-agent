"""The reader for the graph-manifest generator's seals.

`tests/test_board_drift.py`'s lesson, applied on day one rather than after: a generator with no
reader is an ASPIRATIONAL seal, and an aspirational seal is indistinguishable from a real one
while nobody looks. `scripts/generate_graph_manifest_schema.py` implements three checks —
schema-matches-models, every ratified row valid, population non-empty — and this file is what
turns them into enforcement. It ships in the same commit as the generator, deliberately.

ADR-0050 §1.2 requires the drift test "including its positive control, so the seal cannot pass
because the generator vanished". That control is `test_the_generator_is_actually_runnable`, and
it is first in the file because every assertion after it passes vacuously without it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "scripts" / "generate_graph_manifest_schema.py"
_SCHEMA = _ROOT / "schemas" / "graph_manifest.schema.json"
_POLICY = _ROOT / "policy" / "graphs"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_GEN), *args],
        cwd=_ROOT, capture_output=True, text=True,
    )


def test_the_generator_is_actually_runnable():
    """POSITIVE CONTROL. Without this, a deleted or unimportable generator makes every
    assertion below pass by never running — which is the exact failure ADR-0050 §1.2 names."""
    assert _GEN.exists(), f"the generator is gone: {_GEN}"
    r = _run("--check")
    assert r.returncode in (0, 1), (
        f"the generator did not run at all (exit {r.returncode}) — every drift assertion "
        f"below is vacuous until this passes.\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_the_committed_schema_matches_the_models():
    r = _run("--check")
    assert r.returncode == 0, (
        "graph-manifest schema drift, or an invalid ratified row:\n" + r.stdout + r.stderr
    )


def test_the_committed_schema_is_parseable_and_describes_the_contract():
    """The artifact has to be usable by something other than this repo's Python.

    Named fields rather than a count: a count passes when one field is swapped for another,
    and these six are the contract — both Contract D ends, the slot declarations, the arity
    the eligibility gate reads, the refusal disposition, and the verb itself.
    """
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    for field in ("verb", "input_uri", "output_uri", "slots", "arity", "refusal"):
        assert field in props, f"the committed schema does not describe {field!r}"
    assert schema.get("additionalProperties") is False, (
        "the schema must forbid extra properties — an unmodelled field in a ratified row is a "
        "contract clause nothing enforces"
    )


def test_an_invalid_ratified_row_fails_the_generator():
    """PROVEN TO BITE, on a copy. The generator's row validation is the rail that keeps an
    invalid manifest failing at merge instead of at boot in a pod, so it has to actually fail.

    Uses a temp policy dir rather than mutating the real one: a test that writes a broken row
    into `policy/graphs/` and crashes leaves the repo red for the next lane.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp_policy = Path(td) / "graphs"
        shutil.copytree(_POLICY, tmp_policy)
        (tmp_policy / "broken.yaml").write_text(
            "graph_id: broken\nmodule: graphs.x\nverb: no_colon_here\n"
            "name: x\ndescription: x\n"
            "input_uri: http://x#A\noutput_uri: http://x#B\n",
            encoding="utf-8",
        )
        from iagent_mesh.graph_manifest import load_manifests

        with pytest.raises(ValueError) as exc:
            load_manifests(tmp_policy)
        assert "broken.yaml" in str(exc.value), (
            "the failure must NAME THE FILE — 'a manifest is invalid' is not actionable at "
            "merge time, and naming the file is what makes it fixable without a bisect"
        )
