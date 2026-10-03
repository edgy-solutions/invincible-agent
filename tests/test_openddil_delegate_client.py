"""OpenDDIL's delegate client (iagent-openddil) — Keycloak mints its secret.

Declares a new `keycloak.extraServiceClients` entry, `iagent-openddil`, whose `kind` is
`delegate` and which carries NO `secretRef`: Keycloak generates its secret at creation, and this
chart never supplies, regenerates or rotates one for it. `onBehalfOf` records three principals
(operator.atlantia, operator.borduria, liaison) — a DECLARATION only, this commit; nothing in
the BFF consumes it yet.

`extraServiceClients` is a SEPARATE key from `keycloak.serviceClients`, same schema, that an
environment overlay can set to APPEND clients without replacing the base list (a Helm overlay
REPLACES a list wholesale). iagent-openddil lives there, in values-sandbox.yaml, and NOT in the
base values.yaml's serviceClients — its onBehalfOf principals only exist in the sandbox
overlay's nonInteractiveUsers, so declaring it in the base list would make the base chart fail
to render on its own (the STOP finding this commit's amendment resolves).

This also makes `secretRef` optional chart-wide, and introduces `kind` (service | delegate) and
`onBehalfOf` as general serviceClients/extraServiceClients fields, validated once in the shared
named template `invincible-agent.validateServiceClients` (templates/_helpers.tpl) — which
validates the CONCATENATION of both lists — and called from BOTH consumers — the first-boot
realm import (keycloak-configmap.yaml) and the realm reconcile job (realm-reconcile-job.yaml) —
so the rule lives in one place rather than two copies that could drift.

Arms:
  (a) the base values.yaml renders ALONE (no overlay) and its import carries no iagent-openddil.
  (b) the import JSON for iagent-openddil has no "secret" key, and carries BOTH the authz-id and
      initiator_kind mappers with the right claim values.
  (c) the reconcile script creates iagent-openddil without a secret, with an initiator_kind
      mapper in the create payload, and never touches an EXISTING client's secret.
  (d) every pre-existing client's rendered import object AND reconcile script segments are
      byte-identical to the base sha's render (client list derived from values.yaml, not typed),
      and extraServiceClients APPENDS to serviceClients rather than replacing it.
  (e) kind other than service/delegate fails the render, for EITHER list.
  (f) onBehalfOf on a service client fails the render.
  (g) an onBehalfOf user absent from nonInteractiveUsers fails the render, naming it.
  (h) a bad onBehalfOf role fails the render.
  (i) the reconcile verify (readback) step checks initiator_kind for a delegate client.

Follows the shape of test_stateful_core_resources_and_spread.py: render with `helm template` and
assert on the real rendered text/parsed output, never on an empty string.

Run: uv run --frozen python -m pytest tests/test_openddil_delegate_client.py -v
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_BASE_SHA = "9d7be1260e0e73937911b26b75df98b6f77f41b5"  # lane/01-stateful-spread tip this builds on

_NEW_CLIENT_ID = "iagent-openddil"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", _CHART, *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(_REPO), timeout=300,
    )


def _render(*extra: str) -> str:
    """Render the chart, failing the test with helm's own error rather than an empty string —
    an assertion over a failed render's empty output would pass vacuously."""
    r = _run(list(extra))
    assert r.returncode == 0, (
        f"helm template failed — assertions below would pass vacuously on its empty output:\n"
        f"{r.stderr[-1500:]}"
    )
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _render_fails(*extra: str) -> str:
    """Render expecting a FAILURE; returns stderr for message assertions."""
    r = _run(list(extra))
    assert r.returncode != 0, "expected helm template to fail the render, but it succeeded"
    return r.stderr


_SANDBOX_ARGS = ["-f", str(_REPO / _CHART / "values-sandbox.yaml")]
# values-sandbox.secret.yaml is untracked and absent in this worktree (confirmed: `ls` 404s).
# No dummy --set values were needed anywhere in this file: every render below (positive and
# negative) succeeds/fails for the reason under test without supplying one.


def _configmap_clients(rendered: str) -> dict[str, dict]:
    """Parse the keycloak-configmap.yaml's embedded realm-export.json and return
    clientId -> client-object, keyed from the actual parsed JSON (not string search)."""
    docs = yaml.safe_load_all(rendered)
    for doc in docs:
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"].endswith("-keycloak-realm"):
            realm = json.loads(doc["data"]["realm-export.json"])
            return {c["clientId"]: c for c in realm["clients"] if "clientId" in c}
    raise AssertionError("keycloak realm ConfigMap not found in render")


