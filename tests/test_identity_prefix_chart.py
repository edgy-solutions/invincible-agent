"""The identity prefix, chart half (docs/proposals/one-realm-many-instances-the-identity-prefix.md, RULED 2026-11-20).

Each test names the claim it defends. The renders are piped, never saved. MASTER is the chart as it was at
`_MASTER_SHA`, extracted with `git archive` into a temp tree; `IAGENT_CHART_UNDER_TEST` points the whole file at
another chart directory (the seals are run against the unfixed chart that way, to show they bite).

Run: uv run --frozen python -m pytest tests/test_identity_prefix_chart.py -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import io
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_UNDER_TEST = Path(os.environ.get("IAGENT_CHART_UNDER_TEST", str(_CHART)))
_MASTER_SHA = "0e58ed44"
_SANDBOX = ["-f", str(_CHART / "values-sandbox.yaml")]

pytestmark = pytest.mark.skipif(shutil.which("helm") is None or shutil.which("git") is None, reason="helm or git missing")

_AUD_ENV = ("BFF_JWT_ACCEPTED_AUDIENCES", "MESH_JWT_ACCEPTED_AUDIENCES", "GATEWAY_JWT_AUDIENCES")
_ISS_ENV = ("BFF_JWT_ACCEPTED_ISSUERS", "MESH_JWT_ACCEPTED_ISSUERS", "GATEWAY_JWT_ISSUERS")
_NO_AUD_KEYS = ["--set-json", "cortexBff.auth.acceptedAudiences=null", "--set-json", "cortexBff.auth.realmAudience=null"]
_T = ["--set-string", "identity.prefix=t-", "--set", "keycloak.realmObjects=external"]


def _s(path: str, value: str) -> list[str]:
    return ["--set-string", f"{path}={value}"]


def _j(path: str, value) -> list[str]:
    return ["--set-json", f"{path}={json.dumps(value)}"]


def _helm(chart: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "t", str(chart), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=300)


def _render(*args: str, chart: Path | None = None) -> str:
    r = _helm(chart or _UNDER_TEST, *args)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-1200:]}"
    return r.stdout


def _refused(*args: str) -> str:
    r = _helm(_UNDER_TEST, *args)
    assert r.returncode != 0, "expected the render to FAIL, but it succeeded"
    return r.stderr


@pytest.fixture(scope="module")
def master() -> Path:
    import tempfile

    out = subprocess.run(["git", "-C", str(_REPO), "archive", _MASTER_SHA, "helm/invincible-agent"], capture_output=True)
    assert out.returncode == 0, out.stderr.decode()[-500:]
    d = Path(tempfile.mkdtemp(prefix="master-chart-"))
    with tarfile.open(fileobj=io.BytesIO(out.stdout)) as t:
        t.extractall(d)
    yield d / "helm" / "invincible-agent"
    shutil.rmtree(d, ignore_errors=True)


def _docs(rendered: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(rendered) if d]


def _env_sites(rendered: str, names) -> dict[str, str]:
    """`<kind>/<name>/<container>/<ENV>` -> value, for every container env entry (and init container) named in `names`."""
    out: dict[str, str] = {}
    for d in _docs(rendered):
        spec = (d.get("spec") or {})
        tpl = (spec.get("template") or (spec.get("jobTemplate") or {}).get("spec", {}).get("template") or {})
        pod = tpl.get("spec") or {}
        for c in [*(pod.get("containers") or []), *(pod.get("initContainers") or [])]:
            for e in c.get("env") or []:
                if e.get("name") in names and "value" in e:
                    out[f"{d['kind']}/{d['metadata']['name']}/{c['name']}/{e['name']}"] = e["value"]
    return out


def _by_name(rendered: str, kind: str, suffix: str) -> dict:
    (d,) = [d for d in _docs(rendered) if d["kind"] == kind and d["metadata"]["name"].endswith(suffix)]
    return d


def _realm_import(rendered: str) -> dict:
    cm = _by_name(rendered, "ConfigMap", "-keycloak-realm")
    return json.loads(cm["data"]["realm-export.json"])


def _reconcile(rendered: str) -> tuple[str, dict]:
    script = _by_name(rendered, "ConfigMap", "realm-reconcile-script")["data"]["reconcile.sh"]
    bodies = _by_name(rendered, "Secret", "realm-reconcile-bodies")["stringData"]
    return script, bodies


# ---- the seals' site extractors: each returns {site: [values]}; the checkers name the offending site -----------------

def client_id_sites(rendered: str) -> dict[str, list[str]]:
    realm = _realm_import(rendered)
    script, bodies = _reconcile(rendered)
    sites = {
        "realm-import clients[].clientId": [c["clientId"] for c in realm["clients"]],
        "realm-import users[].clientRoles keys": [k for u in realm.get("users", []) for k in (u.get("clientRoles") or {})],
        "reconcile script CID=/SVCID=/PCID=": re.findall(r'^\s*(?:CID|SVCID|PCID)="([^"]+)"', script, re.M),
        "reconcile script ?clientId= lookups": re.findall(r'clients\?clientId=([A-Za-z0-9._-]+)"', script),
        "reconcile bodies clientId": [json.loads(v)["clientId"] for v in bodies.values() if v.startswith("{")],
        "cortex-ui VITE_KEYCLOAK_CLIENT_ID": list(_env_sites(rendered, ("VITE_KEYCLOAK_CLIENT_ID",)).values()),
    }
    sites = {k: [v for v in vs if v != "$CID" and not v.startswith("$")] for k, vs in sites.items()}
    return sites


def audience_list_sites(rendered: str) -> dict[str, str]:
    return _env_sites(rendered, _AUD_ENV)


def mapper_sites(rendered: str) -> dict[str, list[str]]:
    realm = _realm_import(rendered)
    script, bodies = _reconcile(rendered)
    found: dict[str, list[str]] = {"realm-import": [], "reconcile script": [], "reconcile bodies": []}

    def walk(node, bucket):
        if isinstance(node, dict):
            if node.get("name") == "audience-bff":
                bucket.append(node["config"]["included.custom.audience"])
            for v in node.values():
                walk(v, bucket)
        elif isinstance(node, list):
            for v in node:
                walk(v, bucket)

    walk(realm, found["realm-import"])
    for v in bodies.values():
        if v.startswith("{"):
            walk(json.loads(v), found["reconcile bodies"])
    found["reconcile script"] = re.findall(r'"included\.custom\.audience":\s*"([^"]+)"', script)
    return found


def check_client_ids(sites: dict[str, list[str]], prefix: str) -> None:
    for site, ids in sites.items():
        assert ids, f"site {site!r} rendered no client id (a vacuous check)"
        bad = [i for i in ids if not i.startswith(prefix)]
        assert not bad, f"site {site!r} carries a client id without the prefix {prefix!r}: {sorted(set(bad))}"


def check_audience_lists(sites: dict[str, str], aud: str) -> None:
    assert sites, "no accepted-audience env rendered (a vacuous check)"
    assert {s.rsplit("/", 1)[1] for s in sites} == set(_AUD_ENV), "an accepted-audience variable is not rendered anywhere"
    for site, v in sites.items():
        assert v == aud, f"site {site!r} serves the accepted list {v!r}, not exactly {aud!r}"


def check_mappers(sites: dict[str, list[str]], aud: str) -> None:
    for site, vs in sites.items():
        assert vs, f"mapper site {site!r} rendered no audience-bff mapper (a vacuous check)"
        assert set(vs) == {aud}, f"mapper site {site!r} stamps {sorted(set(vs))}, not exactly {aud!r}"


def check_no_bare_audience(rendered: str, prefix: str) -> None:
    script, bodies = _reconcile(rendered)
    realm = json.dumps(_realm_import(rendered))
    bare = re.compile(r"(?<![\w-])cortex-bff(?![\w-])")
    for site, text in (("reconcile script", script), ("reconcile bodies", json.dumps(bodies)), ("realm import", realm)):
        for line in text.splitlines() or [text]:
            if re.search(r"aud", line, re.I):
                assert not bare.search(line), f"site {site!r} holds a bare cortex-bff audience: {line.strip()[:160]}"
    for site, v in _env_sites(rendered, (*_AUD_ENV,)).items():
        assert not bare.search(v), f"site {site!r} holds a bare cortex-bff audience"


# ---- 1. the no-op, measured as one --------------------------------------------------------------------------------

def _line_diff(a: str, b: str) -> list[str]:
    import difflib

    return [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
            if not l.startswith(("---", "+++", "@@"))]


# The base chart's difference from master, pinned once and reused by tests/test_oidc_broker_chart.py (RULED 2026-11-20, 2 retirement):
# the shared ConfigMap gains this line, the audience variables go from empty to cortex-bff, and the audience-bff mapper renders.
PINNED_BASE_CONFIGMAP_ADDITIONS = ['+  IAGENT_IDENTITY_PREFIX: ""']
PINNED_BASE_AUDIENCE = "cortex-bff"
PINNED_BASE_MAPPER = "audience-bff"


def without_base_audience_mapper(realm: dict) -> dict:
    """The realm import with the pinned base mapper removed from every client, so it can be compared with master's."""
    import copy

    realm = copy.deepcopy(realm)
    for c in realm["clients"]:
        if "protocolMappers" in c:
            kept = [m for m in c["protocolMappers"] if m.get("name") != PINNED_BASE_MAPPER]
            if kept:
                c["protocolMappers"] = kept
            else:
                del c["protocolMappers"]  # master rendered no key at all for a client with no other mapper
    return realm


