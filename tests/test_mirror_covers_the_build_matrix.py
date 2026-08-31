"""Every image CI builds must be mirrorable to Artifactory. Derived, never remembered.

WHY THIS EXISTS, and it is the third instance of one shape.

`scripts/mirror-to-artifactory.ps1` carries a hand-kept list of images to pull from ghcr and
push to a work-cluster Artifactory. `build-containers.yml` carries the matrix that BUILDS them.
Nothing tied the two together, so a new engine could land in the matrix and never reach the
mirror — and the symptom appears only at work, only on an air-gapped cluster that cannot fall
back to ghcr, as **ImagePullBackOff on a pod unrelated to whatever is being chased**.

MEASURED 2026-08-31: CI built 15 images, the mirror carried 14, and the missing one was
`finance-agent` — the newest engine, exactly the case a hand-kept list forgets.

**AND THE LESSON WAS ALREADY WRITTEN THERE.** The `planning-agent` entry carries a comment
explaining that engine-p was missed for this very reason and that a default-off engine still
needs its image mirrored before anyone turns it on. That comment did not prevent the next
omission, because **a lesson written beside a list does not maintain the list.** Only something
derived does.

THE SAME REMEDY AS `test_service_enumerations_agree`, which exists for the same reason one
layer over: where the thing itself cannot be derived — the mirror has real entries CI never
builds, like doc-tools and third-party images — **derive the POPULATION it must cover** and
make forgetting it FAIL rather than pass quietly.

DIRECTION IS ONE-WAY, deliberately. Every CI-built image must be mirrored; the mirror may
legitimately carry more. Asserting the reverse would force this test to model every
third-party image the work cluster needs, which is not this repo's business.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "build-containers.yml"
_MIRROR = _ROOT / "scripts" / "mirror-to-artifactory.ps1"

#: Images this repo builds but deliberately does NOT mirror. EMPTY, and it stays empty until
#: something earns a place here WITH ITS REASON — an exclusion list is where a gap goes to
#: look intentional.
_NOT_MIRRORED: set[str] = set()


def _built() -> set[str]:
    """The service names build-containers.yml's matrix actually builds."""
    return set(re.findall(r"^\s+- service:\s*(\S+)\s*$",
                          _WORKFLOW.read_text(encoding="utf-8"), re.M))


def _mirrored() -> set[str]:
    """The invincible-agent images the mirror script pulls from ghcr."""
    return set(re.findall(r"src='ghcr\.io/edgy-solutions/invincible-agent/([^:']+):",
                          _MIRROR.read_text(encoding="utf-8")))


def test_the_two_lists_are_both_readable():
    """A regex that silently matches nothing would make every assertion below vacuous.

    The tell this guards against is the one this repo keeps meeting: a uniform extreme result
    — zero built, or zero mirrored — is an instrument failure wearing a finding's clothes.
    """
    built, mirrored = _built(), _mirrored()
    assert len(built) >= 10, f"the build matrix parsed to {len(built)} services; regex is wrong"
    assert len(mirrored) >= 10, f"the mirror parsed to {len(mirrored)} images; regex is wrong"


def test_every_image_ci_builds_can_be_mirrored_to_artifactory():
    """The seal. A new engine that reaches the matrix must reach the mirror in the same change.

    Failing here is cheap. Failing at work is an ImagePullBackOff on an air-gapped cluster,
    found by whoever is mid-diagnosis of something else entirely.
    """
    missing = sorted(_built() - _mirrored() - _NOT_MIRRORED)
    assert not missing, (
        f"{len(missing)} image(s) built by .github/workflows/build-containers.yml are NOT in "
        f"scripts/mirror-to-artifactory.ps1: {missing}. A work cluster cannot fall back to "
        f"ghcr, so an unmirrored image is an ImagePullBackOff the moment its chart flag is "
        f"turned on — DEFAULT-OFF IS NOT PROTECTION, it is a default. Add the entry, or add "
        f"the name to _NOT_MIRRORED with the reason it is deliberate."
    )


def test_the_engine_count_comment_is_not_stale():
    """The comment above the list states a count, and a stated count that drifts is a small
    lie that makes a reader trust a list they should be re-deriving.

    Found stale 2026-08-31: it read `Engine fleet (11)` and had been written before engine-fin
    existed. Asserted here rather than fixed-and-forgotten, because the next engine moves it
    again.
    """
    text = _MIRROR.read_text(encoding="utf-8")
    m = re.search(r"Engine fleet \((\d+)\)", text)
    assert m, "the inventory comment no longer states an engine count — update this test too"
    stated = int(m.group(1))
    # The fleet = every mirrored iagent image minus cortex-bff and the two dagster runtimes,
    # which the comment names separately.
    fleet = _mirrored() - {"cortex-bff", "dagster-server", "dagster-control-plane"}
    assert stated == len(fleet), (
        f"the comment says the engine fleet is {stated}; the list actually carries "
        f"{len(fleet)}: {sorted(fleet)}"
    )
