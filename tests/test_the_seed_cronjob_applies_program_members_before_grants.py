"""The seed CronJob applies program_members.yaml, before the reader-grant sync.

At 0.4.92 the hourly topaz-seed run applied six syncs and never ran program_member_sync, so a
membership change in the policy repo reached Topaz only at the next helm upgrade (through the
taskGrantSync hook). The order is "program_members.yaml before the grant sync": the CronJob runs
program_member_sync, then recipient_reader_sync, after the asset sync and before grant_sync.

The seal reads the RENDERED script in every policy-source mode, and takes the hook's own
invocation as the reference, so the two callers cannot drift apart.
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

_CHART = "helm/invincible-agent"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_MODES = {
    "image": [],
    "git": ["--set", "topazSeed.policySource.type=git",
            "--set", "topazSeed.policySource.git.repoUrl=https://example.invalid/policy.git"],
    "configMap": ["--set", "topazSeed.policySource.type=configMap",
                  "--set", "topazSeed.policySource.configMap.name=policy-overlay"],
}

_ORDER = [
    "topaz_sync", "datahub_topaz_sync", "program_member_sync", "recipient_reader_sync",
    "grant_sync", "ontology_compartment_sync", "task_grant_sync", "capability_grant_sync",
]
_NUMBER_WORDS = {"six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_INVOKE = re.compile(r"^\s*(?:GRANT_SYNC_RC=0\s*)?python policy/sync/(\w+)\.py\b(.*)$", re.M)


def _render(*sets: str) -> str:
    r = subprocess.run(["helm", "template", "t", _CHART, *sets],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"helm template failed: {r.stderr[-2000:]}"
    return r.stdout


def _doc(stdout: str, kind: str, name: str) -> str:
    docs = [d for d in stdout.split("\n---") if re.search(rf"^kind: {kind}$", d, re.M)
            and re.search(rf"^  name: {re.escape(name)}$", d, re.M)]
    assert len(docs) == 1, f"expected one {kind} {name}, got {len(docs)}"
    return docs[0]


def _cronjob(mode: str) -> str:
    return _doc(_render("--set", "topazSeed.enabled=true", *_MODES[mode]), "CronJob", "t-topaz-seed")


def _invocations(doc: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).split("||")[0].strip()) for m in _INVOKE.finditer(doc)
            if m.group(1) != "validate_policy"]


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_the_seed_runs_every_sync_in_the_ruled_order(mode):
    names = [n for n, _ in _invocations(_cronjob(mode))]
    assert names == _ORDER, f"{mode} mode: the seed runs {names}, expected {_ORDER}"


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_program_members_are_applied_before_the_grant_sync(mode):
    names = [n for n, _ in _invocations(_cronjob(mode))]
    assert names.count("program_member_sync") == 1, f"{mode}: program_member_sync runs {names.count('program_member_sync')}x"
    pm, rr, gs = (names.index(n) for n in ("program_member_sync", "recipient_reader_sync", "grant_sync"))
    assert names.index("topaz_sync") < pm < rr < gs, (
        f"{mode} mode: program_member_sync must run after the manifest load (topaz_sync) and "
        f"before grant_sync, with recipient_reader_sync between them; got {names}")


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_the_seed_points_both_legs_at_the_composed_files(mode):
    doc = _cronjob(mode)
    leg = doc.index("python policy/sync/program_member_sync.py")
    for var, f in (("PROGRAM_MEMBERS_FILE", "program_members.yaml"),
                   ("RECIPIENT_READERS_FILE", "recipient_readers.yaml")):
        m = re.search(rf'^\s*export {var}="\$POLICY_DIR/{re.escape(f)}"$', doc, re.M)
        assert m and m.start() < leg, f"{mode} mode: {var} is not exported to $POLICY_DIR/{f} before the leg"
    # The recipient leg is gated on a flag that every mode sets before the leg runs.
    sets = [m.start() for m in re.finditer(r"^\s*RECIPIENT_READERS_PRESENT=[01]$", doc, re.M)]
    assert sets and max(sets) < leg, f"{mode} mode: RECIPIENT_READERS_PRESENT is not set before the leg"
    if mode != "image":
        assert 'cp "$OVERLAY/recipient_readers.yaml" /work/policy/' in doc, (
            f"{mode} mode: the overlay's recipient_readers.yaml is never composed into /work/policy")


def test_the_seed_invokes_program_member_sync_exactly_as_the_hook_does():
    hook = _doc(_render("--set", "taskGrantSync.enabled=true"), "Job", "t-task-grant-sync")
    ref = dict(_invocations(hook))
    # Control: the reference is the hook's real invocation, not an empty parse.
    assert "program_member_sync" in ref and "recipient_reader_sync" in ref, sorted(ref)
    for mode in sorted(_MODES):
        seed = dict(_invocations(_cronjob(mode)))
        for n in ("program_member_sync", "recipient_reader_sync"):
            assert seed.get(n) == ref[n], f"{mode} mode: the seed runs {n} with {seed.get(n)!r}, the hook with {ref[n]!r}"


@pytest.mark.parametrize("mode", sorted(_MODES))
def test_the_banner_counts_the_syncs_it_ran(mode):
    doc = _cronjob(mode)
    m = re.search(r"SEED COMPLETE — (\w+) syncs applied", doc)
    assert m, f"{mode} mode: no completion banner"
    assert _NUMBER_WORDS.get(m.group(1)) == len(_invocations(doc)), (
        f"{mode} mode: the banner says {m.group(1)!r} syncs, the run invokes {len(_invocations(doc))}")
