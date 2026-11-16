"""PRIME-SKIPS-UNCHANGED SEAL -- an ontology domain whose inputs did not change does no work.

WHY. The helm prime hook ran ~23 Dagster ingest runs through two global run slots on every
roll, though on a roll where no ontology changed that work was identical to the last roll's.

THE GRANULARITY IS THE DOMAIN. doc-tools POST-appends every file of a domain into ONE graph,
dropped once per domain, so one file's triples cannot be removed or kept alone: a domain with a
changed file is dropped and fully reloaded; a domain with none is neither dropped nor loaded.

WHAT THIS SEALS, end to end through `trigger_ingest_jobs`, with ONE stateful fake substrate
(Dagster, Fuseki, the load records, the bucket ETags) shared across calls, so a second run sees
what the first left behind:
  * nothing changed -> nothing launched, nothing dropped, no compaction;
  * a changed ETag -> only that domain, and ALL of that domain's files;
  * a changed or unreadable loader, a lost graph, fewer classes, --force -> reload;
  * a failed run -> no record, the records are deleted BEFORE the drop, the next run reloads;
  * no wait -> nothing is recorded.
Domains are derived from the real manifest by counting; no domain name is typed here.
"""
from __future__ import annotations

import collections
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "setup" / "prime_databases.py"
_MOD_NAME = "prime_databases__skip_unchanged_test"

_TRIPLES_PER_FILE = 7
_CLASSES_PER_FILE = 3


def _mod():
    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_MOD_NAME, None)
        pytest.skip(f"prime_databases not importable here: {type(exc).__name__}: {exc}")
    return m


@pytest.fixture(scope="module", autouse=True)
def _put_the_loaded_module_back():
    saved = {n: (n in sys.modules, sys.modules.get(n)) for n in (_MOD_NAME,)}
    yield
    for n, (had, prior) in saved.items():
        if had:
            sys.modules[n] = prior
        else:
            sys.modules.pop(n, None)


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _State:
    """The fake substrate. Every fake below reads and writes this one object."""

    def __init__(self, m):
        self.m = m
        self.loader = "loader-1"
        self.loader_present = True
        self.etags = {e["s3_key"]: f"etag-{i}-v1" for i, e in enumerate(m.CANONICAL_TTL_MANIFEST)}
        self.jena: dict[str, int] = collections.defaultdict(int)
        self.neo4j: dict[str, int] = collections.defaultdict(int)
        self.records: dict[str, dict] = {}
        self.launched: list[tuple[str, str]] = []
        self.dropped: list[str] = []
        self.compactions = 0
        self.events: list[tuple[str, str]] = []
        self.fail_keys: set[str] = set()
        self.refuse_launch_keys: set[str] = set()
        self.run_key: dict[str, str] = {}
        self._n = 0

    def reset_calls(self):
        self.launched.clear()
        self.dropped.clear()
        self.compactions = 0
        self.events.clear()


def _domains(m):
    c = collections.Counter(e["domain"] for e in m.CANONICAL_TTL_MANIFEST)
    single = next(d for d, n in sorted(c.items()) if n == 1)
    multi = next(d for d, n in sorted(c.items()) if n > 1)
    return single, multi


def _keys(m, domain):
    return sorted(e["s3_key"] for e in m.CANONICAL_TTL_MANIFEST if e["domain"] == domain)


