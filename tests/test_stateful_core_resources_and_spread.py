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
_STATEFUL_NODE_LABEL_KEY = "iagent.io/stateful-node"

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


def _pod_templates(rendered: str) -> list[tuple[str, str, dict, dict]]:
    """Every rendered object that carries a pod template — a Deployment/StatefulSet's
    spec.template, or a (Cron)Job's spec.template / spec.jobTemplate.spec.template — as
    (kind, name, pod_spec, pod_template_labels). This DERIVES the "every pod template the chart
    renders" population from the render itself, rather than from template filenames, so a new
    template is picked up automatically and a removed one drops out on its own."""
    docs = yaml.safe_load_all(rendered)
    out: list[tuple[str, str, dict, dict]] = []
    for doc in docs:
        if not doc:
            continue
        spec = doc.get("spec") or {}
        if "jobTemplate" in spec:
            tmpl = spec["jobTemplate"]["spec"]["template"]
        elif "template" in spec:
            tmpl = spec["template"]
        else:
            continue
        pod_spec = tmpl["spec"]
        tmpl_labels = (tmpl.get("metadata") or {}).get("labels", {})
        out.append((doc["kind"], doc["metadata"]["name"], pod_spec, tmpl_labels))
    return out


def _is_stateful_core(template_labels: dict) -> bool:
    return template_labels.get(_SPREAD_LABEL_KEY) == _SPREAD_LABEL_VALUE


def _avoids_stateful_nodes(pod_spec: dict, label_key: str = _STATEFUL_NODE_LABEL_KEY) -> bool:
    """True iff EVERY nodeSelectorTerm (terms are OR'd together) carries a DoesNotExist
    matchExpression on label_key. A partial term would still let the pod land on a labelled node
    via whichever term lacks the expression, so "any term" is not sufficient — it must be all."""
    terms = (
        (pod_spec.get("affinity") or {})
        .get("nodeAffinity", {})
        .get("requiredDuringSchedulingIgnoredDuringExecution", {})
        .get("nodeSelectorTerms", [])
    )
    if not terms:
        return False
    for term in terms:
        exprs = term.get("matchExpressions") or []
        if not any(
            e.get("key") == label_key and e.get("operator") == "DoesNotExist" for e in exprs
        ):
            return False
    return True


class _DupKeyLoader(yaml.SafeLoader):
    """A YAML loader that REFUSES a mapping with a repeated `affinity` key, instead of the
    default last-one-wins. Plain yaml.safe_load would silently accept two `affinity:` keys in
    the same document and hand back only the second — exactly the failure mode the spec's merge
    requirement exists to prevent, so the detector must not share that blind spot.

    Scoped to the `affinity` key specifically (not "any duplicate key") — this chart has
    pre-existing, unrelated duplicate keys elsewhere (e.g. a repeated env var name in some
    container's env list) that are out of scope for this check and would otherwise false-positive
    it on every run."""


def _dup_key_construct_mapping(loader, node, deep=False):
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        if key == "affinity" and key in mapping:
            raise ValueError("duplicate 'affinity' key in mapping")
        mapping[key] = value
    return mapping


_DupKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _dup_key_construct_mapping
)


@pytest.fixture(scope="module")
def sandbox() -> str:
    return _render(*_sandbox_values_args())


@pytest.fixture(scope="module")
def statefulsets(sandbox: str) -> dict[str, dict]:
    sts = _statefulsets(sandbox)
    missing = [n for n in _STATEFULSETS if n not in sts]
    assert not missing, f"expected StatefulSets missing from the sandbox render: {missing}"
    return sts


@pytest.fixture(scope="module")
def pod_templates(sandbox: str) -> list[tuple[str, str, dict, dict]]:
    return _pod_templates(sandbox)


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


# ── "NOT STATEFUL NODES" — every pod template except the stateful-core three must refuse to
#    land on a node labelled for the stateful-core's local volumes ──────────────────────────────
#
# Chart item (architect order, 2026-10-02, following roll #16): global.statefulNodes adds a
# REQUIRED nodeAffinity (DoesNotExist on global.statefulNodes.labelKey) to every pod template in
# this chart OTHER than keycloak/restate/weaviate, so the reservation holds with no cordon.


# ── (a) every non-stateful-core pod template avoids nodes labelled for stateful-core ──────────

