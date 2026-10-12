"""Every caller of engine-o's gated verdict is classified (the caller side of the service-identity ruling).

RULINGS (Chris, 2026-10-10, relayed by lane/74): "(a) service lookups (review composer) run
on_behalf_of the task's requesting person"; "(b) scripts and restate_analyst send a real test
persona or get refused -- a domains list is never an entitlement".

The ENGINE side is sealed in `test_service_identity_is_never_a_grant.py`: a caller with no person
sees seeded content only. THIS file is the CALLER side: a PARTITIONED census of every site in
`src/ agent_fleet/ scripts/ setup/` that sends a request reaching engine-o's gated verdict
(`/resolve`, `/resolve_instance`, `/fill_slots`, `/notice_parts`, `/enumerate_instances`, plus
restate_analyst's `/analyze`, which forwards to engine-o `/resolve`). Every site is in exactly one
class. WHAT IS DERIVED FROM THE CODE is the split this ruling turns on, PERSON vs NO_PERSON (does
the payload the site sends carry `user_email` at all). The split of PERSON into TOKEN and FORWARD is
DECLARED, checked only as far as "`config.user_email` or a parameter named user_email appears in
the function". Whether the supervisor's callers really pass `config.user_email` into rows 1-3 is
NOT this file's subject. MEASURED 2026-10-11: `execute_subtask` handing `_classify_route`
`user_email=""` instead of `config.user_email` stays green here AND in
`tests/routing/test_resolve_instance_hears_the_caller.py`; it is killed by lane/74's
`tests/test_the_person_reaches_the_migrated_route.py` (two arms: "not the caller's own identity",
"passes the literal ''"). That file owns the provenance of the supervisor's hops.

  TOKEN       the payload carries `user_email`, fed by the supervisor config (set by cortex-bff from
              the token) -- directly (`config.user_email`) or through a parameter named user_email.
  FORWARD     the payload carries `user_email` relayed from the site's own caller.
  NO_PERSON   the payload has no `user_email` key at all.

DOMAINS_WITHOUT_PERSON is a sub-shape of NO_PERSON: the payload has `domains` (or
`entitled_domains`) and no `user_email`. That is the exact shape ruling (b) names, and the shape the
corpus arm of `test_service_identity_is_never_a_grant` proves gets SEEDED CONTENT ONLY.

THE NO_PERSON CLASS IS THE POPULATION THE PLANNED 422 `no_person` REFUSAL ON /resolve_instance WILL
BREAK. That refusal may land only when the class is empty or each member has been re-pointed to a
person (lane/74 owns the caller-side changes). A site moving from NO_PERSON to a person-carrying
class is EXPECTED: MOVE ITS ROW AND SAY WHY in the row's comment; do not loosen a predicate.

How the census is taken: the detector walks every tracked .py/.sh file under the four roots
(tests excluded) and finds each `.post(...)` / `urllib Request(...)` whose URL ends in a route as a
FULL path segment (so `/resolve` never matches `/resolve_instance` or `/resolved`), or is held in
a local/module name that is, or is the env-named constant (`ONTOLOGY_RESOLVE_URL`,
`ENUMERATE_INSTANCES_URL`), or is an f-string over `RESTATE_ANALYST_URL` ending `/analyze`. The
found set must EQUAL the declared set. Two sites are not detectable by URL form (a registry
`endpoint_url` fan-out and an in-process handler call) and are declared as such with their own
existence checks. The detector has a positive control that runs on inline source.
"""
from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("src", "agent_fleet", "scripts", "setup")

ROUTE_RE = re.compile(r"/(resolve|resolve_instance|fill_slots|notice_parts|enumerate_instances)$")
# A constant named in the URL position stands for a route even when the path is not in the literal.
ENV_ROUTES = {"ONTOLOGY_RESOLVE_URL": "/resolve", "ENUMERATE_INSTANCES_URL": "/enumerate_instances"}
ANALYZE_HOLE = "RESTATE_ANALYST_URL"
SH_ROUTE_RE = re.compile(r"/(resolve|resolve_instance|fill_slots|notice_parts|enumerate_instances)(?![\w/])")

DS = "src/iagent/defs/dynamic_supervisor.py"
RA = "agent_fleet/restate_analyst/main.py"
OS_ = "agent_fleet/ontology_service/main.py"
RC = "agent_fleet/restate_analyst/review_composer.py"
RRC = "scripts/run_resolver_corpus.py"