def test_an_empty_prefix_renders_byte_identical_to_master_for_the_overlay_that_sets_cortex_bff(master):
    """CLAIM: with an empty prefix the sandbox overlay (acceptedAudiences/realmAudience = cortex-bff) renders as master did,
    but for the one new line, the shared ConfigMap's IAGENT_IDENTITY_PREFIX: ""."""
    old = _render(*_SANDBOX, chart=master)
    new = _render(*_SANDBOX)
    assert _line_diff(old, new) == PINNED_BASE_CONFIGMAP_ADDITIONS


# ---- 2. the base chart is not a no-op, and its two differences are exactly these -------------------------------------

def test_the_base_chart_differs_from_master_by_exactly_the_audience_and_the_mapper(master):
    """CLAIM: the base render differs from master only in (1) accepted-audience variables empty -> cortex-bff and (2) the
    audience-bff mapper now rendering; it equals master rendered with those two values set, plus IAGENT_IDENTITY_PREFIX."""
    old = _render(chart=master)
    new = _render()
    old_aud = _env_sites(old, _AUD_ENV)
    assert old_aud and set(old_aud.values()) == {""}, "master's base is expected to serve EMPTY audience lists"
    assert set(_env_sites(new, _AUD_ENV).values()) == {"cortex-bff"}
    assert "audience-bff" not in old, "master's base renders no audience mapper"
    assert "audience-bff" in new
    twin = _render(*_j("cortexBff.auth.acceptedAudiences", ["cortex-bff"]), *_s("cortexBff.auth.realmAudience", "cortex-bff"),
                   chart=master)
    assert _line_diff(twin, new) == PINNED_BASE_CONFIGMAP_ADDITIONS, "the base differs from master in more than the two named ways"


