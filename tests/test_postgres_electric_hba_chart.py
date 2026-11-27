"""Electric's role confined to the projections database in pg_hba (postgresql.electricHba.enabled, default OFF).

The rendered pg_hba is EVALUATED here by a small first-match matcher (PostgreSQL's rule: the first line whose connection
type, database, user and address all match decides; no match refuses). The grid is every combination of connection kind,
database, user and address class, for BOTH image styles. Seals:

1. OFF: no ConfigMap, no `hba_file` arg, no volume, no checksum annotation: the StatefulSet is as before.
2. ON: Electric's role is admitted on the projections database and nowhere else: not another database, not the
   `replication` keyword, not the local socket. (A logical replication connection names its database, so it is the
   database line that admits Electric's slot on the projections database; the `replication` keyword matches physical
   streams only.) The Electric lines are the same for both image styles.
3. EVERY OTHER ROLE keeps what the assumed image default gives it: the decision for every non-Electric cell equals the
   decision of the default lines alone, over the whole grid. The default lines are typed ONCE per style here, as the
   assumption the chart states (neither is readable from the chart; the Bitnami one is inferred from its scripts'
   documented behaviour), and compared as whole decisions.
4. The StatefulSet delivers the file: the library image by `hba_file=` naming a file in a mount of the rendered
   ConfigMap; Bitnami by mounting it in /bitnami/postgresql/conf (its scripts copy it; inferred). The pod template
   carries a checksum that changes when the role changes.
5. The render REFUSES: Bitnami before the live read is confirmed, a missing electric.db.enabled or electric.enabled, an
   external Postgres, an unknown style, a bad role, an unknown auth method.
6. `defaultLines` (the rows read from the live server) replaces the assumed defaults.
"""
from __future__ import annotations

import ipaddress
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_VALUES = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
_ROLE = _VALUES["electric"]["db"]["role"]
_PROJ = _VALUES["postgresql"]["auth"]["database"]
_METHOD = _VALUES["postgresql"]["electricHba"]["authMethod"]
_REMOTE = "192.0.2.7"   # a documentation address (RFC 5737): a remote client
_COMMON = ["--set", "electric.db.enabled=true", "--set", "postgresql.electricHba.enabled=true"]
_ON = {
    "postgres": [*_COMMON, "--set", "postgresql.imageStyle=postgres"],
    "bitnami": [*_COMMON, "--set", "postgresql.imageStyle=bitnami",
                "--set", "postgresql.electricHba.bitnamiDefaultsConfirmed=true"],
}

# THE ASSUMPTIONS, typed once per style: the default pg_hba of the image (inferred, not read from the chart). Whole
# lines, compared as decisions.
_DEFAULT = {
    "postgres": f"""
local   all    all    trust
host    all    all    127.0.0.1/32    trust
host    all    all    ::1/128    trust
local   replication    all    trust
host    replication    all    127.0.0.1/32    trust
host    replication    all    ::1/128    trust
host    all    all    all    {_METHOD}
""",
    "bitnami": f"""
local   all    all    {_METHOD}
host    all    all    127.0.0.1/32    {_METHOD}
host    all    all    ::1/128    {_METHOD}
local   replication    all    {_METHOD}
host    replication    all    127.0.0.1/32    {_METHOD}
host    replication    all    ::1/128    {_METHOD}
host    all    all    0.0.0.0/0    {_METHOD}
host    all    all    ::/0    {_METHOD}
""",
}
_STYLES = ["postgres", "bitnami"]


def _helm(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "r", str(_CHART), *extra], capture_output=True, text=True,
                          cwd=str(_REPO), timeout=300)


