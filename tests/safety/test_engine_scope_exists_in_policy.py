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
