"""An engine's declared scope must EXIST in the policy vocabularies — derived, not listed.

**THE GAP THIS CLOSES, AND IT IS A GAP WITH NO SEAL OF ANY KIND.** An engine names its scope in
code (`OWNER_PERSONA`, `DOMAINS`); `policy/personas.yaml` and `policy/domains.yaml` hold the
vocabularies those names must come from. **Nothing compared them.** The coupling was enforced
only INDIRECTLY — `PolicyBundle._validate` refuses a *group grant* naming an unknown persona — so
it fires only once somebody writes the grant, and never for an engine whose grant nobody wrote yet.

That is exactly how it played out twice, in opposite directions:

    engine-cost   named COST_ANALYST before it existed in personas.yaml. Caught, because the
                  grant WAS written and the sync refused it. The indirect check worked.
    engine-safety named nothing at all. Registered with owner_persona=None and domains=None —
                  and a verb with NO domains is DOMAIN-AGNOSTIC, visible to EVERY caller, which
                  is the inverse of the gate ADR-0051 §5 is built on. No grant existed to refuse,
                  so no check fired, and the state was invisible for as long as it went unnoticed.

**A CHECK THAT ONLY FIRES WHEN SOMEONE WRITES A SECOND FILE IS NOT A CHECK ON THE FIRST ONE.**

── THE POPULATION IS DERIVED, WITH EXCLUSIONS THAT CARRY REASONS ───────────────────────────────
The set of engines is globbed from `agent_fleet/*/main.py` and filtered to those that actually
call `register_engine_to_mesh`, so an engine added tomorrow is covered on arrival. Every member is
either asserted or named in `_NO_SCOPE_YET` **with a reason** — a hand-written inclusion list fails
silently when something is missing from it, and an exclusion list fails loudly.

── WHY IT READS THE SOURCE WITH `ast` RATHER THAN IMPORTING ────────────────────────────────────
Importing an engine's `main` builds its app and can reach for env vars and clients. `ast` reads the
module-level assignments without running anything — and it resolves a one-hop name reference,
because `cost_agent` spells `DOMAINS = [DOMAIN]`. A regex would have read that as a domain literally
named "DOMAIN" and either failed honest data or passed on a name nothing defines.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_FLEET = _REPO / "agent_fleet"

#: Engines that register verbs but declare NO scope constants, each with the reason it is not a
#: defect. An entry here is a claim, not a silence — and the seal below fails if a name in this
#: map has stopped being a registering engine, so the exclusions cannot rot into fiction.
_NO_SCOPE_YET: dict[str, str] = {
    "data_analyst": "Engine DA serves every caller; its scope is the per-asset dataset gate, not a domain.",
    "datahub_wrapper": "catalog wrapper — DATA_ENGINEERING gating is the 2026-07-02 stopgap on query_metadata, not a verb domain.",
    "graph_host": "registers from policy/graphs/*.yaml ROWS, which carry their own owner_persona and domains per graph.",
    "neo4j_expert": "substrate expert, domain-agnostic by design — it answers about the graph, not about a domain's subjects.",
    "ontology_service": "Engine O is the resolver; its registrations are per-domain providers named at each call site.",
    "restate_analyst": "the workflow substrate registers infrastructural verbs, not domain ones.",
    "weaviate_expert": "substrate expert, same as neo4j_expert.",
}


def _registering_engines() -> dict[str, Path]:
    """Every `agent_fleet/*/main.py` that calls `register_engine_to_mesh` — the population."""
    out: dict[str, Path] = {}
    for p in sorted(_FLEET.glob("*/main.py")):
        if "register_engine_to_mesh" in p.read_text(encoding="utf-8"):
            out[p.parent.name] = p
    return out


def _module_scope(path: Path) -> dict:
    """The scope each `register_engine_to_mesh` CALL passes — not the module's constants.

    **THE FIRST VERSION READ `OWNER_PERSONA`/`DOMAINS` AS MODULE CONSTANTS AND WAS WRONG.** It
    reported `planning_agent` as unscoped, and Engine P is correctly scoped — it passes
    `domains=["PORTFOLIO_PLANNING"]` INLINE at each of its three call sites rather than hoisting a
    constant. **An over-constrained seal, which fails honest data rather than dishonest data**, and
    that is the one kind of wrong check that gets "fixed" by deleting it.

    The fact under test was never "does this module define a constant" — it is **what scope does
    this engine actually register with**, and that lives in the call. Reading the call covers both
    spellings and is strictly closer to the subject.

    Name references are resolved one hop against module-level literals, because `cost_agent` spells
    `DOMAINS = [DOMAIN]`. An unresolvable expression yields None and the engine must then be
    excluded with a reason — which is how `graph_host`, registering from `p["owner_persona"]` rows,
    lands honestly outside this seal rather than passing it by accident.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # The ASSIGNMENT NODE, not the evaluated value. Storing only literals lost the case that
    # matters: `DOMAINS = [DOMAIN]` is not a literal, so `DOMAINS` never entered the table and
    # `domains=DOMAINS` resolved to None — the reader reporting "unscoped" for an engine that is
    # scoped through two hops. Keeping the node lets resolution recurse.
    assigned: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                assigned[t.id] = node.value

    def value_of(node, depth: int = 0):
        if node is None or depth > 4:        # depth guard: a cycle must not hang the suite
            return None
        try:
            return ast.literal_eval(node)
        except (ValueError, SyntaxError):
            pass
        if isinstance(node, ast.Name):                       # domains=DOMAINS
            return value_of(assigned.get(node.id), depth + 1)
        if isinstance(node, ast.List):                       # DOMAINS = [DOMAIN]
            out = []
            for elt in node.elts:
                v = value_of(elt, depth + 1)
                if v is None:
                    return None
                out.append(v)
            return out
        return None

    domains: set = set()
    personas: set = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "register_engine_to_mesh"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        d = value_of(kw.get("domains"))
        if d:
            domains.update(d)
        p = value_of(kw.get("owner_persona"))
        if isinstance(p, str):
            personas.add(p)

    return {
        "DOMAINS": sorted(domains) or None,
        "OWNER_PERSONA": sorted(personas)[0] if len(personas) == 1 else (sorted(personas) or None),
    }


