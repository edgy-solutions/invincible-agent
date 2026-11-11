"""Job 26 (architect via Chris, 2026-11-11): an export profile with no grant is not an error, and a
`can_export:<name>` row naming a profile this deployment does not know refuses THAT ROW ONLY.

The ruling, as sealed here:
  1. no grant for a profile -> deny by default (absent from the listing, refused at the route),
     never an error anywhere;
  2. a grant naming an unknown profile -> that row is refused with a report, the sync proceeds and
     exits 0;
  3. known = the image's base profiles + the deployment's overlay profiles, composed by each
     family's own loader (policy/export_profile_sources.yaml); the sample profiles are known only
     where the sample overlay is loaded (the sandbox sets the *_OVERLAY_DIRS variables).

No seal reaches live Topaz: `main()` runs against the rail test's `_Fake` directory client.

Run:  uv run python -m pytest tests/security/test_an_export_grant_names_a_known_profile_or_that_row_is_refused.py -q
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
from topaz_sync import DirObject, DirRelation  # noqa: E402

from tests.security.test_can_export_capability_rail import _Fake  # noqa: E402

GROUP = "alert-processors"
SAMPLE_REVIEW = ROOT / "policy" / "overlays" / "sample" / "exports"
SAMPLE_FIN = ROOT / "policy" / "overlays" / "sample" / "fin_export_profiles"
SAMPLES = ("part-list", "part-list-reviewed")
_ENV = ("INGEST_EXPORT_PROFILE_DIR", "INGEST_EXPORT_PROFILE_OVERLAY_DIRS", "EXPORT_PROFILE_POLICY_DIR",
        "EXPORT_PROFILE_OVERLAY_DIRS", "FIN_EXPORT_PROFILE_POLICY_DIR", "FIN_EXPORT_PROFILE_OVERLAY_DIRS")


def _row(group=GROUP):
    return {"granted_by": "seed", "reason": "test", "grant_to_groups": [group]}


def _overlay(tmp_path, *names):
    d = tmp_path / "overlay"
    d.mkdir(exist_ok=True)
    for n in names:
        (d / f"{n}.yaml").write_text(yaml.safe_dump({
            "name": n, "label": n, "grain": "per_notice", "columns": [
                {"output": "Id", "field": "notice_id", "granularity": "notice"}]}), encoding="utf-8")
    return d


class _Door:
    """TopazClient's context-manager face over the rail test's directory double."""
    def __init__(self, fake):
        self.fake = fake

    def __call__(self, url):
        return self

    def __enter__(self):
        return self.fake

    def __exit__(self, *a):
        return False


def run_sync(monkeypatch, tmp_path, capsys, rows, env=None, grants_file=None):
    """main() on `rows` (or a grants file) with exactly the overlay env given. Returns
    (exit code, fake client, stdout, stderr)."""
    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, str(v))
    if grants_file is None:
        grants_file = tmp_path / "grants.yaml"
        grants_file.write_text(yaml.safe_dump({"capabilities": rows}), encoding="utf-8")
    monkeypatch.setenv("CAPABILITY_GRANTS_FILE", str(grants_file))
    raw = yaml.safe_load(Path(grants_file).read_text(encoding="utf-8"))
    groups = {g for r in raw["capabilities"].values() for g in r.get("grant_to_groups", [])}
    fake = _Fake(objects={DirObject("group", g) for g in groups})
    monkeypatch.setattr(topaz_sync, "TopazClient", _Door(fake))
    code = cgs.main()
    out = capsys.readouterr()
    return code, fake, out.out, out.err


def applied(fake):
    """The can_export profile names that hold an invoker relation."""
    return {r.object_id[len("can_export:"):] for r in fake.relations
            if r.object_type == "capability" and r.object_id.startswith("can_export:")}


def listed(env_dirs, fake, monkeypatch):
    """The review-export listing's rule: a profile the loader serves AND the caller may export (the
    gateway's `_may_export_profile`, a Topaz can_invoke, which is the invoker relation here)."""
    from iagent import export_profiles
    for k, v in env_dirs.items():
        monkeypatch.setenv(k, str(v))
    export_profiles.clear_cache()
    try:
        served = set(export_profiles.load_profiles())
    finally:
        export_profiles.clear_cache()
    return served & applied(fake)


# -- 1. a deployment with no export grants syncs clean --------------------------------------

