"""The release reads its tags back from the registry, and every build carries its OCI labels.

`retag_images_by_digest.py --verify` is the release job's evidence that `:<chart version>` names
the bytes the manifest records. These arms drive it with a resolver double, so the comparison and
its controls are measured here without a registry. Each arm that expects a refusal has a twin that
expects acceptance, which differs only in the one thing the guard decides on.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "retag_images_by_digest.py"
_RELEASE_WF = _REPO / ".github" / "workflows" / "release-helm-charts.yml"
_BUILD_WF = _REPO / ".github" / "workflows" / "build-containers.yml"

_spec = importlib.util.spec_from_file_location("retag_images_by_digest", _SCRIPT)
retag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(retag)

_REG = "ghcr.io/edgy-solutions/invincible-agent"
_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_COMMIT = "360fbeb6fbecae36076632b503dc5f691a58f1e3"


def _manifest(tmp_path: pathlib.Path, version: str = "0.4.65", images=None, missing=()) -> str:
    p = tmp_path / "image-digests.json"
    p.write_text(json.dumps({
        "chart_version": version, "commit": _COMMIT, "registry": _REG,
        "images": {"cortex-bff": _A, "graph-host": _B} if images is None else images,
        "missing": list(missing), "failed": [], "expected": 2,
    }), encoding="utf-8")
    return str(p)


def _registry(tags: dict):
    """A resolver that knows exactly `tags` and refuses everything else, as a registry does."""
    return lambda ref: tags.get(ref)


_GOOD = {f"{_REG}/cortex-bff:0.4.65": _A, f"{_REG}/graph-host:0.4.65": _B}


def test_tags_that_name_the_manifest_digests_verify(tmp_path) -> None:
    assert retag.verify(_manifest(tmp_path), "0.4.65", _registry(_GOOD)) == 0


def test_a_tag_at_another_digest_fails(tmp_path) -> None:
    moved = dict(_GOOD, **{f"{_REG}/graph-host:0.4.65": _A})
    assert retag.verify(_manifest(tmp_path), "0.4.65", _registry(moved)) == 1


def test_a_tag_that_does_not_resolve_fails(tmp_path) -> None:
    absent = {k: v for k, v in _GOOD.items() if "graph-host" not in k}
    assert retag.verify(_manifest(tmp_path), "0.4.65", _registry(absent)) == 1


def test_a_resolver_that_cannot_say_no_is_caught_by_the_controls(tmp_path) -> None:
    """Every real tag matches here; only the controls can tell this resolver is broken."""
    yes = lambda ref: _A if "cortex-bff" in ref else _B  # noqa: E731
    assert retag.verify(_manifest(tmp_path), "0.4.65", yes) == 1


def test_each_control_alone_is_enough_to_fail(tmp_path) -> None:
    repo = f"{_REG}/cortex-bff"
    for ref in (f"{repo}@{retag.FAKE_DIGEST}", f"{repo}:{_COMMIT[:8]}",
                f"{repo}:0.4.65-control-never-pushed"):
        leaky = dict(_GOOD, **{ref: _A})
        assert retag.verify(_manifest(tmp_path), "0.4.65", _registry(leaky)) == 1, ref


def test_a_manifest_for_another_version_is_refused(tmp_path) -> None:
    assert retag.verify(_manifest(tmp_path, "0.4.64"), "0.4.65", _registry(_GOOD)) == 2


def test_a_manifest_naming_nothing_at_all_is_refused(tmp_path) -> None:
    assert retag.verify(_manifest(tmp_path, images={}), "0.4.65", _registry(_GOOD)) == 2


def test_a_still_building_matrix_is_a_warning_not_a_failure(tmp_path) -> None:
    """The push-triggered release runs alongside the build: every image can be missing (exit 3)."""
    m = _manifest(tmp_path, images={}, missing=["cortex-bff", "graph-host"])
    assert retag.verify(m, "0.4.65", _registry(_GOOD)) == 3


def test_a_partial_manifest_still_checks_what_was_tagged(tmp_path) -> None:
    m = _manifest(tmp_path, images={"cortex-bff": _A}, missing=["graph-host"])
    assert retag.verify(m, "0.4.65", _registry(_GOOD)) == 3
    moved = dict(_GOOD, **{f"{_REG}/cortex-bff:0.4.65": _B})
    assert retag.verify(m, "0.4.65", _registry(moved)) == 1


def _step(wf: str, header: str) -> int:
    return wf.index(f"      - name: {header}")


def test_the_release_job_verifies_between_the_retag_and_the_upload() -> None:
    wf = _RELEASE_WF.read_text(encoding="utf-8")
    retag_at = _step(wf, "Retag images to the chart version, by digest")
    verify_at = _step(wf, "Verify the release tags resolve to the manifest digests")
    upload_at = _step(wf, "Attach the digest manifest to the chart release")
    assert retag_at < verify_at < upload_at
    block = wf[verify_at:upload_at]
    code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
    assert "retag_images_by_digest.py --verify" in code
    assert "steps.retag.outputs.version" in code
    # Under `bash -e` an uncaptured exit aborts the step, and the exit-3 warning below cannot run.
    assert "|| rc=$?" in code and '"$rc" = "3"' in code


def test_every_build_carries_the_oci_labels() -> None:
    wf = _BUILD_WF.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in wf.splitlines() if not ln.lstrip().startswith("#"))
    builds = code.count("docker buildx build")
    assert builds == 3
    assert code.count("$TAGS $LABELS") == builds
    assert "org.opencontainers.image.revision=${{ github.sha }}" in code
    assert "org.opencontainers.image.version=${CHART_VERSION}" in code
    assert "helm/invincible-agent/Chart.yaml" in code