def _reconcile_script(rendered: str) -> str:
    """Return the realm-reconcile Job's shell script (the container's args string)."""
    docs = yaml.safe_load_all(rendered)
    for doc in docs:
        if doc and doc.get("kind") == "Job" and doc["metadata"]["name"].endswith("-realm-reconcile"):
            args = doc["spec"]["template"]["spec"]["containers"][0]["args"]
            assert len(args) == 1
            return args[0]
    raise AssertionError("realm-reconcile Job not found in render")


_SEGMENT_SPLIT = re.compile(
    # The YAML block scalar strips the common leading indentation from every line, so these
    # anchors are at column 0 in the PARSED string (verified: the raw args[0] string has no
    # leading spaces before "CID=", unlike the template source).
    r'(?=\nCID="|\n# .. NON-INTERACTIVE USERS|\n\[ "\$rc")'
)


def _client_segments(script: str) -> dict[str, list[str]]:
    """Split the reconcile script into per-client segments. Each client appears exactly twice
    (once in the create/repair loop, once in the readback loop); segments are bounded so that
    trailing fixed boilerplate (the NON-INTERACTIVE USERS block, the final rc check) never
    leaks into the LAST client's segment regardless of how many clients precede or follow it —
    a naive "to next CID or EOF" split would make a client's segment text depend on its
    POSITION in the list, which is not what "byte-identical per client" should mean."""
    chunks = _SEGMENT_SPLIT.split(script)
    out: dict[str, list[str]] = {}
    for chunk in chunks:
        m = re.match(r'\nCID="([^"]+)"', chunk)
        if not m:
            continue
        out.setdefault(m.group(1), []).append(chunk)
    return out


@pytest.fixture(scope="module")
def sandbox_render() -> str:
    return _render(*_SANDBOX_ARGS)


@pytest.fixture(scope="module")
def base_render() -> str:
    """The base values.yaml ALONE, no overlay — this must render on its own (the STOP finding
    this amendment resolves: onBehalfOf's referential check used to require principals that only
    exist in the sandbox overlay's nonInteractiveUsers)."""
    return _render()


@pytest.fixture(scope="module")
def base_sha_render() -> str:
    """Render the chart as it stood at the base sha, using ITS OWN values files (extracted via
    `git archive`, never a live worktree checkout — read-only, no git-worktree/stash
    interaction)."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ia-base-sha-") as td:
        tar = subprocess.run(
            ["git", "archive", _BASE_SHA, "--", "helm/invincible-agent"],
            capture_output=True, cwd=str(_REPO), timeout=60,
        )
        assert tar.returncode == 0, tar.stderr.decode(errors="replace")
        extract = subprocess.run(
            ["tar", "-x"], input=tar.stdout, capture_output=True, cwd=td, timeout=60,
        )
        assert extract.returncode == 0, extract.stderr.decode(errors="replace")
        chart_dir = Path(td) / "helm" / "invincible-agent"
        assert (chart_dir / "Chart.yaml").exists()
        r = subprocess.run(
            ["helm", "template", "t", str(chart_dir), "-f", str(chart_dir / "values-sandbox.yaml")],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        assert r.returncode == 0, f"base-sha render failed:\n{r.stderr[-1500:]}"
        return r.stdout


def _pre_existing_client_ids() -> list[str]:
    """Derive the base sha's client list from ITS OWN values.yaml — never a literal list typed
    here, which would silently stop tracking the real population the moment either side
    changed."""
    out = subprocess.run(
        ["git", "show", f"{_BASE_SHA}:helm/invincible-agent/values.yaml"],
        capture_output=True, cwd=str(_REPO), timeout=30,
    )
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    values = yaml.safe_load(out.stdout)
    ids = [c["clientId"] for c in values["keycloak"]["serviceClients"]]
    assert ids and _NEW_CLIENT_ID not in ids
    return ids


def _base_values_service_client_ids() -> list[str]:
    """Parse the CURRENT worktree's values.yaml (not the base sha) for keycloak.serviceClients
    client ids — the population extraServiceClients must APPEND to, never replace. Derived from
    the real file, never hand-typed, so it keeps tracking the real list if either side changes."""
    values = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    ids = [c["clientId"] for c in values["keycloak"]["serviceClients"]]
    assert ids and _NEW_CLIENT_ID not in ids, (
        "iagent-openddil belongs in extraServiceClients (values-sandbox.yaml), not the base "
        "serviceClients list"
    )
    return ids


def _probe_extra_args(extra_service_clients: list[dict]) -> list[str]:
    """Like _probe_args, but overrides keycloak.extraServiceClients instead of serviceClients —
    for probing that the shared validator also covers the second list."""
    return _SANDBOX_ARGS + ["--set-json", f"keycloak.extraServiceClients={json.dumps(extra_service_clients)}"]


# ─────────────────────────────── (a) base values.yaml renders alone ───────────────────────────────

def test_base_values_renders_alone_without_openddil(base_render):
    """The STOP finding this amendment resolves: base values.yaml must render with no overlay at
    all, and since iagent-openddil now lives in extraServiceClients (sandbox-only), it must be
    ABSENT from the base render's import."""
    clients = _configmap_clients(base_render)
    assert _NEW_CLIENT_ID not in clients, (
        "iagent-openddil comes from extraServiceClients (sandbox overlay only), not base values.yaml"
    )
    # Sanity: this is a real, populated render, not an empty/broken one.
    assert "iagent-graph-host" in clients
    for cid in _base_values_service_client_ids():
        assert cid in clients


