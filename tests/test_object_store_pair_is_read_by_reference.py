"""THE CHART HOLDS NO OBJECT-STORE CREDENTIAL AS A VALUE: it reads Secrets by reference.

The store pair used to be literals in values.yaml, values-sandbox.yaml and two templates, copied
into a ConfigMap and into env maps. Now:

* every consumer gets MINIO_/S3_/AWS_ credentials by `secretKeyRef` to the CONSUMER Secret;
* only the bucket-init job reads the ADMIN (root) Secret;
* a hook creates the consumer Secret ONLY IF ABSENT and never replaces it;
* an env map that still sets a MINIO_/S3_ key is refused at render.

NOTHING HERE WRITES A RENDER TO DISK (renders hold `kind: Secret`) and NOTHING PRINTS A VALUE:
the old literals are read from the base commit inside the test, held in memory, and only ever
compared; failure messages carry a count or a location, never the string.

Run: uv run pytest tests/test_object_store_pair_is_read_by_reference.py -v
"""
from __future__ import annotations

import contextlib
import fnmatch
import io
import base64
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_BASE = "bc6c9a9b"  # the commit before this change: the literals are still in its files
_SANDBOX = ["-f", f"{_CHART}/values-sandbox.yaml"]
_ADMIN = ["--set", "objectStore.adminSecret.name=a"]
_CONSUMER = "t-object-store"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

# A credential env name: the three prefixes, and a name that carries a key or a secret.
_CRED = re.compile(r"^(MINIO|S3|AWS)_(ACCESS_KEY|SECRET_KEY|ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)$")
_SIX = ["MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "S3_ACCESS_KEY", "S3_SECRET_KEY",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]


def _run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(_REPO), timeout=300,
    )