# --------------------------------------------------------------------------------------
# The declared table. (file, enclosing function, route, class, site count, how it is found)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Row:
    n: str
    file: str
    function: str
    route: str
    cls: str
    count: int = 1
    found_by: str = "url"  # "url" | "registry" | "inprocess"


ROWS = [
    Row("1", DS, "_resolve_subject", "/resolve", "TOKEN"),
    Row("2", DS, "_fill_slots_from_query", "/fill_slots", "TOKEN"),
    # The post sits in the INNER function `_enumerate` of `_make_enumerator`; the caller dict is
    # bound in the outer one (`_caller = {"user_email": user_email, ...}`, spread into the body).
    Row("3", DS, "_enumerate", "/enumerate_instances", "TOKEN"),
    Row("4", DS, "_call_engine_a_fallback", "/analyze", "TOKEN"),
    Row("5", RA, "_resolve_ontology", "/resolve", "FORWARD"),
    Row("6", OS_, "_call_resolver", "/resolve_instance", "FORWARD", found_by="registry"),
    Row("7", OS_, "_bind_from_scope", "/enumerate_instances", "FORWARD", found_by="inprocess"),
    Row("8", RC, "resolve_subject_via_engine_o", "/resolve_instance", "NO_PERSON"),
    Row("9", RRC, "probe", "/resolve", "NO_PERSON"),
    Row("10", RRC, "stamp", "/resolve", "NO_PERSON", count=2),
    Row("11", RRC, "check_pool", "/resolve", "NO_PERSON"),
    Row("13", "setup/verify_tier3_live.py", "_resolve_query", "/resolve", "NO_PERSON"),
    Row("14", "scripts/phase1_stable_harness.sh", "top level", "/resolve", "NO_PERSON"),
    Row("15", "scripts/elicitation_battery.py", "_fill", "/fill_slots", "NO_PERSON"),
    Row("16", "scripts/slot_fill_battery.py", "_call", "/fill_slots", "NO_PERSON"),
    Row("17", "src/iagent/defs/agent_routers.py", "trigger_restate_analyst", "/analyze", "NO_PERSON"),
]
DOMAINS_WITHOUT_PERSON_ROWS = {"9", "10", "11"}  # run_resolver_corpus.py: probe, stamp x2, check_pool
EXPECTED_NO_PERSON_SITES = 10  # rows 8, 9-11 (4 sites), 13, 14, 15, 16, 17

# A found site that is NOT engine-o. Keyed (file, function, route) -> (hole expected in the URL, why).
EXCLUDED = {
    ("scripts/elicitation_battery.py", "_e", "/enumerate_instances"): (
        "engine_p",
        "URL base is the `engine_p` argument ('against the LIVE provider': engine-p's own "
        "/enumerate_instances), not the engine_o argument its sibling `_fill` posts to",
    ),
}


# --------------------------------------------------------------------------------------
# The detector
# --------------------------------------------------------------------------------------
@dataclass
class Site:
    file: str
    function: str
    route: str
    line: int
    holes: tuple = ()
    node: Any = None
    scopes: list = field(default_factory=list)  # enclosing defs, innermost first
    tree: Any = None
    shell_cmd: str = ""

    @property
    def key(self):
        return (self.file, self.function, self.route)


