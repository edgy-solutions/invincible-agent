"""THE CHART MUST RENDER WITH NO VALUES FILE — because that is what every tool assumes.

`helm template helm/invincible-agent` FAILED on bare defaults, and had for some time:

    dagster.yaml:131            .Values.dagster.daemon.image.registry     nil
    dagster-user-code.yaml:120  .Values.dagster.docToolsCodeLocation      nil

Both are templates reading a key `values.yaml` never declared. `daemon.image.*` was
introduced deliberately — the template's own comment records that `webserver.image.*`
prevented per-component overrides — and the values block was never added.
`docToolsCodeLocation` was declared only in `values-sandbox.yaml`.

WHY A BROKEN BARE RENDER COSTS MORE THAN IT LOOKS. It is not the daemon that breaks; it is
every check that renders to verify something else:

* I could not render to confirm a ConfigMap line I had just written, and fell back to comparing
  its template expressions against a sibling line known to work. That caught the typo I had
  actually made (`.Values.ontologyService.port`, which does not exist and renders EMPTY), but
  only because I chose a good fallback — the render was the check I wanted.

* The LangGraph lane nearly shipped a FALSE GREEN from it: `helm template` against bare
  defaults returned **zero** occurrences of `engine-b` after retiring it — and zero because
  the render had FAILED, exit 1, producing no output at all. **A grep for ABSENCE over empty
  output is indistinguishable from success.** They caught it by rendering against
  `values-sandbox.yaml` instead and asserting what SHOULD be present alongside what should not.

That is the shape this file is built on, and it is theirs: **an absence assertion is only worth
its positive control.** Every "X is gone" check below is paired with "and Y is still here".

Run: uv run --frozen pytest tests/test_chart_renders_on_bare_defaults.py -v
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed"
)


def _render(*extra: str) -> str:
    """Render the chart, failing the test with helm's own error rather than an empty string.

    Returning "" on failure is precisely the trap this file documents: every downstream
    assertion about absence would then pass.
    """
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, (
        f"helm template failed — every absence assertion below would pass vacuously "
        f"on its empty output:\n{r.stderr[-700:]}"
    )
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


@pytest.fixture(scope="module")
def bare() -> str:
    return _render()


# ── it renders at all, and the render is non-empty ──────────────────────────

def test_the_chart_renders_with_no_values_file(bare: str):
    """THE REGRESSION. Two undeclared keys made this exit 1 for every caller."""
    assert "kind: Deployment" in bare


def test_the_render_is_substantial_not_a_stub(bare: str):
    """A positive control on the render itself: a chart that emitted one object would
    satisfy every assertion below while being obviously wrong."""
    assert bare.count("kind: Deployment") >= 15, (
        f"only {bare.count('kind: Deployment')} Deployments rendered"
    )


# ── the two keys that were missing ──────────────────────────────────────────

def test_the_daemon_declares_its_own_image():
    """`dagster.yaml` reads `.Values.dagster.daemon.image.*` on purpose — per-component
    overrides. A template reading a key values.yaml does not declare is the producer/consumer
    mismatch this repo keeps finding, in a chart instead of a payload."""
    v = (_REPO / _CHART / "values.yaml").read_text(encoding="utf-8")
    i = v.index("\n  daemon:")
    block = v[i:i + 700]
    assert "image:" in block, "dagster.daemon.image is undeclared again"


def test_docToolsCodeLocation_is_declared_and_OFF_by_default():
    """Declared so the render works; off because an optional second code location pointing at
    a sibling repo's service must be opted into, not inherited by every deployment."""
    v = (_REPO / _CHART / "values.yaml").read_text(encoding="utf-8")
    i = v.index("docToolsCodeLocation:")
    block = v[i:i + 200]
    assert "enabled: false" in block


# ── absence, each with its control ──────────────────────────────────────────

def test_engine_b_is_gone_AND_the_engines_that_remain_are_present():
    """THE LANGGRAPH LANE'S CHECK, in the form they arrived at. Asserting only that
    `t-engine-b` is absent passes on an empty render, on a typo in the name, and on a chart
    that renders nothing at all. The control is the engines that must still be there.

    RENDERED AGAINST values-sandbox.yaml, NOT BARE DEFAULTS — and the control is what taught
    me that. My first version asserted eight engines against the bare render and found six:
    cost, f and fin are `enabled: false` by default and only come up in a real deployment. So
    a bare render is the right place to ask "does it render", and the wrong place to ask
    "which engines are deployed". The positive control failed honestly rather than being
    lowered to match."""
    out = _render("-f", "helm/invincible-agent/values-sandbox.yaml")
    # RELEASE-PREFIXED. `helm template t` names resources `t-engine-cost`, not
    # `iagent-engine-cost` — and my first version looked for the `iagent-` prefix and "found"
    # six, because that string appears in hardcoded service URLs elsewhere in the output. The
    # control was measuring a coincidence. Second thing it caught about my own assumptions.
    expected = ("engine-a", "engine-cost", "engine-d", "engine-e", "engine-f",
                "engine-fin", "engine-o", "engine-p", "engine-w")
    nl = chr(10)
    missing = [e for e in expected if f"name: t-{e}{nl}" not in out]
    assert not missing, f"the control failed — these did not render: {missing}"
    # THE RESOURCE, not the string. `t-engine-b` still appears once — in the ConfigMap's
    # LANGGRAPH_SUPPORT_SVC_URL, which the LangGraph lane named as known residue: its only
    # reader is `synthesize_stateful`, which catches ConnectionError and returns
    # {"status": "skipped"}, so it degrades honestly. Asserting on the bare string would fail
    # on documented residue and force someone to weaken the check under time pressure. What
    # must not come back is the WORKLOAD.
    assert f"name: t-engine-b{nl}" not in out, (
        "Engine B renders as a resource again; it was retired 2026-09-06 (ADR-0046 §8.4)"
    )
    assert "LANGGRAPH_SUPPORT_SVC_URL" in out, (
        "the residue is gone — if the config key was removed, delete this control and the "
        "note above with it rather than leaving a comment describing a state that ended"
    )


def test_the_enumerate_url_points_at_the_fanout_AND_has_a_port(bare: str):
    """The line I could not render when I wrote it. `.Values.ontologyService.port` does not
    exist and would render `:/enumerate_instances` — a URL that is wrong in a way no absence
    check would notice, because the key IS present and merely empty."""
    line = next(l for l in bare.splitlines() if "ENUMERATE_INSTANCES_URL" in l)
    assert "-engine-o" in line, f"not the fan-out: {line.strip()}"
    assert ":8084/enumerate_instances" in line, (
        f"empty or wrong port — the values key is probably misnamed: {line.strip()}"
    )