# ─────────────────────────────── (b) import JSON ───────────────────────────────

def test_import_has_no_secret_key_for_openddil(sandbox_render):
    clients = _configmap_clients(sandbox_render)
    assert _NEW_CLIENT_ID in clients
    assert "secret" not in clients[_NEW_CLIENT_ID], (
        "iagent-openddil has no secretRef — the import must omit \"secret\" so Keycloak mints one"
    )


def test_import_carries_both_mappers_for_openddil(sandbox_render):
    mappers = {m["name"]: m for m in _configmap_clients(sandbox_render)[_NEW_CLIENT_ID]["protocolMappers"]}
    assert mappers["authz-id-svc"]["config"]["claim.value"] == "svc:openddil"
    assert mappers["authz-id-svc"]["config"]["claim.name"] == "email"
    ik = mappers["initiator-kind-svc"]
    assert ik["config"]["claim.name"] == "initiator_kind"
    assert ik["config"]["claim.value"] == "delegate"
    assert ik["protocolMapper"] == "oidc-hardcoded-claim-mapper"


def test_import_service_clients_get_no_initiator_kind_mapper(sandbox_render):
    clients = _configmap_clients(sandbox_render)
    for cid, c in clients.items():
        if cid in ("cortex-ui", _NEW_CLIENT_ID):
            continue
        names = {m["name"] for m in c.get("protocolMappers", [])}
        assert "initiator-kind-svc" not in names, f"{cid} is not a delegate client"


# ─────────────────────────────── (c) reconcile create ───────────────────────────────

def test_reconcile_creates_openddil_without_secret_and_with_initiator_kind(sandbox_render):
    """Scoped to the CREATE sub-block specifically (the text before this segment's own first
    "else"): the segment as a WHOLE also contains the REPAIR branch, which legitimately mentions
    initiator-kind-svc too (its own HAS2 repair check) — asserting over the whole segment would
    pass even if the CREATE payload's mapper were dropped, since the repair branch's occurrence
    would still satisfy a substring search (verified: this is exactly what mutant m2 does)."""
    script = _reconcile_script(sandbox_render)
    seg = _client_segments(script)[_NEW_CLIENT_ID][0]  # create/repair-loop occurrence
    create_block = seg.split("else", 1)[0]
    assert '"secret":' not in create_block, "create payload for a secretRef-less client must omit \"secret\""
    assert '"name": "initiator-kind-svc"' in create_block
    assert '"claim.value": "delegate"' in create_block


def test_reconcile_never_touches_an_existing_clients_secret(sandbox_render):
    """For EVERY existing client's own create/repair segment (bounded by _client_segments, so
    this never spills into a NEIGHBOUR client's "if absent -> creating" block, which also
    legitimately contains a "secret" line for ITS OWN creation): the "present" (repair) branch —
    the text after that one client's own first "else" — must never mention a secret at all."""
    segs = _client_segments(_reconcile_script(sandbox_render))
    for cid in _pre_existing_client_ids():
        seg = segs[cid][0]  # create/repair-loop occurrence
        present_branch = seg.split("else", 1)[1]
        assert '"secret"' not in present_branch, (
            f"{cid}: an existing client's secret must never be set/rotated by the reconcile job"
        )


# ─────────────────────────────── (d) existing clients unchanged; extraServiceClients appends ───────────────────────────────