def _ident(expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    try:
        return ast.unparse(expr)
    except Exception:  # noqa: BLE001
        return "?"


def _url_parts(node):
    """(joined literal text, hole identifiers) for a str constant / f-string, else (None, ())."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, ()
    if isinstance(node, ast.JoinedStr):
        text = "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
        holes = tuple(_ident(v.value) for v in node.values if isinstance(v, ast.FormattedValue))
        return text, holes
    return None, ()


def _scopes_of(node, parents):
    out, cur = [], parents.get(id(node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(cur)
        cur = parents.get(id(cur))
    return out


def _assigned_before(scope, name, line):
    """The latest `name = <value>` (plain or annotated) in `scope` before `line`, or None."""
    best = None
    for n in ast.walk(scope):
        val = tgt = None
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            tgt, val = n.targets[0], n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            tgt, val = n.target, n.value
        if isinstance(tgt, ast.Name) and tgt.id == name and n.lineno < line:
            if best is None or n.lineno > best.lineno:
                best = n
    return best.value if best is not None else None


def _module_env_route(tree, name):
    """A module-level `NAME = ...("ENV_NAME", ...)` whose env name is a known route constant."""
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgts = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in tgts) and n.value is not None:
                for sub in ast.walk(n.value):
                    if isinstance(sub, ast.Constant) and sub.value in ENV_ROUTES:
                        return ENV_ROUTES[sub.value]
    return None


def _route_of(url, scopes, tree, line):
    """(route, holes) when `url` reaches an engine-o route, else None. Follows ONE assignment."""
    for _ in range(2):
        text, holes = _url_parts(url)
        if text is not None:
            m = ROUTE_RE.search(text)
            if m:
                return "/" + m.group(1), holes
            if text.endswith("/analyze") and ANALYZE_HOLE in holes:
                return "/analyze", holes
            if text.strip("/") == "":
                for h in holes:
                    if h in ENV_ROUTES:
                        return ENV_ROUTES[h], holes
            return None
        ident = _ident(url) if isinstance(url, (ast.Name, ast.Attribute)) else None
        if ident is None:
            return None
        if ident in ENV_ROUTES:
            return ENV_ROUTES[ident], ()
        if isinstance(url, ast.Name):
            for sc in scopes:
                val = _assigned_before(sc, ident, line)
                if val is not None:
                    url = val
                    break
            else:
                r = _module_env_route(tree, ident)
                return (r, ()) if r else None
            continue
        return None
    return None


def find_py_sites(src: str, path: str) -> list[Site]:
    tree = ast.parse(src)
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    decorators = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in n.decorator_list:
                decorators.update(id(x) for x in ast.walk(d))
    sites = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or id(n) in decorators:
            continue
        f = n.func
        is_post = isinstance(f, ast.Attribute) and f.attr == "post"
        is_req = (isinstance(f, ast.Name) and f.id == "Request") or (
            isinstance(f, ast.Attribute) and f.attr == "Request")
        if not (is_post or is_req):
            continue
        url = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == "url"), None)
        if url is None:
            continue
        scopes = _scopes_of(n, parents)
        hit = _route_of(url, scopes, tree, n.lineno)
        if hit is None:
            continue
        sites.append(Site(path, scopes[0].name if scopes else "<module>", hit[0], n.lineno,
                          hit[1], n, scopes, tree))
    return sites


def find_sh_sites(src: str, path: str) -> list[Site]:
    lines = src.splitlines()
    sites = []
    for i, ln in enumerate(lines):
        if not re.search(r"\bcurl\b", ln) or ln.lstrip().startswith("#"):
            continue
        m = SH_ROUTE_RE.search(ln)
        if not m:
            continue
        j, cmd = i, ln
        while cmd.rstrip().endswith("\\") and j + 1 < len(lines):
            j += 1
            cmd += "\n" + lines[j]
        sites.append(Site(path, "top level", "/" + m.group(1), i + 1, (), None, [], None, cmd))
    return sites


def _tracked_files():
    out = subprocess.run(["git", "ls-files", "--", *ROOTS], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    keep = []
    for p in out:
        if not p or not p.endswith((".py", ".sh")):
            continue
        parts = p.split("/")
        if "tests" in parts[:-1] or parts[-1].startswith(("test_", "conftest")):
            continue
        keep.append(p)
    return keep


_CACHE: dict = {}


def census() -> list[Site]:
    if "sites" not in _CACHE:
        sites = []
        for p in _tracked_files():
            src = (ROOT / p).read_text(encoding="utf-8", errors="replace")
            if p.endswith(".py"):
                try:
                    sites += find_py_sites(src, p)
                except SyntaxError:
                    continue
            else:
                sites += find_sh_sites(src, p)
        _CACHE["sites"] = sites
    return _CACHE["sites"]


# --------------------------------------------------------------------------------------
# Payload derivation (the class comes from this, not from the label)
# --------------------------------------------------------------------------------------
def _name_keys(name, scopes, line, seen):
    for sc in scopes:
        keys, found = set(), False
        val = _assigned_before(sc, name, line)
        if val is not None:
            found = True
            keys |= _expr_keys(val, scopes, line, seen | {name})
        for n in ast.walk(sc):  # later `name["k"] = ...` assignments in the same function
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and t.value.id == name and isinstance(t.slice, ast.Constant)
                            and isinstance(t.slice.value, str)):
                        keys.add(t.slice.value)
                        found = True
        if found:
            return keys
    return set()


def _expr_keys(expr, scopes, line, seen=frozenset()) -> set:
    keys: set = set()
    if isinstance(expr, ast.Dict):
        for k, v in zip(expr.keys, expr.values):
            if k is None:  # **spread
                keys |= _expr_keys(v, scopes, line, seen)
            elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
    elif isinstance(expr, ast.Name):
        if expr.id not in seen:
            keys |= _name_keys(expr.id, scopes, line, seen)
    elif isinstance(expr, ast.Call):  # json.dumps({...}).encode()
        for sub in [expr.func, *expr.args]:
            keys |= _expr_keys(sub, scopes, line, seen)
    elif isinstance(expr, ast.Attribute):
        keys |= _expr_keys(expr.value, scopes, line, seen)
    return keys


def payload_keys(site: Site) -> set:
    call = site.node
    body = next((k.value for k in call.keywords if k.arg == "json"), None)
    if body is None:
        body = next((k.value for k in call.keywords if k.arg == "data"), None)
    if body is None:
        return set()
    return _expr_keys(body, site.scopes, call.lineno)


def derived_class(site: Site) -> str:
    """PERSON when the payload names `user_email`, else NO_PERSON."""
    if site.shell_cmd:
        return "PERSON" if "user_email" in site.shell_cmd else "NO_PERSON"
    return "PERSON" if "user_email" in payload_keys(site) else "NO_PERSON"


# --------------------------------------------------------------------------------------
# Undetectable-by-URL rows: the registry fan-out and the in-process handler call
# --------------------------------------------------------------------------------------
def _parse(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    return tree, parents


def _func(tree, name):
    hits = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == name]
    return hits[0] if hits else None


def registry_site(row: Row) -> Site | None:
    """`_call_resolver`: a `.post(endpoint_url, json=...)` where endpoint_url is the registry's."""
    tree, parents = _parse(row.file)
    fn = _func(tree, row.function)
    if fn is None:
        return None
    registry_bound = _assigned_before(fn, "endpoint_url", 10**9)
    if not (registry_bound is not None and 'get("endpoint_url"' in ast.unparse(registry_bound).replace("'", '"')):
        return None
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "post"
                and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "endpoint_url"):
            return Site(row.file, fn.name, row.route, n.lineno, (), n, _scopes_of(n, parents), tree)
    return None


