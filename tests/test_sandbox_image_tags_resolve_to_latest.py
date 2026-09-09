"""The sandbox tracks master, so every image it runs must RESOLVE to `latest`.

WHY THIS EXISTS. Engine P was deployed with `enginePlanning.image.tag: ""` in values.yaml
and no override in values-sandbox.yaml, and went straight to ImagePullBackOff asking for
`planning-agent:2026.07.02` — a tag that has never existed, because the planning agent was
built for the first time that day.

The chart had TWO working conventions for the same outcome, and nothing named them:

  * declare `tag: "latest"` in values.yaml            (engineA, engineE, engineW, ...)
  * declare `tag: ""` + override in values-sandbox    (engineO, engineD, engineF, ...)

Both resolved to `latest`. A component that did NEITHER fell through to the chart
appVersion — a July snapshot. For components that existed in July that tag resolves and the
mistake is invisible; for anything built since, the pod cannot start.

REWRITTEN 2026-09-09, AND THE REWRITE IS THE POINT.

This file used to resolve tags with its own `_resolve_tag`, whose docstring read "Mirror
templates/_helpers.tpl" — A COPY OF THE PRECEDENCE CHAIN, inside the test that exists to
police that chain. When the chart's floor was changed from `Chart.AppVersion` to `latest` —
fixing, at the source, the exact break described above — this file went red reporting the
old floor. The mirror had drifted, and it was the mirror that was wrong.

It now renders with `helm template`, so there is ONE implementation of the precedence and
this reads its output. Same move as deleting the routing-record copy rather than sealing the
agreement between two producers; see [[a-green-seal-can-be-green-for-the-wrong-reason]].

The per-component `tag: "latest"` literals this file was written to tolerate are also gone
from both values files. They were not merely redundant once the floor was fixed — a
component tag BEATS a global one, so each was a hole in any fleet-wide `global.imageTag`
commit pin.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

CHART = pathlib.Path(__file__).resolve().parents[1] / "helm" / "invincible-agent"

#: Images built from this repo. Third-party images carry their own versions and must not be
#: swept in — a test demanding postgres resolve to `latest` would be asking for the opposite
#: of what pinning is for.
_OURS = re.compile(r"ghcr\.io/[^/]+/invincible-agent/([a-z0-9-]+):(\S+)")


def _load(name: str) -> dict:
    return yaml.safe_load((CHART / name).read_text(encoding="utf-8")) or {}


def _rendered_tags(*extra: str) -> dict:
    """`image-name -> tag`, from `helm template` — the REAL helper, never a mirror of it."""
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm not on PATH")
    proc = subprocess.run(
        [helm, "template", "t", str(CHART), "-f", str(CHART / "values-sandbox.yaml"), *extra],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    found = dict(_OURS.findall(proc.stdout))
    # FLOOR ON THE DERIVATION. A render that yielded two images would satisfy every
    # assertion below while checking almost nothing — a scrape that reads too little fails
    # OPEN, which is the failure mode no mutation covers.
    assert len(found) >= 10, f"the render scrape found only {len(found)}: {sorted(found)}"
    return found


def test_every_sandbox_enabled_built_image_resolves_to_latest() -> None:
    """An UNPINNED render must put every image of ours on `latest`.

    Asserted on what helm actually produces, not on which convention a component used —
    the chart is allowed to keep both, and neither is the "right" one to imitate.
    """
    app_version = str(_load("Chart.yaml").get("appVersion", ""))
    offenders = [
        f"{name} -> {tag!r}" for name, tag in sorted(_rendered_tags().items())
        if tag != "latest"
    ]
    assert not offenders, (
        "sandbox-enabled components resolve to a tag other than 'latest':\n  "
        + "\n  ".join(offenders)
        + f"\n\nThe chart's floor is `global.defaultImageTag`. appVersion is {app_version!r} "
        "and names an image CI has never published — it publishes `:<git-sha>` and "
        "`:latest`, and nothing else."
    )


def test_a_component_that_declares_NOTHING_still_resolves() -> None:
    """THE ENGINE P CASE, now structural rather than conventional.

    The two working conventions were both per-component, so a new component that used
    neither fell through to appVersion and could not start. The floor is now a tag that
    exists, which makes declaring nothing safe by construction.
    """
    assert _load("values.yaml")["global"]["defaultImageTag"] == "latest"


def test_no_literal_tag_shadows_a_fleet_pin() -> None:
    """The other half, and the reason the literals were removed rather than left alone.

    A component's own `tag` beats `global.imageTag`, so every `tag: "latest"` in a values
    file was a service the commit pin would silently skip — leaving a fleet that reads
    uniform in the census while running two different commits.
    """
    for name in ("values.yaml", "values-sandbox.yaml"):
        raw = (CHART / name).read_text(encoding="utf-8")
        assert 'tag: "latest"' not in raw, (
            f"{name} declares a literal 'latest' tag again — a component tag beats "
            f"global.imageTag, so this is a hole in any fleet-wide commit pin"
        )


def test_the_pin_moves_everything_it_should() -> None:
    """THE CONTROL on the two tests above. `latest` everywhere would also be produced by a
    helper that ignored the global knob entirely; this is what distinguishes a floor that
    works from one that is merely always chosen."""
    tags = _rendered_tags("--set", "global.imageTag=deadbeefcafe")
    stuck = sorted(n for n, t in tags.items() if t != "deadbeefcafe")
    assert not stuck, f"image(s) ignored the fleet pin: {stuck}"
