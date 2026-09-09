""":latest IDENTIFIES NOTHING — the chart must be pinnable, and the pin must reach everything.

WHY. On 2026-09-08 the question "is the fix on the pod?" was answered twice by a person
squinting at pod age and then importing a symbol by hand. Under `:latest` pod age is not
evidence: a pod started an hour ago may run a week-old image, and a week-old pod may have
been running the newest image the whole time.

WHAT THIS SEALS, and all three were broken when it was written:

  * `global.imageTag` reaches EVERY image built from this repo. It initially reached seven
    of twelve, because a component's own `tag` beats a global one and fourteen values
    entries said `tag: "latest"` outright.
  * the floor is a tag that EXISTS. The chain fell through to `Chart.AppVersion`
    (`2026.07.02`), and CI publishes `:<git-sha>` and `:latest` and nothing else — so every
    values file was papering over a broken default with the same literal that made the pin
    unreachable.
  * unset changes NOTHING. A migration that alters today's deploy is not a migration.

Run: uv run --frozen pytest tests/test_the_fleet_can_be_pinned_to_one_commit.py -v
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"
_WORKFLOW = _REPO / ".github" / "workflows" / "build-containers.yml"

#: Images built from this repo. Third-party images (postgres, restate, keycloak) carry
#: their own versions and MUST NOT move with a commit pin — a test that swept them in would
#: be demanding the chart pin postgres to a git sha.
OURS = re.compile(r"ghcr\.io/[^/]+/invincible-agent/([a-z0-9-]+):(\S+)")

_PIN = "abc123def456"


def _render(*extra: str) -> dict:
    """`name -> tag` for every image of ours the chart renders."""
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm not on PATH")
    proc = subprocess.run(
        [helm, "template", "t", str(_CHART), "-f", str(_SANDBOX), *extra],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    found = dict(OURS.findall(proc.stdout))
    # THE FLOOR ON THE DERIVATION. A render that produced two images would pass every
    # assertion below while testing almost nothing — the scrape reading too little fails
    # OPEN. See [[a-green-seal-can-be-green-for-the-wrong-reason]].
    assert len(found) >= 10, f"the render scrape found only {len(found)}: {sorted(found)}"
    return found


def test_the_pin_reaches_EVERY_image_we_build():
    """THE ENUMERATION LAW. It reached seven of twelve when written: a component's own tag
    beats a global one, and fourteen values entries said `tag: "latest"` outright. A pin
    that silently skips five services is worse than none, because the census then reports
    a fleet that looks uniform and is not."""
    tags = _render("--set", f"global.imageTag={_PIN}")
    unpinned = sorted(n for n, t in tags.items() if t != _PIN)
    assert not unpinned, (
        f"{len(unpinned)} image(s) ignored global.imageTag: {unpinned} — a component tag "
        f"beats a global one, so any literal left in a values file is a hole in the pin"
    )


def test_UNSET_is_exactly_today():
    """A migration that changes the current deploy is not a migration. Every service runs
    `:latest` right now and must keep doing so until someone sets the knob."""
    tags = _render()
    wrong = sorted(f"{n}:{t}" for n, t in tags.items() if t != "latest")
    assert not wrong, f"the default changed for: {wrong}"


def test_the_floor_is_a_tag_that_EXISTS():
    """`Chart.AppVersion` names an image that has never been published — CI pushes
    `:<git-sha>` and `:latest` and nothing else. Falling through to it is a latent break
    that every environment was hiding with a per-component literal, and that literal is
    what made the pin unreachable. Asserted on the RENDER rather than on the helper's
    source, so rewriting the helper cannot quietly restore the old floor."""
    app_version = next(
        ln.split(":", 1)[1].strip().strip('"')
        for ln in (_CHART / "Chart.yaml").read_text(encoding="utf-8").splitlines()
        if ln.startswith("appVersion:")
    )
    tags = _render()
    assert app_version not in set(tags.values()), (
        f"an image resolved to Chart.AppVersion ({app_version!r}), which the registry has "
        f"never had"
    )


def test_a_component_may_still_override_deliberately():
    """THE CONTROL. A pin that could not be overridden would block a hotfix under test —
    and, more to the point, an assertion that everything ALWAYS equals the global would
    also pass against a helper that ignored component tags entirely."""
    tags = _render("--set", f"global.imageTag={_PIN}",
                   "--set", "engineO.image.tag=hotfix-1")
    assert tags["ontology-service"] == "hotfix-1", tags["ontology-service"]
    assert tags["cortex-bff"] == _PIN, "one override leaked into the rest of the fleet"


# ── the stamp the census reads ──────────────────────────────────────────────

def test_every_runtime_stage_bakes_the_commit():
    """THE PROCESS COLUMN'S SOURCE. Baked at build time, not injected by the chart: a
    chart-injected tag is a claim about what was REQUESTED, and under `:latest` it is not
    even that. Three inline Dockerfiles cover all sixteen services; a stage that misses the
    stamp reports `n/a` forever and its services are invisible to the census."""
    wf = _WORKFLOW.read_text(encoding="utf-8")
    dockerfiles = re.findall(r"cat << 'EOF' > (Dockerfile\.\S+)", wf)
    assert len(dockerfiles) == 3, f"the Dockerfile set changed: {dockerfiles}"
    assert wf.count("ENV IAGENT_GIT_SHA=$GIT_SHA") == len(dockerfiles), (
        f"{wf.count('ENV IAGENT_GIT_SHA=$GIT_SHA')} stage(s) stamp the commit but there "
        f"are {len(dockerfiles)} Dockerfiles — a runtime without the stamp is invisible "
        f"to the census"
    )
    assert wf.count("ARG GIT_SHA=unknown") == len(dockerfiles)


def test_every_build_PASSES_the_commit():
    """`ARG` without `--build-arg` defaults to the literal 'unknown', which the census
    treats as absent — a stamp that is present and always says 'unknown' is worse than no
    stamp, because the column looks populated."""
    wf = _WORKFLOW.read_text(encoding="utf-8")
    builds = wf.count("docker buildx build")
    passes = wf.count("--build-arg GIT_SHA=")
    assert builds == passes, (
        f"{builds} build invocation(s) but {passes} pass GIT_SHA — the unfed one bakes "
        f"'unknown'"
    )


def test_the_census_treats_unknowable_as_NOT_current():
    """The census's own disposition, which is the half that makes it usable as a gate.

    `:latest` with no stamp cannot be placed against a ref. Reporting that as passing is
    how a census becomes decoration — and it is the whole population today, so getting this
    backwards would make the tool answer "all current" for a fleet it cannot see."""
    src = (_REPO / "scripts" / "version_census.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.unparse(main)
    assert "UNKNOWN (no stamp, unpinned tag)" in body
    # The unknown branch must ALSO mark the service bad; a verdict string with no
    # consequence is a label, not a gate.
    unknown_branch = body.split("UNKNOWN (no stamp, unpinned tag)")[1][:200]
    assert "bad.append" in unknown_branch, (
        "an unplaceable service is labelled UNKNOWN but not counted against the gate"
    )


# ── /version: the process's own answer ──────────────────────────────────────

def _vp():
    import sys
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from agent_fleet.utils.version_endpoint import version_payload
    return version_payload


def test_an_unstamped_image_reports_NULL_not_a_plausible_string(monkeypatch):
    """`unknown` is what an image built before the stamp existed bakes into `ARG GIT_SHA`.
    Passing that through as a STRING would give every consumer a truthy value that looks
    like an answer — the census would place it, the UI would print it, and a fleet with no
    identity would read as one that has it. Absent is reported as absent."""
    monkeypatch.delenv("IAGENT_GIT_SHA", raising=False)
    assert _vp()("engine-x")["git_sha"] is None
    monkeypatch.setenv("IAGENT_GIT_SHA", "unknown")
    assert _vp()("engine-x")["git_sha"] is None, (
        "the literal 'unknown' reached a consumer as if it were a commit"
    )
    monkeypatch.setenv("IAGENT_GIT_SHA", "50649d966b1b")
    assert _vp()("engine-x")["git_sha"] == "50649d966b1b"


def test_the_spec_and_the_process_are_reported_SEPARATELY(monkeypatch):
    """A disagreement between them is the finding — the pod did not restart, or something
    is serving that the spec did not describe. Collapsing them into one field removes the
    only way to tell those apart, and under `:latest` the spec identifies nothing at all."""
    monkeypatch.setenv("IAGENT_GIT_SHA", "aaaaaaaaaaaa")
    monkeypatch.setenv("IAGENT_IMAGE_TAG", "latest")
    p = _vp()("engine-x")
    assert p["git_sha"] == "aaaaaaaaaaaa" and p["image_tag"] == "latest"
    assert p["repo"] == "invincible-agent", (
        "the payload must name its own repo — the frontend rolls separately and holding it "
        "to this repo's head would call a correct deploy stale"
    )


def test_EVERY_service_mounts_it():
    """THE ENUMERATION LAW, with the population derived from the services that exist rather
    than from a list someone maintains. A service missing the mount is invisible to the
    census forever, and the fleet reads complete without it."""
    import ast
    mains = sorted(_REPO.glob("agent_fleet/*/main.py"))
    assert len(mains) >= 12, f"only found {len(mains)} services"
    missing = []
    for f in mains:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        has_app = any(
            isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "app" for t in n.targets)
            and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", "") == "FastAPI"
            for n in tree.body
        )
        if not has_app:
            continue  # cortex_bff re-exports the gateway's app; sealed below
        mounted = any(
            isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_mount_version"
            for n in ast.walk(tree)
        )
        if not mounted:
            missing.append(f.parent.name)
    assert not missing, f"service(s) with no /version mount: {missing}"


def test_the_gateway_mounts_it_AND_aggregates():
    """The BFF is the one service whose app lives outside `agent_fleet/`, and it is also
    where the aggregator has to be: one call from outside the cluster instead of thirteen
    execs from inside it, which is the difference between a check that gets run and one
    that does not."""
    import ast
    gw = ast.parse((_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(gw)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_mount_version"]
    assert calls, "the gateway does not mount /version"
    fn = next((n for n in ast.walk(gw)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "fleet_version"), None)
    assert fn is not None, "no /fleet/version aggregator"
    body = ast.unparse(fn)
    assert "unreachable" in body, (
        "the aggregator drops services it cannot reach — a mid-roll pod, a crash-looping "
        "pod and one that was never deployed all vanish, and the fleet reads complete"
    )


def test_the_targets_are_DERIVED_from_the_environment():
    """A hardcoded service list is how a new engine's URL lands in the ConfigMap and the
    census silently does not include it. The population comes from the deployment."""
    import ast
    gw = ast.parse((_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(gw)
              if isinstance(n, ast.FunctionDef) and n.name == "_fleet_version_targets")
    body = ast.unparse(fn)
    assert "os.environ.items()" in body, "the target list is not derived from the environment"
    assert "_PUBLIC_URL" in body
