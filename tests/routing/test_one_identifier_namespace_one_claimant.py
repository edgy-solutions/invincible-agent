"""One identifier namespace, one claimant -- the HAZ-1004 ruling, sealed end to end.

RULED 2026-10-12 (architect, lane/saf's Q3): "an identifier namespace (a prefix pattern) is
claimed by exactly one engine, declared in that engine's registration. A resolver refuses a fuzzy
match across namespaces." Engine-o stops matching HAZ-.

MEASURED on sandbox at e977c32b, engine-o's own `/resolve_instance` (the pcn provider), no person:

    'HAZ-1004' -> HX3120004Q    pcn#Component  0.556
                  AZV5001RA4-7  pcn#Component  0.5      (the floor)
    'HAZ-1003' -> []

Two part numbers sharing three characters with a hazard id cleared the pcn floor on a difflib ratio.
With Engine S's exact `safety#Hazard` beside them in SUSTAINMENT, the fan-out saw two claimants and
two subjects and refused the bind as `ambiguous_in_domain` -- lane/01's live run, 3 of 3. HAZ-1003
bound because its trailing `3` matches neither part number (0.444 and 0.4).

WHAT IS SEALED, in the order the declaration travels:
  1. the engine's emitter carries `id_namespaces` to the registrar (and refuses a bare string);
  2. the registrar's manifest admits it, refuses a prefix that is not one, and writes it to the edge;
  3. discovery reads it off the edge under the same name, through a decoder that will not iterate
     a string into one-letter prefixes;
  4. the fan-out refuses a NON-OWNER's FUZZY candidate for a term in a declared namespace, keeps
     an exact one, and names what it refused in its log line.

THE CONTROL IS THE LIVE FAILURE. The same fan-out, the same measured candidates, with Engine S
declaring nothing, must still answer `ambiguous_in_domain`: that is today's behaviour, and it is
what proves the declaration -- not some other change -- is what binds the hazard.

Run: uv run --frozen pytest tests/routing/test_one_identifier_namespace_one_claimant.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

from agent_fleet.ontology_service.instance_resolution import (  # noqa: E402
    InstanceCandidate,
    claimed_namespaces,
    declared_id_namespaces,
    refuse_cross_namespace,
)

_PCN = "http://internal/sustainment/pcn#Component"
_HAZ = "http://internal/sustainment/safety#Hazard"
_EO = "engine_o_sustainment"
_S = "engine_safety_sustainment"
_FIN = "engine_fin_finance"


def _measured():
    """The three candidates the live fan-out saw for 'HAZ-1004' (scores as measured)."""
    return [
        InstanceCandidate("http://internal/components/HX3120004Q", _PCN, "HX3120004Q", 0.556, _EO),
        InstanceCandidate("http://internal/components/AZV5001RA4-7", _PCN, "AZV5001RA4-7", 0.5, _EO),
        InstanceCandidate("http://internal/sustainment/safety/HAZ-1004", _HAZ, "HAZ-1004", 1.0, _S),
    ]


def _resolvers(s_namespaces=("HAZ-",)):
    return [
        {"provider": _EO, "endpoint_url": "http://stub/eo", "timeout_s": None,
         "domains": ["SUSTAINMENT"], "id_namespaces": []},
        {"provider": _S, "endpoint_url": "http://stub/s", "timeout_s": None,
         "domains": ["SUSTAINMENT"], "id_namespaces": list(s_namespaces)},
    ]


# ── 4. the rule, pure ─────────────────────────────────────────────────────────────────────────

def test_the_measured_part_numbers_are_refused_and_the_hazard_is_kept():
    kept, refused, claimed = refuse_cross_namespace(
        _measured(), terms=["HAZ-1004"], resolvers=_resolvers())
    assert [c.label for c in kept] == ["HAZ-1004"]
    assert sorted(c.label for c in refused) == ["AZV5001RA4-7", "HX3120004Q"]
    assert claimed == {"HAZ-": frozenset({_S})}


def test_the_OWNERs_fuzzy_candidate_is_kept():
    """Ownership, not exactness, is what keeps the owner's claim. Every other arm's owner
    candidate is labelled exactly the term, so it would survive the exact-name rule alone; this
    one matches the term by neither label nor IRI local name."""
    owned = InstanceCandidate("http://internal/sustainment/safety/hz-1004-chafe", _HAZ,
                              "Hydraulic line chafe", 0.7, _S)
    kept, refused, _ = refuse_cross_namespace(
        [owned] + _measured()[:2], terms=["HAZ-1004"], resolvers=_resolvers())
    assert kept == [owned] and len(refused) == 2


def test_no_declaration_refuses_nothing():
    """Today's behaviour: a provider that declares no namespace claims nothing."""
    kept, refused, claimed = refuse_cross_namespace(
        _measured(), terms=["HAZ-1004"], resolvers=_resolvers(s_namespaces=()))
    assert len(kept) == 3 and refused == [] and claimed == {}