def test_1_no_export_grants_syncs_clean(monkeypatch, tmp_path, capsys):
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, {"can_drop:thing": _row()})
    assert code == 0, (out, err)
    assert "can_export rows: 0 applied, 0 refused" in out
    assert "REFUSED" not in err and applied(fake) == set()
    assert DirObject("capability", "can_drop:thing") in fake.objects  # the sync did run


# -- 2. a grant to the deployment's own overlay profile syncs and lists ---------------------

def test_2_a_grant_to_its_own_overlay_profile_syncs_and_lists(monkeypatch, tmp_path, capsys):
    ov = _overlay(tmp_path, "mine")
    env = {"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": ov}
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, {"can_export:mine": _row()}, env)
    assert code == 0 and "REFUSED" not in err, (out, err)
    assert "can_export rows: 1 applied, 0 refused" in out
    assert applied(fake) == {"mine"}
    assert listed(env, fake, monkeypatch) == {"mine"}


def test_2_control_the_same_grant_without_the_overlay_is_refused(monkeypatch, tmp_path, capsys):
    _overlay(tmp_path, "mine")  # on disk, but no deployment loads it
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, {"can_export:mine": _row()})
    assert code == 0
    assert applied(fake) == set() and "REFUSED ROW capability[can_export:mine]" in err


# -- 3. an unknown name refuses that row only ------------------------------------------------

def test_3_an_unknown_name_refuses_that_row_and_the_others_still_apply(monkeypatch, tmp_path, capsys):
    ov = _overlay(tmp_path, "mine")
    env = {"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": ov}
    rows = {"can_export:mine": _row(), "can_export:nosuch": _row(), "can_drop:thing": _row()}
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, rows, env)
    assert code == 0, (out, err)                                    # the job exit stays clean
    assert applied(fake) == {"mine"}
    assert DirObject("capability", "can_drop:thing") in fake.objects
    refused = [ln for ln in err.splitlines() if ln.startswith("REFUSED ROW")]
    assert len(refused) == 1 and "capability[can_export:nosuch]" in refused[0], err
    assert "'nosuch'" in refused[0] and "not an export profile this deployment knows" in refused[0]
    assert "mine" in refused[0]                                     # the report lists what IS known
    assert "can_export rows: 1 applied, 1 refused" in out           # the summary is on stdout


def test_3_control_the_same_set_minus_the_unknown_row_applies_identically(monkeypatch, tmp_path, capsys):
    ov = _overlay(tmp_path, "mine")
    env = {"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": ov}
    full = {"can_export:mine": _row(), "can_export:nosuch": _row(), "can_drop:thing": _row()}
    _, with_bad, _, _ = run_sync(monkeypatch, tmp_path, capsys, full, env)
    del full["can_export:nosuch"]
    code, without, out, err = run_sync(monkeypatch, tmp_path, capsys, full, env)
    assert code == 0 and "REFUSED" not in err and "1 applied, 0 refused" in out
    assert with_bad.relations == without.relations


def test_3_a_refused_rows_old_relations_are_pruned_not_kept(monkeypatch, tmp_path, capsys):
    """A row that was applied earlier and now names an unknown profile loses its relation: refusing
    the row is not 'leave whatever Topaz holds'."""
    stale = DirRelation("capability", "can_export:gone", "invoker", "group", GROUP, "member")
    for v in _ENV:
        monkeypatch.delenv(v, raising=False)
    grants = tmp_path / "g.yaml"
    grants.write_text(yaml.safe_dump({"capabilities": {"can_export:gone": _row()}}), encoding="utf-8")
    monkeypatch.setenv("CAPABILITY_GRANTS_FILE", str(grants))
    fake = _Fake(objects={DirObject("group", GROUP)}, relations={stale})
    monkeypatch.setattr(topaz_sync, "TopazClient", _Door(fake))
    assert cgs.main() == 0
    assert applied(fake) == set(), fake.relations


# -- 4. the sandbox, with the sample overlay, lists both samples -------------------------------

SANDBOX = {"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": SAMPLE_REVIEW, "FIN_EXPORT_PROFILE_OVERLAY_DIRS": SAMPLE_FIN}


def test_4_sandbox_with_the_sample_overlay_lists_both_samples_to_their_grantees(monkeypatch, tmp_path, capsys):
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, None, SANDBOX,
                                    grants_file=ROOT / "policy" / "capability_grants.yaml")
    assert code == 0 and "REFUSED ROW" not in err, (out, err)
    assert "0 refused" in out
    assert set(SAMPLES) <= applied(fake)
    for name in SAMPLES:  # each to the group its row names
        assert DirRelation("capability", f"can_export:{name}", "invoker", "group", GROUP, "member") in fake.relations
    assert set(SAMPLES) <= listed({"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": SAMPLE_REVIEW}, fake, monkeypatch)


