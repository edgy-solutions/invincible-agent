"""ADR-0037 §1's coverage gate, verbs only in v1: every registered verb has a page that explains it.

ONE ARM PER VERB, RED FOR EVERY VERB NO PAGE EXPLAINS. A verb is "explained" when some
`mesh:DocPage` in `setup/ontologies/docs_corpus.ttl` (the compiled corpus, which is what primes)
carries `mesh:explains <verb>`. Today almost every verb is uncovered, so `_ALLOWLIST` names them
(architect 10-23 #3: "allowlisted by name for now"). The list is meant to shrink, and it is
guarded both ways: an entry whose verb gained a page reds as stale, and an entry naming no
registered verb reds as a typo, because an exemption nobody can falsify exempts anything.

THE POPULATION IS DERIVED, NEVER LISTED. `iagent_pure.registration_sites.scan` reads every call
to `register_engine_to_mesh` (aliases included) under `agent_fleet/` and `src/`, the same
population the re-register and compact-verb seals read. A call whose `verb=` is not a literal is
reported `unresolved` by the scanner. Each such file is resolved below by a NAMED rule that
reads the table it iterates. An unresolved file with no rule reds, and so does a rule that
yields nothing. A file nobody could read would otherwise be a quietly shorter population, and
every verb it registers would pass this gate by being absent.

WHAT IT DOES NOT DECIDE. ADR-0037 §1 says "a `concept` doc"; the dispatch says "a page". This
gate counts any DocPage, whatever its `doc_kind`. On 2026-10-23 no covering page is a `concept`:
all six covered verbs are covered by `how-to` runbooks. Which reading binds is the architect's call.

Run: uv run --frozen --extra agent-fleet pytest tests/docs/test_every_registered_verb_has_a_page.py -q
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

rdflib = pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from iagent_pure.registration_sites import python_files, scan  # noqa: E402

_CORPUS = _REPO / "setup" / "ontologies" / "docs_corpus.ttl"
_MESH = "http://invincible-agent/mesh#"
_DOCPAGE = rdflib.URIRef(_MESH + "DocPage")
_EXPLAINS = rdflib.URIRef(_MESH + "explains")
_COMPACT = re.compile(r"^[a-z][a-zA-Z0-9]*:[a-z][A-Za-z0-9]*$")


# ── the population ──────────────────────────────────────────────────────────────────────────────

def _dict_verb_entries(path: Path) -> set[str]:
    """Every `"verb": "<prefix>:<name>"` string entry in a dict literal in `path`. These are the
    tables the table-driven engines iterate when they register."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "verb"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    out.add(v.value)
    return out


def _module_constant(path: Path, name: str) -> set[str]:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            return {node.value.value}
    return set()


def _graph_manifest_verbs() -> set[str]:
    """graph_host registers `p["verb_iri"]` once per ratified manifest in `policy/graphs/`."""
    import yaml

    out = set()
    for p in sorted((_REPO / "policy" / "graphs").glob("*.yaml")):
        verb = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("verb")
        if isinstance(verb, str):
            out.add(verb)
    return out


def _in_file(rel: str):
    return lambda: _dict_verb_entries(_REPO / rel)


# file -> how its non-literal `verb=` is read. Named per file: adding a table-driven engine is a
# red here until somebody says where its verbs live.
_RESOLVERS = {
    "agent_fleet/cost_agent/main.py": _in_file("agent_fleet/cost_agent/main.py"),
    "agent_fleet/docs_agent/main.py": _in_file("agent_fleet/docs_agent/main.py"),
    "agent_fleet/finance_agent/main.py": _in_file("agent_fleet/finance_agent/main.py"),
    "agent_fleet/planning_agent/main.py": _in_file("agent_fleet/planning_agent/main.py"),
    "agent_fleet/safety_agent/main.py": _in_file("agent_fleet/safety_agent/main.py"),
    "agent_fleet/graph_host/main.py": _graph_manifest_verbs,
    # `verb=_notice_parts.VERB`
    "agent_fleet/ontology_service/main.py": lambda: _module_constant(
        _REPO / "agent_fleet/ontology_service/notice_parts.py", "VERB"),
}


def _sites():
    return scan(python_files(_REPO / "agent_fleet", _REPO / "src"), root=_REPO)


def registered_verbs() -> dict[str, str]:
    """verb -> the file that registers it, literal sites first, then the resolved tables."""
    sites = _sites()
    out = dict(sites.verbs)
    for rel in sorted(sites.unresolved):
        resolver = _RESOLVERS.get(rel)
        if resolver is None:
            continue  # reds in test_every_unresolved_registration_has_a_named_resolver
        for verb in sorted(resolver()):
            out.setdefault(verb, rel)
    return out


# ── the corpus ──────────────────────────────────────────────────────────────────────────────────

def _corpus() -> "rdflib.Graph":
    return rdflib.Graph().parse(_CORPUS, format="turtle")


def _compact(g: "rdflib.Graph", term) -> str:
    try:
        prefix, _ns, local = g.compute_qname(term)
        return f"{prefix}:{local}"
    except Exception:  # noqa: BLE001
        return str(term)


def page_edges() -> dict[str, list[str]]:
    """page (compact) -> its `mesh:explains` targets (compact), for every DocPage, edgeless too."""
    g = _corpus()
    out = {}
    for page in sorted(g.subjects(rdflib.RDF.type, _DOCPAGE)):
        out[_compact(g, page)] = sorted(_compact(g, o) for o in g.objects(page, _EXPLAINS))
    return out