def test_an_identifier_outside_every_namespace_is_untouched():
    """The declaration scopes HAZ- identifiers only; engine-o keeps matching its own part numbers."""
    cands = [InstanceCandidate("http://internal/components/HX3120004Q", _PCN, "HX3120004Q", 0.9, _EO)]
    kept, refused, _ = refuse_cross_namespace(cands, terms=["HX3120004"], resolvers=_resolvers())
    assert kept == cands and refused == []


def test_a_non_owners_EXACT_name_is_kept():
    """Fuzzy is refused, exact is not: a part literally named the term is a real second claim."""
    exact = InstanceCandidate("http://internal/components/HAZ-1004", _PCN, "HAZ-1004", 1.0, _EO)
    kept, refused, _ = refuse_cross_namespace(
        [exact] + _measured(), terms=["HAZ-1004"], resolvers=_resolvers())
    assert exact in kept and sorted(c.label for c in refused) == ["AZV5001RA4-7", "HX3120004Q"]


def test_an_exact_IRI_local_name_is_kept_when_the_label_differs():
    exact = InstanceCandidate("http://internal/components/HAZ-1004", _PCN, "a part", 1.0, _EO)
    kept, refused, _ = refuse_cross_namespace([exact], terms=["HAZ-1004"], resolvers=_resolvers())
    assert kept == [exact] and refused == []


def test_EVERY_non_owner_is_refused_not_only_engine_o():
    """The rule belongs to the class: any provider without the declaration loses a fuzzy claim."""
    other = InstanceCandidate("fin:p9", "fin#Program", "Hazard Program 1004", 0.6, _FIN)
    rs = _resolvers() + [{"provider": _FIN, "domains": ["SUSTAINMENT"], "id_namespaces": []}]
    kept, refused, _ = refuse_cross_namespace(
        _measured() + [other], terms=["HAZ-1004"], resolvers=rs)
    assert other in refused and [c.provider for c in kept] == [_S]


@pytest.mark.parametrize("term", ["haz-1004", "the hazard HAZ-1004", "(HAZ-1004)?"])
def test_the_namespace_is_found_case_insensitively_and_inside_a_phrase(term):
    assert claimed_namespaces([term], _resolvers()) == {"HAZ-": frozenset({_S})}


def test_the_prefix_must_START_a_token():
    assert claimed_namespaces(["XHAZ-1004", "1004HAZ-"], _resolvers()) == {}


def test_a_contested_prefix_keeps_every_declarer_as_an_owner():
    rs = _resolvers() + [{"provider": _FIN, "id_namespaces": ["HAZ-"]}]
    assert claimed_namespaces(["HAZ-1"], rs) == {"HAZ-": frozenset({_S, _FIN})}


@pytest.mark.parametrize("value,expected", [
    ("HAZ-", []),                       # a string is not a list: never iterated into H, A, Z, -
    (["HAZ-", "CSI-"], ["HAZ-", "CSI-"]),
    ([" HAZ- "], ["HAZ-"]),
    (["", "  ", "HA Z", None, 3], []),  # blank claims everything; whitespace never matches
    (None, []),
])
def test_the_decoder_reads_only_a_list_of_real_prefixes(value, expected):
    assert declared_id_namespaces(value) == expected


# ── 2. the registrar ──────────────────────────────────────────────────────────────────────────

