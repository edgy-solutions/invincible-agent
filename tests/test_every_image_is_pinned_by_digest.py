"""EVERY IMAGE THE CHART RUNS IS PINNED BY DIGEST (ruled 2026-11-04, 0.4.79).

The rule: no container or initContainer of a rendered workload names an image by tag alone.
Ours are pinned by the digests `scripts/retag_images_by_digest.py` records; third party by the
digests `values.yaml` `global.imageDigests` holds; the release workflow joins them into
`values-release-<version>.yaml` (`scripts/write_release_values.py`) and seals the render
(`scripts/seal_image_digests.py`). `scripts/upgrade-sandbox.sh` rolls with that file and resolves
nothing.

The tests render with `helm template` and assert on the parsed output. Arms:

  1. base + fixture: every image `@sha256:`.
  2. base + values-sandbox.yaml + fixture: the same.
  3. base + values-sandbox.yaml + fixture + every optional workload on: the same. A census proves
     the flag file is complete: every `enabled: false` flag in values.yaml that adds an image
     when switched on is in `scripts/values-every-workload.yaml`.
  4. CONTROL: base WITHOUT the fixture fails the seal, and every failing image is ours. This
     proves the seal can fire AND that the third-party pins are complete.
  5. The seal on hand-made streams.
  6. The generator, offline through an injected HTTP layer.
  7. `scripts/upgrade-sandbox.sh`, statically (the behavioural arm is in
     tests/test_an_upgrade_runs_from_the_release_tag.py, whose harness stubs helm and gh).

The fixture's digests are FAKE (sha256 of the service name). They pin nothing real.

Run: uv run pytest tests/test_every_image_is_pinned_by_digest.py -v
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
import retag_images_by_digest as retag  # noqa: E402
import seal_image_digests as seal  # noqa: E402
import write_release_values as gen  # noqa: E402

_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"
_FIXTURE = _REPO / "tests" / "fixtures" / "values-release-fixture.yaml"
_EVERY = _REPO / "scripts" / "values-every-workload.yaml"
_HELPERS = _CHART / "templates" / "_helpers.tpl"
_VALUES = _CHART / "values.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")

_SHA = re.compile(r"@sha256:[0-9a-f]{64}$")


def _render(*files: Path) -> str:
    cmd = ["helm", "template", "invincible-agent", str(_CHART)]
    for f in files:
        cmd += ["-f", str(f)]
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr.strip().splitlines()[-1:]
    assert "kind: Deployment" in done.stdout, "an empty render proves nothing"
    return done.stdout


def _prefix() -> str:
    g = yaml.safe_load(_VALUES.read_text(encoding="utf-8"))["global"]
    return f"{g['imageRegistry']}/{g['imagePrefix']}/"


def _assert_sealed(text: str, population_floor: int) -> list[str]:
    images = seal.rendered_images(text)
    assert len(images) >= population_floor, f"only {len(images)} images rendered; the render is not the chart"
    assert seal.unpinned(text) == []
    for image in images:
        assert _SHA.search(image), image
    return images


# --------------------------------------------------------------------------------------------
# The fixture is derived from the matrix, so a new service cannot be forgotten by it.
# --------------------------------------------------------------------------------------------

def test_the_fixture_has_one_row_per_service_in_the_build_matrix():
    rows = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))["global"]["imageDigests"]
    services = retag.services_from_matrix()
    assert len(services) >= 15
    want = {f"{retag.REGISTRY}/{retag.PREFIX}/{s}": f"sha256:{hashlib.sha256(s.encode()).hexdigest()}"
            for s in services}
    assert rows == want


# ---- arms 1-3 ------------------------------------------------------------------------------

def test_arm1_base_with_the_release_values_is_all_digest():
    images = _assert_sealed(_render(_FIXTURE), 30)
    assert any(i.startswith(_prefix()) for i in images), "none of ours rendered: the control below would be vacuous"


def test_arm2_sandbox_with_the_release_values_is_all_digest():
    _assert_sealed(_render(_SANDBOX, _FIXTURE), 30)


def test_arm3_every_optional_workload_on_is_all_digest():
    base = seal.rendered_images(_render(_SANDBOX, _FIXTURE))
    every = _assert_sealed(_render(_SANDBOX, _EVERY, _FIXTURE), 40)
    assert len(every) > len(base), "switching every workload on added no pod: the flag file is inert"


def _enabled_flags(values: dict) -> list[tuple[str, ...]]:
    """Paths (depth 1 and 2) of every dict whose `enabled` is False, derived from values.yaml."""
    out = []
    for k, v in values.items():
        if not isinstance(v, dict) or k == "global":
            continue
        if v.get("enabled") is False:
            out.append((k,))
        for k2, v2 in v.items():
            if isinstance(v2, dict) and v2.get("enabled") is False:
                out.append((k, k2))
    return out


def test_arm3_census_every_flag_that_adds_an_image_is_in_the_workload_file(tmp_path: Path):
    values = yaml.safe_load(_VALUES.read_text(encoding="utf-8"))
    every = yaml.safe_load(_EVERY.read_text(encoding="utf-8"))
    baseline = len(seal.rendered_images(_render(_SANDBOX, _EVERY, _FIXTURE)))
    # Switch each flag OFF on top of the every-workload render: a flag whose image count drops is
    # one the file needs; it must be on in the file (or this render could not have contained it).
    missing = []
    for path in _enabled_flags(values):
        node = every
        for p in path:
            node = node.get(p, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and node.get("enabled") is True:
            continue
        # not on in the file: switching it ON must add no image (or fail for a missing input,
        # which is reported rather than assumed harmless)
        probe = copy.deepcopy(every)
        cur = probe
        for p in path[:-1]:
            cur = cur.setdefault(p, {})
        cur.setdefault(path[-1], {})["enabled"] = True
        f = tmp_path / ("-".join(path) + ".yaml")
        f.write_text(yaml.safe_dump(probe), encoding="utf-8")
        done = subprocess.run(["helm", "template", "x", str(_CHART), "-f", str(_SANDBOX), "-f", str(f),
                               "-f", str(_FIXTURE)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            missing.append(f"{'.'.join(path)}: does not render alone ({done.stderr.strip().splitlines()[-1:]})")
        elif len(seal.rendered_images(done.stdout)) > baseline:
            missing.append(f"{'.'.join(path)}: adds an image and is not on in scripts/values-every-workload.yaml")
    assert missing == []


# ---- arm 4: the control ---------------------------------------------------------------------

def test_arm4_control_base_without_the_release_values_fails_and_only_ours_fail():
    text = _render()
    bad = seal.unpinned(text)
    assert bad, "the seal did not fire on a render with no release values"
    ours = _prefix()
    not_ours = [i for i in bad if not i.startswith(ours)]
    assert not_ours == [], f"third-party images with no digest in values.yaml: {not_ours}"
    # and ours are exactly the tag-only ones: every one of them is named by the fixture
    rows = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))["global"]["imageDigests"]
    for image in bad:
        repo = image.rsplit(":", 1)[0]
        assert repo in rows, f"{image} is ours and the matrix has no such service"


# ---- arm 5: the seal ------------------------------------------------------------------------

def _stream(*images: str, kind: str = "Deployment") -> str:
    pod = {"containers": [{"name": f"c{n}", "image": i} for n, i in enumerate(images)]}
    return yaml.safe_dump({"kind": kind, "spec": {"template": {"spec": pod}}})


def test_arm5_a_tag_only_image_fails_the_seal():
    assert seal.unpinned(_stream("example.invalid/x:1.0")) == ["example.invalid/x:1.0"]


def test_arm5_a_digest_of_63_hex_fails_and_64_passes():
    assert seal.unpinned(_stream("example.invalid/x@sha256:" + "a" * 63)) != []
    assert seal.unpinned(_stream("example.invalid/x@sha256:" + "a" * 64)) == []


def test_arm5_init_containers_are_sealed_too():
    doc = {"kind": "Deployment", "spec": {"template": {"spec": {
        "containers": [{"name": "a", "image": "e.invalid/x@sha256:" + "a" * 64}],
        "initContainers": [{"name": "b", "image": "e.invalid/y:1"}]}}}}
    assert seal.unpinned(yaml.safe_dump(doc)) == ["e.invalid/y:1"]


def test_arm5_a_secret_is_skipped_without_being_read():
    secret = yaml.safe_dump({"kind": "Sec" + "ret", "data": {"image": "ZXZpbDox"},
                             "spec": {"template": {"spec": {"containers": [{"image": "e.invalid/leak:1"}]}}}})
    assert seal.rendered_images(secret) == []
    assert seal.unpinned(secret + "---\n" + _stream("e.invalid/x@sha256:" + "a" * 64)) == []


def test_arm5_an_empty_stream_is_not_sealed(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(""))
    assert seal.main() == 1


# ---- arm 6: the generator, offline ----------------------------------------------------------

def _manifest(tmp_path: Path, services: list[str], **over) -> Path:
    m = {"registry": f"{retag.REGISTRY}/{retag.PREFIX}", "chart_version": "9.9.9", "commit": "c" * 40,
         "images": {s: f"sha256:{hashlib.sha256(s.encode()).hexdigest()}" for s in services},
         "missing": [], "failed": []}
    m.update(over)
    p = tmp_path / "image-digests.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def _head_confirming(registry, repo, digest):
    return 200, digest


def test_arm6_the_generator_writes_every_matrix_service_and_every_third_party_row(tmp_path: Path):
    services = retag.services_from_matrix()
    out = tmp_path / "values-release-9.9.9.yaml"
    rc = gen.main(["--manifest", str(_manifest(tmp_path, services)), "--chart-version", "9.9.9",
                   "--out", str(out)], head=_head_confirming)
    assert rc == 0
    rows = yaml.safe_load(out.read_text(encoding="utf-8"))["global"]["imageDigests"]
    for s in services:
        assert rows[f"{retag.REGISTRY}/{retag.PREFIX}/{s}"].startswith("sha256:")
    third = {k for k in rows if not k.startswith(f"{retag.REGISTRY}/{retag.PREFIX}/")}
    assert len(third) >= 15
    # the file the generator wrote seals the chart it was generated for
    _assert_sealed(_render(out, _EVERY), 40)


def test_arm6_a_short_manifest_is_refused_with_3(tmp_path: Path):
    services = retag.services_from_matrix()
    rc = gen.main(["--manifest", str(_manifest(tmp_path, services[:-1])), "--chart-version", "9.9.9",
                   "--out", str(tmp_path / "o.yaml")], head=_head_confirming)
    assert rc == 3 and not (tmp_path / "o.yaml").exists()


def test_arm6_a_manifest_carrying_failed_is_refused_with_3(tmp_path: Path):
    services = retag.services_from_matrix()
    rc = gen.main(["--manifest", str(_manifest(tmp_path, services, failed=[services[0]])),
                   "--chart-version", "9.9.9", "--out", str(tmp_path / "o.yaml")], head=_head_confirming)
    assert rc == 3


def test_arm6_a_third_party_image_rendered_without_a_digest_is_refused_with_4(tmp_path: Path):
    services = retag.services_from_matrix()
    render = lambda chart, values: _stream("e.invalid/third:1.0")  # noqa: E731
    with pytest.raises(gen.Refused) as r:
        gen.generate(_manifest(tmp_path, services), str(_CHART), "9.9.9", tmp_path / "o.yaml", None,
                     head=_head_confirming, render=render, services=services)
    assert r.value.code == 4 and "e.invalid/third:1.0" in str(r.value)


def test_arm6_a_digest_the_registry_answers_404_for_is_refused_with_5(tmp_path: Path):
    services = retag.services_from_matrix()
    with pytest.raises(gen.Refused) as r:
        gen.generate(_manifest(tmp_path, services), str(_CHART), "9.9.9", tmp_path / "o.yaml",
                     str(_EVERY), head=lambda reg, repo, d: (404, None), services=services)
    assert r.value.code == 5


def test_arm6_a_digest_the_registry_holds_as_another_is_refused_with_5(tmp_path: Path):
    services = retag.services_from_matrix()
    with pytest.raises(gen.Refused) as r:
        gen.generate(_manifest(tmp_path, services), str(_CHART), "9.9.9", tmp_path / "o.yaml",
                     str(_EVERY), head=lambda reg, repo, d: (200, "sha256:" + "0" * 64), services=services)
    assert r.value.code == 5


def test_arm6_a_manifest_for_another_chart_version_is_refused(tmp_path: Path):
    services = retag.services_from_matrix()
    rc = gen.main(["--manifest", str(_manifest(tmp_path, services)), "--chart-version", "1.0.0",
                   "--out", str(tmp_path / "o.yaml")], head=_head_confirming)
    assert rc == 3


# ---- the helper -----------------------------------------------------------------------------

def test_the_helper_looks_up_the_map_and_has_no_prefix_test():
    text = _HELPERS.read_text(encoding="utf-8")
    body = text[text.index('define "invincible-agent.image"'):]
    body = body[:body.index("{{- end }}\n", body.index("{{- end -}}\n{{- end"))]
    assert "imageDigests" in body
    assert "hasPrefix" not in body and "global.imagePrefix" not in body.split("$digest :=")[1]


# ---- arm 7: upgrade-sandbox.sh, statically --------------------------------------------------

def test_arm7_the_roll_script_downloads_the_release_artifact_and_seals_before_helm_upgrade():
    sh = (_REPO / "scripts" / "upgrade-sandbox.sh").read_text(encoding="utf-8")
    assert "gh release download" in sh and "values-release-" in sh
    assert "seal_image_digests.py" in sh
    assert sh.index("seal_image_digests.py") < sh.index("exec helm upgrade")
    assert sh.index("gh release download") < sh.index("seal_image_digests.py")
    assert "global.imageTag" in sh and "REFUSING" in sh
    # the release file is the LAST values file
    last = [m for m in re.finditer(r'"\$\{_release_values\}"', sh)]
    assert last, "the release values file is not appended"
    assert "ALLOW_UNRESOLVABLE_IMAGE_TAG" not in sh
    for registry_read in ("regdigest", "imagetools", "docker manifest", "skopeo"):
        assert registry_read not in sh, f"the roll reads a registry ({registry_read})"


def test_arm7_the_release_workflow_generates_seals_and_attaches_before_publish():
    wf = (_REPO / ".github" / "workflows" / "release-helm-charts.yml").read_text(encoding="utf-8")
    gen_at = wf.index("write_release_values.py")
    seal_at = wf.index("seal_image_digests.py")
    assert wf.index("Verify the release tags resolve") < gen_at < seal_at < wf.index("Run chart-releaser")
    assert "scripts/values-every-workload.yaml" in wf
    attach = wf[wf.index("Attach the digest manifest"):]
    assert "values-release-" in attach and "--clobber" in attach
