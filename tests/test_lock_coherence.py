"""Every uv.lock agrees with its pyproject — the ARTIFACT boundary, guarded.

WHAT THIS EXISTS TO CATCH, stated as it actually happened rather than in the abstract.

2026-08-08: `iagent-mesh` was declared in TEN engine pyprojects and present in ZERO uv.lock
files. The container build ran `uv sync --frozen`, which installs exactly the lock and SKIPS
the freshness check — so ten images were published without the module, CI passed on every one,
and Engine W CrashLoopBackOff'd with `ModuleNotFoundError: No module named 'iagent_mesh'` the
moment it was rolled. The `provenance-telemetry==0.1.0` repin rode the identical hole: pinned
in pyproject, absent from every lock, so those images would have shipped the old git-URL build.

THREE CLAIMS THAT ARE NOT THE SAME CLAIM. `tests/test_transport_auth_applied_everywhere.py`
asserts fifty properties of the SOURCE TREE and would have passed identically over ten images
that all crash at import, because every one of its assertions reads a `.py` file. The gap:

    SOURCE-COMPLETE          the tree wires it          (that suite)
    ARTIFACT-COMPLETE        the image contains it      (THIS FILE + `uv sync --locked`)
    OPERATIONALLY-OBSERVED   a pod served under it      (the roll litany)

A green in one is routinely read as evidence for the others. It is not, and this module exists
because that conflation cost a fleet-wide roll.

WHY A GUARD AND NOT A HABIT. The build flag is now `--locked`, which fails on divergence — the
structural fix. This test is the fast local echo of it, so the divergence is caught at commit
time rather than at image-build time, and so the OBLIGATION IS VISIBLE IN THE SUITE rather than
buried in a workflow file nobody reads. Both are kept: `--locked` is authoritative, this is the
early warning.

And the sentence that earned this file: the defect was committed by the author of the rule, in
the same change that named it, hours after filing it. NAMING A CLASS PROVIDES ZERO PROTECTION
AGAINST INSTANTIATING IT — ONLY GUARDS DO.
"""
from __future__ import annotations

import re
from datetime import date
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._treewalk import find_files

_ROOT = Path(__file__).resolve().parents[1]


def _locked_projects() -> list[Path]:
    """Every directory holding a uv.lock — derived, never hand-listed."""
    # PRUNING walk, not rglob-then-filter. rglob must TRAVERSE a directory to yield anything
    # from it, so the exclusion ran after the descent it was meant to prevent — and the descent
    # hit `.venv.wsl/lib64`, raising WinError 1920 at IMPORT time and removing this whole file
    # from the run while the suite still printed green. See tests/_treewalk.py.
    found = sorted({p.parent for p in find_files(_ROOT, "uv.lock")})
    assert found, "positive control: no uv.lock found anywhere — the glob is broken"
    return found


@pytest.mark.parametrize("proj", _locked_projects(),
                         ids=lambda p: str(p.relative_to(_ROOT)).replace("\\", "/") or "root")
