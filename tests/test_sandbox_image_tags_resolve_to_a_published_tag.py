"""An unpinned image must resolve to a tag SOMETHING PUBLISHES — and the publisher is asserted here.

WHY THIS EXISTS. Engine P was deployed with `enginePlanning.image.tag: ""` and no sandbox
override, and went straight to ImagePullBackOff asking for `planning-agent:2026.07.02` — a tag
that has never existed, because the planning agent was built for the first time that day. The
chart's floor fell through to `Chart.AppVersion`, a July snapshot: for components that existed in
July it resolved and the mistake was invisible; for anything newer the pod could not start.

THE PROPERTY IS "A TAG THAT EXISTS". `latest` was the MECHANISM, and this file used to assert the
mechanism — its own name said `..._resolve_to_latest`. That was right while CI published
`:<git-sha>` and `:latest` and nothing else.

RENAMED AND REWRITTEN 2026-09-17, because that premise is now false and THIS CHANGE IS WHAT MADE
IT FALSE. The release workflow retags every image of the build matrix, by digest, to the chart
version; the chart's floor is `Chart.Version`. An unpinned deploy now names an artifact instead
of a moving label.

  latest      an unpinned deploy got whatever `latest` was AT PULL TIME — a different artifact on
              Tuesday than on Monday, from the same chart, with nothing recording they differed
  0.3.78      "install chart 0.3.78" means one set of bytes, forever

── THE ARM THAT DID NOT EXIST BEFORE ────────────────────────────────────────────────────────────

The old file asserted the floor and took CI's behaviour FROM A SENTENCE IN ITS OWN DOCSTRING
("CI publishes `:<git-sha>` and `:latest`"). Both ends were checked and the relation between them
was checked nowhere — so on the day the publisher changed, every arm here would have stayed green
about a floor whose guarantee had evaporated.
`test_THE_FLOOR_IS_A_TAG_THE_RELEASE_ACTUALLY_PUBLISHES` is that join, read from the release
workflow rather than restated.

A floor that resolves is worth nothing if nothing publishes what it resolves to.

Run: uv run --frozen pytest tests/test_sandbox_image_tags_resolve_to_a_published_tag.py -v
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

_REPO = pathlib.Path(__file__).resolve().parents[1]
CHART = _REPO / "helm" / "invincible-agent"
_RELEASE_WF = _REPO / ".github" / "workflows" / "release-helm-charts.yml"

#: Images built from this repo. Third-party images carry their own versions and must not be
#: swept in — a test demanding postgres resolve to the chart version would be asking for the
#: opposite of what pinning is for.
_OURS = re.compile(r"ghcr\.io/[^/]+/invincible-agent/([a-z0-9-]+):(\S+)")


def _load(name: str) -> dict:
    return yaml.safe_load((CHART / name).read_text(encoding="utf-8")) or {}


def _chart_version() -> str:
    """READ, never restated. A literal here would be a second declaration of the version, and it
    would go stale on the next bump while still passing."""
    v = str(_load("Chart.yaml").get("version", "")).strip()
    assert v, "Chart.yaml declares no version"
    return v


def _rendered_tags(*extra: str) -> dict:
    """`image-name -> tag`, from `helm template` — the REAL helper, never a mirror of it.

    This file used to resolve tags with its own `_resolve_tag`, whose docstring read "Mirror
    templates/_helpers.tpl". When the chart's floor changed, the mirror drifted and reported the
    old floor — and the mirror was what was wrong. One implementation, read here.
    """
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
    # FLOOR ON THE DERIVATION. A render that yielded two images would satisfy every assertion
    # below while checking almost nothing — a scrape that reads too little fails OPEN, which is
    # the failure mode no mutation covers.
    assert len(found) >= 10, f"the render scrape found only {len(found)}: {sorted(found)}"
    return found


#: The retag step's header. Named once so the slice below and the reader agree on which step.
_RETAG_STEP = "- name: Retag images to the chart version, by digest"


def _retag_block() -> str:
    """The retag STEP alone, bounded by the next step.

    SCOPED, and the scoping is not cosmetic. The first draft of the join arm asserted
    `helm show chart helm/invincible-agent` against the whole file and SURVIVED a mutation that
    broke the retag step's copy — because the version-GUARD step upstream contains the same
    line, and the assertion was reading that one. A check matching a string anywhere in a file
    answers about the file, not about the step it names.
    """
    wf = _RELEASE_WF.read_text(encoding="utf-8")
    # ANCHORED ON THE STEP HEADER, not on the script name. Bounding from the invocation started
    # the slice AFTER the version derivation the join arm is about — the arm passed by reading a
    # block that could not contain what it asserted, which is the same defect one layer in.
    i = wf.index(_RETAG_STEP)
    j = wf.index(chr(10) + "      - name:", i + len(_RETAG_STEP))
    block = wf[i:j]
    assert "retag_images_by_digest.py" in block, (
        "the retag step no longer invokes the retag script, or the step header moved and this "
        "slice is reading a different step"
    )
    return block


def _retag_code() -> str:
    """The retag step with its COMMENTS REMOVED, which is the only text an assertion about
    behaviour may read.

    MEASURED, not anticipated. `"|| rc=$?" in _retag_block()` passed against a step whose guard
    had been deleted — because the comment ABOVE the guard, the one explaining why the guard is
    load-bearing, contains the same characters. The check was satisfied by the prose describing
    the fix while the fix itself was gone: the instrument and its subject shared a surface, and
    the better-scoped block is what pulled the comment into range.

    A string check cannot see a behaviour. Stripping the commentary at least stops it seeing the
    documentation of one.
    """
    return chr(10).join(
        ln for ln in _retag_block().splitlines() if not ln.lstrip().startswith("#")
    )


def test_every_sandbox_enabled_built_image_resolves_to_the_chart_version() -> None:
    """An UNPINNED render must put every image of ours on the chart's own version.

    Asserted on what helm actually produces, not on which convention a component used — the
    chart is allowed to keep both, and neither is the "right" one to imitate.
    """
    want = _chart_version()
    offenders = [
        f"{name} -> {tag!r}" for name, tag in sorted(_rendered_tags().items()) if tag != want
    ]
    assert not offenders, (
        f"sandbox-enabled components resolve to a tag other than the chart version {want!r}:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe chart's floor is `global.defaultImageTag`, which is empty so the chain falls "
        "through to Chart.Version — the tag the release retags every built image to."
    )


def test_a_component_that_declares_NOTHING_still_resolves() -> None:
    """THE ENGINE P CASE, and the reason the floor is structural rather than conventional.

    The two working conventions (`tag: "latest"`, or `tag: ""` plus a sandbox override) were
    both PER-COMPONENT, so a new component using neither fell through to appVersion and could
    not start. The second assertion is on the RENDER rather than on a values literal: the
    property is that declaring nothing is safe, not that a key holds a particular string.
    """
    assert _load("values.yaml")["global"]["defaultImageTag"] == "", (
        "the floor was given a literal again — a literal default is a second place the version "
        "is declared, and it wins over Chart.Version silently when the chart is bumped"
    )
    app_version = str(_load("Chart.yaml").get("appVersion", ""))
    tags = _rendered_tags()
    assert app_version not in set(tags.values()), (
        f"an image resolved to Chart.AppVersion ({app_version!r}), which the registry has never "
        f"had — this is the Engine P break, returned"
    )


def test_THE_FLOOR_IS_A_TAG_THE_RELEASE_ACTUALLY_PUBLISHES() -> None:
    """THE JOIN, and the arm this file spent its whole life without.

    Every other assertion here is about the CHART. Whether the tag the chart names EXISTS was
    taken from a sentence in this file's own docstring. Both ends correct, the relation asserted
    nowhere — so when the publisher changed, nothing here could notice.

    Read from the release workflow: it must invoke the retag with the chart version, and that
    version must be DERIVED from the chart rather than typed into the workflow.
    """
    assert "retag_images_by_digest.py" in _RELEASE_WF.read_text(encoding="utf-8"), (
        "the release no longer retags images, so the chart's floor names a tag nothing "
        "publishes — every unpinned deploy is an ImagePullBackOff waiting for a new component"
    )
    block = _retag_code()
    assert "--chart-version" in block, (
        "the retag is invoked without the tag it is supposed to create"
    )
    assert "helm show chart helm/invincible-agent" in block, (
        "the release does not derive the version from the chart, so the tag it publishes and the "
        "tag the chart resolves to are two independent declarations that agree until they do not"
    )


def test_THE_THREE_STATE_EXIT_CAN_ACTUALLY_FIRE() -> None:
    """REACHABILITY, which no assertion about the branch itself can reach.

    A GitHub `run:` block is `bash -e`. The retag step's `rc=3 -> warning` branch was first
    written under an unguarded invocation, so the step aborted AT the python line and the branch
    could never run — a still-building matrix would have FAILED the release, the opposite of
    what the branch says. The branch was correct and unreachable at the same time.
    """
    assert "|| rc=$?" in _retag_code(), (
        "the retag's exit code is captured on a separate line under `bash -e`, so a non-zero "
        "exit aborts the step and the three-state handling below it cannot fire"
    )


def test_no_literal_tag_shadows_a_fleet_pin() -> None:
    """The other half, and the reason the per-component literals were removed rather than left.

    A component's own `tag` beats `global.imageTag`, so every `tag: "latest"` in a values file
    was a service the commit pin would silently skip — leaving a fleet that reads uniform in the
    census while running two different commits.
    """
    for name in ("values.yaml", "values-sandbox.yaml"):
        raw = (CHART / name).read_text(encoding="utf-8")
        assert 'tag: "latest"' not in raw, (
            f"{name} declares a literal 'latest' tag again — a component tag beats "
            f"global.imageTag, so this is a hole in any fleet-wide commit pin"
        )


def test_the_pin_moves_everything_it_should() -> None:
    """THE CONTROL on the tests above. A uniform render would ALSO be produced by a helper that
    ignored the global knob entirely; this is what distinguishes a floor that works from one
    that is merely always chosen."""
    tags = _rendered_tags("--set", "global.imageTag=deadbeefcafe")
    stuck = sorted(n for n, t in tags.items() if t != "deadbeefcafe")
    assert not stuck, f"image(s) ignored the fleet pin: {stuck}"
