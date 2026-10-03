"""TOPAZ MANIFEST LOAD — closes the "topazSeed is default-OFF" gap for the ReBAC schema itself.

82ed0b7f added the `program` type to topaz-configmap.yaml's manifest.yaml. The roll shipped
the configmap, but nothing LOADED it into Topaz's directory in sandbox (topazSeed.enabled:
false; the only loader was a hand-run `topaz ds set manifest`), so program_member_sync died
E20026 until a human loaded it by hand. `templates/topaz-manifest-load-job.yaml` folds the
load into the roll, gated by `topazManifestLoad.enabled` (off in base, on in sandbox), at hook
weight "2" — strictly before taskGrantSync's weight "3" — running `policy/sync/load_manifest.py`.

A manifest SET REPLACES THE WHOLE SCHEMA (no partial/merge apply), so the script is not a
blind "load the file": it fail-closed PRE-CHECKS that the live directory declares no top-level
type the file does not (else it would silently DROP that type's objects/relations), loads,
then READS BACK that every file type is present. See policy/sync/load_manifest.py's header.

This file covers:
  (a) chart render: base has no Job; sandbox has exactly one, hook weight "2" strictly before
      the task-grant Job's weight "3" (both read from the render, never restated), mounting
      manifest.yaml from the topaz-config ConfigMap, carrying the stateful-node exclusion.
  (b) policy/sync/load_manifest.py unit arms (i)-(iv) against a recording double.
  (c) TopazClient.get_manifest() against a real httpx transport stub (200 / 404 / 500).

Run: uv run pytest tests/test_topaz_manifest_load_job.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_SCRIPT = _REPO / "scripts" / "upgrade-sandbox.sh"

_SYNC = _REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from topaz_sync import TopazClient  # noqa: E402
from load_manifest import (  # noqa: E402
    load_manifest,
    missing_after_load,
    parse_types,
    precheck,
)

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(*extra: str) -> str:
    """Render the chart, failing on helm's own error rather than an empty string — an absence
    assertion over a failed render's empty output passes vacuously."""
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, (
        f"helm template failed — every absence assertion below would pass vacuously on its "
        f"empty output:\n{r.stderr[-700:]}"
    )
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _sandbox_values_args() -> list[str]:
    """DERIVE the sandbox values-file list from scripts/upgrade-sandbox.sh's own VALUES array
    (same helper as test_task_grant_startup_sync_renders.py) rather than typing
    `values-sandbox.yaml` by hand — the render under test must receive the exact overlay set a
    real sandbox upgrade would pass."""
    src = _SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"VALUES=\((.*?)\)", src, re.S)
    assert m, "scripts/upgrade-sandbox.sh's VALUES array is not in the recognised shape"
    paths = re.findall(r'"\$\{CHART\}/([^"]+)"', m.group(1))
    assert paths, "parsed zero paths out of upgrade-sandbox.sh's VALUES array"
    assert "values-sandbox.yaml" in paths
    args: list[str] = []
    chart_dir = _REPO / _CHART
    for p in paths:
        f = chart_dir / p
        if f.exists():
            args += ["-f", str(f)]
    return args


@pytest.fixture(scope="module")
def bare() -> str:
    return _render()


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_sandbox_values_args())


# ── (a) chart render ─────────────────────────────────────────────────────────

def test_bare_defaults_render_no_manifest_load_job(bare: str):
    assert "topaz-manifest-load" not in bare, (
        "topazManifestLoad.enabled defaults to true, or the guard is missing — bare defaults "
        "must never surprise-run a schema load"
    )


def test_sandbox_renders_exactly_one_manifest_load_job(sandbox: str):
    assert sandbox.count("name: t-topaz-manifest-load\n") == 1, (
        "expected exactly one topaz-manifest-load Job in the sandbox render"
    )


def test_sandbox_job_hook_weight_strictly_before_task_grant(sandbox: str):
    """Read BOTH weights from the render — never restate either as a literal — so a change to
    either Job's weight is caught here rather than silently reordering the hooks."""
    def weight_after(marker: str) -> int:
        i = sandbox.index(marker)
        block = sandbox[i:i + 900]
        m = re.search(r'"helm\.sh/hook-weight":\s*"(-?\d+)"', block)
        assert m, f"no hook-weight found after {marker!r}"
        return int(m.group(1))

    manifest_weight = weight_after("name: t-topaz-manifest-load")
    grant_weight = weight_after("name: t-task-grant-sync")
    assert manifest_weight < grant_weight, (
        f"manifest-load weight {manifest_weight} must be strictly before task-grant weight "
        f"{grant_weight} — a new type must exist before anything writes objects of it"
    )