def _vocab(filename: str, key: str) -> set:
    doc = yaml.safe_load((_REPO / "policy" / filename).read_text(encoding="utf-8")) or {}
    return set(doc.get(key) or [])


def test_the_population_is_not_empty_and_the_vocabularies_load():
    """THE FLOOR. Every assertion below quantifies over these three; an empty one makes the whole
    file pass while measuring nothing."""
    assert _registering_engines(), "no registering engines found — the derivation is broken"
    assert _vocab("personas.yaml", "personas"), "personas.yaml read as empty"
    assert _vocab("domains.yaml", "domains"), "domains.yaml read as empty"


def test_every_registering_engine_is_either_scoped_or_excluded_WITH_A_REASON():
    """THE PARTITION. No engine may be undecided — that is the state safety sat in.

    A missing entry fails here rather than quietly falling outside the assertions below, which is
    the whole difference between an exclusion list and an inclusion list.
    """
    engines = _registering_engines()
    undecided = [
        name for name, path in engines.items()
        if name not in _NO_SCOPE_YET and not _module_scope(path)["DOMAINS"]
    ]
    assert not undecided, (
        f"{undecided} register verbs, declare no DOMAINS, and are not excluded with a reason. A "
        "verb with no domains is DOMAIN-AGNOSTIC — visible to every caller regardless of "
        "entitlement — so this is a grant decision made by an omitted argument"
    )


def test_the_exclusions_still_name_registering_engines():
    """An exclusion for an engine that no longer registers is a claim about nothing, and it would
    keep a real gap hidden if that name were ever reused."""
    engines = _registering_engines()
    stale = sorted(set(_NO_SCOPE_YET) - set(engines))
    assert not stale, f"excluded but no longer registering verbs: {stale}"
    for name, reason in _NO_SCOPE_YET.items():
        assert len(reason) > 20, f"{name}'s exclusion reason is too thin to review: {reason!r}"


@pytest.mark.parametrize("engine", sorted(set(_registering_engines()) - set(_NO_SCOPE_YET)))
def test_the_declared_domain_exists_in_the_vocabulary(engine):
    """THE SEAL. A domain the policy files do not know is a scope that entitles nobody."""
    declared = _module_scope(_registering_engines()[engine])["DOMAINS"]
    assert declared, f"{engine} declares no DOMAINS but is not excluded"
    known = _vocab("domains.yaml", "domains")
    unknown = sorted(set(declared) - known)
    assert not unknown, (
        f"{engine} registers under {unknown}, which policy/domains.yaml does not declare — the "
        "sync refuses every group grant naming it, so no cell can ever carry this domain and the "
        "engine's verbs are unreachable by entitlement"
    )


