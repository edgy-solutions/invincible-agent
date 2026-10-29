"""The sandbox names its own grantor in an overlay; the seed stays deployment-neutral.

Architect, 2026-10-27 (ruling 5 on the policy-refusal rule): "the sandbox overlay names the
sandbox's actual approver (alice). The seed stays neutral; overlays are what deployments are
for." The overlay is `policy/overlays/sample/grantors/`, read by cortex-bff through
`GRANTOR_OVERLAY_DIRS` in `helm/invincible-agent/values-sandbox.yaml` only.

Three ways this goes wrong without failing anything else, each an arm below:
  - the env names a directory that is not there: `compose_rows` globs `*.yaml`, so a missing
    directory composes NOTHING and every refusal quietly reads the seed;
  - the chart grows a default: every deployment then names the sandbox's approver;
  - an overlay row drops the seed's `object_scoped`: a refusal then names the asset, and a
    withheld asset stops answering like an absent one (ADR-0047 §5.1).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from src.iagent.authz import refusal as mod

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "invincible-agent"
OVERLAY = ROOT / "policy" / "overlays" / "sample" / "grantors"
ENV = "GRANTOR_OVERLAY_DIRS"
#: The image root: cortex-bff is built from the repo root into /app (build-containers.yml).
IMAGE_ROOT = "/app/"


def _sandbox_dirs() -> list[str]:
    values = yaml.safe_load((CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    raw = ((values.get("cortexBff") or {}).get("env") or {}).get(ENV)
    assert raw, f"values-sandbox.yaml sets no cortexBff.env.{ENV}: the sandbox reads the seed"
    return [p for p in raw.split(":") if p]  # the pod is Linux: pathsep is ':'


def _in_repo(image_path: str) -> Path:
    assert image_path.startswith(IMAGE_ROOT), f"{image_path!r} is not under the image root"
    return ROOT / image_path[len(IMAGE_ROOT):]


def _compose(monkeypatch, dirs: "list[Path] | None") -> dict:
    monkeypatch.setattr(mod, "_GRANTORS_CACHE", None)
    if dirs is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        import os
        monkeypatch.setenv(ENV, os.pathsep.join(str(d) for d in dirs))
    out = mod.grantors()
    monkeypatch.setattr(mod, "_GRANTORS_CACHE", None)
    return out


def test_the_sandbox_points_the_bff_at_a_directory_that_has_rows():
    for d in _sandbox_dirs():
        local = _in_repo(d)
        assert local.is_dir(), f"{d} is not in the image: the overlay composes nothing, silently"
        rows = sorted(local.glob("*.yaml"))
        assert rows, f"{d} has no rows: the overlay composes nothing"
        for r in rows:
            assert "SAMPLE" in r.read_text(encoding="utf-8"), (
                f"{r.name} is not labelled SAMPLE; a reader cannot tell the fixture from the thing")


def test_the_chart_sets_no_default():
    """A default would put the sandbox's approver in front of every deployment's callers."""
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert ENV not in (((values.get("cortexBff") or {}).get("env")) or {})
    for t in (CHART / "templates").glob("*.yaml"):
        assert ENV not in t.read_text(encoding="utf-8"), f"{t.name} sets {ENV}"


def test_the_sandbox_names_alice_for_asset_grants_and_nothing_else_moves(monkeypatch):
    seed = _compose(monkeypatch, None)
    sandbox = _compose(monkeypatch, [_in_repo(d) for d in _sandbox_dirs()])
    assert "alice@example.com" in sandbox["asset_grants"].who
    # CONTROL: the seed does not already say it, so the arm above is the overlay's doing.
    assert "alice@example.com" not in seed["asset_grants"].who
    assert set(sandbox) == set(seed)
    moved = {f for f in seed if sandbox[f] != seed[f]}
    overlaid = {yaml.safe_load(r.read_text(encoding="utf-8"))["family"]
                for r in OVERLAY.glob("*.yaml")}
    assert moved == overlaid == {"asset_grants"}


def test_an_overlay_row_keeps_the_seed_rows_scope_and_rail(monkeypatch):
    """An overlay replaces the row whole, so it restates these; it may not change them."""
    seed = _compose(monkeypatch, None)
    for r in sorted(OVERLAY.glob("*.yaml")):
        row = yaml.safe_load(r.read_text(encoding="utf-8"))
        s = seed[row["family"]]
        assert row.get("object_scoped", False) is s.object_scoped, f"{r.name} changes object_scoped"
        assert row.get("rail_file") == s.rail_file, f"{r.name} changes rail_file"


def test_the_sandbox_refusal_names_the_family_alone(monkeypatch):
    """End to end through the overlay: an asset refusal carries alice and never the asset."""
    import os
    monkeypatch.setenv(ENV, os.pathsep.join(str(_in_repo(d)) for d in _sandbox_dirs()))
    monkeypatch.setattr(mod, "_GRANTORS_CACHE", None)
    r = mod.refusal("asset_grants", "can_read(dataset)")
    assert r["grantable_by"].startswith("alice@example.com")
    with pytest.raises(ValueError):
        mod.refusal("asset_grants:urn:li:dataset:x", "can_read(dataset)")


def test_the_seed_names_no_person():
    for f in sorted((ROOT / "policy" / "grantors").glob("*.yaml")):
        row = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert "@" not in f"{row['who']} {row['how']}", f"seed row {f.name} names a person"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_the_rendered_bff_carries_the_overlay():
    r = subprocess.run(
        ["helm", "template", "t", str(CHART), "-f", str(CHART / "values-sandbox.yaml"),
         "--show-only", "templates/frontend.yaml"],
        capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-2000:]
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    bff = [d for d in docs if d.get("kind") == "Deployment" and "bff" in d["metadata"]["name"]]
    assert len(bff) == 1, [d["metadata"]["name"] for d in docs]
    env = {e["name"]: e.get("value") for c in bff[0]["spec"]["template"]["spec"]["containers"]
           for e in c.get("env") or []}
    assert env.get(ENV) == ":".join(_sandbox_dirs())