def explained() -> dict[str, list[str]]:
    """target (compact) -> the pages that explain it."""
    out: dict[str, list[str]] = {}
    for page, targets in page_edges().items():
        for t in targets:
            out.setdefault(t, []).append(page)
    return out


# ── today's exemptions ──────────────────────────────────────────────────────────────────────────

# Registered verbs no page explains yet, measured 2026-10-23 on lane/01-207. Each is a page somebody
# owes, written from doing the task (docs/runbooks/README.md, "Do not write a page for a task
# nobody here has done"), never a generated stub (ADR-0037 §5).
_ALLOWLIST = frozenset({
    "mesh:analyzeDataset",
    "mesh:analyzeWithCodeAgent",
    "mesh:assessDeferralRisk",
    "mesh:assessImpact",
    "mesh:checkFreshness",
    "mesh:costCategoryBreakdown",
    "mesh:costLaborComposition",
    "mesh:costLotBreakdown",
    "mesh:costPriceComposition",
    "mesh:costRateAssumptions",
    "mesh:costRateComparison",
    "mesh:costSupplierConcentration",
    "mesh:costUnitPriceTrend",
    "mesh:describeAsset",
    "mesh:draftRiskAssessment",
    "mesh:enumerateCatalog",
    "mesh:explain",
    "mesh:failureTrendForThisPlatformByMonth",
    "mesh:filterByTag",
    "mesh:finBurnRate",
    "mesh:finEacCalculation",
    "mesh:finEacComparison",
    "mesh:finFundingStatus",
    "mesh:finPerformanceIndices",
    "mesh:finVarianceAnalysis",
    "mesh:finVarianceDrivers",
    "mesh:findOrphanedHazards",
    "mesh:findSchema",
    "mesh:lookupOwnership",
    "mesh:packageExport",
    "mesh:planCapabilityPath",
    "mesh:planCommitScenario",
    "mesh:planCostCurve",
    "mesh:planCoverageGap",
    "mesh:planDependencyNeighborhood",
    "mesh:planDependencyViolations",
    "mesh:planDiff",
    "mesh:planFundingGap",
    "mesh:planMaturityGrid",
    "mesh:planProcessEvolution",
    "mesh:planSchedule",
    "mesh:planSessionChanges",
    "mesh:planSiteLoad",
    "mesh:planTechFootprint",
    "mesh:proposeDisposition",
    "mesh:queryKnowledgeGraph",
    "mesh:retrieveKnowledge",
    "mesh:traceLineage",
    "mesh:whatFailedOnThisPart",
    "mesh:whichPartsDoesThisNoticeAffect",
})


# ── the population is real ──────────────────────────────────────────────────────────────────────

def test_every_unresolved_registration_has_a_named_resolver():
    missing = sorted(set(_sites().unresolved) - set(_RESOLVERS))
    assert not missing, (
        f"{missing} register a verb this gate cannot read: say where its verbs live in _RESOLVERS. "
        f"Skipping it would let every verb it registers pass the gate by being absent.")


@pytest.mark.parametrize("rel", sorted(_RESOLVERS))
def test_every_resolver_yields_a_compact_verb(rel):
    got = _RESOLVERS[rel]()
    assert got, f"the resolver for {rel} yields no verb: its table moved or was renamed"
    assert all(_COMPACT.match(v) for v in got), sorted(v for v in got if not _COMPACT.match(v))


def test_no_resolver_is_left_over():
    stale = sorted(set(_RESOLVERS) - set(_sites().unresolved))
    assert not stale, f"{stale} no longer register through a computed verb; remove the resolver"


def test_the_population_holds_the_verbs_a_page_already_explains():
    # Control: the two verbs adding-an-engine.md explains are registered by literal sites, and
    # mesh:explain only through docs_agent's table, so all three halves of the derivation are read.
    verbs = registered_verbs()
    for v in ("mesh:resolveInstance", "mesh:enumerateInstances", "mesh:explain",
              "mesh:finProgramBrief"):
        assert v in verbs, f"{v} is registered but the derivation did not find it"


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", sorted(registered_verbs()))
def test_every_registered_verb_has_a_page(verb):
    if verb in _ALLOWLIST:
        pytest.skip(f"{verb}: allowlisted, no page yet")
    pages = explained().get(verb)
    assert pages, (
        f"{verb} (registered in {registered_verbs()[verb]}) has no page that explains it. "
        f"Write one from doing the task, or add it to _ALLOWLIST with the architect's OK.")


def test_no_allowlisted_verb_has_a_page():
    stale = sorted(v for v in _ALLOWLIST if v in explained())
    assert not stale, f"{stale} now have pages: take them off _ALLOWLIST"


def test_every_allowlisted_name_is_a_registered_verb():
    unknown = sorted(_ALLOWLIST - set(registered_verbs()))
    assert not unknown, f"{unknown} are not registered verbs: the allowlist exempts nothing real"


def test_the_gate_is_asserting_something():
    # Control: if no registered verb had a page, every gate arm above would be a skip.
    verbs, ex = registered_verbs(), explained()
    assert {v for v in verbs if v in ex} >= {"mesh:resolveInstance", "mesh:seedCanvas"}