def test_the_base_still_refuses_every_token_through_the_empty_issuer_list():
    """CLAIM: deny-by-default is kept by acceptedIssuers: [] -- every issuer list is empty in the base render."""
    sites = _env_sites(_render(), _ISS_ENV)
    assert {s.rsplit("/", 1)[1] for s in sites} == set(_ISS_ENV)
    assert set(sites.values()) == {""}, "the base chart must serve no accepted issuer"


# ---- 3. prefix t- ---------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def prefixed() -> str:
    return _render(*_SANDBOX, *_T, *_NO_AUD_KEYS)


def test_every_rendered_client_id_starts_with_the_prefix(prefixed):
    """CLAIM: every client id the realm or the browser sees starts with t- (a broker's clientId is not one)."""
    check_client_ids(client_id_sites(prefixed), "t-")


def test_a_brokers_client_id_is_not_prefixed(prefixed):
    """CLAIM (4d): a broker's clientId is the id registered at the upstream provider; the prefix never reaches it."""
    brokers = ["--set-json", "keycloak.brokers.openddil.enabled=true", "--set-json", "keycloak.brokers.openddil.publicCA=true",
               "--set", "keycloak.brokers.openddil.existingSecret=x"]
    on = _render(*_SANDBOX, *_s("identity.prefix", "t-"), *_j("keycloak.realmOwner", True), *_NO_AUD_KEYS, *brokers)
    script, bodies = _reconcile(on)
    text = script + json.dumps(bodies)
    assert '"clientId":"iagent-broker"' in text.replace(" ", ""), "the control found no broker client id at all"
    assert "t-iagent-broker" not in text, "the broker's upstream client id was prefixed"


def test_every_accepted_audience_list_is_exactly_the_derived_audience(prefixed):
    """CLAIM: the BFF, the engines, the registrar and the central gateway each accept exactly [t-cortex-bff]."""
    check_audience_lists(audience_list_sites(prefixed), "t-cortex-bff")


def test_every_audience_bff_mapper_stamps_exactly_the_derived_audience(prefixed):
    """CLAIM: the realm import, the reconcile script and the bodies it applies stamp exactly t-cortex-bff."""
    check_mappers(mapper_sites(prefixed), "t-cortex-bff")


def test_no_rendered_value_holds_a_bare_cortex_bff_audience(prefixed):
    """CLAIM: no audience-bearing line or env value holds the unprefixed audience."""
    check_no_bare_audience(prefixed, "t-")


