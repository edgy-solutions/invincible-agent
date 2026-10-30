"""Fixtures for engine-r core."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_fleet.repository_agent import repo_core, sshsig
from engine_r_fixtures import build_source, make_policy


@pytest.fixture
def signer():
    return sshsig.Signer.generate()


@pytest.fixture
def world(tmp_path, signer):
    source = build_source(tmp_path / "source.git")
    policy = make_policy(signer)
    repo = repo_core.Repo.init_bare(tmp_path / "engine.git", "invincible-agent", policy)
    imported = repo.import_from(str(tmp_path / "source.git"))
    return SimpleNamespace(
        repo=repo, source=source, imported=imported, policy=policy, signer=signer, tmp=tmp_path
    )