@pytest.mark.parametrize("engine", sorted(set(_registering_engines()) - set(_NO_SCOPE_YET)))
def test_the_declared_persona_exists_in_the_vocabulary(engine):
    """Same check for the persona. It does NOT gate — `src/iagent/auth.py` discards the persona
    half before any verb filter — but a persona absent from the vocabulary makes the group grant
    unwritable, which is how the cell that WOULD gate never gets created."""
    persona = _module_scope(_registering_engines()[engine])["OWNER_PERSONA"]
    if persona is None:
        pytest.skip(f"{engine} declares no OWNER_PERSONA; the domain half is what gates")
    assert persona in _vocab("personas.yaml", "personas"), (
        f"{engine} answers as {persona!r}, which policy/personas.yaml does not declare — "
        "`PolicyBundle._validate` refuses any group grant naming it"
    )


def test_a_cell_actually_grants_each_declared_domain():
    """THE OTHER DIRECTION, and the one that would have caught engine-safety on day one.

    A domain in the vocabulary that NO group grants is reachable by nobody: registration is not
    entitlement, and `policy/groups.yaml` records four engines that learned it the same way.
    """
    groups = yaml.safe_load((_REPO / "policy" / "groups.yaml").read_text(encoding="utf-8")) or {}
    granted = {
        g["domain"]
        for grp in (groups.get("groups") or {}).values()
        for g in (grp.get("grants") or [])
    }
    ungranted = []
    for engine, path in _registering_engines().items():
        if engine in _NO_SCOPE_YET:
            continue
        for d in _module_scope(path)["DOMAINS"] or []:
            if d not in granted:
                ungranted.append(f"{engine} -> {d}")
    assert not ungranted, (
        "engine domain(s) that no group grants — the verbs register and no user can reach "
        f"them: {ungranted}"
    )


def test_the_checker_can_say_no():
    """THE CONTROL. The resolver has only ever been handed real names; a resolver that returned
    nothing would satisfy every membership test above by comparing empty sets."""
    scope = _module_scope(_FLEET / "safety_agent" / "main.py")
    assert scope["DOMAINS"] == ["SUSTAINMENT"], f"the ast reader is broken: {scope}"
    assert scope["OWNER_PERSONA"] == "SAFETY_ENGINEER", f"the ast reader is broken: {scope}"
    # THE INDIRECTION CASE, asserted by name because it is what defeats a regex: cost_agent
    # spells `DOMAINS = [DOMAIN]`, and a reader that could not follow it would report a domain
    # literally called "DOMAIN" — failing honest data, which is the kind of wrong check that
    # gets deleted rather than fixed.
    cost = _module_scope(_FLEET / "cost_agent" / "main.py")
    assert cost["DOMAINS"] == ["PRODUCTION_COST"], (
        f"the one-hop name resolution is broken — cost_agent reads as {cost['DOMAINS']}"
    )
    assert "NOT_A_REAL_DOMAIN" not in _vocab("domains.yaml", "domains")


# ---------------------------------------------------------------------------
# THE ENDPOINT SHAPE — a second coupling with no seal until 2026-09-14
# ---------------------------------------------------------------------------

#: Fleet CAPABILITY verbs whose endpoint is one-per-engine BY DESIGN — a provider answers for a
#: whole class, so there is no verb to put in the path. Keyed on the VERB rather than on a URL
#: pattern, because the question is what kind of registration this is, and only the verb says so.
_FIXED_ENDPOINT_VERBS = {"mesh:resolveInstance", "mesh:enumerateInstances"}