def inprocess_site(row: Row) -> Site | None:
    """`_bind_from_scope`: a direct call of the `enumerate_instances` handler; the request's
    keyword arguments are the payload."""
    tree, parents = _parse(row.file)
    fn = _func(tree, row.function)
    if fn is None:
        return None
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "enumerate_instances":
            return Site(row.file, fn.name, row.route, n.lineno, (), n, _scopes_of(n, parents), tree)
    return None


def _inprocess_keys(site: Site) -> set:
    req = site.node.args[0]
    assert isinstance(req, ast.Call), "the handler is no longer called with a request constructor"
    return {k.arg for k in req.keywords if k.arg}


def _sites_for(row: Row) -> list[Site]:
    if row.found_by == "registry":
        s = registry_site(row)
        return [s] if s else []
    if row.found_by == "inprocess":
        s = inprocess_site(row)
        return [s] if s else []
    return [s for s in census() if s.key == (row.file, row.function, row.route)]


def _keys_of(row: Row, site: Site) -> set:
    return _inprocess_keys(site) if row.found_by == "inprocess" else payload_keys(site)


def _has_param(site: Site, name: str) -> bool:
    return any(a.arg == name for sc in site.scopes
               for a in [*sc.args.args, *sc.args.kwonlyargs])


# --------------------------------------------------------------------------------------
# Arm A: the population, derived not sampled
# --------------------------------------------------------------------------------------
def test_POPULATION_found_by_detector_equals_the_declared_set():
    declared = Counter()
    for r in ROWS:
        if r.found_by == "url":
            declared[(r.file, r.function, r.route)] += r.count
    found = Counter()
    excluded_seen = set()
    for s in census():
        if s.key in EXCLUDED:
            hole, _why = EXCLUDED[s.key]
            assert hole in s.holes, (
                f"{s.file}:{s.line} {s.route} is EXCLUDED as a non-engine-o service on the strength "
                f"of the URL hole {hole!r}, but its URL holes are {s.holes!r} -- undecided fails")
            excluded_seen.add(s.key)
            continue
        found[s.key] += 1
    for s in census():
        if s.key not in EXCLUDED and declared[s.key] < 1:
            raise AssertionError(
                f"an unclassified engine-o caller: {s.file}:{s.line} {s.route} -- classify it; "
                f"do not widen the predicate")
    assert found == declared, (
        f"the declared table and the census disagree.\n  declared-not-found: "
        f"{dict(declared - found)}\n  found-not-declared (count): {dict(found - declared)}")
    assert excluded_seen == set(EXCLUDED), f"an EXCLUDED entry no longer exists: {set(EXCLUDED) - excluded_seen}"
    for key, (_h, why) in EXCLUDED.items():
        assert why.strip(), f"{key} is excluded with no reason"