def test_4_the_sandbox_values_set_the_variables_this_seal_assumes():
    env = yaml.safe_load((ROOT / "helm" / "invincible-agent" / "values-sandbox.yaml")
                         .read_text(encoding="utf-8"))["agentFleet"]["env"]
    for k, v in SANDBOX.items():
        assert env[k] == "/app/" + Path(v).relative_to(ROOT).as_posix(), (k, env.get(k))


# -- 5. the same sync without the sample overlay -------------------------------------------------

def test_5_without_the_sample_overlay_the_sample_rows_are_refused_as_unknown_and_the_rest_applies(
        monkeypatch, tmp_path, capsys):
    grants = ROOT / "policy" / "capability_grants.yaml"
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, None, None, grants_file=grants)
    assert code == 0, (out, err)
    refused = {ln.split("capability[can_export:")[1].split("]")[0]
               for ln in err.splitlines() if ln.startswith("REFUSED ROW")}
    assert set(SAMPLES) <= refused, err
    # the control: the rest applies. Every can_export row not refused holds its relation.
    want = {k[len("can_export:"):] for k in yaml.safe_load(grants.read_text(encoding="utf-8"))["capabilities"]
            if k.startswith("can_export:")}
    assert applied(fake) == want - refused and applied(fake), (applied(fake), want, refused)
    assert not (set(SAMPLES) & applied(fake))
    # and a seed profile is among what applied: the refusal is not a blanket.
    seed = {p.stem for p in (ROOT / "policy" / "exports").glob("*.yaml")}
    assert seed & applied(fake)


# -- 6. no grant is not an error, in any family ------------------------------------------------------

def test_6_a_known_profile_with_no_grant_is_absent_from_the_listing_and_the_sync_is_clean(
        monkeypatch, tmp_path, capsys):
    ov = _overlay(tmp_path, "mine")
    env = {"INGEST_EXPORT_PROFILE_OVERLAY_DIRS": ov}
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, {"can_drop:thing": _row()}, env)
    assert code == 0 and "REFUSED" not in err, (out, err)
    assert listed(env, fake, monkeypatch) == set()                # absent: deny by default
    # control: the grant makes the same profile listed.
    code, fake, out, err = run_sync(monkeypatch, tmp_path, capsys, {"can_export:mine": _row()}, env)
    assert listed(env, fake, monkeypatch) == {"mine"}


def test_6_the_route_of_each_gating_family_asks_can_export_and_none_errors_on_a_missing_grant():
    """The doors that ask can_export refuse on a False answer (a 403/refusal), never raise a
    'profile has no grant' error. Source-level: each gate is called at its listing and its route."""
    gw = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert gw.count("await _may_export_profile(") >= 3          # review-export: listing + routes
    assert gw.count("_plan_may_export(") >= 3                   # answer-export: def + listing + route
    cost = (ROOT / "agent_fleet" / "cost_agent" / "main.py").read_text(encoding="utf-8")
    assert "_plan_can_export_or_refuse" in cost
    for src in (gw, cost):
        assert "has no grant" not in src and "no can_export row" not in src


