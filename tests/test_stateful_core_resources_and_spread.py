"""KEYCLOAK, RESTATE AND WEAVIATE MUST CARRY MEMORY LIMITS AND A PREFERRED SPREAD AFFINITY.

Chart item before roll #16 (architect order, 2026-10-02): resource limits on Keycloak, Restate,
Weaviate and MinIO, plus affinity that spreads them across nodes.

MinIO (`iagent-minio`) is NOT covered here — it is deployed externally to this chart (see the
`minioBucketInit` comment block in values.yaml: "a separate manifest, not chart dependencies").
There is no MinIO pod template anywhere in `helm/invincible-agent/templates/`, so there is
nothing in this repo to assert resources or affinity on for it.

THE AFFINITY MUST STAY PREFERRED, NEVER REQUIRED. All three components' PVCs are
`storageClass: local-path`, and the four PVs measured 2026-10-02 (these three plus MinIO) are
all pinned to the SAME node — `local-path` has no cross-node migration. A REQUIRED pod
anti-affinity on the shared spread label would leave every pod after the first permanently
Pending, asking the scheduler to avoid the only node any of them can run on. So this file
asserts the preferred term is present AND that no required term exists at all — the second half
is not redundant with the first: a template could carry both.

THE SHARED LABEL MUST NEVER REACH A STATEFULSET'S spec.selector.matchLabels. Selectors are
immutable on an existing StatefulSet; adding a label there breaks `helm upgrade` on any release
that already exists. This file asserts the label is absent from `spec.selector.matchLabels`
specifically, not merely present somewhere in the manifest — an absence check anchored to the
right subtree, not the whole block.

Follows the shape of test_chart_renders_on_bare_defaults.py / test_task_grant_startup_sync_renders.py:
render with `helm template` and assert on the real (parsed) output, never on an empty string —
see test_chart_renders_on_bare_defaults.py's header for the false-green this guards against.

Run: uv run pytest tests/test_stateful_core_resources_and_spread.py -v
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_SCRIPT = _REPO / "scripts" / "upgrade-sandbox.sh"

_SPREAD_LABEL_KEY = "iagent.io/spread-group"
_SPREAD_LABEL_VALUE = "stateful-core"

# StatefulSet name -> values key the "drop its resources" mutant (m1) disables.
_STATEFULSETS = {
    "t-keycloak": "keycloak",
    "t-restate": "restate",
    "t-weaviate": "weaviate",
}

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(*extra: str) -> str:
    """Render the chart, failing the test with helm's own error rather than an empty string —
    an absence assertion over a failed render's empty output passes vacuously (see
    test_chart_renders_on_bare_defaults.py)."""
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, (
        f"helm template failed — every absence assertion below would pass vacuously on its "
        f"empty output:\n{r.stderr[-1200:]}"
    )
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _sandbox_values_args() -> list[str]:
    """DERIVE the sandbox values-file list from scripts/upgrade-sandbox.sh's own VALUES array
    rather than typing `values-sandbox.yaml` by hand — the two must never disagree about which
    overlays a sandbox render receives. Untracked/absent files (the gitignored secret overlay)
    are skipped, same as test_task_grant_startup_sync_renders.py does."""
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


def _statefulsets(rendered: str) -> dict[str, dict]:
    """Parse every StatefulSet out of a multi-document helm render, keyed by metadata.name."""
    docs = yaml.safe_load_all(rendered)
    out: dict[str, dict] = {}
    for doc in docs:
        if not doc or doc.get("kind") != "StatefulSet":
            continue
        out[doc["metadata"]["name"]] = doc
    return out


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_sandbox_values_args())


@pytest.fixture(scope="module")
def statefulsets(sandbox: str) -> dict[str, dict]:
    sts = _statefulsets(sandbox)
    missing = [n for n in _STATEFULSETS if n not in sts]
    assert not missing, f"expected StatefulSets missing from the sandbox render: {missing}"
    return sts


# ── positive control: there are no MORE spread-labelled StatefulSets than expected, and MinIO
#    genuinely has no pod template of its own in this chart ─────────────────────────────────

def test_minio_has_no_pod_template_in_this_chart():
    """Positive control for the spec's own scope note: MinIO is deployed externally, so the
    only MinIO-related template this chart owns is the bucket-init Job, never a StatefulSet or
    Deployment. If this ever stops being true, the three-component scope below is wrong and
    this test should be the one to say so."""
    templates_dir = _REPO / _CHART / "templates"
    names = {p.name for p in templates_dir.glob("*minio*")}
    assert names == {"minio-bucket-init-job.yaml"}, (
        f"expected minio's ONLY template to be the bucket-init Job, found: {sorted(names)} — "
        "if a StatefulSet/Deployment was added for it, it also needs resources + the spread "
        "label/affinity, and this test's scope comment is now stale"
    )


# ── (a) each of the three carries a non-empty resources.limits.memory ──────────────────────

@pytest.mark.parametrize("name", sorted(_STATEFULSETS))
def test_statefulset_has_memory_limit(name: str, statefulsets: dict[str, dict]):
    containers = statefulsets[name]["spec"]["template"]["spec"]["containers"]
    assert containers, f"{name}: no containers found"
    mem_limits = [
        c.get("resources", {}).get("limits", {}).get("memory") for c in containers
    ]
    assert any(mem_limits), (
        f"{name}: no container carries resources.limits.memory: {mem_limits}"
    )


# ── (b) each carries the spread label in pod-template metadata, and NOT in spec.selector ────

@pytest.mark.parametrize("name", sorted(_STATEFULSETS))
def test_statefulset_carries_spread_label_on_pod_template_only(
    name: str, statefulsets: dict[str, dict]
):
    sts = statefulsets[name]
    template_labels = sts["spec"]["template"]["metadata"].get("labels", {})
    assert template_labels.get(_SPREAD_LABEL_KEY) == _SPREAD_LABEL_VALUE, (
        f"{name}: pod template metadata is missing {_SPREAD_LABEL_KEY}={_SPREAD_LABEL_VALUE}"
    )
    selector_labels = sts["spec"]["selector"].get("matchLabels", {})
    assert _SPREAD_LABEL_KEY not in selector_labels, (
        f"{name}: spec.selector.matchLabels carries {_SPREAD_LABEL_KEY} — StatefulSet selectors "
        "are immutable, so this would break `helm upgrade` on an existing release"
    )


# ── (c) each carries the preferred anti-affinity term, and NO required term ────────────────

@pytest.mark.parametrize("name", sorted(_STATEFULSETS))
def test_statefulset_has_preferred_not_required_anti_affinity(
    name: str, statefulsets: dict[str, dict]
):
    pod_spec = statefulsets[name]["spec"]["template"]["spec"]
    affinity = pod_spec.get("affinity") or {}
    anti = affinity.get("podAntiAffinity") or {}

    preferred = anti.get("preferredDuringSchedulingIgnoredDuringExecution") or []
    assert preferred, f"{name}: no preferred pod anti-affinity term found"
    term = preferred[0]
    assert term.get("weight") == 100
    match_labels = (
        term.get("podAffinityTerm", {}).get("labelSelector", {}).get("matchLabels", {})
    )
    assert match_labels.get(_SPREAD_LABEL_KEY) == _SPREAD_LABEL_VALUE
    assert term.get("podAffinityTerm", {}).get("topologyKey") == "kubernetes.io/hostname"

    assert "requiredDuringSchedulingIgnoredDuringExecution" not in anti, (
        f"{name}: a REQUIRED anti-affinity term is present — all four local-path PVs in this "
        "deployment are pinned to the SAME node, so this would wedge every pod but the first "
        "into Pending forever"
    )


# ── the flip: prove the spread gate can go to zero ──────────────────────────────────────────

def test_disabling_stateful_spread_removes_every_spread_label_and_affinity():
    off = _render(*_sandbox_values_args(), "--set", "global.statefulSpread.enabled=false")
    sts = _statefulsets(off)
    for name in _STATEFULSETS:
        assert name in sts, f"{name}: missing from the disabled-spread render"
        template_labels = sts[name]["spec"]["template"]["metadata"].get("labels", {})
        assert _SPREAD_LABEL_KEY not in template_labels, (
            f"{name}: spread label still present with global.statefulSpread.enabled=false"
        )
        affinity = sts[name]["spec"]["template"]["spec"].get("affinity")
        assert not affinity, (
            f"{name}: affinity still present with global.statefulSpread.enabled=false: {affinity}"
        )