def test_UNDETECTABLE_ROWS_exist_where_they_are_declared():
    r6 = next(r for r in ROWS if r.n == "6")
    r7 = next(r for r in ROWS if r.n == "7")
    s6, s7 = registry_site(r6), inprocess_site(r7)
    assert s6 is not None, (
        "row 6 (_call_resolver): no `.post(endpoint_url, ...)` with endpoint_url taken from the "
        "registry row's `endpoint_url` -- the registry fan-out moved; re-derive the row")
    assert s7 is not None, (
        "row 7 (_bind_from_scope): no direct call of the `enumerate_instances` handler -- the "
        "in-process call moved; re-derive the row")


def test_the_scripts_directory_sh_scan_sees_the_curl_line():
    sh = [s for s in census() if s.file.endswith(".sh")]
    assert [(s.file, s.route) for s in sh] == [("scripts/phase1_stable_harness.sh", "/resolve")]


# --------------------------------------------------------------------------------------
# Arm B: positive control for the detector (inline source)
# --------------------------------------------------------------------------------------
def _routes(src):
    return [(s.function, s.route) for s in find_py_sites(src, "x.py")]


def test_CONTROL_detector_finds_the_positive_forms():
    assert _routes('import requests\ndef f(X):\n    requests.post(f"{X}/resolve_instance", json={})\n') \
        == [("f", "/resolve_instance")]
    assert _routes("def g():\n    client.post(url=ONTOLOGY_RESOLVE_URL, json={})\n") == [("g", "/resolve")]
    assert _routes('def h(b):\n    u = f"{b}/fill_slots"\n    s.post(u, json={})\n') == [("h", "/fill_slots")]
    assert _routes('import os\n_E = os.getenv("ENUMERATE_INSTANCES_URL", "")\n'
                   "def k():\n    requests.post(_E, json={})\n") == [("k", "/enumerate_instances")]
    assert _routes('def m():\n    requests.post(f"{RESTATE_ANALYST_URL}/analyze", json={})\n') \
        == [("m", "/analyze")]
    assert _routes('def n(url):\n    urllib.request.Request(f"{url}/notice_parts", data=b"")\n') \
        == [("n", "/notice_parts")]
    sh = find_sh_sites('curl -s -X POST http://h:1/resolve \\\n  -d \'{"query":"w"}\'\n', "a.sh")
    assert [(s.route, "user_email" in s.shell_cmd) for s in sh] == [("/resolve", False)]


def test_CONTROL_detector_ignores_the_negative_forms():
    assert _routes('@app.post("/resolve")\nasync def resolve(r):\n    return 1\n') == []
    assert _routes('def a():\n    x = "/resolve_instance"\n    return x\n') == []
    assert _routes('def b():\n    requests.post("http://h/resolved", json={})\n') == []
    assert _routes('def c(b):\n    requests.post(f"{b}/resolve_instance/extra", json={})\n') == []
    assert _routes('def d(b):\n    requests.post(f"{b}/measure/{fn}", json={})\n') == []
    assert _routes('def e(b):\n    requests.post(f"{OTHER}/analyze", json={})\n') == []
    assert find_sh_sites('echo "POST /resolve_instance"\n# curl http://h/resolve\n', "a.sh") == []


def test_CONTROL_payload_derivation_reads_spread_subscript_and_absence():
    def keys(src):
        (s,) = find_py_sites(src, "x.py")
        return payload_keys(s)

    base = "def f(b, u):\n"
    assert keys(base + '    requests.post(f"{b}/resolve", json={"query": 1})\n') == {"query"}
    assert keys(base + '    p = {"query": 1}\n    if u:\n        p["user_email"] = u\n'
                '    requests.post(f"{b}/resolve", json=p)\n') == {"query", "user_email"}
    assert keys("def o(u):\n    c = {'user_email': u}\n    def i():\n"
                '        requests.post(f"{b}/resolve", json={"q": 1, **c})\n') == {"q", "user_email"}
    assert keys(base + '    body = json.dumps({"query": 1}).encode()\n'
                '    urllib.request.Request(f"{b}/fill_slots", data=body)\n') == {"query"}