def _render(*extra: str) -> str:
    """Render, failing with helm's own error: an empty render would pass every absence test."""
    r = _run(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _docs(text: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(text) if d]


def _specs(docs: list[dict]):
    for d in docs:
        kind = d.get("kind")
        if kind == "CronJob":
            yield d, d["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        elif kind in ("Deployment", "StatefulSet", "Job", "DaemonSet"):
            yield d, d["spec"]["template"]["spec"]
        elif kind == "Pod":
            yield d, d["spec"]


def _containers(spec: dict):
    return list(spec.get("containers") or []) + list(spec.get("initContainers") or [])


@pytest.fixture(scope="module")
def sandbox_text() -> str:
    return _render(*_SANDBOX)


@pytest.fixture(scope="module")
def sandbox_docs(sandbox_text: str) -> list[dict]:
    return _docs(sandbox_text)


# ── (a) census: every credential env is a secretKeyRef ───────────────────────

def test_no_credential_env_is_a_literal_and_each_reads_the_consumer_secret(sandbox_docs):
    seen = 0
    bad: list[str] = []
    for d, spec in _specs(sandbox_docs):
        for c in _containers(spec):
            for e in c.get("env") or []:
                n = e["name"]
                if _CRED.match(n):
                    seen += 1
                    ref = (e.get("valueFrom") or {}).get("secretKeyRef")
                    if "value" in e or not ref or ref["name"] != _CONSUMER:
                        bad.append(f"{d['kind']}/{d['metadata']['name']}:{c['name']}:{n}")
                if n.startswith("MC_HOST") and "value" in e:
                    bad.append(f"{d['kind']}/{d['metadata']['name']}:{c['name']}:{n}")
    assert not bad, f"credential env that is a literal or reads another Secret: {bad}"
    assert seen >= 30, f"only {seen} credential env entries: the census is too thin"


def test_bucket_init_reads_the_admin_secret_by_reference(sandbox_docs):
    jobs = [(d, s) for d, s in _specs(sandbox_docs) if d["metadata"]["name"] == "t-minio-bucket-init"]
    assert len(jobs) == 1
    env = {e["name"]: e for c in _containers(jobs[0][1]) for e in c["env"]}
    for n in ("STORE_ADMIN_KEY", "STORE_ADMIN_SECRET"):
        ref = env[n]["valueFrom"]["secretKeyRef"]
        assert ref["name"] == "iagent-object-store-admin" and "value" not in env[n]
    for n in ("CONSUMER_ACCESS_KEY", "CONSUMER_SECRET_KEY"):
        assert env[n]["valueFrom"]["secretKeyRef"]["name"] == _CONSUMER


def test_no_configmap_carries_a_credential_key(sandbox_docs):
    cms = [d for d in sandbox_docs if d["kind"] == "ConfigMap"]
    assert len(cms) >= 5, "census too thin"
    bad = [f"{d['metadata']['name']}:{k}" for d in cms for k in (d.get("data") or {}) if _CRED.match(k)]
    assert not bad, f"credential keys in ConfigMap data: {bad}"
    assert any(d["metadata"]["name"] == "t-config" for d in cms), "the shared ConfigMap is missing"


def test_every_envfrom_config_container_also_gets_the_pair(sandbox_docs):
    """Every container that envFroms the shared ConfigMap (except third-party electric) names the six."""
    checked = 0
    missing: list[str] = []
    for d, spec in _specs(sandbox_docs):
        for c in _containers(spec):
            cm = [f for f in (c.get("envFrom") or []) if (f.get("configMapRef") or {}).get("name") == "t-config"]
            if not cm or "electric" in d["metadata"]["name"]:
                continue
            checked += 1
            names = {e["name"] for e in c.get("env") or []}
            if not set(_SIX) <= names:
                missing.append(f"{d['metadata']['name']}:{c['name']}")
    assert not missing, f"containers on the shared ConfigMap without the store pair: {missing}"
    assert checked >= 12, f"only {checked} containers checked"


# ── (b) the old literals are gone (with a control: they WERE in the base) ────

def _base_file(path: str) -> str:
    r = subprocess.run(["git", "show", f"{_BASE}:{path}"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(_REPO), timeout=60)
    assert r.returncode == 0, f"cannot read {path} at the base commit"
    return r.stdout


def _old_literals() -> dict[str, str]:
    """name -> value, held in memory only; names are locations, never the value."""
    out: dict[str, str] = {}
    vals = yaml.safe_load(_base_file(f"{_CHART}/values.yaml"))
    sand = yaml.safe_load(_base_file(f"{_CHART}/values-sandbox.yaml"))
    mbi = vals["minioBucketInit"]
    out["values.minioBucketInit.accessKey"] = mbi["accessKey"]
    out["values.minioBucketInit.secretKey"] = mbi["secretKey"]
    for dep, blk in vals["userDeployments"].items():
        for part in ("codeLocation", "broker"):
            env = ((blk or {}).get(part) or {}).get("env") or {}
            for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
                if k in env:
                    out[f"values.userDeployments.{dep}.{part}.{k}"] = env[k]
    for blk in ("agentFleet", "cortexBff"):
        env = (sand.get(blk) or {}).get("env") or {}
        for k in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"):
            if k in env:
                out[f"sandbox.{blk}.{k}"] = env[k]
    broker = _base_file(f"{_CHART}/templates/domain-broker.yaml")
    for k in ("s3AccessKey", "s3SecretKey"):
        m = re.search(rf'{k}\s*\|\s*default\s*"([^"]+)"', broker)
        assert m, f"the base domain-broker no longer has the {k} default (test is stale)"
        out[f"template.domain-broker.{k}"] = m.group(1)
    return out


def test_the_old_literals_are_in_the_base_and_absent_from_the_render(sandbox_text):
    lits = _old_literals()
    assert len(lits) >= 12, f"only {len(lits)} old literals recovered: the census is too thin"
    assert all(len(v) >= 6 for v in lits.values()), "a recovered literal is too short to search for"

    # CONTROL: the base commit's files do contain every one of them.
    base_text = "\n".join(_base_file(f"{_CHART}/{p}") for p in
                          ("values.yaml", "values-sandbox.yaml", "templates/domain-broker.yaml"))
    not_in_base = [k for k, v in lits.items() if v not in base_text]
    assert not not_in_base, f"control failed: not found in the base files: {not_in_base}"

    # THE CLAIM: none is in a render (compared in memory; only the location is named).
    present = [k for k, v in lits.items() if v in sandbox_text]
    assert not present, f"old literal still rendered at: {present}"

    # The chart's own files no longer contain them either.
    now = "\n".join((_REPO / _CHART / p).read_text(encoding="utf-8") for p in
                    ("values.yaml", "values-sandbox.yaml", "templates/domain-broker.yaml"))
    in_files = [k for k, v in lits.items() if v in now]
    assert not in_files, f"old literal still in a chart file at: {in_files}"


# ── (c) the hook ─────────────────────────────────────────────────────────────

def _hook_docs(docs: list[dict]) -> list[dict]:
    return [d for d in docs if d["metadata"]["name"] == "t-object-store-secret"]


def test_the_hook_renders_when_the_consumer_secret_is_unnamed(sandbox_docs):
    kinds = sorted(d["kind"] for d in _hook_docs(sandbox_docs))
    assert kinds == ["Job", "Role", "RoleBinding", "ServiceAccount"]


def test_the_hook_does_not_render_when_the_consumer_secret_is_named():
    docs = _docs(_render(*_SANDBOX, *_ADMIN, "--set", "objectStore.consumerSecret.name=mine"))
    assert _hook_docs(docs) == []
    # control: it is the name that decided, and the consumers now read `mine`
    refs = {e["valueFrom"]["secretKeyRef"]["name"]
            for _, s in _specs(docs) for c in _containers(s) for e in c.get("env") or []
            if _CRED.match(e["name"])}
    assert refs == {"mine"}


def test_the_hook_weights_and_policy(sandbox_docs):
    hook = _hook_docs(sandbox_docs)
    bucket = next(d for d in sandbox_docs if d["metadata"]["name"] == "t-minio-bucket-init")
    bw = int(bucket["metadata"]["annotations"]["helm.sh/hook-weight"])
    for d in hook:
        a = d["metadata"]["annotations"]
        assert a["helm.sh/hook"] == "pre-install,pre-upgrade"
        assert a["helm.sh/hook-delete-policy"] == "before-hook-creation"
    job = next(d for d in hook if d["kind"] == "Job")
    assert int(job["metadata"]["annotations"]["helm.sh/hook-weight"]) < bw
    for d in hook:
        if d["kind"] != "Job":
            assert int(d["metadata"]["annotations"]["helm.sh/hook-weight"]) < int(
                job["metadata"]["annotations"]["helm.sh/hook-weight"])


def _script(docs: list[dict]) -> str:
    job = next(d for d in _hook_docs(docs) if d["kind"] == "Job")
    return job["spec"]["template"]["spec"]["containers"][0]["command"][2]


def test_the_script_generates_nothing_at_render_and_the_role_restricts_get(sandbox_docs, sandbox_text):
    assert "randAlphaNum" not in _script(sandbox_docs)
    assert "randAlphaNum" not in sandbox_text
    for p in (_REPO / _CHART / "templates").glob("*.yaml"):
        t = re.sub(r"\{\{-?\s*/\*.*?\*/\s*-?\}\}", "", p.read_text(encoding="utf-8"), flags=re.S)
        assert "randAlphaNum" not in t, p.name
        assert not re.search(r"lookup\s+\"", t), p.name
    role = next(d for d in _hook_docs(sandbox_docs) if d["kind"] == "Role")
    get = [r for r in role["rules"] if "get" in r["verbs"]]
    assert len(get) == 1 and get[0]["resourceNames"] == [_CONSUMER]
    create = [r for r in role["rules"] if "create" in r["verbs"]]
    assert len(create) == 1 and not create[0].get("resourceNames") and create[0]["verbs"] == ["create"]
    ctr = next(d for d in _hook_docs(sandbox_docs) if d["kind"] == "Job")["spec"]["template"]["spec"]["containers"][0]
    sc = ctr["securityContext"]
    assert sc["runAsNonRoot"] and sc["readOnlyRootFilesystem"] and sc["allowPrivilegeEscalation"] is False
    assert sc["capabilities"]["drop"] == ["ALL"]


# ── (d) the refusals, each with a control differing only in the refused field ─

@pytest.mark.parametrize("path,key", [
    ("agentFleet.env", "MINIO_ACCESS_KEY"),
    ("agentFleet.env", "S3_SECRET_KEY"),
    ("agentFleet.env", "AWS_ACCESS_KEY_ID"),
    ("cortexBff.env", "AWS_SECRET_ACCESS_KEY"),
    ("userDeployments.pub-tools.broker.env", "AWS_ACCESS_KEY_ID"),
    ("cortexBff.env", "MINIO_SECRET_KEY"),
    ("userDeployments.dag-tools.codeLocation.env", "S3_ACCESS_KEY"),
])
def test_an_env_map_with_a_store_key_is_refused_and_its_control_renders(path, key):
    refused = _run(*_SANDBOX, *_ADMIN, "--set", f"{path}.{key}=x")
    assert refused.returncode != 0
    assert key in refused.stderr and "objectStore.consumerSecret" in refused.stderr
    assert "x" != refused.stderr.strip()  # not a vacuous message
    control = _run(*_SANDBOX, *_ADMIN, "--set", f"{path}.MINIO_REGION=x")
    assert control.returncode == 0, control.stderr[-400:]


def test_bucket_init_with_no_admin_secret_is_refused_and_its_control_renders():
    refused = _run(*_SANDBOX, "--set", "objectStore.adminSecret.name=")
    assert refused.returncode != 0
    assert "objectStore.adminSecret.name" in refused.stderr
    assert _run(*_SANDBOX).returncode == 0  # control: only the admin name differs
    # and with no store configured and the job off, it renders (nothing to refuse)
    assert _run(*_SANDBOX, "--set", "objectStore.adminSecret.name=",
                "--set", "minioBucketInit.enabled=false").returncode == 0


@pytest.mark.parametrize("flag", ["minioBucketInit.enabled=false", "objectStore.consumerUser.create=false"])
def test_a_generated_pair_with_no_store_user_is_refused_and_its_control_renders(flag):
    refused = _run(*_SANDBOX, "--set", flag)
    assert refused.returncode != 0
    assert "consumerSecret.name" in refused.stderr and "consumerUser.create" in refused.stderr
    # control 1: the same flag renders once the deployment names the pair
    assert _run(*_SANDBOX, "--set", flag, "--set", "objectStore.consumerSecret.name=mine").returncode == 0
    # control 2: without the flag it renders
    assert _run(*_SANDBOX).returncode == 0


def test_a_bare_render_configures_no_store_and_renders_neither_hook_nor_refusal():
    docs = _docs(_render())
    assert _hook_docs(docs) == []
    assert not [d for d, _ in _specs(docs) if d["metadata"]["name"] == "t-minio-bucket-init"]
    refs = {e["valueFrom"]["secretKeyRef"]["name"]
            for _, s in _specs(docs) for c in _containers(s) for e in c.get("env") or []
            if _CRED.match(e["name"])}
    assert refs == {_CONSUMER}
    assert len([d for d in docs if d["kind"] == "Deployment"]) >= 5  # control: a real render



def _optional_flags(docs: list[dict]) -> set:
    return {bool(e["valueFrom"]["secretKeyRef"].get("optional"))
            for _, s in _specs(docs) for c in _containers(s) for e in c.get("env") or []
            if _CRED.match(e["name"])}


@pytest.mark.parametrize("case,extra,want", [
    # nothing names or creates the pair (no store): pods start without the keys, as before
    ("bare", [], {True}),
    # the hook creates the pair: a missing Secret is a defect and must stop the pod
    ("generated", _SANDBOX, {False}),
    # the deployment names the pair: a misspelt name must stop the pod, not start it keyless
    ("named", [*_SANDBOX, "--set", "objectStore.consumerSecret.name=named-pair"], {False}),
])
def test_a_consumer_ref_is_optional_only_when_nothing_supplies_the_pair(case, extra, want):
    flags = _optional_flags(_docs(_render(*extra)))
    assert flags == want, f"{case}: optional flags on the consumer refs are {flags}, expected {want}"

# ── (e) the script's create-if-absent logic, against a fake API ──────────────

def _load_ensure(docs: list[dict]):
    ns: dict = {"__name__": "object_store_secret_script"}
    exec(compile(_script(docs), "<hook-script>", "exec"), ns)  # noqa: S102 - the chart's own script
    return ns["ensure"]


class _FakeApi:
    def __init__(self, get_status: int, data: dict | None):
        self.get_status, self.data, self.writes = get_status, data, []

    def __call__(self, method, path, body=None):
        if method == "GET":
            return self.get_status, ({"data": self.data} if self.data is not None else None)
        self.writes.append((method, path, body))
        return 201, body


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _call(ensure, api):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ensure(api, "ns", "sec", "access-key", "secret-key")
    return rc, buf.getvalue()


def test_absent_secret_is_created_once_with_the_right_shape_and_nothing_is_printed(sandbox_docs):
    ensure = _load_ensure(sandbox_docs)
    api = _FakeApi(404, None)
    rc, out = _call(ensure, api)
    assert rc == 0 and out.strip() == "created"
    assert len(api.writes) == 1 and api.writes[0][0] == "POST"
    body = api.writes[0][2]
    assert body["type"] == "Opaque"
    assert body["metadata"]["annotations"] == {"helm.sh/resource-policy": "keep"}
    assert not body["metadata"].get("labels")
    access = base64.b64decode(body["data"]["access-key"]).decode()
    secret = base64.b64decode(body["data"]["secret-key"]).decode()
    assert re.fullmatch(r"[A-Z0-9]{20}", access) and re.fullmatch(r"[A-Za-z0-9]{40}", secret)
    assert access not in out and secret not in out and _b64(access) not in out


def test_present_secret_with_both_keys_is_left_alone(sandbox_docs):
    ensure = _load_ensure(sandbox_docs)
    api = _FakeApi(200, {"access-key": _b64("AAAA"), "secret-key": _b64("BBBB")})
    rc, out = _call(ensure, api)
    assert rc == 0 and out.strip() == "present" and api.writes == []
    assert "AAAA" not in out and "BBBB" not in out


@pytest.mark.parametrize("empty", ["access-key", "secret-key"])
def test_present_secret_with_an_empty_or_missing_key_is_refused_and_never_written(sandbox_docs, empty):
    ensure = _load_ensure(sandbox_docs)
    data = {"access-key": _b64("AAAA"), "secret-key": _b64("BBBB")}
    data[empty] = ""
    api = _FakeApi(200, data)
    rc, out = _call(ensure, api)
    assert rc != 0 and empty in out and api.writes == []
    assert "AAAA" not in out and "BBBB" not in out
    # missing (not just empty) is the same refusal
    del data[empty]
    rc, out = _call(ensure, _FakeApi(200, data))
    assert rc != 0 and empty in out


def test_an_api_error_is_a_refusal_not_a_create(sandbox_docs):
    ensure = _load_ensure(sandbox_docs)
    api = _FakeApi(403, None)
    rc, _ = _call(ensure, api)
    assert rc != 0 and api.writes == []


# ── (g) every bucket a consumer reads is in the consumer policy ───────────────

_ARN = re.compile(r"arn:aws:s3:::([A-Za-z0-9._*-]+)")
_S3URL = re.compile(r"s3a?://([A-Za-z0-9._*-]+)")
_ENV_GET = re.compile(
    r"""os\.(?:environ\.get|getenv)\(\s*["']([A-Z0-9_]*BUCKET[A-Z0-9_]*)["']\s*,\s*["']([^"']+)["']""")
_CONST = re.compile(r"""^_([A-Z0-9_]*BUCKET[A-Z0-9_]*)\s*=\s*["']([^"']+)["']""", re.M)
_SKIP_DIRS = {"__pycache__", ".venv", "node_modules"}


def _policy_buckets(text: str) -> set[str]:
    """The bucket names in the Resource arns of the rendered bucket-init script."""
    out: set[str] = set()
    for d in _docs(text):
        if d.get("kind") != "Job":
            continue
        for c in _containers(d["spec"]["template"]["spec"]):
            script = "\n".join(str(x) for x in (c.get("command") or []) + (c.get("args") or []))
            if "policy create" in script:
                out |= set(_ARN.findall(script))
    return out


def _rendered_census(text: str) -> dict[str, set[str]]:
    """name -> where, from ConfigMap data and container env literals."""
    found: dict[str, set[str]] = {}

    def add(name: str, where: str) -> None:
        name = name.strip()
        if name:
            found.setdefault(name, set()).add(where)

    def scan(key: str, val, where: str) -> None:
        if not isinstance(val, str):
            return
        for m in _S3URL.findall(val):
            add(m, f"{where}:{key}(s3://)")
        if "BUCKET" in key and "PREFIX" not in key and not val.startswith(("s3://", "s3a://")):
            for part in val.split(","):
                add(part, f"{where}:{key}")

    docs = _docs(text)
    for d in docs:
        if d.get("kind") == "ConfigMap":
            for k, v in (d.get("data") or {}).items():
                scan(k, v, f"ConfigMap/{d['metadata']['name']}")
    for d, spec in _specs(docs):
        for c in _containers(spec):
            for e in c.get("env") or []:
                scan(e.get("name", ""), e.get("value"), f"{d['kind']}/{d['metadata']['name']}")
    return found


def _code_census() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for top in ("src", "agent_fleet"):
        for p in (_REPO / top).rglob("*.py"):
            if _SKIP_DIRS & set(p.parts):
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            rel = p.relative_to(_REPO).as_posix()
            for key, default in _ENV_GET.findall(src):
                if "PREFIX" in key:
                    continue
                for part in default.split(","):
                    found.setdefault(part.strip(), set()).add(f"{rel}:{key}(default)")
            for name, lit in _CONST.findall(src):
                n = lit + "*" if "PREFIX" in name else lit
                found.setdefault(n, set()).add(f"{rel}:_{name}")
    return found


def _census(text: str) -> dict[str, set[str]]:
    out = _rendered_census(text)
    for k, v in _code_census().items():
        out.setdefault(k, set()).update(v)
    return out


def _covered(name: str, policy: set[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(p, name) for p in policy)


def _uncovered(text: str) -> dict[str, set[str]]:
    policy = _policy_buckets(text)
    assert policy, "no bucket arn found in the rendered bucket-init script"
    return {n: w for n, w in _census(text).items() if not _covered(n, policy)}


def test_every_bucket_a_consumer_reads_is_in_the_consumer_policy(sandbox_text):
    census = _census(sandbox_text)
    # Control A: the census saw what it must see
    for must in ("processing-artifacts", "doc-pages", "ontologies", "publog-lake", "dag-lake"):
        assert must in census, f"census missed {must}: {sorted(census)}"
    assert len(census) >= 5
    missing = _uncovered(sandbox_text)
    assert not missing, "buckets read by consumers but absent from the policy: " + "; ".join(
        f"{n} <- {sorted(w)}" for n, w in sorted(missing.items()))


@pytest.mark.parametrize("override", ["null"])
def test_the_policy_check_fails_when_the_extra_buckets_are_dropped(override):
    """Control B: the same check, on a render without consumerUser.buckets, must fail naming the extras."""
    text = _render(*_SANDBOX, "--set", f"objectStore.consumerUser.buckets={override}")
    missing = _uncovered(text)
    assert "processing-artifacts" in missing, sorted(missing)