def test_preexisting_clients_import_unchanged(sandbox_render, base_sha_render):
    old = _configmap_clients(base_sha_render)
    new = _configmap_clients(sandbox_render)
    for cid in _pre_existing_client_ids():
        assert new[cid] == old[cid], f"{cid}'s rendered import object changed"


def test_preexisting_clients_reconcile_segments_unchanged(sandbox_render, base_sha_render):
    """Compare each pre-existing client's two segments (create/repair, readback), trailing
    newlines stripped: the LAST client in the OLD list sits directly against the fixed
    "NON-INTERACTIVE USERS" / final-rc-check boilerplate (one blank line of static separator),
    while in the NEW list it is immediately followed by another client's CID (no blank line) —
    a one-newline difference from WHERE a segment sits, not from what it renders. Comparing the
    content with trailing newlines stripped keeps the assertion about the client's OWN
    templated text rather than its neighbour's position."""
    old_segs = _client_segments(_reconcile_script(base_sha_render))
    new_segs = _client_segments(_reconcile_script(sandbox_render))
    for cid in _pre_existing_client_ids():
        old = [s.rstrip("\n") for s in old_segs[cid]]
        new = [s.rstrip("\n") for s in new_segs[cid]]
        assert old == new, f"{cid}'s reconcile script segments changed"


def test_sandbox_extraserviceclients_appends_base_clients(sandbox_render):
    """extraServiceClients must APPEND iagent-openddil to the base serviceClients list, never
    REPLACE it — a Helm overlay replaces a list wholesale, which is exactly the failure mode a
    second, separate key exists to avoid."""
    clients = _configmap_clients(sandbox_render)
    for cid in _base_values_service_client_ids():
        assert cid in clients, f"{cid}: extraServiceClients must append, not replace, serviceClients"
    assert _NEW_CLIENT_ID in clients


# ─────────────────────────────── (e)-(h) render-time validation ───────────────────────────────

def _probe_args(service_clients: list[dict]) -> list[str]:
    return _SANDBOX_ARGS + ["--set-json", f"keycloak.serviceClients={json.dumps(service_clients)}"]


def test_bad_kind_fails_render():
    err = _render_fails(*_probe_args([
        {"clientId": "iagent-probe", "authzId": "svc:probe", "kind": "bogus"},
    ]))
    assert "iagent-probe" in err and "bogus" in err


def test_onbehalfof_on_service_client_fails_render():
    err = _render_fails(*_probe_args([
        {
            "clientId": "iagent-probe", "authzId": "svc:probe", "kind": "service",
            "onBehalfOf": [{"user": "platform-registrar", "role": "operator"}],
        },
    ]))
    assert "iagent-probe" in err and "onBehalfOf" in err


def test_onbehalfof_user_not_in_nonInteractiveUsers_fails_render_naming_it():
    err = _render_fails(*_probe_args([
        {
            "clientId": "iagent-probe", "authzId": "svc:probe", "kind": "delegate",
            "onBehalfOf": [{"user": "nobody-such-user", "role": "operator"}],
        },
    ]))
    assert "nobody-such-user" in err


def test_onbehalfof_bad_role_fails_render():
    err = _render_fails(*_probe_args([
        {
            "clientId": "iagent-probe", "authzId": "svc:probe", "kind": "delegate",
            "onBehalfOf": [{"user": "platform-registrar", "role": "bogus-role"}],
        },
    ]))
    assert "iagent-probe" in err and "bogus-role" in err


def test_bad_kind_in_extraServiceClients_fails_render():
    """The shared validator must cover BOTH lists: an invalid entry in extraServiceClients alone
    (serviceClients left at its real, valid sandbox contents) must still fail the render."""
    err = _render_fails(*_probe_extra_args([
        {"clientId": "iagent-probe-extra", "authzId": "svc:probe-extra", "kind": "bogus"},
    ]))
    assert "iagent-probe-extra" in err and "bogus" in err


# ─────────────────────────────── (i) readback checks initiator_kind ───────────────────────────────

def test_readback_fails_a_delegate_client_missing_initiator_kind(sandbox_render):
    script = _reconcile_script(sandbox_render)
    seg = _client_segments(script)[_NEW_CLIENT_ID][1]  # readback-loop occurrence
    assert "initiator-kind-svc" in seg
    assert "initiator_kind not minted by any mapper" in seg


def test_readback_does_not_check_initiator_kind_for_service_clients(sandbox_render):
    script = _reconcile_script(sandbox_render)
    segs = _client_segments(script)
    for cid in _pre_existing_client_ids():
        readback_seg = segs[cid][1]
        assert "initiator_kind" not in readback_seg, f"{cid} is a service client"