_REG_MOD = "mesh_registrar_main__id_namespaces_test"


def _registrar():
    cached = sys.modules.get(_REG_MOD)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(
        _REG_MOD, _REPO / "agent_fleet" / "mesh_registrar" / "main.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[_REG_MOD] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_REG_MOD, None)
        pytest.fail(f"mesh_registrar must be importable for this suite: {exc!r}")
    return m


_MANIFEST = dict(
    name="engine_safety_sustainment_resolve_instance",
    verb_iri="mesh:resolveInstance",
    input_uri="http://invincible-agent/mesh#InstanceIdentifier",
    output_uri="http://invincible-agent/mesh#InstanceResolution",
    endpoint_url="http://stub/s/resolve_instance",
    owner_persona="SAFETY_ENGINEER",
    domains=["SUSTAINMENT"],
)


def _bag(manifest: dict) -> dict:
    m = _registrar()
    return m._build_rel_props_for_saga(
        manifest=m.RegistrationManifest(**manifest), provider=_S,
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,engine_safety_sustainment,PROD)")


def test_a_declaration_reaches_the_edge_as_a_list_of_strings():
    assert _bag({**_MANIFEST, "id_namespaces": ["HAZ-", "CSI-"]})["id_namespaces"] == ["HAZ-", "CSI-"]


def test_no_declaration_is_written_as_an_EMPTY_LIST_so_a_withdrawal_clears_the_edge():
    """The writer merges with `onMatchProps`, so an omitted key keeps its old value."""
    assert _bag(_MANIFEST)["id_namespaces"] == []


@pytest.mark.parametrize("bad", ["", "   ", "H", "HA Z"])
def test_the_registrar_refuses_a_prefix_that_is_not_one(bad):
    m = _registrar()
    with pytest.raises(Exception, match="id_namespaces"):
        m.RegistrationManifest(**{**_MANIFEST, "id_namespaces": ["HAZ-", bad]})


def test_the_audit_record_says_what_the_edge_was_told():
    m = _registrar()
    props = m._build_custom_properties(
        m.RegistrationManifest(**{**_MANIFEST, "id_namespaces": ["HAZ-", "CSI-"]}))
    assert props["mesh_id_namespaces"] == "HAZ-,CSI-"


# ── 1. the engine's emitter ───────────────────────────────────────────────────────────────────

def _emitted(monkeypatch, **kw) -> dict:
    from agent_fleet.utils import mesh_registration as mr  # noqa: PLC0415

    sent: dict = {}

    class _Ok:
        registered = True

        def announcement(self, component):
            return f"registered {component}"

    def _capture(url, manifest, **_k):
        sent.update(manifest)
        return _Ok()

    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("MESH_REGISTRAR_URL", "http://stub-registrar")
    monkeypatch.setattr(mr, "register_with_mesh", _capture)
    mr.register_engine_to_mesh(
        name=_MANIFEST["name"], description="d", verb=_MANIFEST["verb_iri"],
        input_uri=_MANIFEST["input_uri"], output_uri=_MANIFEST["output_uri"],
        endpoint_url=_MANIFEST["endpoint_url"], owner_persona="SAFETY_ENGINEER",
        domains=["SUSTAINMENT"], **kw)
    return sent


def test_the_engine_emitter_sends_the_declaration_to_the_registrar(monkeypatch):
    assert _emitted(monkeypatch, id_namespaces=["HAZ-"])["id_namespaces"] == ["HAZ-"]


def test_the_engine_emitter_refuses_a_bare_string(monkeypatch):
    with pytest.raises(TypeError, match="list of prefixes"):
        _emitted(monkeypatch, id_namespaces="HAZ-")


# ── 3 + 4. discovery and the fan-out, through engine-o's real main.py ───────────────────────────

@pytest.fixture(scope="module")
def main():
    """engine-o's real main.py, imported PACKAGE-FIRST: the one module object every other file
    patches. A private-name load with the package dir on sys.path made second copies of main's
    bare-imported siblings (notice_parts), and a later file's patch then missed the copy main ran
    (measured: tests/security/test_q8_flips_on_one_precondition.py went red after this file)."""
    return pytest.importorskip(
        "agent_fleet.ontology_service.main",
        reason="ontology_service not importable here; run under the agent-fleet extra")


class _Outcome:
    def __init__(self, provider, candidates):
        self.provider, self.candidates = provider, candidates
        self.status, self.endpoint_url, self.elapsed_s = "ok", "http://stub", 0.01


def _fan_out(main, monkeypatch, resolvers, identifier="HAZ-1004"):
    monkeypatch.setattr(main, "_discover_instance_resolvers",
                        lambda *a, **k: main.MeshResult.answered(resolvers))
    by_provider = {}
    for c in _measured():
        by_provider.setdefault(c.provider, []).append(c)

    async def _call(resolver, term, query, **_caller):
        return _Outcome(resolver["provider"], by_provider.get(resolver["provider"], []))

    monkeypatch.setattr(main, "_call_resolver", _call)
    return asyncio.run(main._resolve_instance(identifier, "q", ["SUSTAINMENT"]))


def test_CONTROL_without_the_declaration_the_live_failure_reproduces(main, monkeypatch):
    subject, prov = _fan_out(main, monkeypatch, _resolvers(s_namespaces=()))
    assert subject is None and prov["instance_match"] == "ambiguous_in_domain"


def test_with_the_declaration_HAZ_1004_binds_to_the_hazard(main, monkeypatch):
    subject, prov = _fan_out(main, monkeypatch, _resolvers())
    assert prov["instance_match"] != "ambiguous_in_domain"
    assert subject == _HAZ, prov


def test_the_log_line_names_what_matched_and_what_was_refused(main, monkeypatch, capsys):
    _fan_out(main, monkeypatch, _resolvers())
    line = next(l for l in capsys.readouterr().out.splitlines() if "fan-out for 'HAZ-1004'" in l)
    assert f"('{_EO}', 'HX3120004Q', 0.556)" in line and f"('{_EO}', 'AZV5001RA4-7', 0.5)" in line
    assert f"namespace_refused=[('{_EO}', 'HX3120004Q'), ('{_EO}', 'AZV5001RA4-7')]" in line


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher):
        assert "r.id_namespaces  AS id_namespaces" in cypher
        return type("R", (), {"data": lambda _s: self._rows})()


