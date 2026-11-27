"""The seed CronJob applies program_members.yaml, before the reader-grant sync.

At 0.4.92 the hourly topaz-seed run applied six syncs and never ran program_member_sync, so a
membership change in the policy repo reached Topaz only at the next helm upgrade (through the
taskGrantSync hook). The order is "program_members.yaml before the grant sync": the CronJob runs
program_member_sync, then recipient_reader_sync, after the asset sync and before grant_sync.

The seal reads the RENDERED script in every policy-source mode, and takes the hook's own
invocation as the reference, so the two callers cannot drift apart.
"""
from __future__ import annotations

import os
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


# ── ADDED 2026-11-26: THE RENDERED SCRIPT, RUN (gov, #579: T4, T5 and T6 survived the text seals) ──
# The text seals above read which syncs the script NAMES. They do not read which ones it RUNS:
# the recipient-readers gate is three shell lines (the overlay's `[ -f ]`, the flag each branch
# sets, and the leg's `= "1"`), and a mutant of any one of them left every test green. So the
# seed container's rendered script runs here under `sh`, with its absolute paths moved into a
# temporary root and a stub `python` first on PATH that records its argv. Nothing applies;
# the shell's own branches are what is measured.
_ROOTS = re.compile(r"(?<![\w$./-])/(app|work|overlay-src|overlay|topaz-config)(?=[/\s\"']|$)", re.M)
_DATA = re.compile(r"^\s*for f in ([\w. ]+); do$", re.M)
_STUB = "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$STUB_LOG\"\n"


def _seed_script(mode: str) -> str:
    import yaml
    spec = yaml.safe_load(_cronjob(mode))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    scripts = [c["args"][0] for c in spec["containers"]
               if c.get("args") and "RECIPIENT READER SYNC" in c["args"][0]]
    assert len(scripts) == 1, f"{mode} mode: expected one seed container, found {len(scripts)}"
    return scripts[0]


def _run_seed(mode: str, tmp_path, *, recipient_readers: bool) -> tuple[int, list[str], str]:
    root = tmp_path.as_posix()
    script = _seed_script(mode)
    (tmp_path / "app" / "policy").mkdir(parents=True)
    for enum in ("personas.yaml", "domains.yaml"):
        (tmp_path / "app" / "policy" / enum).write_text("{}\n", encoding="utf-8")
    if mode != "image":
        overlay = tmp_path / ("overlay-src/repo/policy" if mode == "git" else "overlay")
        overlay.mkdir(parents=True)
        m = _DATA.search(script)
        assert m, f"{mode} mode: the script has no data-file loop"
        for f in m.group(1).split():
            (overlay / f).write_text("{}\n", encoding="utf-8")
        if recipient_readers:
            (overlay / "recipient_readers.yaml").write_text("{}\n", encoding="utf-8")
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    (stub_dir / "python").write_text(_STUB, encoding="utf-8", newline="\n")
    (stub_dir / "python").chmod(0o755)
    log = tmp_path / "argv.log"
    env = {**os.environ, "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
           "STUB_LOG": log.as_posix()}
    r = subprocess.run(["sh", "-c", _ROOTS.sub(lambda m: f"{root}/{m.group(1)}", script)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    ran = [ln.split()[0].rsplit("/", 1)[-1].removesuffix(".py")
           for ln in (log.read_text(encoding="utf-8").splitlines() if log.exists() else []) if ln.strip()]
    return r.returncode, ran, r.stderr


_RUN_CASES = [("image", True), ("configMap", True), ("configMap", False), ("git", True), ("git", False)]


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh not installed")
@pytest.mark.parametrize("mode,present", _RUN_CASES, ids=[f"{m}-{'present' if p else 'absent'}" for m, p in _RUN_CASES])
def test_recipient_reader_sync_runs_exactly_when_the_overlay_has_the_file(tmp_path, mode, present):
    rc, ran, stderr = _run_seed(mode, tmp_path, recipient_readers=present)
    assert rc == 0, f"{mode} mode: the script exited {rc}: {stderr[-1500:]}"
    # Control: the stub really stood in for python, and the run reached the last leg.
    assert ran[:1] == ["validate_policy"] and ran[-1:] == ["capability_grant_sync"], ran
    assert ("recipient_reader_sync" in ran) is present, (
        f"{mode} mode, recipient_readers.yaml {'present' if present else 'absent'}: ran {ran}")
    skipped = "recipient_reader_sync skipped" in stderr
    assert skipped is (not present), f"{mode} mode: the skip warning is {'missing' if not present else 'spurious'}"
    if mode != "image":
        copied = (tmp_path / "work" / "policy" / "recipient_readers.yaml").exists()
        assert copied is present, f"{mode} mode: the composed policy dir {'lacks' if present else 'has'} the file"
