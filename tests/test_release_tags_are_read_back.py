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


def test_a_manifest_with_every_image_missing_is_exit_3(tmp_path) -> None:
    """Exit 3 is still distinct from 1, so the log says WHICH; the release fails on both."""
    m = _manifest(tmp_path, images={}, missing=["cortex-bff", "graph-host"])
    assert retag.verify(m, "0.4.65", _registry(_GOOD)) == 3


def test_a_partial_manifest_still_checks_what_was_tagged(tmp_path) -> None:
    m = _manifest(tmp_path, images={"cortex-bff": _A}, missing=["graph-host"])
    assert retag.verify(m, "0.4.65", _registry(_GOOD)) == 3
    moved = dict(_GOOD, **{f"{_REG}/cortex-bff:0.4.65": _B})
    assert retag.verify(m, "0.4.65", _registry(moved)) == 1


def _step(wf: str, header: str) -> int:
    return wf.index(f"      - name: {header}")


def _code(block: str) -> str:
    return "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


def test_the_release_tags_and_verifies_before_it_publishes() -> None:
    """Retag, then verify, then chart-releaser, then the manifest: a release exists only over
    images that are tagged and read back. chart-releaser ran FIRST until 2026-10-25."""
    wf = _RELEASE_WF.read_text(encoding="utf-8")
    retag_at = _step(wf, "Retag images to the chart version, by digest")
    verify_at = _step(wf, "Verify the release tags resolve to the manifest digests")
    publish_at = _step(wf, "Run chart-releaser")
    upload_at = _step(wf, "Attach the digest manifest to the chart release")
    assert retag_at < verify_at < publish_at < upload_at
    verify = _code(wf[verify_at:publish_at])
    assert "retag_images_by_digest.py --verify" in verify
    assert "steps.retag.outputs.version" in verify
    # Under `bash -e` an uncaptured exit aborts the step before the annotation; a `| tee` would
    # hand rc tee's exit (the default shell has no pipefail).
    assert "|| rc=$?" in verify and 'exit "$rc"' in verify and "| tee" not in verify


def test_no_missing_image_is_a_warning() -> None:
    """Exit 3 was a `::warning::` in both steps, which is how 0 of 19 published green."""
    wf = _RELEASE_WF.read_text(encoding="utf-8")
    steps = _code(wf[_step(wf, "Retag images to the chart version, by digest"):
                     _step(wf, "Run chart-releaser")])
    assert "::warning::" not in steps
    assert "3) echo \"::error::" in steps and "exit 3" in steps


def test_a_dispatch_must_name_the_release_tags_own_commit() -> None:
    wf = _RELEASE_WF.read_text(encoding="utf-8")
    retag_step = _code(wf[_step(wf, "Retag images to the chart version, by digest"):
                          _step(wf, "Verify the release tags resolve to the manifest digests")])
    assert 'refs/tags/invincible-agent-${version}^{commit}' in retag_step
    assert '"${tagged}" != "${sha}"' in retag_step