def test_the_shared_configmap_exports_the_prefix_to_every_pod(prefixed):
    """CLAIM: IAGENT_IDENTITY_PREFIX is in the shared ConfigMap, equal to the value."""
    (cm,) = [d for d in _docs(prefixed) if d["kind"] == "ConfigMap" and "IAGENT_IDENTITY_PREFIX" in d.get("data", {})]
    assert cm["data"]["IAGENT_IDENTITY_PREFIX"] == "t-"


# mutation controls (permanent): a checker fed one site with the prefix dropped fails NAMING that site
def test_mutation_controls_name_the_site_that_lost_the_prefix(prefixed):
    """CLAIM: each seal above bites: drop the prefix from one site of its part and it fails naming that site."""
    sites = client_id_sites(prefixed)
    for site in sites:
        mut = {k: ([i.removeprefix("t-") for i in v] if k == site else v) for k, v in sites.items()}
        with pytest.raises(AssertionError, match=re.escape(site)):
            check_client_ids(mut, "t-")
    lists = audience_list_sites(prefixed)
    for site in lists:
        with pytest.raises(AssertionError, match=re.escape(site)):
            check_audience_lists({**lists, site: "cortex-bff"}, "t-cortex-bff")
    maps = mapper_sites(prefixed)
    for site in maps:
        with pytest.raises(AssertionError, match=re.escape(site)):
            check_mappers({**maps, site: ["cortex-bff"]}, "t-cortex-bff")


# ---- 4. refusals, each with a passing control ------------------------------------------------------------------------

_EXT = ["--set", "keycloak.realmObjects=external"]
_ZED = _j("keycloak.extraServiceClients", [{"clientId": "zed-thing", "secretRef": "x", "authzId": "svc:zed"}])

_REFUSALS = [
    ("pattern T-", [*_s("identity.prefix", "T-"), *_EXT], "must be empty or match", [*_s("identity.prefix", "t-"), *_EXT]),
    ("pattern t (no hyphen)", [*_s("identity.prefix", "t"), *_EXT], "must be empty or match", [*_s("identity.prefix", "t-"), *_EXT]),
    ("pattern t-x- (hyphen inside)", [*_s("identity.prefix", "t-x-"), *_EXT], "must be empty or match",
     [*_s("identity.prefix", "tx-"), *_EXT]),
    ("pattern 13 characters", [*_s("identity.prefix", "abcdefghijklm-"), *_EXT], "must be empty or match",
     [*_s("identity.prefix", "abcdefghijkl-"), *_EXT]),
    ("role stem iagent-", [*_s("identity.prefix", "iagent-"), *_EXT], "is the start of the role literal",
     [*_s("identity.prefix", "t-"), *_EXT]),
    ("role stem cortex-", [*_s("identity.prefix", "cortex-"), *_EXT], "is the start of the role literal",
     [*_s("identity.prefix", "t-"), *_EXT]),
    ("a stem read from a declared client, not a typed list", [*_s("identity.prefix", "zed-"), *_EXT, *_ZED],
     'role literal "zed-thing"', [*_s("identity.prefix", "zed-"), *_EXT]),
    ("non-empty + managed without realmOwner", _s("identity.prefix", "t-"), "realmOwner",
     [*_s("identity.prefix", "t-"), *_j("keycloak.realmOwner", True)]),
    ("external + empty without soleInstanceInRealm", _EXT, "soleInstanceInRealm",
     [*_EXT, *_j("identity.soleInstanceInRealm", True)]),
    ("acceptedAudiences other than AUD", [*_s("identity.prefix", "t-"), *_EXT, *_j("cortexBff.auth.acceptedAudiences", ["cortex-bff"])],
     "acceptedAudiences is retired", [*_s("identity.prefix", "t-"), *_EXT, *_j("cortexBff.auth.acceptedAudiences", ["t-cortex-bff"])]),
    ("an extra accepted audience beside AUD", [*_s("identity.prefix", "t-"), *_EXT,
                                              *_j("cortexBff.auth.acceptedAudiences", ["t-cortex-bff", "p-cortex-bff"])],
     "acceptedAudiences is retired", [*_s("identity.prefix", "t-"), *_EXT, *_j("cortexBff.auth.acceptedAudiences", ["t-cortex-bff"])]),
    ("realmAudience other than AUD", [*_s("identity.prefix", "t-"), *_EXT, *_s("cortexBff.auth.realmAudience", "cortex-bff")],
     "realmAudience is retired", [*_s("identity.prefix", "t-"), *_EXT, *_s("cortexBff.auth.realmAudience", "t-cortex-bff")]),
    ("realmObjects not managed|external", _s("keycloak.realmObjects", "shared"), "must be", _s("keycloak.realmObjects", "managed")),
]