# --------------------------------------------------------------------------------------
# Arm C: the class of each site, derived from the code
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"row{r.n}-{r.function}-{r.cls}")
def test_CLASS_of_each_site_is_the_class_its_payload_has(row):
    sites = _sites_for(row)
    assert len(sites) == row.count, (
        f"row {row.n} ({row.file}::{row.function} {row.route}): expected {row.count} site(s), "
        f"found {len(sites)}")
    for s in sites:
        if row.found_by == "url" and s.shell_cmd:
            has_person = "user_email" in s.shell_cmd
            assert (not has_person) if row.cls == "NO_PERSON" else has_person
            continue
        keys = _keys_of(row, s)
        assert keys, f"row {row.n} ({row.function}): no payload keys derived -- the derivation is blind here"
        if row.cls == "NO_PERSON":
            assert "user_email" not in keys, (
                f"row {row.n} ({row.file}:{s.line} {row.function} {row.route}) is declared NO_PERSON "
                f"but its payload now carries `user_email`. It has MOVED to a person-carrying class: "
                f"move its row (TOKEN/FORWARD), lower the NO_PERSON count, and say why.")
        else:
            assert "user_email" in keys, (
                f"row {row.n} ({row.file}:{s.line} {row.function} {row.route}) is declared "
                f"{row.cls} but its payload has no `user_email` key (keys: {sorted(keys)})")
            fed = _has_param(s, "user_email")
            if row.cls == "TOKEN":
                fn_text = "".join(ast.unparse(sc) for sc in s.scopes)
                fed = fed or "config.user_email" in fn_text
                assert fed, (f"row {row.n} TOKEN: neither `config.user_email` nor a `user_email` "
                             f"parameter feeds the payload in {row.function}")
            else:
                assert fed, (f"row {row.n} FORWARD: no `user_email` parameter relays the caller's "
                             f"identity in {row.function}")


# --------------------------------------------------------------------------------------
# Arm D: DOMAINS_WITHOUT_PERSON (the shape ruling (b) names)
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("row", [r for r in ROWS if r.n in DOMAINS_WITHOUT_PERSON_ROWS],
                         ids=lambda r: f"row{r.n}-{r.function}")
def test_DOMAINS_WITHOUT_PERSON_sends_domains_and_no_user_email(row):
    sites = _sites_for(row)
    assert len(sites) == row.count
    for s in sites:
        keys = payload_keys(s)
        assert keys & {"domains", "entitled_domains"}, (
            f"{row.file}:{s.line} {row.function} no longer sends a domains list: it is not "
            f"DOMAINS_WITHOUT_PERSON any more; reclassify it")
        assert "user_email" not in keys, (
            f"{row.file}:{s.line} {row.function} sends domains AND user_email: it has moved out "
            f"of DOMAINS_WITHOUT_PERSON (a domains list was never an entitlement; a person is). "
            f"Move its row and say why")


# --------------------------------------------------------------------------------------
# Arm E: the count
# --------------------------------------------------------------------------------------
def test_NO_PERSON_class_has_exactly_the_declared_population():
    declared = sum(r.count for r in ROWS if r.cls == "NO_PERSON")
    derived = 0
    for r in ROWS:
        for s in _sites_for(r):
            cls = "PERSON" if (r.found_by == "inprocess" and "user_email" in _inprocess_keys(s)) \
                else derived_class(s)
            derived += cls == "NO_PERSON"
    assert declared == EXPECTED_NO_PERSON_SITES, (
        f"the declared NO_PERSON population is {declared}, expected {EXPECTED_NO_PERSON_SITES}")
    assert derived == EXPECTED_NO_PERSON_SITES, (
        f"NO_PERSON now has {derived} derived site(s); the table says {EXPECTED_NO_PERSON_SITES}. "
        f"The 422 `no_person` refusal on /resolve_instance may land ONLY when this class is empty "
        f"or each member has been re-pointed to a person (lane/74 owns the caller-side changes). "
        f"A site that moved from NO_PERSON to a person-carrying class is EXPECTED: move its row "
        f"and say why; do not loosen the predicate.")