def _yaml(path: pathlib.Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_release_is_called_by_the_build_and_needs_it() -> None:
    """THE ROOT CAUSE: the release had its own `push` trigger and raced the matrix."""
    rel = _yaml(_RELEASE_WF)
    triggers = rel.get("on", rel.get(True))  # PyYAML reads a bare `on:` key as True
    assert "push" not in triggers and "workflow_call" in triggers and "workflow_dispatch" in triggers
    jobs = _yaml(_BUILD_WF)["jobs"]
    release = jobs["release"]
    assert release["uses"] == "./.github/workflows/release-helm-charts.yml"
    assert "build" in release["needs"] and "release-gate" in release["needs"]
    assert "always()" not in str(release.get("if", ""))
    gate = jobs["release-gate"]
    assert "build" in gate["needs"] and gate["if"].startswith("always()")
    assert "needs.build.result" in _code(gate["steps"][0]["run"])
    assert "helm/" in jobs["helm-changed"]["steps"][-1]["run"]


# ── THE NO-OVERWRITE GUARD ─────────────────────────────────────────────────────────────────
_SVCS = ["cortex-bff", "graph-host"]
_SRC = {f"{_REG}/cortex-bff:{_COMMIT}": _A, f"{_REG}/graph-host:{_COMMIT}": _B}


def _dst(states: dict):
    """A destination reader: `states` maps a service to its tag_state; unnamed ones are absent."""
    return lambda ref: states.get(ref.split("/")[-1].split(":")[0], ("absent", None))


def _plan(states: dict, src=None) -> dict:
    return retag.plan(_SVCS, _COMMIT, "0.4.69", _registry(_SRC if src is None else src), _dst(states))


def test_absent_tags_are_planned_and_nothing_refuses() -> None:
    p = _plan({})
    assert p["tag"] == {"cortex-bff": _A, "graph-host": _B} and retag.refusal(p) is None


def test_a_tag_already_at_the_built_digest_is_left_alone() -> None:
    p = _plan({"graph-host": ("present", _B)})
    assert p["already"] == {"graph-host": _B} and "graph-host" not in p["tag"]
    assert retag.refusal(p) is None


def test_a_tag_at_another_digest_is_a_conflict_and_refuses() -> None:
    """The twin of the arm above: the same present tag, one digest different."""
    p = _plan({"graph-host": ("present", _A)})
    assert p["conflicts"] == {"graph-host": {"tagged": _A, "built": _B}}
    assert retag.refusal(p) == 4


def test_an_unreadable_destination_refuses_rather_than_creates() -> None:
    p = _plan({"graph-host": ("unreadable", None)})
    assert "graph-host" not in p["tag"] and retag.refusal(p) == 1


def test_a_missing_source_image_refuses() -> None:
    p = _plan({}, src={f"{_REG}/cortex-bff:{_COMMIT}": _A})
    assert p["missing"] == ["graph-host"] and retag.refusal(p) == 3


def test_tag_state_tells_absent_from_unreadable(monkeypatch) -> None:
    for rc, out, want in ((1, "ERROR: ghcr.io/x:0.4.69: not found", ("absent", None)),
                          (1, "ERROR: MANIFEST_UNKNOWN: manifest unknown", ("absent", None)),
                          (1, "ERROR: dial tcp: connection reset by peer", ("unreadable", None)),
                          (0, f"{_A}\n", ("present", _A))):
        monkeypatch.setattr(retag, "_run", lambda cmd, r=rc, o=out: (r, o))
        assert retag.tag_state("ghcr.io/x:0.4.69") == want, out


def _main(monkeypatch, tmp_path, dst: dict) -> "tuple[int, list, dict]":
    """Run main() against a registry double; return (exit, the creates it issued, the manifest)."""
    creates: list = []

    def run(cmd):
        if cmd[3] == "create":
            creates.append(cmd)
            return 0, ""
        ref = cmd[4]
        if ref in _SRC:
            return 0, _SRC[ref]
        if ref in dst:
            return 0, dst[ref]
        return 1, f"ERROR: {ref}: not found"

    monkeypatch.setattr(retag, "_run", run)
    monkeypatch.setattr(retag, "services_from_matrix", lambda: list(_SVCS))
    out = tmp_path / "image-digests.json"
    summary = tmp_path / "summary.md"
    monkeypatch.setattr("sys.argv", ["retag", "--chart-version", "0.4.69", "--sha", _COMMIT,
                                     "--manifest", str(out), "--summary-file", str(summary)])
    rc = retag.main()
    return rc, creates, json.loads(out.read_text(encoding="utf-8"))


def test_a_conflict_anywhere_means_no_tag_is_written_anywhere(monkeypatch, tmp_path) -> None:
    rc, creates, m = _main(monkeypatch, tmp_path, {f"{_REG}/graph-host:0.4.69": _A})
    assert rc == 4 and creates == []
    assert m["conflicts"] == {"graph-host": {"tagged": _A, "built": _B}} and m["images"] == {}
    assert "CONFLICT `graph-host:0.4.69`" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_the_same_registry_without_the_conflict_tags_only_what_is_absent(monkeypatch, tmp_path) -> None:
    """The control: graph-host already at ITS digest. One create, for cortex-bff, by digest."""
    rc, creates, m = _main(monkeypatch, tmp_path, {f"{_REG}/graph-host:0.4.69": _B})
    assert rc == 0
    assert [c[-3:] for c in creates] == [["-t", f"{_REG}/cortex-bff:0.4.69", f"{_REG}/cortex-bff@{_A}"]]
    assert m["images"] == {"cortex-bff": _A, "graph-host": _B} and m["already_tagged"] == ["graph-host"]


def test_every_build_carries_the_oci_labels() -> None:
    wf = _BUILD_WF.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in wf.splitlines() if not ln.lstrip().startswith("#"))
    builds = code.count("docker buildx build")
    assert builds == 3
    assert code.count("$TAGS $LABELS") == builds
    assert "org.opencontainers.image.revision=${{ github.sha }}" in code
    assert "org.opencontainers.image.version=${CHART_VERSION}" in code
    assert "helm/invincible-agent/Chart.yaml" in code
