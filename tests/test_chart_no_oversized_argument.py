"""No rendered container argument or literal env value may exceed Linux's per-string limit.

Linux caps ONE exec argument (and one environment string) at MAX_ARG_STRLEN = 131072 bytes (32 pages).
The realm-reconcile Job passed its whole shell script as a single `sh -c` argument; with sandbox values
the script rendered at 153266 bytes (0.4.84: 123363) and the 0.4.85 pod died with
`exec /bin/sh: argument list too long`. Nothing in the chart's tests measured a rendered argument, so
the growth was invisible until the roll.

This seal renders the chart (defaults and sandbox values, as an install and as an upgrade) and checks
every command/args element and every literal env value of every pod-bearing kind. A script that must
be long ships as a mounted file instead: `realm-reconcile`'s Job now has NO `args` (asserted below).

ConfigMap and Secret data are bounded by the API server's 1 MiB object limit, so the script now living
in a ConfigMap is bounded too.

Controls, because a checker that cannot fire is the failure this file exists to prevent:
  * the boundary: exactly 131072 bytes passes, 131073 is flagged, for an arg and for an env value;
  * the render path: a real render with an oversized value planted in a container env is flagged.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = _CHART / "values-sandbox.yaml"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

MAX_ARG_STRLEN = 131072
MAX_OBJECT_BYTES = 1048576  # the API server's 1 MiB cap on a ConfigMap / Secret

_POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}


def _pod_spec(doc: dict) -> dict | None:
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        return ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template", {}).get("spec")
    if kind in _POD_KINDS:
        return (spec.get("template") or {}).get("spec")
    return None


def oversized(docs: list[dict], limit: int = MAX_ARG_STRLEN) -> list[str]:
    """Every command/args element and literal env value over `limit` bytes, named kind/name/container/field."""
    found = []
    for doc in docs:
        spec = _pod_spec(doc)
        if spec is None:
            continue
        who = f"{doc['kind']}/{doc['metadata']['name']}"
        for c in [*(spec.get("containers") or []), *(spec.get("initContainers") or [])]:
            for field in ("command", "args"):
                for i, el in enumerate(c.get(field) or []):
                    n = len(str(el).encode("utf-8"))
                    if n > limit:
                        found.append(f"{who}/{c['name']}/{field}[{i}]: {n} bytes")
            for e in c.get("env") or []:
                if "value" in e:
                    n = len(str(e["value"]).encode("utf-8"))
                    if n > limit:
                        found.append(f"{who}/{c['name']}/env[{e['name']}]: {n} bytes")
    return found


def oversized_objects(docs: list[dict], limit: int = MAX_OBJECT_BYTES) -> list[str]:
    found = []
    for doc in docs:
        if doc.get("kind") not in ("ConfigMap", "Secret"):
            continue
        total = sum(len(str(v).encode("utf-8")) for k in ("data", "stringData") for v in (doc.get(k) or {}).values())
        if total >= limit:
            found.append(f"{doc['kind']}/{doc['metadata']['name']}: {total} bytes of data")
    return found


def largest(docs: list[dict]) -> tuple[int, int]:
    """(largest command/args element, largest literal env value), in bytes."""
    a = e = 0
    for doc in docs:
        spec = _pod_spec(doc)
        for c in [*((spec or {}).get("containers") or []), *((spec or {}).get("initContainers") or [])]:
            for field in ("command", "args"):
                a = max([a, *(len(str(x).encode("utf-8")) for x in c.get(field) or [])])
            e = max([e, *(len(str(v["value"]).encode("utf-8")) for v in c.get("env") or [] if "value" in v)])
    return a, e


def _render(*extra: str, upgrade: bool = False) -> list[dict]:
    cmd = ["helm", "template", "t", str(_CHART), *extra]
    if upgrade:
        cmd.append("--is-upgrade")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-1500:]}"
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    assert docs, "helm rendered nothing and reported success"
    return docs


# never a *.secret.yaml: the sandbox values file alone is what these renders use
_CASES = {
    "defaults-install": ([], False),
    "defaults-upgrade": ([], True),
    "sandbox-install": (["-f", str(_SANDBOX)], False),
    "sandbox-upgrade": (["-f", str(_SANDBOX)], True),
}


@pytest.fixture(scope="module", params=sorted(_CASES))
def rendered(request) -> list[dict]:
    extra, upgrade = _CASES[request.param]
    return _render(*extra, upgrade=upgrade)


# ------------------------------------------------------------------ the seal

def test_no_rendered_argument_or_env_value_is_over_the_limit(rendered):
    # positive control: the population is real, or an empty render would pass vacuously
    assert sum(1 for d in rendered if d["kind"] in _POD_KINDS) > 5
    assert not oversized(rendered), "a container string over MAX_ARG_STRLEN (131072 bytes):\n" + "\n".join(oversized(rendered))


def test_no_configmap_or_secret_is_over_the_object_limit(rendered):
    assert sum(1 for d in rendered if d["kind"] == "ConfigMap") > 3
    assert not oversized_objects(rendered), "\n".join(oversized_objects(rendered))


def test_the_realm_reconcile_job_has_no_args_its_script_is_a_mounted_file(rendered):
    # The script is the ConfigMap's reconcile.sh, mounted at /scripts; the Job runs `sh /scripts/reconcile.sh`.
    jobs = [d for d in rendered if d["kind"] == "Job" and d["metadata"]["name"].endswith("-realm-reconcile")]
    if not jobs:
        pytest.skip("keycloak realm reconcile is not enabled in this render")
    (c,) = jobs[0]["spec"]["template"]["spec"]["containers"]
    assert "args" not in c, "the realm-reconcile Job must not carry its script as an argument"
    assert c["command"] == ["sh", "/scripts/reconcile.sh"]
    (cm,) = [d for d in rendered if d["kind"] == "ConfigMap" and d["metadata"]["name"].endswith("-realm-reconcile-script")]
    assert "reconcile.sh" in cm["data"]


# ------------------------------------------------------------------ control 1: the boundary

def _job(arg: str | None = None, env_value: str | None = None) -> dict:
    c: dict = {"name": "probe", "image": "x", "command": ["sh", "-c"]}
    if arg is not None:
        c["args"] = [arg]
    if env_value is not None:
        c["env"] = [{"name": "PROBE", "value": env_value}]
    return {"kind": "Job", "metadata": {"name": "probe"}, "spec": {"template": {"spec": {"containers": [c]}}}}


def test_boundary_an_arg_of_exactly_the_limit_passes_and_one_byte_more_is_flagged():
    assert oversized([_job(arg="x" * MAX_ARG_STRLEN)]) == []
    flagged = oversized([_job(arg="x" * (MAX_ARG_STRLEN + 1))])
    assert flagged == [f"Job/probe/probe/args[0]: {MAX_ARG_STRLEN + 1} bytes"], flagged


def test_boundary_an_env_value_of_exactly_the_limit_passes_and_one_byte_more_is_flagged():
    assert oversized([_job(env_value="x" * MAX_ARG_STRLEN)]) == []
    flagged = oversized([_job(env_value="x" * (MAX_ARG_STRLEN + 1))])
    assert flagged == [f"Job/probe/probe/env[PROBE]: {MAX_ARG_STRLEN + 1} bytes"], flagged


def test_boundary_is_in_bytes_not_characters():
    # 3-byte characters: 43691 of them are 131073 bytes though only 43691 characters
    assert oversized([_job(arg="─" * 43691)]), "the limit is bytes of UTF-8, not characters"
    assert oversized([_job(arg="─" * 43690)]) == []


def test_boundary_the_object_limit_fires_too():
    cm = {"kind": "ConfigMap", "metadata": {"name": "big"}, "data": {"a": "x" * MAX_OBJECT_BYTES}}
    ok = {"kind": "ConfigMap", "metadata": {"name": "ok"}, "data": {"a": "x" * (MAX_OBJECT_BYTES - 1)}}
    assert oversized_objects([cm]) and oversized_objects([ok]) == []


# ------------------------------------------------------------------ control 2: the real render path

def test_a_real_render_with_an_oversized_env_value_is_flagged(tmp_path):
    # keycloak.auth.adminPassword lands in the realm-reconcile Job's container env as a literal value, so the
    # checker is proven to see what a real helm render produces, not only a synthetic document.
    probe = "KC_ADMIN_PASSWORD"  # keycloak.auth.adminPassword is a literal env value of the realm-reconcile Job
    probe_values = tmp_path / "probe-values.yaml"  # a file: 140 kB would overflow the Windows command line
    probe_values.write_text(yaml.safe_dump({"keycloak": {"auth": {"adminPassword": "x" * 140000}}}), encoding="utf-8")
    docs = _render("-f", str(_SANDBOX), "-f", str(probe_values))
    hits = [m for m in oversized(docs) if f"env[{probe}]" in m]
    assert hits, "the render path does not reach the checker: an oversized env value went unflagged"
    assert all("140000 bytes" in m for m in hits), hits
    # and without it the same render is clean, so the flag is the probe's and nothing else's
    assert not oversized(_render("-f", str(_SANDBOX)))


def test_report_the_largest_rendered_values():
    # not an assertion on a number: it prints the figures a reviewer asks for (pytest -s)
    for name, (extra, upgrade) in sorted(_CASES.items()):
        a, e = largest(_render(*extra, upgrade=upgrade))
        print(f"{name}: largest arg {a} bytes, largest env value {e} bytes")
        assert a <= MAX_ARG_STRLEN and e <= MAX_ARG_STRLEN