def _endpoint_templates(path: Path) -> list[tuple[str, str, bool]]:
    """`(verb, endpoint_url-as-source, varies_per_registration)` for each registration call.

    ⛔ AND THE RULE IS "THE URL VARIES PER VERB", NOT "THE URL CONTAINS `/measure/`" — my second
    over-constraint on the same seal in ten minutes. Checking for the literal substring flagged
    engine-cost's `f"{base}/{spec['endpoint']}"`, which is CORRECT: each spec carries its own
    endpoint, so that URL does vary per registration. I had encoded one engine's SPELLING of the
    property instead of the property.

    `varies` counts interpolations: one (`{base}`) means a constant path shared by every verb —
    the defect — and two or more means something per-registration is in the path. That is the
    fact the registrar cares about, because it bakes `endpoint_url` per verb and a shared URL
    leaves the mesh unable to reach one verb rather than another.

    Read as SOURCE rather than evaluated: the question is the SHAPE of the f-string — whether the
    verb appears in the path — and evaluating it would need a running engine and answer something
    else.

    ⛔ THE FIRST VERSION RETURNED ONLY THE URL AND WAS OVER-CONSTRAINED — the third time today I
    wrote a seal that fails HONEST data. It flagged cost, finance and planning for registering
    `/resolve_instance` and `/enumerate_instances` with no per-verb segment, which is CORRECT for
    those: an instance provider answers for a whole class, so there is no verb to put in a path.
    The URL alone cannot distinguish a measure from a provider; the VERB can, so the verb is
    carried alongside and the rule applies only where it means something.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "register_engine_to_mesh":
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            url = kw.get("endpoint_url")
            if url is None:
                continue
            verb_node = kw.get("verb")
            try:
                verb = str(ast.literal_eval(verb_node)) if verb_node is not None else ""
            except (ValueError, SyntaxError):
                verb = ""      # a loop variable — `v["verb"]`, `spec["verb"]`
            interpolations = sum(
                1 for n in ast.walk(url) if isinstance(n, ast.FormattedValue)
            )
            out.append((verb, ast.unparse(url), interpolations >= 2))
    return out


#: Engines whose registered endpoints legitimately carry no per-verb segment, each with a reason.
#: An exclusion list rather than an inclusion list: a new engine is covered on arrival and has to
#: argue its way OUT, which is the direction that fails loudly.
_ENDPOINT_EXEMPT: dict[str, str] = {
    "data_analyst": "Engine DA registers a single analysis endpoint; its verbs are selected by payload, not by URL.",
    "datahub_wrapper": "catalog wrapper - its endpoints are catalog operations rather than measures.",
    "graph_host": "registers from policy/graphs/*.yaml rows, each carrying its own endpoint.",
    "neo4j_expert": "substrate expert - one query endpoint, no per-verb measures.",
    "ontology_service": "Engine O registers resolver/provider endpoints named per capability, not per measure.",
    "restate_analyst": "workflow substrate - infrastructural endpoints.",
    "weaviate_expert": "substrate expert, same as neo4j_expert.",
    "safety_agent": "checked explicitly below, so a change to ITS shape reds by name rather than by count.",
}


def test_THE_VERB_IS_IN_THE_PATH_not_in_the_body():
    """**THE DIVERGENCE THAT MADE EVERY SAFETY VERB UNCALLABLE, and nothing checked it.**

    engine-safety registered ONE endpoint — `{base}/analyze` — and expected the verb in the
    envelope. The fleet's dispatcher puts the verb in the URL PATH and sends `{query, params}`
    with no `fn`, so every dispatch arrived as a 422 on a field the caller had no reason to send.

    **The engine's own seals were green throughout**, because they posted in the engine's dialect:
    the test agreed with the engine, both disagreed with the fleet, and that agreement is exactly
    what made it look verified. A seal that speaks its subject's dialect cannot detect that the
    dialect is wrong — so this one is derived from the OTHER ENGINES instead.

    And the registrar's own constraint is the affirmative argument, in engine-cost's words: it
    BAKES `endpoint_url` into the mesh PER VERB, so a single body-dispatched route gives every
    verb the same URL and the mesh has no way to reach one rather than another.
    """
    offenders: list[str] = []
    for engine, path in _registering_engines().items():
        if engine in _ENDPOINT_EXEMPT:
            continue
        for verb, expr, varies in _endpoint_templates(path):
            if verb in _FIXED_ENDPOINT_VERBS:
                continue
            if not varies:
                offenders.append(f"{engine}: {verb or '<loop verb>'} -> endpoint_url={expr}")
    assert not offenders, (
        "engine(s) registering an endpoint with no per-verb segment — the registrar bakes one "
        f"URL per verb, so every verb would carry the same address:\n  " + "\n  ".join(offenders)
    )


def test_ENGINE_S_SPECIFICALLY_registers_one_endpoint_per_verb():
    """Named rather than counted, because safety_agent is exempted above and an exemption that
    hides the very engine the seal was written for is the fixture-that-cannot-fail."""
    exprs = [e for _v, e, _x in _endpoint_templates(_FLEET / "safety_agent" / "main.py")]
    measures = [e for e in exprs if "/measure/" in e]
    assert measures, f"engine-safety registers no per-verb measure endpoint: {exprs}"
    assert any("v['fn']" in e or 'v["fn"]' in e for e in measures), (
        f"the measure endpoint does not interpolate the verb: {measures}"
    )
    assert not any("/analyze" in e for e in exprs), (
        "the single-door /analyze endpoint is back — the dispatcher cannot call it"
    )


def test_the_endpoint_reader_can_say_no():
    """THE CONTROL. A reader that returned nothing would satisfy the assertions above by having
    no offenders — so it must be shown to find the real expressions it quantifies over."""
    cost = [e for _v, e, _x in _endpoint_templates(_FLEET / "cost_agent" / "main.py")]
    assert cost, "the reader found no endpoint_url in engine-cost, which registers several"
    assert any("{" in e for e in cost), f"engine-cost reads as having no interpolated endpoint: {cost}"
    for name, reason in _ENDPOINT_EXEMPT.items():
        assert len(reason) > 20, f"{name}'s endpoint exemption reason is too thin to review"