def test_non_stateful_core_pod_templates_avoid_stateful_nodes(
    pod_templates: list[tuple[str, str, dict, dict]]
):
    non_core = [
        (kind, name, pod_spec)
        for kind, name, pod_spec, labels in pod_templates
        if not _is_stateful_core(labels)
    ]
    # Measured on the sandbox render 2026-10-02: 39 non-stateful-core pod templates (28
    # Deployments, 8 Jobs, 3 StatefulSets). The floor below is deliberately well under that — it
    # exists to catch population derivation silently breaking (e.g. _pod_templates stops
    # matching anything), not to pin the exact count, which will grow as the chart does.
    assert len(non_core) >= 30, (
        f"only {len(non_core)} non-stateful-core pod templates found in the sandbox render — "
        "population derivation may be broken (see _pod_templates)"
    )
    missing = [f"{kind}/{name}" for kind, name, pod_spec in non_core if not _avoids_stateful_nodes(pod_spec)]
    assert not missing, (
        f"{len(missing)} non-stateful-core pod template(s) do not carry a REQUIRED nodeAffinity "
        f"DoesNotExist on {_STATEFUL_NODE_LABEL_KEY} in every nodeSelectorTerm: {missing}"
    )


# ── (b) no stateful-core pod template carries the rule ────────────────────────────────────────

def test_stateful_core_pod_templates_do_not_avoid_stateful_nodes(
    pod_templates: list[tuple[str, str, dict, dict]]
):
    core = [
        (kind, name, pod_spec)
        for kind, name, pod_spec, labels in pod_templates
        if _is_stateful_core(labels)
    ]
    assert len(core) == 3, f"expected exactly 3 stateful-core pod templates, found {len(core)}: {core}"
    unexpected = [f"{kind}/{name}" for kind, name, pod_spec in core if _avoids_stateful_nodes(pod_spec)]
    assert not unexpected, (
        "stateful-core pod template(s) unexpectedly carry the avoid-stateful-nodes rule — this "
        f"would keep them off the very node(s) they are reserved for: {unexpected}"
    )


# ── (c) disabling global.statefulNodes removes the rule everywhere ────────────────────────────

def test_disabling_stateful_nodes_removes_the_rule_everywhere():
    off = _render(*_sandbox_values_args(), "--set", "global.statefulNodes.enabled=false")
    assert _STATEFUL_NODE_LABEL_KEY not in off, (
        "global.statefulNodes.enabled=false but the label key string still appears somewhere "
        "in the render"
    )
    carriers = [
        f"{kind}/{name}"
        for kind, name, pod_spec, _labels in _pod_templates(off)
        if _avoids_stateful_nodes(pod_spec)
    ]
    assert not carriers, (
        f"pod template(s) still carry the avoid-stateful-nodes rule with "
        f"global.statefulNodes.enabled=false: {carriers}"
    )


# ── (d) no rendered document has duplicate affinity keys ──────────────────────────────────────

def test_no_rendered_document_has_duplicate_affinity_keys(sandbox: str):
    """Guards the spec's MERGE requirement: a template that gains its own pre-existing affinity
    block must merge this rule into it, never emit a second `affinity:` key. Plain YAML treats a
    duplicate mapping key as last-one-wins and would never surface this, so the detector uses its
    own loader that raises on a repeat key instead of silently keeping the second."""
    bad: list[str] = []
    for doc_text in re.split(r"(?m)^---$", sandbox):
        if not doc_text.strip():
            continue
        try:
            list(yaml.load_all(doc_text, Loader=_DupKeyLoader))
        except ValueError as e:
            bad.append(str(e))
        except yaml.YAMLError:
            pass  # a naive split on "---" lines can cut a multi-line scalar; unrelated here
    assert not bad, f"duplicate mapping key(s) found in the sandbox render: {bad}"


# ── (e) labelKey override is honoured ──────────────────────────────────────────────────────────

def test_stateful_node_label_key_override_is_honoured():
    custom_key = "example.io/custom-stateful-label"
    rendered = _render(
        *_sandbox_values_args(), "--set", f"global.statefulNodes.labelKey={custom_key}"
    )
    assert _STATEFUL_NODE_LABEL_KEY not in rendered, (
        "the default label key still appears in the render after overriding "
        "global.statefulNodes.labelKey"
    )
    non_core = [
        (kind, name, pod_spec)
        for kind, name, pod_spec, labels in _pod_templates(rendered)
        if not _is_stateful_core(labels)
    ]
    missing = [
        f"{kind}/{name}"
        for kind, name, pod_spec in non_core
        if not _avoids_stateful_nodes(pod_spec, label_key=custom_key)
    ]
    assert not missing, (
        f"{len(missing)} non-stateful-core pod template(s) do not carry the overridden "
        f"labelKey ({custom_key}): {missing}"
    )
