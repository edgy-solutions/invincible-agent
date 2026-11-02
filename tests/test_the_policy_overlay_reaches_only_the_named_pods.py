"""A DEPLOYMENT'S PRIVATE OVERLAY REACHES THE NAMED PODS, THE NAMED DIRS, AT A PINNED REF -- AND NOTHING ELSE.

WHY THIS EXISTS. The finance overlay rows (`docs/contracts/finance-overlays.md`) are read from
directories named by `MEASURE_VERB_OVERLAY_DIRS`, `FIN_EXPORT_PROFILE_OVERLAY_DIRS` (engine-fin) and
`CANVAS_OVERLAY_DIRS` (cortex-bff). The sandbox's are baked into the image. A private repo had no
way in: `topazSeed.policySource.git` clones only in the seed CronJob and task-grant-sync. Chris
ruled 2026-11-02 that an initContainer clones the policy repo at a pinned ref into the pods
(`policyOverlay` in values.yaml).

WHAT CAN GO WRONG, AND WHICH ARM HOLDS IT.

* It reaches a pod it was not meant for (an engine reading the repo's users and grants): b, and the
  mount arm c (the main container never sees the clone, `overlay-src`).
* The main container can write to what it was given: c asserts `readOnly: true`.
* It tracks a branch, so a roll fetches whatever the branch holds that day: the script arm (g) runs
  the RENDERED script and a branch name must fail; the ref has no default (e).
* A missing required directory starts the service with no rows, silently: g.
* It rendered when OFF and changed a pod nobody asked it to change: a. (The byte-for-byte
  base-vs-HEAD render was measured by hand when this landed; this arm holds the shape.)

SKIPS, HONESTLY. Arms that render use `helm template` and skip without `helm`; the script arm needs
`sh` and `git` as well. CI's pytest jobs install no helm, so those arms DO NOT FIRE THERE. The
`text_*` arms always run: they read the templates and values as text, so a regression in the guard,
the read-only mount or the ref rule still reds in CI.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir . -o addopts="" -q tests/test_the_policy_overlay_reaches_only_the_named_pods.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_HELPERS = (_CHART / "templates" / "_helpers.tpl").read_text(encoding="utf-8")
_ENGINES = (_CHART / "templates" / "engines.yaml").read_text(encoding="utf-8")
_FRONTEND = (_CHART / "templates" / "frontend.yaml").read_text(encoding="utf-8")
_VALUES = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

_HAVE_HELM = shutil.which("helm") is not None
needs_helm = pytest.mark.skipif(not _HAVE_HELM, reason="helm not installed (CI's pytest jobs have none)")

_REPO_URL = "https://git.example.com/org/policy.git"
_SHA = "0123456789abcdef0123456789abcdef01234567"
_ON = [
    "--set", "engineFinance.enabled=true",
    "--set", "policyOverlay.enabled=true",
    "--set-string", f"policyOverlay.ref={_SHA}",
    "--set", f"topazSeed.policySource.git.repoUrl={_REPO_URL}",
]


def _helm(*args: str, values: bool = False) -> subprocess.CompletedProcess:
    base = ["helm", "template", "t", str(_CHART)]
    if values:
        base += ["-f", str(_CHART / "values-sandbox.yaml")]
    return subprocess.run([*base, *args], capture_output=True, text=True, cwd=str(_REPO), timeout=300)


def _render(*args: str, values: bool = False) -> list[dict]:
    """Rendered documents; a failed render FAILS the test rather than yielding an empty list, because
    every absence assertion below would otherwise pass vacuously."""
    r = _helm(*args, values=values)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _deployments(docs: list[dict]) -> dict[str, dict]:
    return {d["metadata"]["name"]: d["spec"]["template"]["spec"] for d in docs if d.get("kind") == "Deployment"}


def _init(spec: dict) -> dict | None:
    return next((c for c in spec.get("initContainers", []) if c["name"] == "fetch-policy-overlay"), None)


def _env(container: dict) -> dict[str, str]:
    return {e["name"]: e.get("value") for e in container.get("env", [])}


# ── TEXT ARMS: always run, helm or not ──────────────────────────────────────────────────────


def test_text_off_by_default_and_the_ref_has_no_default():
    po = _VALUES["policyOverlay"]
    assert po["enabled"] is False
    assert po["ref"] == "", "a default ref would pin every deployment to a ref nobody chose"
    rows = {c: [(r["dir"], r["env"]) for r in rows] for c, rows in po["components"].items()}
    assert rows == {
        "engine-fin": [("measure_verbs", "MEASURE_VERB_OVERLAY_DIRS"),
                       ("fin_export_profiles", "FIN_EXPORT_PROFILE_OVERLAY_DIRS")],
        "cortex-bff": [("canvases", "CANVAS_OVERLAY_DIRS")],
    }


def test_text_the_sandbox_does_not_turn_it_on():
    sandbox = yaml.safe_load((_CHART / "values-sandbox.yaml").read_text(encoding="utf-8"))
    assert not (sandbox.get("policyOverlay") or {}).get("enabled")


def test_text_both_pod_templates_use_the_one_guard():
    guard = 'include "invincible-agent.policyOverlayActive"'
    assert _ENGINES.count(guard) == 1 and _FRONTEND.count(guard) == 1
    for tpl in ("Init", "Volumes", "Mounts", "Env"):
        name = f'"invincible-agent.policyOverlay{tpl}"'
        assert name in _ENGINES and name in _FRONTEND, tpl
        # each is reached only inside the `if $ov` the guard sets
    assert _ENGINES.count("{{- if $ov }}") >= 3 and _FRONTEND.count("{{- if $ov }}") >= 3


def test_text_the_main_container_mounts_the_copy_read_only_and_never_the_clone():
    m = re.search(r'define "invincible-agent.policyOverlayMounts" -}}(.*?)\{\{- end -\}\}', _HELPERS, re.S)
    assert m, "the mounts helper is gone"
    body = m.group(1)
    assert "name: policy-overlay" in body and "readOnly: true" in body
    assert "overlay-src" not in body, "the main container must not see the clone (the repo's users and grants)"


def test_text_the_script_pins_and_refuses():
    assert 'want="refs/tags/$GIT_REF"' in _HELPERS, "a non-sha ref must be fetched as a TAG only"
    assert "{40}" in _HELPERS
    assert 'git rev-parse HEAD)" != "$GIT_REF"' in _HELPERS, "a sha pin is asserted after the fetch"
    assert "is missing from the repo" in _HELPERS and "exit 1" in _HELPERS, "a missing required dir is fatal"


def test_text_the_render_fails_without_a_ref_or_a_repo():
    assert 'fail "policyOverlay.ref is required' in _HELPERS
    assert 'fail "topazSeed.policySource.git.repoUrl is required when policyOverlay.enabled' in _HELPERS


# ── RENDER ARMS ─────────────────────────────────────────────────────────────────────────────


@needs_helm
@pytest.mark.parametrize("values", [False, True], ids=["bare-defaults", "sandbox-values"])
def test_a_off_renders_no_overlay_anywhere(values):
    r = _helm(values=values)
    assert r.returncode == 0, r.stderr[-500:]
    assert "fetch-policy-overlay" not in r.stdout
    assert "policy-overlay" not in r.stdout
    deps = _deployments([d for d in yaml.safe_load_all(r.stdout) if d])
    assert "t-cortex-bff" in deps, "positive control: the render holds the Deployments"


@needs_helm
def test_b_exactly_the_named_pods_get_the_init_container():
    deps = _deployments(_render(*_ON, values=True))
    got = {n for n, s in deps.items() if _init(s)}
    assert got == {"t-engine-fin", "t-cortex-bff"}, got
    assert len(deps) > 10, "positive control: many other Deployments were rendered and checked"


@needs_helm
def test_c_main_containers_mount_the_copy_read_only_and_not_the_clone():
    deps = _deployments(_render(*_ON, values=True))
    for name in ("t-engine-fin", "t-cortex-bff"):
        main = deps[name]["containers"][0]
        mounts = {m["name"]: m for m in main["volumeMounts"]}
        assert mounts["policy-overlay"].get("readOnly") is True, name
        assert "overlay-src" not in mounts, name
        init_mounts = {m["name"] for m in _init(deps[name])["volumeMounts"]}
        assert {"overlay-src", "policy-overlay"} <= init_mounts, "positive control: init sees both"


@needs_helm
def test_d_the_env_names_the_delivered_paths():
    deps = _deployments(_render(*_ON, values=True))
    fin = _env(deps["t-engine-fin"]["containers"][0])
    assert fin["MEASURE_VERB_OVERLAY_DIRS"] == "/policy-overlay/measure_verbs"
    assert fin["FIN_EXPORT_PROFILE_OVERLAY_DIRS"] == "/policy-overlay/fin_export_profiles"
    bff = _env(deps["t-cortex-bff"]["containers"][0])
    assert bff["CANVAS_OVERLAY_DIRS"] == "/policy-overlay/canvases"
    assert "CANVAS_OVERLAY_DIRS" not in fin and "MEASURE_VERB_OVERLAY_DIRS" not in bff


@needs_helm
def test_d_the_bff_keeps_its_tls_trust_volume_beside_the_overlay():
    spec = _deployments(_render(
        *_ON, "--set", "cortexBff.tlsTrust.secretName=x", "--set", "cortexBff.tlsTrust.secretKey=k",
        "--set", "cortexBff.tlsTrust.mountPath=/etc/ca.pem"))["t-cortex-bff"]
    assert {v["name"] for v in spec["volumes"]} == {"work-ca-bundle", "overlay-src", "policy-overlay"}
    assert {m["name"] for m in spec["containers"][0]["volumeMounts"]} == {"work-ca-bundle", "policy-overlay"}


@needs_helm
def test_e_no_ref_fails_naming_the_ref_and_no_repo_fails_naming_the_repo():
    r = _helm("--set", "policyOverlay.enabled=true",
              "--set", f"topazSeed.policySource.git.repoUrl={_REPO_URL}", values=True)
    assert r.returncode != 0 and "policyOverlay.ref" in r.stderr, r.stderr[-400:]
    r = _helm("--set", "policyOverlay.enabled=true", "--set-string", f"policyOverlay.ref={_SHA}", values=True)
    assert r.returncode != 0 and "topazSeed.policySource.git.repoUrl" in r.stderr, r.stderr[-400:]


@needs_helm
def test_f_the_seeds_credential_and_ca_are_reused():
    deps = _deployments(_render(
        *_ON, "--set", "topazSeed.policySource.git.authSecretName=the-auth",
        "--set", "topazSeed.policySource.git.caSecretName=the-ca"))
    for name in ("t-engine-fin", "t-cortex-bff"):
        init = _init(deps[name])
        env = {e["name"]: e for e in init["env"]}
        for k, key in (("GIT_USERNAME", "username"), ("GIT_PASSWORD", "password")):
            ref = env[k]["valueFrom"]["secretKeyRef"]
            assert ref == {"name": "the-auth", "key": key}, (name, k)
        assert env["GIT_SSL_CAINFO"]["value"] == "/git-ca/ca.crt"
        assert env["GIT_REPO_URL"]["value"] == _REPO_URL and env["GIT_REF"]["value"] == _SHA
        vols = {v["name"]: v for v in deps[name]["volumes"]}
        assert vols["git-ca"]["secret"]["secretName"] == "the-ca"
        assert "git-ca" not in {m["name"] for m in deps[name]["containers"][0].get("volumeMounts", [])}


# ── THE SCRIPT RUNS ─────────────────────────────────────────────────────────────────────────

_HAVE_SH_GIT = shutil.which("sh") is not None and shutil.which("git") is not None
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always",
}


def _file_url(p: Path) -> str:
    """`file://` URL of a local bare repo. On Windows `Path.as_uri()` gives `file:///C:/...`, which a
    native git run from `sh` reads as the path `/C:/...`; `file://C:/...` is read correctly."""
    return "file://" + p.as_posix() if os.name == "nt" else p.as_uri()


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_GIT_ENV, capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr[-300:]}"
    return r.stdout.strip()


def _commit(work: Path, files: dict[str, str | None], msg: str) -> str:
    for rel, body in files.items():
        p = work / rel
        if body is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")
    _g(work, "add", "-A")
    _g(work, "commit", "-q", "-m", msg)
    return _g(work, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def script():
    if not (_HAVE_HELM and _HAVE_SH_GIT):
        pytest.skip("needs helm, sh and git")
    spec = _deployments(_render(*_ON))["t-engine-fin"]
    return _init(spec)["args"][0]


@pytest.fixture()
def origin(tmp_path):
    """A bare repo over file:// with real history:
         c1  measure_verbs/a.yaml=one, fin_export_profiles/p.yaml, users.yaml   tags v1 (light), v1a (annotated)
         c2  (branch main) measure_verbs/a.yaml=tip                             tag none
         c3  branch nomv: measure_verbs removed                                 tag nomv
         c4  branch noprof: fin_export_profiles removed                         tag noprof
    """
    bare, work = tmp_path / "origin.git", tmp_path / "work"
    _g(tmp_path, "init", "-q", "--bare", str(bare))
    _g(bare, "config", "uploadpack.allowReachableSHA1InWant", "true")
    _g(tmp_path, "init", "-q", "-b", "main", str(work))
    c1 = _commit(work, {"measure_verbs/a.yaml": "one\n", "fin_export_profiles/p.yaml": "prof\n",
                        "users.yaml": "users: [secret-grants]\n"}, "c1")
    _g(work, "tag", "v1")
    _g(work, "tag", "-a", "-m", "annotated", "v1a")
    c2 = _commit(work, {"measure_verbs/a.yaml": "tip\n"}, "c2")
    _g(work, "branch", "nomv", c1)
    _g(work, "branch", "noprof", c1)
    _g(work, "remote", "add", "origin", _file_url(bare))
    _g(work, "-c", "protocol.file.allow=always", "push", "-q", "origin", "main")
    _g(work, "-c", "protocol.file.allow=always", "push", "-q", "origin", "--tags")
    # the two variants, tagged
    _g(work, "switch", "-q", "nomv")
    _commit(work, {"measure_verbs/a.yaml": None}, "c3")
    _g(work, "tag", "nomv")
    _g(work, "switch", "-q", "noprof")
    _commit(work, {"fin_export_profiles/p.yaml": None}, "c4")
    _g(work, "tag", "noprof")
    _g(work, "-c", "protocol.file.allow=always", "push", "-q", "origin", "--tags")
    return {"url": _file_url(bare), "c1": c1, "c2": c2}


def _run(script: str, tmp: Path, url: str, ref: str):
    src, out = tmp / "overlay-src", tmp / "policy-overlay"
    src.mkdir()
    out.mkdir()
    body = script.replace("/overlay-src", src.as_posix()).replace("/policy-overlay", out.as_posix())
    env = {**_GIT_ENV, "GIT_REPO_URL": url, "GIT_REF": ref, "MSYS_NO_PATHCONV": "1"}
    r = subprocess.run(["sh", "-c", body], env=env, capture_output=True, text=True, timeout=120)
    return r, out


def test_g_a_full_sha_gets_that_commit_and_only_the_named_dirs(script, origin, tmp_path):
    r, out = _run(script, tmp_path, origin["url"], origin["c1"])
    assert r.returncode == 0, r.stderr[-500:]
    assert (out / "measure_verbs" / "a.yaml").read_text() == "one\n"
    assert (out / "fin_export_profiles" / "p.yaml").exists()
    assert sorted(p.name for p in out.iterdir()) == ["fin_export_profiles", "measure_verbs"]
    assert not list(out.rglob("users.yaml")), "the repo's users must never reach the pod"


@pytest.mark.parametrize("tag", ["v1", "v1a"], ids=["lightweight", "annotated"])
def test_g_a_tag_gets_the_tagged_commit_not_the_branch_tip(script, origin, tmp_path, tag):
    r, out = _run(script, tmp_path, origin["url"], tag)
    assert r.returncode == 0, r.stderr[-500:]
    assert (out / "measure_verbs" / "a.yaml").read_text() == "one\n"
    assert origin["c1"] in r.stdout, "the commit the tag peels to is reported"


def test_g_a_branch_name_fails(script, origin, tmp_path):
    r, out = _run(script, tmp_path, origin["url"], "main")
    assert r.returncode != 0, "a branch must never be accepted as a pin"
    assert not list(out.iterdir())


def test_g_a_short_sha_is_not_a_pin(script, origin, tmp_path):
    r, _ = _run(script, tmp_path, origin["url"], origin["c1"][:12])
    assert r.returncode != 0


def test_g_a_missing_required_dir_fails_naming_it(script, origin, tmp_path):
    r, out = _run(script, tmp_path, origin["url"], "nomv")
    assert r.returncode != 0
    assert "measure_verbs" in r.stderr


def test_g_a_missing_optional_dir_succeeds_and_creates_nothing(script, origin, tmp_path):
    r, out = _run(script, tmp_path, origin["url"], "noprof")
    assert r.returncode == 0, r.stderr[-500:]
    assert sorted(p.name for p in out.iterdir()) == ["measure_verbs"]
    assert "fin_export_profiles" in r.stdout and "optional" in r.stdout