def test_sandbox_job_mounts_manifest_yaml_from_topaz_config(sandbox: str):
    i = sandbox.index("name: t-topaz-manifest-load")
    block = sandbox[i:i + 4000]
    assert "name: t-topaz-config" in block
    assert "key: manifest.yaml" in block
    assert "path: manifest.yaml" in block
    assert "mountPath: /topaz-config" in block


def test_sandbox_job_runs_load_manifest(sandbox: str):
    i = sandbox.index("name: t-topaz-manifest-load")
    block = sandbox[i:i + 4000]
    assert "load_manifest.py" in block


def test_sandbox_job_carries_the_stateful_node_exclusion(sandbox: str):
    """This Job runs on a plain node like every other startup-sync Job — see
    _helpers.tpl's invincible-agent.avoidStatefulNodes. Asserted explicitly here in addition to
    test_stateful_core_resources_and_spread.py's generic sweep, since this is the behaviour the
    spec calls out by name."""
    i = sandbox.index("name: t-topaz-manifest-load")
    block = sandbox[i:i + 4000]
    assert "DoesNotExist" in block


# ── the flip: prove (a) actually tests something ────────────────────────────

def test_flipping_topazManifestLoad_off_makes_the_seal_go_red():
    off = _render(*_sandbox_values_args(), "--set", "topazManifestLoad.enabled=false")
    assert "topaz-manifest-load" not in off, (
        "disabling topazManifestLoad still rendered a manifest-load resource — the enabled "
        "gate is not wired to the template"
    )


# ── real manifest types, derived from the rendered configmap (never typed by hand) ──────────

def _real_manifest_types(sandbox: str) -> set[str]:
    # Find the FULL line (including its leading indent), not just the substring — indexing on
    # the bare "manifest.yaml: |" text drops its own leading spaces and under-measures the
    # key's indent, which would make the body-end check below fire too late (or never).
    key_line_start = sandbox.rindex("\n", 0, sandbox.index("manifest.yaml: |")) + 1
    lines = sandbox[key_line_start:].splitlines()
    key_indent = len(lines[0]) - len(lines[0].lstrip(" "))
    # The block-scalar body: every subsequent line indented deeper than "manifest.yaml: |"
    # itself, up to the first non-blank line that returns to that indent or shallower (the
    # next configmap key / resource boundary).
    body_lines = []
    for line in lines[1:]:
        if line.strip() == "":
            body_lines.append("")
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= key_indent:
            break
        body_lines.append(line[key_indent + 2:])  # de-indent by the block-scalar's own 2 spaces
    return parse_types("\n".join(body_lines))


def test_real_manifest_types_derived_from_rendered_configmap(sandbox: str):
    """Sanity check on the derivation helper itself — not a judgment call, a parse: the
    manifest.yaml committed to the chart is known (from the survey) to declare these types."""
    types = _real_manifest_types(sandbox)
    assert {"user", "dataset", "document", "ontology_class", "task_audience", "program"} <= types


# ── (b) load_manifest.py unit arms, against a recording double ─────────────

class _RecordingClient:
    """Records calls; serves get_manifest() from a mutable `live` string that set_manifest can
    update, so arm (ii)/(iv) can assert the SECOND get_manifest() reflects the load."""

    def __init__(self, live: str = ""):
        self.live = live
        self.set_calls: list[Path] = []
        self.get_calls = 0

    def get_manifest(self) -> str:
        self.get_calls += 1
        return self.live

    def set_manifest_from_file(self, path: Path) -> None:
        self.set_calls.append(path)
        self.live = path.read_text()


def _manifest_file(tmp_path: Path, types: dict) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump({"types": types}))
    return p


def test_arm_i_live_extra_type_refuses_and_never_calls_set(tmp_path, sandbox: str):
    """(i) live declares a type the file does not -> non-zero naming it, set() never called."""
    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}})
    client = _RecordingClient(live=yaml.safe_dump({"types": {"user": {}, "legacy_widget": {}}}))
    rc = load_manifest(client, file_path)
    assert rc != 0
    assert client.set_calls == [], "pre-check must refuse BEFORE any set() call"


def test_arm_ii_fresh_empty_live_loads_and_passes_readback(tmp_path):
    """(ii) fresh/empty live -> set() called once, readback passes."""
    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}, "program": {}})
    client = _RecordingClient(live="")
    rc = load_manifest(client, file_path)
    assert rc == 0
    assert len(client.set_calls) == 1
    assert client.get_calls == 2  # pre-check + readback


