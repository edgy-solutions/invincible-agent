"""Bob's three sample capability grants exist only through the sandbox sample overlay.

The ruling: `bob@example.com` holds exactly `can_export:part-list`, `can_export:part-list-reviewed`
and `ingest:exportBatch`, as a USER grant, `granted_by: seed`, through
`policy/overlays/sample/capability_grants.yaml`, switched on by the sandbox values key
`CAPABILITY_GRANT_OVERLAY_DIRS`. The shared seed names no sample user. The overlay loader rule is
add, and nothing else; every refusal exits 2 with nothing written to Topaz.

Run:  uv run python -m pytest -c pyproject.toml --rootdir=. tests/security/test_bobs_sample_grants_apply_only_with_the_sample_overlay.py -q
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "policy" / "sync"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import capability_grant_sync as cgs  # noqa: E402
import topaz_sync  # noqa: E402

BOB = "bob@example.com"
THREE = {"can_export:part-list", "can_export:part-list-reviewed", "ingest:exportBatch"}
SEED = ROOT / "policy" / "capability_grants.yaml"
SAMPLE_DIR = ROOT / "policy" / "overlays" / "sample"
SAMPLE = SAMPLE_DIR / "capability_grants.yaml"
CHART = ROOT / "helm" / "invincible-agent"
LINE = 'export CAPABILITY_GRANT_OVERLAY_DIRS="/app/policy/overlays/sample"'


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _seed():
    caps, errs = cgs.load_capabilities(_yaml(SEED))
    assert not errs, errs
    return caps


def _holders(caps) -> set[str]:
    return {c.key for c in caps if BOB in c.grant_to}


def _bob_relations(caps) -> set[str]:
    return {r.object_id for r in cgs.derive_desired(caps).relations
            if r.subject_type == "user" and r.subject_id == BOB}


def _row(**over):
    row = {"granted_by": "seed", "reason": "test", "grant_to": [BOB]}
    row.update(over)
    return row


def _apply(rows: dict):
    return cgs.apply_capability_overlays(_seed(), [("test", {"capabilities": rows})])


# ── the grants ──────────────────────────────────────────────────────────────────────────────

def test_with_the_sample_overlay_bob_gains_exactly_the_three():
    """The seed already grants bob two `mesh:` verbs for bob's persona's cell (bob's own rows, not
    this overlay's). The overlay adds exactly THREE on top and no other capability."""
    seed_held = _holders(_seed())
    assert not (seed_held & THREE)
    merged, errs = cgs.apply_capability_overlays(_seed(), [(str(SAMPLE), _yaml(SAMPLE))])
    assert not errs, errs
    assert _holders(merged) == seed_held | THREE
    assert _bob_relations(merged) == seed_held | THREE
    assert _holders(merged) - seed_held == THREE


def test_the_overlay_rows_are_user_grants_by_seed_and_nothing_more():
    rows = _yaml(SAMPLE)["capabilities"]
    assert set(rows) == THREE
    for key, row in rows.items():
        assert set(row) == {"granted_by", "reason", "grant_to"}, key
        assert row["granted_by"] == "seed" and row["grant_to"] == [BOB], key


def test_control_without_the_overlay_bob_holds_none_of_the_three():
    seed = _seed()
    assert _holders(seed) & THREE == set()
    assert _bob_relations(seed) & THREE == set()


def test_the_shared_seed_names_bob_on_none_of_the_three():
    """Raw text of the three seed blocks: bob's grants on them exist only via the overlay."""
    rows = _yaml(SEED)["capabilities"]
    for key in THREE:
        assert key in rows, key
        assert BOB not in yaml.safe_dump(rows[key]), key


def test_the_merge_only_adds():
    seed = _seed()
    merged, errs = cgs.apply_capability_overlays(seed, [(str(SAMPLE), _yaml(SAMPLE))])
    assert not errs
    assert [c.key for c in merged] == [c.key for c in seed]
    for before, after in zip(seed, merged):
        assert set(before.grant_to) <= set(after.grant_to)
        assert after.grant_to_groups == before.grant_to_groups
        assert (after.granted_by, after.reason) == (before.granted_by, before.reason)
        if before.key in THREE:
            assert after.grant_to == before.grant_to + (BOB,)
        else:
            assert after == before
    for key in THREE:  # the seed's own grantees (alert-processors) are still there
        assert next(c for c in merged if c.key == key).grant_to_groups


def test_a_repeated_grantee_is_not_duplicated():
    once, _ = cgs.apply_capability_overlays(_seed(), [(str(SAMPLE), _yaml(SAMPLE))])
    twice, errs = cgs.apply_capability_overlays(once, [(str(SAMPLE), _yaml(SAMPLE))])
    assert not errs and twice == once


# ── the refusals ────────────────────────────────────────────────────────────────────────────

def test_a_row_for_a_capability_the_seed_lacks_is_refused():
    _merged, errs = _apply({"can_export:not-in-the-seed": _row()})
    assert any("cannot create a capability" in e for e in errs), errs


@pytest.mark.parametrize("field", ["grant_to_groups_replace", "revoke"])
def test_a_row_with_a_field_beyond_the_four_is_refused(field):
    _merged, errs = _apply({"can_export:part-list": _row(**{field: ["x"]})})
    assert any(field in e for e in errs), errs


def test_a_row_with_no_reason_is_refused():
    row = _row()
    del row["reason"]
    _merged, errs = _apply({"can_export:part-list": row})
    assert any("reason" in e for e in errs), errs


def test_a_refused_overlay_is_not_partly_applied_by_main(tmp_path, monkeypatch):
    """main() returns 2 and never builds a Topaz client: a listed dir lacking the file."""
    def _boom(*a, **k):
        raise AssertionError("TopazClient constructed on a refused overlay")
    monkeypatch.setattr(topaz_sync, "TopazClient", _boom)
    monkeypatch.setenv("CAPABILITY_GRANTS_FILE", str(SEED))
    for listed in (tmp_path, tmp_path / "no-such-dir"):
        monkeypatch.setenv(cgs.OVERLAY_ENV, str(listed))
        assert cgs.main() == 2


def test_main_returns_2_on_a_refused_row_without_touching_topaz(tmp_path, monkeypatch):
    (tmp_path / cgs.OVERLAY_FILE).write_text(yaml.safe_dump(
        {"capabilities": {"can_export:part-list": _row(revoke=["x"])}}), encoding="utf-8")

    def _boom(*a, **k):
        raise AssertionError("TopazClient constructed on a refused overlay")
    monkeypatch.setattr(topaz_sync, "TopazClient", _boom)
    monkeypatch.setenv("CAPABILITY_GRANTS_FILE", str(SEED))
    monkeypatch.setenv(cgs.OVERLAY_ENV, str(tmp_path))
    assert cgs.main() == 2


@pytest.mark.parametrize("value", [None, "", "  "])
def test_env_unset_or_empty_names_no_overlay(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(cgs.OVERLAY_ENV, raising=False)
    else:
        monkeypatch.setenv(cgs.OVERLAY_ENV, value)
    assert cgs.overlay_dirs() == []
    seed = _seed()
    merged, errs = cgs.apply_capability_overlays(seed, [])
    assert merged == seed and not errs


# ── the chart ───────────────────────────────────────────────────────────────────────────────

needs_helm = pytest.mark.skipif(shutil.which("helm") is None,
                                reason="helm not installed (CI's pytest jobs have none)")


def _task_grant_sync_script(*values: str) -> str:
    cmd = ["helm", "template", "t", str(CHART), "--set", "taskGrantSync.enabled=true"]
    for v in values:
        cmd += ["-f", v]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    jobs = [d for d in yaml.safe_load_all(r.stdout)
            if d and d.get("kind") == "Job" and d["metadata"]["name"].endswith("-task-grant-sync")]
    assert len(jobs) == 1, "expected exactly one task-grant-sync Job"
    spec = jobs[0]["spec"]["template"]["spec"]
    # every container's command/args, as plain strings (no YAML line folding)
    return "\n".join(str(x) for c in spec["containers"] for x in [*(c.get("command") or []), *(c.get("args") or [])])


@needs_helm
def test_the_sandbox_values_switch_the_overlay_on_for_the_sync_job():
    text = _task_grant_sync_script(str(CHART / "values-sandbox.yaml"))
    assert LINE in text


@needs_helm
def test_the_default_values_leave_it_off():
    assert "CAPABILITY_GRANT_OVERLAY_DIRS" not in _task_grant_sync_script()