def test_6_no_validator_or_sync_site_errors_on_a_missing_grant_or_an_unknown_name():
    """The census as a text seal: the two error forms are gone from the sync scripts."""
    for rel in ("policy/sync/validate_policy.py", "policy/sync/capability_grant_sync.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "NOBODY could export it" not in text, rel
        assert "NOT a known export profile" not in text, rel
    for script in (ROOT / "policy" / "sync").glob("*.py"):
        assert "offline_overlays" not in script.read_text(encoding="utf-8"), script.name


# -- 7. the Jobs see the pods' overlay env (the chart) -------------------------------------------------

_CHART = ROOT / "helm" / "invincible-agent"
needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed (CI has none)")


def _strings(node):
    """Every string leaf of a rendered document: the shell scripts, unescaped."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _scripts(*args):
    r = subprocess.run(["helm", "template", "t", str(_CHART), "-f", str(_CHART / "values-sandbox.yaml"),
                        "--set", "topazSeed.enabled=true", *args],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 0, r.stderr[-700:]
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    out = {}
    for d in docs:
        if d.get("kind") in ("CronJob", "Job") and any(
                s in d["metadata"]["name"] for s in ("topaz-seed", "task-grant-sync")):
            out[d["metadata"]["name"]] = chr(10).join(_strings(d))
    return out


@needs_helm
def test_7_both_jobs_export_the_pods_overlay_variables_before_they_sync():
    scripts = _scripts()
    assert len(scripts) == 2, list(scripts)
    for name, text in scripts.items():
        for k, v in SANDBOX.items():
            line = f'export {k}="/app/' + Path(v).relative_to(ROOT).as_posix() + '"'
            assert line in text, (name, line)
        assert text.index("INGEST_EXPORT_PROFILE_OVERLAY_DIRS") < text.index("capability_grant_sync"), name


@needs_helm
def test_7_a_git_overlay_adds_each_component_dir_that_exists_on_the_job():
    scripts = _scripts("--set", "policyOverlay.enabled=true", "--set-string",
                       "policyOverlay.ref=0123456789abcdef0123456789abcdef01234567",
                       "--set", "topazSeed.policySource.type=git",
                       "--set", "topazSeed.policySource.git.repoUrl=https://git.example.com/org/policy.git")
    for name, text in scripts.items():
        assert 'if [ -d "/overlay-src/repo/exports" ]; then export INGEST_EXPORT_PROFILE_OVERLAY_DIRS=' in text, name


# -- 8. the sync Jobs mount the pods' overlay: same variable, same directory ---------------------------

def _render(*args):
    r = subprocess.run(["helm", "template", "t", str(_CHART), "-f", str(_CHART / "values-sandbox.yaml"),
                        "--set", "topazSeed.enabled=true", *args],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert r.returncode == 0, r.stderr[-700:]
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _pod_env(docs, name_part):
    dep = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith(name_part))
    maps = {d["metadata"]["name"]: d.get("data") or {} for d in docs if d.get("kind") == "ConfigMap"}
    env = {}
    for c in dep["spec"]["template"]["spec"]["containers"]:
        for ef in c.get("envFrom", []):  # the shared config a pod reads whole
            env.update(maps.get((ef.get("configMapRef") or {}).get("name"), {}))
        env.update({e["name"]: e.get("value") for e in c.get("env", [])})
    return env


def _job_texts(docs):
    return {d["metadata"]["name"]: chr(10).join(_strings(d)) for d in docs
            if d.get("kind") in ("CronJob", "Job")
            and any(s in d["metadata"]["name"] for s in ("topaz-seed", "task-grant-sync"))}


@needs_helm
def test_8_every_overlay_variable_a_pod_carries_is_exported_by_both_jobs_with_the_pods_value():
    docs = _render()
    # the variables the export loaders read (the registry's rows), as the pod that serves them sees them
    names = {r["overlay_env"] for r in yaml.safe_load(
        (ROOT / "policy" / "export_profile_sources.yaml").read_text(encoding="utf-8"))["sources"] if r["overlay_env"]}
    seen = _pod_env(docs, "cortex-bff")
    pod = {k: v for k, v in seen.items() if k in names}
    assert "INGEST_EXPORT_PROFILE_OVERLAY_DIRS" in pod, pod
    jobs = _job_texts(docs)
    assert len(jobs) == 2, list(jobs)
    for name, text in jobs.items():
        for k, v in pod.items():
            assert f'export {k}="{v}"' in text, (name, k, v)


@needs_helm
def test_8_with_a_git_overlay_the_jobs_dir_is_the_pods_dir_for_every_component_row():
    docs = _render("--set", "policyOverlay.enabled=true", "--set-string",
                   "policyOverlay.ref=0123456789abcdef0123456789abcdef01234567",
                   "--set", "topazSeed.policySource.type=git",
                   "--set", "topazSeed.policySource.git.repoUrl=https://git.example.com/org/policy.git",
                   "--set", "engineFinance.enabled=true")
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    rows = [(comp, r) for comp, rs in values["policyOverlay"]["components"].items() for r in rs]
    assert rows
    jobs = _job_texts(docs)
    assert len(jobs) == 2
    for comp, r in rows:
        pod_dir = _pod_env(docs, comp.replace("engine-", "engine-", 1)).get(r["env"])
        assert pod_dir and pod_dir.endswith("/" + r["dir"]), (comp, r, pod_dir)
        for name, text in jobs.items():
            assert (f'if [ -d "/overlay-src/repo/{r["dir"]}" ]; then '
                    f'export {r["env"]}="/overlay-src/repo/{r["dir"]}"; fi') in text, (name, r)