@pytest.fixture
def world(monkeypatch):
    m = _mod()
    st = _State(m)
    monkeypatch.setenv("DAGSTER_URL", "http://dagster.invalid")
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)

    def _post(url, json=None, data=None, timeout=None, **_kw):  # noqa: A002
        if data is not None and "update" in data:
            g = data["update"].split("<")[1].rstrip(">")
            d = g.rsplit("/", 1)[1]
            st.jena[d] = 0
            st.dropped.append(d)
            st.events.append(("drop", d))
            return _Resp({})
        q = json["query"]
        if "workspaceOrError" in q:
            entries = ([{"name": m.DAGSTER_INGEST_LOCATION, "versionKey": st.loader}]
                       if st.loader_present else [{"name": "some-other-location", "versionKey": "x"}])
            return _Resp({"data": {"workspaceOrError": {"__typename": "Workspace",
                                                        "locationEntries": entries}}})
        if "addDynamicPartition" in q:
            return _Resp({"data": {"addDynamicPartition": {
                "__typename": "AddDynamicPartitionSuccess"}}})
        if "launchPipelineExecution" in q:
            cfg = json["variables"]["executionParams"]["runConfigData"]["ops"]["ingest_ontology_to_jena"]["config"]
            domain = cfg["extra_metadata"]["domain"]
            s3_key = cfg["file_url"].split("/", 3)[3]
            if s3_key in st.refuse_launch_keys:
                return _Resp({"data": {"launchPipelineExecution": {
                    "__typename": "PythonError", "message": "refused"}}})
            st._n += 1
            rid = f"run-{st._n}"
            st.run_key[rid] = s3_key
            st.launched.append((domain, s3_key))
            st.events.append(("launch", domain))
            st.jena[domain] += _TRIPLES_PER_FILE  # the ingest lands its triples and classes
            st.neo4j[domain] += _CLASSES_PER_FILE
            return _Resp({"data": {"launchPipelineExecution": {
                "__typename": "LaunchRunSuccess", "run": {"runId": rid}}}})
        if "runOrError" in q:
            rid = q.split('runId:"')[1].split('"')[0]
            status = "FAILURE" if st.run_key[rid] in st.fail_keys else "SUCCESS"
            return _Resp({"data": {"runOrError": {"__typename": "Run", "status": status}}})
        raise AssertionError(f"unrouted request: {url} {q[:80]}")

    monkeypatch.setattr(m.requests, "post", _post)

    def _compact(*_a, **_k):
        st.compactions += 1

    monkeypatch.setattr(m, "_compact_jena", _compact)

    def _etags(entries):
        return {e["s3_key"]: st.etags.get(e["s3_key"]) for e in entries}

    def _delete(domains):
        for d in sorted(domains):
            st.records.pop(d, None)
            st.events.append(("delete", d))

    def _write(domain, digest, loader, files, jena_triples, neo4j_classes):
        st.records[domain] = {"digest": digest, "loader": loader, "files": list(files),
                              "jena_triples": jena_triples, "neo4j_classes": neo4j_classes}
        st.events.append(("write", domain))

    # raising=False so the no-op control (master has none of these) reaches the assertions;
    # test_the_io_boundaries_exist makes a missing name loud on the real tree.
    monkeypatch.setattr(m, "_read_object_etags", _etags, raising=False)
    monkeypatch.setattr(m, "_jena_triple_count", lambda d: st.jena.get(d, 0), raising=False)
    monkeypatch.setattr(m, "_neo4j_class_count", lambda d: st.neo4j.get(d, 0), raising=False)
    monkeypatch.setattr(m, "_read_load_records", lambda: {d: dict(r) for d, r in st.records.items()},
                        raising=False)
    monkeypatch.setattr(m, "_delete_load_records", _delete, raising=False)
    monkeypatch.setattr(m, "_write_load_record", _write, raising=False)
    return st


def _run(st, *, wait=True, force=False):
    m = st.m
    kwargs = {"wait": wait, "wait_timeout": 60}
    # The no-op control runs this file against master, whose function has no `force`.
    if "force" in inspect.signature(m.trigger_ingest_jobs).parameters:
        kwargs["force"] = force
    return m.trigger_ingest_jobs(**kwargs)


def _first_run(st):
    _run(st)
    assert sorted(st.launched) == sorted(
        (e["domain"], e["s3_key"]) for e in st.m.CANONICAL_TTL_MANIFEST
    ), "the first run, with no records, must load every file"
    st.reset_calls()


def test_the_io_boundaries_exist():
    m = _mod()
    for name in ("_read_object_etags", "_jena_triple_count", "_neo4j_class_count",
                 "_read_load_records", "_delete_load_records", "_write_load_record",
                 "_read_loader_identity", "domain_digest", "decide_reloads"):
        assert callable(getattr(m, name, None)), f"{name} is missing from the prime"


def test_a_second_run_with_no_change_loads_nothing(world):
    st = world
    _first_run(st)
    _run(st)
    assert st.launched == [], f"an unchanged prime launched {len(st.launched)} runs"
    assert st.dropped == [], f"an unchanged prime dropped {st.dropped}"
    assert st.compactions == 0, "an unchanged prime compacted the store"


def test_one_changed_ontology_loads_only_that_one(world):
    st = world
    single, _multi = _domains(st.m)
    _first_run(st)
    (key,) = _keys(st.m, single)
    st.etags[key] = "etag-changed"
    _run(st)
    assert [k for _d, k in st.launched] == [key]
    assert st.dropped == [single]