def _render(*extra: str) -> list[dict]:
    r = _helm(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _rules(text: str) -> list[list[str]]:
    return [ln.split() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _decide(rules, ctype: str, db: str, user: str, addr: str | None, physical: bool) -> str | None:
    """First-match decision. `physical` = a physical replication stream (matches the `replication` keyword only); a
    logical one names its database and matches on it like any connection."""
    for r in rules:
        t, rdb, ruser = r[0], r[1], r[2]
        if t != ctype:
            continue
        if not ((rdb == "all" and not physical) or (rdb == "replication" and physical)
                or (rdb == db and not physical)):
            continue
        if ruser not in ("all", user):
            continue
        if t == "host":
            a, method = r[3], r[4]
            if a != "all":
                ip, net = ipaddress.ip_address(addr), ipaddress.ip_network(a)
                if ip.version != net.version or ip not in net:
                    continue
        else:
            method = r[3]
        return method
    return None


_CONNS = [("local", None), ("host", "127.0.0.1"), ("host", "::1"), ("host", _REMOTE), ("host", "2001:db8::7")]
_DBS = [_PROJ, "iagent_other", "postgres"]
_USERS = [_ROLE, "iagent", "postgres", "someone_else"]


def _grid():
    for ctype, addr in _CONNS:
        for db in _DBS:
            for user in _USERS:
                for physical in (False, True):
                    yield ctype, db, user, addr, physical


def _hba_text(docs) -> str:
    cm = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "r-postgresql-hba")
    return cm["data"]["pg_hba.conf"]


def _sts(docs) -> dict:
    return next(d for d in docs if d.get("kind") == "StatefulSet" and d["metadata"]["name"] == "r-postgresql")


@pytest.mark.parametrize("style", _STYLES)
def test_off_changes_nothing(style):
    docs = _render("--set", f"postgresql.imageStyle={style}")
    assert not [d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "r-postgresql-hba"]
    pod = _sts(docs)["spec"]["template"]
    assert "hba_file" not in yaml.safe_dump(pod)
    assert not pod["spec"].get("volumes")
    assert "checksum/pg-hba" not in (pod["metadata"].get("annotations") or {})
    assert not [m for m in pod["spec"]["containers"][0]["volumeMounts"] if m["name"] == "pg-hba"]


@pytest.mark.parametrize("style", _STYLES)
def test_on_admits_electrics_role_on_the_projections_database_only(style):
    rules = _rules(_hba_text(_render(*_ON[style])))
    assert _decide(rules, "host", _PROJ, _ROLE, _REMOTE, False) == _METHOD
    for db in ("iagent_other", "postgres"):
        assert _decide(rules, "host", db, _ROLE, _REMOTE, False) == "reject"
    assert _decide(rules, "host", _PROJ, _ROLE, _REMOTE, True) == "reject"      # the `replication` keyword
    assert _decide(rules, "host", _PROJ, _ROLE, "127.0.0.1", True) == "reject"  # even from loopback
    assert _decide(rules, "local", _PROJ, _ROLE, None, False) == "reject"
    assert _decide(rules, "local", _PROJ, _ROLE, None, True) == "reject"


@pytest.mark.parametrize("style", _STYLES)
def test_every_other_role_keeps_the_assumed_image_default_over_the_whole_grid(style):
    rendered = _rules(_hba_text(_render(*_ON[style])))
    default = _rules(_DEFAULT[style])
    cells = [c for c in _grid() if c[2] != _ROLE]
    assert len(cells) >= 90, "the grid shrank: the census is inert"
    wrong = [c for c in cells if _decide(rendered, *c) != _decide(default, *c)]
    assert not wrong, f"{len(wrong)} non-Electric cells differ from the default, first: {wrong[0]}"


@pytest.mark.parametrize("style", _STYLES)
def test_the_matcher_has_a_control_it_can_tell_apart(style):
    # Control: the default alone DOES admit Electric's role everywhere, so the grid can see a missing restriction.
    default = _rules(_DEFAULT[style])
    assert _decide(default, "host", "iagent_other", _ROLE, _REMOTE, False) == _METHOD
    assert _decide(default, "host", "x", "iagent", _REMOTE, True) is None


def test_the_library_image_reads_the_rendered_file_through_hba_file():
    docs = _render(*_ON["postgres"])
    pod = _sts(docs)["spec"]["template"]
    c = pod["spec"]["containers"][0]
    arg = next(a for a in c["args"] if a.startswith("hba_file="))
    path = arg.split("=", 1)[1]
    mount = next(m for m in c["volumeMounts"] if path.startswith(m["mountPath"] + "/"))
    vol = next(v for v in pod["spec"]["volumes"] if v["name"] == mount["name"])
    assert vol["configMap"]["name"] == "r-postgresql-hba"
    assert path.rsplit("/", 1)[1] == "pg_hba.conf"
    a = pod["metadata"]["annotations"]["checksum/pg-hba"]
    b = _sts(_render(*_ON["postgres"], "--set", "electric.db.role=another_role"))["spec"]["template"]["metadata"][
        "annotations"]["checksum/pg-hba"]
    assert a != b


def test_bitnami_mounts_the_rendered_file_where_its_scripts_read_a_custom_one():
    docs = _render(*_ON["bitnami"])
    pod = _sts(docs)["spec"]["template"]
    c = pod["spec"]["containers"][0]
    assert "hba_file" not in yaml.safe_dump(pod)      # bitnami ignores command args
    mount = next(m for m in c["volumeMounts"] if m["name"] == "pg-hba")
    assert mount["mountPath"] == "/bitnami/postgresql/conf" and mount["readOnly"] is True
    vol = next(v for v in pod["spec"]["volumes"] if v["name"] == "pg-hba")
    assert vol["configMap"]["name"] == "r-postgresql-hba"
    assert "pg_hba.conf" in next(d for d in docs if d.get("kind") == "ConfigMap"
                                 and d["metadata"]["name"] == "r-postgresql-hba")["data"]
    assert pod["metadata"]["annotations"]["checksum/pg-hba"]


@pytest.mark.parametrize("style", _STYLES)
def test_default_lines_read_from_the_live_server_replace_the_assumed_ones(style):
    rows = "local   all    all    peer\nhost    all    all    all    scram-sha-256"
    text = _hba_text(_render(*_ON[style], "--set-string", f"postgresql.electricHba.defaultLines={rows}"))
    rules = _rules(text)
    assert _decide(rules, "local", "x", "iagent", None, False) == "peer"
    assert _decide(rules, "host", "x", "iagent", "127.0.0.1", False) == "scram-sha-256"
    assert _decide(rules, "host", _PROJ, _ROLE, _REMOTE, False) == _METHOD      # Electric's lines are unchanged
    assert _decide(rules, "host", "x", _ROLE, _REMOTE, False) == "reject"


@pytest.mark.parametrize("style", _STYLES)
def test_on_adds_no_image(style):
    # The flag adds a ConfigMap and no pod, so scripts/values-every-workload.yaml may carry it without a new image.
    def images(docs):
        out = []
        for d in docs:
            s = d.get("spec", {}).get("template", {}).get("spec", {})
            out += [c["image"] for c in s.get("containers", []) + s.get("initContainers", [])]
        return sorted(out)
    base = ["--set", "electric.db.enabled=true", "--set", f"postgresql.imageStyle={style}"]
    off, on = images(_render(*base)), images(_render(*_ON[style]))
    assert off and off == on
    assert len(_render(*_ON[style])) == len(_render(*base)) + 1   # exactly the ConfigMap


@pytest.mark.parametrize("extra,needle", [
    (["--set", "postgresql.electricHba.bitnamiDefaultsConfirmed=false"], "bitnamiDefaultsConfirmed"),
    (["--set", "electric.db.enabled=false"], "electric.db.enabled"),
    (["--set", "electric.enabled=false"], "electric.enabled"),
    (["--set", "postgresql.enabled=false"], "external Postgres"),
    (["--set", "postgresql.imageStyle=other"], "postgres or bitnami"),
    (["--set", "electric.db.role=Bad-Role"], "plain lower-case SQL identifier"),
    (["--set", "postgresql.electricHba.authMethod=trust"], "scram-sha-256 or md5"),
])
def test_the_render_refuses(extra, needle):
    r = _helm(*_ON["bitnami"], *extra)
    assert r.returncode != 0
    assert needle in r.stderr, r.stderr[-400:]