@pytest.mark.parametrize("label,bad,message,fixed", _REFUSALS, ids=[r[0] for r in _REFUSALS])
def test_each_refusal_fails_the_render_with_its_message_and_its_fix_passes(label, bad, message, fixed):
    """CLAIM: the render refuses `label`, naming it; the same values with the fix applied render."""
    assert message in _refused(*bad)
    _render(*fixed)


def test_empty_or_unset_retired_audience_keys_pass_under_a_prefix():
    """CLAIM (Lane 1's decision): an overlay with an external realm sets realmAudience: "" on purpose; empty or unset passes."""
    _render(*_T, *_j("cortexBff.auth.acceptedAudiences", []), *_s("cortexBff.auth.realmAudience", ""))
    _render(*_T, *_NO_AUD_KEYS)


def test_the_retired_keys_set_to_the_derived_audience_pass_with_an_empty_prefix():
    """CLAIM: the cutover overlay (acceptedAudiences: [cortex-bff], realmAudience: cortex-bff) renders under the empty prefix."""
    _render(*_j("cortexBff.auth.acceptedAudiences", ["cortex-bff"]), *_s("cortexBff.auth.realmAudience", "cortex-bff"))


def test_a_client_named_like_the_audience_is_refused():
    """CLAIM (2): a client id ending in cortex-bff could be resolved into an audience; the render refuses it."""
    err = _refused(*_j("keycloak.extraServiceClients", [{"clientId": "x-cortex-bff", "secretRef": "x", "authzId": "svc:x"}]))
    assert "ends in cortex-bff" in err


def test_a_public_client_colliding_with_the_prefixed_cortex_ui_is_refused():
    """CLAIM: the public-client collision check compares the ids as the realm holds them."""
    err = _refused(*_T, *_NO_AUD_KEYS, *_j("keycloak.publicClients", [{"clientId": "cortex-ui", "redirectUris": ["https://x.example/*"]}]))
    assert "collides with cortex-ui" in err


# ---- 5. realmObjects: external writes no realm-scoped object -----------------------------------------------------------

_REALM_TARGET = re.compile(r"\$API/(users|identity-provider|authentication/flows)")
_WRITE = re.compile(r"curl[^|]*?(-X\s+(POST|PUT|DELETE)\b|\s-d[\s'\"@]|--data)")


def realm_scoped_writes(script: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", script)
    return [l.strip()[:150] for l in joined.splitlines() if "curl" in l and _REALM_TARGET.search(l) and _WRITE.search(l)]


def test_realm_objects_external_writes_no_realm_scoped_object():
    """CLAIM: the external job contains no write to $API/users, identity-provider or authentication/flows, and its
    bodies Secret carries no user body; the detector is controlled by the managed render, which does write them."""
    brokers = ["--set-json", "keycloak.brokers.openddil.enabled=true", "--set-json", "keycloak.brokers.openddil.publicCA=true",
               "--set", "keycloak.brokers.openddil.existingSecret=x"]
    ext_script, ext_bodies = _reconcile(_render(*_SANDBOX, *_T, *_NO_AUD_KEYS, *brokers))
    assert realm_scoped_writes(ext_script) == []
    assert not [k for k in ext_bodies if k.startswith("user-")]
    assert "external" in ext_script
    man_script, man_bodies = _reconcile(_render(*_SANDBOX, *brokers))
    kinds = {m.group(1) for l in realm_scoped_writes(man_script) for m in [_REALM_TARGET.search(l)]}
    assert kinds == {"users", "identity-provider", "authentication/flows"}, f"the control found writes only to {kinds}"
    assert [k for k in man_bodies if k.startswith("user-")]


def test_the_external_job_still_converges_its_own_clients_and_reads_the_realm_objects_it_needs():
    """CLAIM: external keeps this instance's client writes and the readbacks that fail naming a missing realm object."""
    script, _ = _reconcile(_render(*_SANDBOX, *_T, *_NO_AUD_KEYS))
    assert 'curl -sf -X POST -H "$AUTH" -H "Content-Type: application/json" \\\n                  "$API/clients"' in script or "$API/clients" in script
    assert "FAIL user $UN: absent after reconcile" in script
    assert "unmanagedAttributePolicy is not ADMIN_EDIT" in script


def test_managed_with_an_empty_prefix_renders_the_sandbox_as_master_did(master):
    """CLAIM: realmObjects defaults to managed, and that render writes every realm object it wrote on master."""
    old = _reconcile(_render(*_SANDBOX, chart=master))[0]
    new = _reconcile(_render(*_SANDBOX))[0]
    assert old == new
