"""The case runner's input revisions ARE the SDK's ``ArtifactRevision`` chain, and its pull is the
SDK's ``RefreshSpec``: one vocabulary for one thing, and the worker is its first caller.

RULED 2026-10-06: ``refresh_input``'s revision logic was a local reimplementation of
``ArtifactRevision``/``RefreshSpec``, which the SDK owns (0.9.7+). The worker now builds and holds
the chain with the SDK's types, and ca's two conformance arms (0.9.8, ``1e7a717``) run against it
here -- "caller proves, then tag".

THREE KINDS OF ARM, and they need different SDKs:

* the census and the identity arms run on any SDK the runner imports;
* ca's two conformance arms exist only from 0.9.8, so on the root pin (``012a24f``, 0.9.7's
  branch) they SKIP, naming the sha they need. Proven 2026-10-06 against ``ced6133`` (ca's
  ``lane/ca-0.9.8`` head) on ``PYTHONPATH``, ``iagent_mesh.__file__`` checked;
* THE MERGE GATE: the worker IMAGE installs from ``agent_fleet/restate_analyst/pyproject.toml``
  (``uv sync --locked``), which pins ``v0.9.5`` -- a tag with neither type. Until that pin is the
  root's, everything above proved the runner against an SDK its image does not carry, so the gate
  is RED by design until the pin and its lock move together.

Run: uv run --frozen pytest tests/test_the_worker_is_the_sdk_revision_caller.py -v
"""
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import DOOR_BLOCK, R, _body, _Ctx, wr

import iagent_mesh.ingest as sdk_ingest  # noqa: E402
import iagent_mesh.provenance as sdk_provenance  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_AT0, _AT1 = "2026-10-06T00:00:00+00:00", "2026-10-06T00:00:01+00:00"


# ── ONE VOCABULARY ──────────────────────────────────────────────────────────────────────────

def test_THE_RUNNERS_REVISION_TYPES_ARE_THE_SDKS_OWN_OBJECTS():
    """Identity, not shape: a local model with the same fields would pass any shape check."""
    assert R.ArtifactRevision is sdk_ingest.ArtifactRevision
    assert R.RefreshSpec is sdk_ingest.RefreshSpec
    assert R.ProvenanceBlock is sdk_provenance.ProvenanceBlock
    assert type(R.first_revision(_AT0, DOOR_BLOCK)) is sdk_ingest.ArtifactRevision
    ann = R.Trigger.model_fields["refresh"].annotation
    assert sdk_ingest.RefreshSpec in getattr(ann, "__args__", (ann,)), ann


#: The SDK's revision vocabulary. A class of one of these names defined in this repo is a second
#: vocabulary for one thing, whatever its fields.
_SDK_NAMES = {"ArtifactRevision", "RefreshSpec", "ProvenanceBlock"}


def _defined_classes(roots):
    for root in roots:
        for f in root.rglob("*.py"):
            if any(part in {"__pycache__", "baml_client"} or part.startswith(".venv")
                   for part in f.parts):
                continue
            for node in ast.walk(ast.parse(f.read_bytes().decode("utf-8", "replace"))):
                if isinstance(node, ast.ClassDef):
                    yield f.relative_to(_REPO).as_posix(), node.name


def test_NO_MODULE_IN_THIS_REPO_DEFINES_ITS_OWN_REVISION_VOCABULARY():
    roots = [_REPO / "agent_fleet", _REPO / "src"]
    found = list(_defined_classes(roots))
    # POPULATION: the walk reaches the runner's own module and sees its classes.
    assert ("agent_fleet/restate_analyst/case_routing.py", "Trigger") in found
    assert [(f, n) for f, n in found if n in _SDK_NAMES] == []


# ── CA'S TWO ARMS, AGAINST THE REAL SEAM ────────────────────────────────────────────────────

def _arm(name):
    import iagent_mesh.conformance as conf
    fn = getattr(conf, name, None)
    if fn is None:
        pytest.skip(f"iagent_mesh.conformance.{name} is 0.9.8's (ca 1e7a717, lane/ca-0.9.8 "
                    f"ced6133); this venv's SDK ({conf.__file__}) predates it")
    return fn


def test_CA_ARM_THE_CHAIN_IS_BUILT_FROM_ITS_OWN_HEAD():
    """The seam's two build steps are the episode object's own handlers: the holder's ``claim``
    plants revision 1, and ``keep_revision`` appends after whatever head the object holds."""
    check = _arm("check_artifact_revision_chain_contract")
    obj = _Ctx(None, "ep")

    def _initial():
        head = {"revision": R.first_revision(_AT0, DOOR_BLOCK).model_dump(), "facts": {"v": 1}}
        assert asyncio.run(_body(wr.claim)(obj, {"case_id": "EV-1", "head": head})) == "EV-1"
        return sdk_ingest.ArtifactRevision.model_validate(obj.state["revision"]["revision"])

    def _next():
        asyncio.run(_body(wr.keep_revision)(obj, {
            "case_id": "EV-1", "facts": {"v": 2}, "received_at": _AT1, "provenance": DOOR_BLOCK}))
        return sdk_ingest.ArtifactRevision.model_validate(obj.state["revision"]["revision"])

    check(call_build_initial_revision=_initial, call_build_next_revision=_next)


def test_CA_ARM_A_PULL_URL_IS_KEYED_ON_THE_EVENT():
    check = _arm("check_refresh_spec_pull_contract")
    spec = sdk_ingest.RefreshSpec(url_template="https://picture.example/fault/{event_id}",
                                  method="GET", auth="seeding-delegate")
    check(identity_value="EV-417", call_pull_url=lambda: R.refresh_url(spec, "event_id", "EV-417"))


# ── THE MERGE GATE ──────────────────────────────────────────────────────────────────────────

_PIN = re.compile(r'"iagent-mesh @ git\+https://github\.com/edgy-solutions/iagent-mesh-sdk\.git@([^"\s]+)"')


def _pins(path: Path) -> set:
    return set(_PIN.findall(path.read_bytes().decode()))


def test_THE_WORKER_IMAGE_INSTALLS_THE_SDK_THESE_ARMS_RAN_AGAINST():
    """RED UNTIL LANE 1 MOVES THE WORKER'S PIN AND LOCK TOGETHER. The arms above import the
    root venv's SDK; the worker image installs its own pyproject's. If those differ, the image
    runs code no arm here has run -- today it would fail to import ``iagent_mesh.ingest``'s
    ``ArtifactRevision`` at startup, since ``v0.9.5`` carries neither type."""
    root = _pins(_REPO / "pyproject.toml")
    worker = _pins(_REPO / "agent_fleet" / "restate_analyst" / "pyproject.toml")
    # POPULATION: both files pin the SDK, and the root's pins agree with each other.
    assert len(root) == 1 and len(worker) == 1, (root, worker)
    assert worker == root, (
        f"the worker image pins iagent-mesh @{worker.pop()} and the seal ran against "
        f"@{root.pop()}; move agent_fleet/restate_analyst's pin AND its uv.lock to the root's")