def test_one_changed_file_reloads_its_whole_domain_and_nothing_else(world):
    st = world
    _single, multi = _domains(st.m)
    _first_run(st)
    keys = _keys(st.m, multi)
    st.etags[keys[0]] = "etag-changed"
    _run(st)
    assert sorted(k for _d, k in st.launched) == keys
    assert {d for d, _k in st.launched} == {multi}
    assert st.dropped == [multi]


def test_a_changed_loader_reloads_everything(world):
    st = world
    _first_run(st)
    st.loader = "loader-2"
    _run(st)
    assert len(st.launched) == len(st.m.CANONICAL_TTL_MANIFEST)
    assert sorted(st.dropped) == sorted({e["domain"] for e in st.m.CANONICAL_TTL_MANIFEST})


def test_an_unreadable_loader_reloads_everything(world):
    st = world
    _first_run(st)
    st.loader_present = False
    _run(st)
    assert len(st.launched) == len(st.m.CANONICAL_TTL_MANIFEST)


def test_a_lost_graph_reloads_its_domain(world):
    st = world
    single, _multi = _domains(st.m)
    _first_run(st)
    st.jena[single] = 0
    _run(st)
    assert st.dropped == [single]
    assert {d for d, _k in st.launched} == {single}


def test_a_graph_with_a_different_count_reloads_its_domain(world):
    st = world
    single, _multi = _domains(st.m)
    _first_run(st)
    st.jena[single] += 1
    _run(st)
    assert st.dropped == [single]
    assert {d for d, _k in st.launched} == {single}


def test_fewer_classes_than_recorded_reloads_its_domain(world):
    st = world
    _single, multi = _domains(st.m)
    _first_run(st)
    st.neo4j[multi] -= 1
    _run(st)
    assert st.dropped == [multi]
    assert sorted(k for _d, k in st.launched) == _keys(st.m, multi)


def test_a_failed_run_records_nothing_and_the_next_run_reloads(world):
    st = world
    single, _multi = _domains(st.m)
    _first_run(st)
    (key,) = _keys(st.m, single)
    st.etags[key] = "etag-changed"
    st.fail_keys.add(key)
    with pytest.raises(SystemExit):
        _run(st)
    assert not [e for e in st.events if e[0] == "write"], "a failed load left a record"
    assert single not in st.records
    kinds = [k for k, d in st.events if d == single]
    assert kinds.index("delete") < kinds.index("drop"), (
        "the record must be deleted BEFORE the graph is dropped; events: %r" % (st.events,))
    st.reset_calls()
    st.fail_keys.clear()
    _run(st)
    assert [k for _d, k in st.launched] == [key]
    assert st.dropped == [single]


def test_force_reloads_everything(world):
    st = world
    _first_run(st)
    _run(st, force=True)
    assert len(st.launched) == len(st.m.CANONICAL_TTL_MANIFEST)


def test_without_wait_nothing_is_recorded(world):
    st = world
    _run(st, wait=False)
    assert st.launched, "the control: a first run must launch"
    assert st.records == {}
    assert not [e for e in st.events if e[0] == "write"]


def test_the_digest_moves_with_each_input():
    m = _mod()
    rows = [
        {"s3_key": "a/x", "etag": "e1", "domain": "D", "file_url": "s3://b/a/x"},
        {"s3_key": "a/y", "etag": "e2", "domain": "D", "file_url": "s3://b/a/y"},
    ]
    base = m.domain_digest("L", rows)
    assert m.domain_digest("L", list(reversed(rows))) == base, "row order must not matter"
    assert m.domain_digest("L2", rows) != base, "the loader must move the digest"
    for field in ("etag", "file_url", "domain"):
        changed = [dict(rows[0], **{field: rows[0][field] + "-changed"}), rows[1]]
        assert m.domain_digest("L", changed) != base, f"{field} must move the digest"


def test_a_launch_that_failed_records_nothing_for_its_domain(world):
    """A file whose launch failed never enters the await, so the await passes. A record for its
    domain would attest a partial graph, and every later prime would skip it for ever."""
    st = world
    _single, multi = _domains(st.m)
    keys = _keys(st.m, multi)
    st.refuse_launch_keys.add(keys[0])
    _run(st)
    assert multi not in st.records, "a domain with an unlaunched file was recorded as loaded"
    others = {e["domain"] for e in st.m.CANONICAL_TTL_MANIFEST} - {multi}
    assert others and others <= set(st.records), "the other reloaded domains must still be recorded"
    st.reset_calls()
    st.refuse_launch_keys.clear()
    _run(st)
    assert st.dropped == [multi]
    assert sorted(k for _d, k in st.launched) == keys