class _Driver:
    def __init__(self, rows):
        self._rows = rows

    def session(self):
        return _Session(self._rows)


def test_discovery_reads_the_edge_the_registrar_writes(main, monkeypatch):
    """THE JOIN: the registrar's real property bag, read back by engine-o's real discovery,
    decides the fan-out. A rename on any side breaks this rather than going quiet."""
    bag = _bag({**_MANIFEST, "id_namespaces": ["HAZ-"]})
    rows = [
        {"endpoint_url": "http://stub/eo", "provider": _EO, "timeout_s": None,
         "domains": ["SUSTAINMENT"], "id_namespaces": _bag(_MANIFEST)["id_namespaces"]},
        {"endpoint_url": bag["endpoint_url"], "provider": bag["provider"], "timeout_s": None,
         "domains": bag["domains"], "id_namespaces": bag["id_namespaces"]},
        # A string on the edge (a hand write, or a future stringifying hop) is not a declaration.
        {"endpoint_url": "http://stub/x", "provider": "stringly", "timeout_s": None,
         "domains": [], "id_namespaces": "HAZ-"},
    ]
    monkeypatch.setattr(main, "_NEO4J_DRIVER", _Driver(rows))
    # Discovery fills a module-level cache; pinned here so teardown puts it back.
    monkeypatch.setattr(main, "_INSTANCE_RESOLVERS_CACHE", None)
    monkeypatch.setattr(main, "_INSTANCE_RESOLVERS_CACHE_TS", 0.0)
    got = main._discover_instance_resolvers(refresh=True)
    by = {r["provider"]: r["id_namespaces"] for r in got.rows}
    assert by == {_EO: [], _S: ["HAZ-"], "stringly": []}
    kept, refused, _ = refuse_cross_namespace(_measured(), terms=["HAZ-1004"], resolvers=list(got.rows))
    assert [c.provider for c in kept] == [_S] and len(refused) == 2