def test_empty_live_manifest_goes_straight_to_load_not_refused(tmp_path):
    """A fresh cluster's live manifest is "" (get_manifest's 404-> "" normalization) — precheck
    on an empty live_types must be [] (never refuse), so the flow goes straight to
    load-then-readback. Asserted at BOTH levels: the pure function or it is just restating the
    behaviour by a different route."""
    assert precheck({"user", "dataset", "program"}, set()) == []

    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}, "program": {}})
    client = _RecordingClient(live="")  # the same shape get_manifest() returns on a 404
    rc = load_manifest(client, file_path)
    assert rc == 0
    assert client.set_calls == [file_path], "empty live must proceed straight to load, not refuse"
    assert client.get_calls == 2  # pre-check + readback — the refusal branch never returns early


def test_end_to_end_404_live_manifest_loads_via_real_get_manifest(tmp_path):
    """Same claim as above, but through the REAL TopazClient.get_manifest() against an httpx
    stub that actually returns 404 for an empty directory, then 200 with the posted body after
    set_manifest_from_file — proving the 404->"" normalization itself (not a recording double
    standing in for it) is what lets the pre-check proceed rather than refuse."""
    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}, "program": {}})

    class _FreshClusterTransport(httpx.BaseTransport):
        def __init__(self):
            self.live_body: str | None = None  # None == nothing loaded yet == 404

        def handle_request(self, request):
            if request.method == "GET":
                if self.live_body is None:
                    return httpx.Response(404)
                return httpx.Response(200, text=self.live_body)
            if request.method == "POST":
                self.live_body = request.content.decode()
                return httpx.Response(200)
            raise AssertionError(f"unexpected method {request.method}")

    client = TopazClient("http://topaz")
    client._client._transport = _FreshClusterTransport()
    rc = load_manifest(client, file_path)
    assert rc == 0, "a 404 (fresh cluster) live manifest must not be refused by the pre-check"


def test_arm_iii_readback_missing_type_fails(tmp_path, monkeypatch):
    """(iii) readback missing a file type -> non-zero naming it."""
    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}, "program": {}})

    class _LiesOnReadback(_RecordingClient):
        def set_manifest_from_file(self, path: Path) -> None:
            self.set_calls.append(path)
            self.live = yaml.safe_dump({"types": {"user": {}, "dataset": {}}})  # drops "program"

    client = _LiesOnReadback(live="")
    rc = load_manifest(client, file_path)
    assert rc != 0
    assert len(client.set_calls) == 1, "set() IS called in this arm — it is the readback that lies"


def test_arm_iv_identical_or_superset_by_file_loads_and_passes(tmp_path):
    """(iv) file is identical to (or a superset of) live -> loads, passes."""
    file_path = _manifest_file(tmp_path, {"user": {}, "dataset": {}, "program": {}})
    client = _RecordingClient(live=yaml.safe_dump({"types": {"user": {}, "dataset": {}}}))
    rc = load_manifest(client, file_path)
    assert rc == 0
    assert len(client.set_calls) == 1


def test_parse_types_pure():
    assert parse_types("") == set()
    assert parse_types("types:\n  user: {}\n  dataset: {}\n") == {"user", "dataset"}


def test_precheck_pure():
    assert precheck({"user"}, set()) == []  # fresh cluster always proceeds
    assert precheck({"user"}, {"user", "legacy"}) == ["legacy"]
    assert precheck({"user", "legacy"}, {"legacy"}) == []


def test_missing_after_load_pure():
    assert missing_after_load({"user", "program"}, {"user"}) == ["program"]
    assert missing_after_load({"user"}, {"user", "program"}) == []


# ── (c) TopazClient.get_manifest(), against a real httpx transport stub ────

class _StubTransport(httpx.BaseTransport):
    def __init__(self, status: int, body: str = ""):
        self.status = status
        self.body = body

    def handle_request(self, request):
        return httpx.Response(self.status, text=self.body)


def test_get_manifest_200_returns_body():
    client = TopazClient("http://topaz")
    client._client._transport = _StubTransport(200, "types:\n  user: {}\n")
    assert client.get_manifest() == "types:\n  user: {}\n"


def test_get_manifest_404_returns_empty_string():
    """A fresh cluster with no manifest ever loaded — normalized to "" rather than raised."""
    client = TopazClient("http://topaz")
    client._client._transport = _StubTransport(404)
    assert client.get_manifest() == ""


def test_get_manifest_500_raises():
    """Everything else (topaz unreachable/broken) fails CLOSED."""
    client = TopazClient("http://topaz")
    client._client._transport = _StubTransport(500, "internal error")
    with pytest.raises(httpx.HTTPStatusError):
        client.get_manifest()
