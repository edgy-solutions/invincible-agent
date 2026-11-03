"""git's ssh-signature format: round trip, tamper, namespace, and an independent verifier."""
from __future__ import annotations

import shutil
import subprocess  # TEST ONLY: the package under test must not, and a test arm reads its source to prove it

import pygit2
import pytest

from agent_fleet.repository_agent import sshsig
from engine_r_fixtures import COMPLETER, PROPOSER, approval


def test_a_signature_round_trips(signer):
    data = b"tree 0000\nauthor x\n\nmessage\n"
    armored = signer.sign(data)
    assert armored.startswith("-----BEGIN SSH SIGNATURE-----\n") and armored.endswith("-----END SSH SIGNATURE-----\n")
    assert all(len(ln) <= 76 for ln in armored.splitlines()[1:-1])
    assert sshsig.verify(data, armored, signer.public_openssh())


def test_one_changed_byte_fails(signer):
    data = b"payload"
    armored = signer.sign(data)
    assert not sshsig.verify(b"payloae", armored, signer.public_openssh())


def test_the_wrong_namespace_fails(signer):
    armored = signer.sign(b"payload", namespace="git")
    assert not sshsig.verify(b"payload", armored, signer.public_openssh(), namespace="file")
    assert sshsig.verify(b"payload", signer.sign(b"payload", namespace="file"), signer.public_openssh(), namespace="file")


def test_another_key_fails(signer):
    other = sshsig.Signer.generate()
    assert not sshsig.verify(b"payload", signer.sign(b"payload"), other.public_openssh())


def test_a_private_key_round_trips_through_openssh_format(signer):
    again = sshsig.Signer.from_openssh_private(signer.private_openssh())
    assert again.public_openssh() == signer.public_openssh()


def test_garbage_is_false_not_an_exception(signer):
    for junk in ("", "nope", "-----BEGIN SSH SIGNATURE-----\n!!!\n-----END SSH SIGNATURE-----\n"):
        assert sshsig.verify(b"x", junk, signer.public_openssh()) is False


_HAVE = shutil.which("git") and shutil.which("ssh-keygen")


@pytest.mark.skipif(not _HAVE, reason="independent verifier needs both git and ssh-keygen on PATH")
def test_git_verifies_what_propose_signed(world, tmp_path):
    meta = world.repo.propose(
        caller=PROPOSER, target_ref="refs/heads/master", changes={"policy/x.yaml": b"a: 2\n"}, intent="i", message="m"
    )
    merged = world.repo.merge(
        proposal_id=meta["id"], reviewed_sha=meta["head_sha"], approvals=[approval(meta["head_sha"])], completes=COMPLETER
    )
    tag = world.repo.tag(
        name="v1", sha=merged["merge_sha"], caller=COMPLETER, approvals=[approval(merged["merge_sha"])], release=False
    )
    allowed = tmp_path / "allowed_signers"
    allowed.write_text(f"* {world.signer.public_openssh()}\n", encoding="utf-8")
    gitdir = str(tmp_path / "engine.git")

    def git(*args):
        return subprocess.run(
            ["git", "-C", gitdir, "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={allowed}", *args],
            capture_output=True, text=True,
        )

    for sha in (meta["head_sha"], merged["merge_sha"]):
        r = git("verify-commit", sha)
        assert r.returncode == 0, r.stderr
    r = git("verify-tag", tag["tag_object"])
    assert r.returncode == 0, r.stderr

    # control: the verifier is not vacuous -- a different key is refused
    allowed.write_text(f"* {sshsig.Signer.generate().public_openssh()}\n", encoding="utf-8")
    assert git("verify-commit", meta["head_sha"]).returncode != 0