def test_lock_is_coherent_with_pyproject(proj: Path):
    """`uv lock --check` — the same question the build's `--locked` asks, asked earlier.

    Skips only if uv is genuinely unavailable; a skip here means the guard did not run, which
    is why CI must have uv on PATH.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not on PATH — this guard cannot run (CI must provide it)")
    r = subprocess.run(["uv", "lock", "--check"], cwd=proj, capture_output=True, text=True)
    assert r.returncode == 0, (
        f"{proj.relative_to(_ROOT) or 'root'}: uv.lock is STALE against pyproject.toml. The "
        f"image build runs `uv sync --locked` and will FAIL on this. Run `uv lock` in that "
        f"directory and commit the result.\n"
        f"--- uv said ---\n{(r.stderr or r.stdout).strip()[:600]}"
    )


def test_every_declared_internal_dep_reaches_its_lock():
    """A pyproject naming an internal package whose lock never mentions it is THE defect.

    Deliberately independent of `uv lock --check`: that asks whether uv considers the lock
    fresh, which is a claim about uv's own bookkeeping. This asks the question the crash
    actually answered — is the module NAMED in the artifact's dependency set — so the two
    cannot fail for the same reason, and a future uv whose freshness check changes semantics
    does not silently take this guard with it.
    """
    internal = {"iagent-mesh", "provenance-telemetry"}
    problems = []
    for proj in _locked_projects():
        pp = proj / "pyproject.toml"
        if not pp.exists():
            continue
        declared = {n for n in internal
                    if re.search(rf'"{re.escape(n)}\s*[@=<>~!]', pp.read_text(encoding="utf-8"))}
        if not declared:
            continue
        lock = (proj / "uv.lock").read_text(encoding="utf-8")
        for name in sorted(declared):
            if f'name = "{name}"' not in lock:
                problems.append(f"{proj.relative_to(_ROOT) or 'root'}: declares {name!r} but "
                                f"its uv.lock never names it — the image will NOT contain it")
    assert not problems, (
        "pyproject/lock divergence on an internal dependency — this is exactly the shape that "
        "published ten engine images without `iagent_mesh` and crashed Engine W on roll:\n  "
        + "\n  ".join(problems)
    )


_TAG = re.compile(r"v\d+\.\d+\.\d+")
_SHA = re.compile(r"[0-9a-f]{40}")


class _ShaPin:
    """An engine pinned to an untagged SDK sha while it proves a release (caller-proves-then-tag).

    Every field is checked by the arm below. The sha must still be pinned somewhere, or the entry
    is stale. The backstop must not have passed. It must name the tag it shares transport_auth
    with, because the broker arm compares the chart against the TAG and so cannot see a
    sha-pinned engine.
    """

    def __init__(self, release: str, same_auth_as: str, why: str, ends_with: str, backstop: date):
        self.release, self.same_auth_as, self.why = release, same_auth_as, why
        self.ends_with, self.backstop = ends_with, backstop


# Empty since v0.9.9 was tagged (112a649f) and every pin moved to it. The mechanism stays: a future
# sha pin must add a bounded, reasoned entry here or the arms that read it refuse the pin.
SHA_PINS_PENDING_TAG: dict = {}


def test_every_sha_pin_is_live_bounded_and_shares_the_fleet_auth():
    pinned = set()
    for pp in find_files(_ROOT, "pyproject.toml"):
        pinned.update(re.findall(r'"iagent-mesh @ git\+[^"@]+\.git@([0-9a-f]{40})"',
                                 pp.read_text(encoding="utf-8")))
    stale = sorted(set(SHA_PINS_PENDING_TAG) - pinned)
    assert not stale, f"SHA_PINS_PENDING_TAG names shas nothing pins any more; delete: {stale}"
    values = (_ROOT / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8")
    chart = re.search(r"^\s*meshSdkVersion:\s*[\"']?(v\d+\.\d+\.\d+)", values, re.M).group(1)
    today = date.today()
    for sha, e in SHA_PINS_PENDING_TAG.items():
        assert e.why and e.ends_with, f"{sha[:8]}: an exception with no reason or no end condition"
        assert today <= e.backstop, (
            f"{sha[:8]} ({e.release}) passed its backstop {e.backstop} and is still pinned. "
            f"End condition: {e.ends_with}"
        )
        assert e.same_auth_as == chart, (
            f"{sha[:8]} was measured to share transport_auth with {e.same_auth_as}, but the broker "
            f"now installs {chart}. Re-measure against {chart} and update the entry"
        )


def test_domain_broker_sdk_version_matches_the_fleet_pin():
    """The broker installs the SDK at POD START, so its version lives in values.yaml.

    It runs on stock `python:3.12-slim` — NOT the iagent image, which a comment in
    files/domain-broker.py wrongly claimed. That error would have been an outage: broker.py
    imports `iagent_mesh.transport_auth` HARD, so the module could never have resolved there
    however often the iagent image was rebuilt. The roll litany's pre-roll image-carries check
    caught it before the pod was restarted; this test is what keeps it caught.

    The version is asserted EQUAL to the engines' pyproject pin because the broker takes the
    same inbound dependency as the fleet — a skew means it authenticates by different rules
    than the services around it, which is precisely the divergence the one-implementation
    ruling forbids. Two files, one truth, checked.
    """
    values = (_ROOT / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8")
    m = re.search(r"^\s*meshSdkVersion:\s*[\"']?(?P<v>v\d+\.\d+\.\d+)[\"']?", values, re.M)
    assert m, "domainBroker.meshSdkVersion is missing from values.yaml"
    chart_version = m.group("v")

    pins, sha_pins, unparsed = set(), {}, []
    # The SECOND walk site in this file, and the reason the first fix looked complete when it
    # was not: collection stopped failing, 41 tests started running, and this one still raised
    # from inside a test body. A rglob-then-filter that is correct about its RESULT is still
    # wrong about its TRAVERSAL, everywhere it appears.
    #
    # THE MATCHER READS EVERY REF, NOT ONLY A TAG. Until 2026-10-08 it matched `@vX.Y.Z` alone, so
    # lane/saf's sha pin (586c04c9) was invisible and the fleet split across two SDK builds with
    # this arm green. A pin in any other form is refused rather than skipped.
    for pp in find_files(_ROOT, "pyproject.toml"):
        text = pp.read_text(encoding="utf-8")
        mentions = text.count('"iagent-mesh @')
        found = 0
        for pm in re.finditer(r'"iagent-mesh @ git\+[^"@]+\.git@(?P<ref>[^"]+)"', text):
            found += 1
            ref = pm.group("ref")
            if _TAG.fullmatch(ref):
                pins.add(ref)
            elif _SHA.fullmatch(ref):
                sha_pins.setdefault(ref, []).append(pp.parent.relative_to(_ROOT).as_posix())
            else:
                unparsed.append(f"{pp.relative_to(_ROOT).as_posix()}: @{ref}")
        if found != mentions:
            unparsed.append(f"{pp.relative_to(_ROOT).as_posix()}: {mentions - found} pin(s) "
                            f"in a form this matcher does not read")
    assert not unparsed, f"iagent-mesh pins neither a vX.Y.Z tag nor a full sha: {unparsed}"
    unexcused = {sha: where for sha, where in sha_pins.items() if sha not in SHA_PINS_PENDING_TAG}
    assert not unexcused, (
        f"iagent-mesh pinned by sha with no entry in SHA_PINS_PENDING_TAG: {unexcused}. A sha pin "
        f"is a caller proving an untagged release (caller-proves-then-tag); say which release, "
        f"why, and when the tag replaces it"
    )
    assert pins, "no iagent-mesh pyproject pin found — cannot check the broker against the fleet"
    assert len(pins) == 1, f"the fleet's own SDK pins disagree: {sorted(pins)}"
    fleet_version = pins.pop()
    assert chart_version == fleet_version, (
        f"domain-broker installs iagent-mesh {chart_version} but the fleet pins {fleet_version}. "
        f"The broker would authenticate by a different SDK build than the services it sits "
        f"beside. Update helm/invincible-agent/values.yaml -> domainBroker.meshSdkVersion."
    )


def test_the_container_build_uses_locked_not_frozen():
    """`--frozen` installs the lock and SKIPS the freshness check: a wrong artifact, built green.

    Asserted on the workflow SOURCE because no test of this repo's code can observe the flag a
    remote builder used. It is the one place the artifact-boundary guarantee is written down.
    """
    wf = _ROOT / ".github" / "docker" / "Dockerfile.agent"
    assert wf.exists(), "build-containers.yml missing — cannot verify the build's lock discipline"
    src = wf.read_text(encoding="utf-8")
    syncs = re.findall(r"uv sync[^\n;]*", src)
    assert syncs, "no `uv sync` found in the container build — has the build changed shape?"
    offenders = [s.strip() for s in syncs if "--frozen" in s]
    assert not offenders, (
        "the container build uses `uv sync --frozen`, which SKIPS the pyproject/lock freshness "
        "check and therefore turns a divergence into a silently wrong image (this shipped: ten "
        "engines without iagent_mesh). Use `--locked` so the build FAILS instead:\n  "
        + "\n  ".join(offenders)
    )
    assert any("--locked" in s for s in syncs), (
        "no `uv sync --locked` in the container build — the artifact-boundary guarantee is gone"
    )
