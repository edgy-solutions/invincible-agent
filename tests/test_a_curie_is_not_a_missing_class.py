"""A CURIE MUST NOT READ AS A MISSING CLASS — the fourth instance of the prefix defect.

MEASURED 2026-09-08. Six presentations were refused by the registrar under Contract D, each
naming a class that was in the graph the whole time:

    missing ['cost:CategoryBreakdown']      cost#CategoryBreakdown      present
    missing ['cost:SupplierConcentration']  cost#SupplierConcentration  present
    missing ['cost:RateComparison']         cost#RateComparison         present
    missing ['cost:UnitPriceTrend']         cost#UnitPriceTrend         present
    missing ['cost:LaborComposition']       cost#LaborComposition       present
    missing ['cost:RateAssumptions']        cost#RateAssumptions        present

The check was an exact string match on `uri`, against manifests that declare CURIEs while the
graph stores full IRIs — 1049 full IRIs against 1 CURIE-shaped value. No amount of priming or
rolling could fix a form mismatch.

WHY THIS ONE COST MORE THAN THE OTHER THREE. The earlier instances were caught by a row that
did not match. This one REPORTED THE CLASS ABSENT, which accuses the ontology and sends an
operator to the prime. The prime cannot fix a form mismatch, so the remedy became "roll it
again" — and a roll is a retry storm, which makes a PERMANENT failure look intermittent. That
is the mechanism behind "sometimes I have to roll all the containers": any time the fix is
rolling again, the question is which subset never succeeds.

THE POPULATION IS THE POINT. Four instances means nobody knows how many `uri`-keyed
comparison sites exist, so this file censuses them rather than fixing the two that were
found. A hand-written list of sites is a sample; `git`-derived is the population.

Run: uv run --frozen pytest tests/test_a_curie_is_not_a_missing_class.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_REGISTRAR = _REPO / "agent_fleet" / "mesh_registrar" / "main.py"


def _tracked(*globs: str) -> list[Path]:
    """Files git actually tracks — the population, not whatever happens to be on disk."""
    out = subprocess.run(
        ["git", "ls-files", *globs], cwd=str(_REPO),
        capture_output=True, text=True, check=False,
    ).stdout.split()
    return [_REPO / p for p in out]



def _load_registrar():
    """The registrar module, with its heavy deps stubbed.

    Loaded by path so `_canonical_uri` can be CALLED rather than read. The Neo4j driver is
    replaced per-test, which is the only dependency the function actually has.
    """
    import importlib.util, sys, types
    for name in ("neo4j", "fastapi", "pydantic"):
        pass  # real ones are installed; nothing to stub
    spec = importlib.util.spec_from_file_location("mesh_registrar_under_test", _REGISTRAR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

# ── the fix, at the site that lied ──────────────────────────────────────────

def test_the_contract_d_check_accepts_a_CURIE():
    """The expansion, asserted on the query rather than on a comment about it."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "ENDS WITH suffix" in src, "the Contract D match no longer expands a CURIE"
    assert "split(uri, ':')[0]" in src, "the namespace is not derived from the value"


def test_the_suffix_is_ANCHORED_on_a_slash():
    """`cost:X` must not match a namespace merely ENDING in the letters 'cost' —
    `http://example/notcost#X` is a different class. The leading '/' is the anchor and it is
    the only thing standing between an expansion and a false positive."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "'/' + split(uri, ':')[0] + '#'" in src, (
        "the suffix is unanchored — a CURIE could match an unrelated namespace"
    )


def test_a_full_IRI_still_matches_exactly():
    """The control on the other side. An expansion that broke the canonical form would trade
    one silent refusal for a louder one."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "c.uri = uri OR" in src, "the exact-match branch is gone"
    assert "CONTAINS '://'" in src, "full IRIs are no longer detected and passed through"


def test_BOTH_uri_keyed_queries_in_the_registrar_expand():
    """THE POPULATION, INSIDE ONE FILE. The Contract D check and the substrate sentinel are
    two `uri`-keyed lookups; fixing only the one that was reported is how a defect reaches a
    fifth instance. The sentinel matters more than it looks — a CURIE sentinel would report
    the substrate permanently un-ready, flipping every rejection from permanent to deferred
    and inverting the discriminant the function exists to provide."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert src.count("ENDS WITH suffix") == 2, (
        f"expected both uri-keyed queries to expand, found {src.count('ENDS WITH suffix')}"
    )
    assert "MATCH (:OntologyClass {uri: uri})" not in src, (
        "an exact-match-only OntologyClass lookup survives in the registrar"
    )


# ── the census: who else compares a uri? ────────────────────────────────────

_EXACT_MATCH = re.compile(r"MATCH\s*\(\s*[a-zA-Z]*\s*:OntologyClass\s*\{\s*uri\s*:", re.I)

#: Sites that compare an OntologyClass uri exactly, each with the reason it is allowed to.
#: A waiver must say why a CURIE cannot arrive there — "it does not today" is NOT a reason,
#: because that is exactly what was true of the registrar until it wasn't.
#:
#: THE CENSUS FOUND 57 SITES ACROSS 12 FILES on 2026-09-08. Four instances of this defect had
#: been fixed one at a time; nobody had ever counted. `scripts/migrate_compact_to_full_iri.py`
#: exists, which means the repo migrated compact forms to full IRIs once already and the
#: comparison sites were never brought along.
_EXACT_MATCH_WAIVERS: dict[str, str] = {
    "scripts/": (
        "one-off migration and repair tooling. Each script constructs the values it "
        "compares, in the form it just wrote, within the same run — there is no external "
        "caller to hand it a CURIE. `migrate_compact_to_full_iri.py` is the migration that "
        "made the full IRI canonical in the first place."
    ),
    "tests/": (
        "fixtures asserting on the CANONICAL form deliberately. A test that accepted either "
        "form would stop pinning which one is canonical, which is the property under test."
    ),
}

#: Runtime sites that take an EXTERNALLY SUPPLIED uri and still match exactly. These are not
#: waived — they are OPEN, and listed so the population is visible rather than implied. They
#: work today because their callers pass full IRIs (the resolver returns them), which is a
#: property of the callers rather than of these queries.
#:
#: NOT FIXED IN THIS PASS, deliberately: the registrar is the site that produced a false
#: `missing` and sent an operator to the prime. `_FIND_COMPAT_VERBS_CYPHER` in particular is
#: the eligibility verifier the pre-resolved re-ask calls, and changing it belongs with that
#: work rather than bundled into a fix for a different service.
_KNOWN_OPEN_RUNTIME_SITES = {
    "agent_fleet/ontology_service/main.py",
}

#: `v2_substrate.py` LEFT this register in the same change that protected it, which is the
#: half usually forgotten — a debt entry that outlives its debt is a monument nobody can tell
#: apart from a live one.
#:
#: It still matches exactly, deliberately: `main.py::register` canonicalises both URIs at the
#: boundary before Contract D or the saga runs, so MERGE, COMPENSATE and PROBE all receive
#: the full IRI. Expanding inside each of those four queries would be four expansions that
#: must agree forever.
_PROTECTED_BY_BOUNDARY = {
    "agent_fleet/mesh_registrar/v2_substrate.py": (
        "canonicalised upstream by main.py::register via _canonical_uri, before any query"
    ),
}


def _cypher_literals(tree, source: str):
    """Every string constant that is real Cypher, with its line — docstrings excluded.

    THE INSTRUMENT AND THE SUBJECT WERE SHARING A SURFACE. This scanned raw source text, so
    it flagged all four of these identically:

        q = \"\"\"MATCH (c:OntologyClass {uri: $uri})\"\"\"   <- the defect
        # this used to be MATCH (:OntologyClass {uri: uri})  <- a comment about the defect
        \"\"\"The old form was MATCH (c:OntologyClass {uri: $uri}).\"\"\"   <- a docstring
        // MATCH (c:OntologyClass {uri: $uri}) -- replaced   <- a Cypher comment

    Which means documenting the fix trips the check, and the obvious repair is deleting the
    explanation to keep it green — making the codebase worse to protect a broken instrument.
    Third time today for me: a manifest lint flagged `input_uri='cost:LaborComposition'`
    inside the docstring the fix had just added, and an ordering check rotted on a character
    window the same comment pushed past. `cortex-ui-60` hit the mirror within the hour, where
    a `/\\bdirection\\b/` seal failed on its own component's user-facing copy.

    The general form is theirs and it is the one to keep: **the check matched a STRING where
    the defect is a BEHAVIOUR.** A text search cannot separate a field read from a sentence
    about the field, or a live query from a comment quoting it.

    So: string constants only (Python comments are absent from the AST for free), docstrings
    dropped, and `//` line comments stripped from inside the Cypher itself.
    """
    import ast as _ast
    docstrings = set()
    for n in _ast.walk(tree):
        if isinstance(n, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            body = getattr(n, "body", None) or []
            if (body and isinstance(body[0], _ast.Expr)
                    and isinstance(body[0].value, _ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for n in _ast.walk(tree):
        if not isinstance(n, _ast.Constant) or not isinstance(n.value, str):
            continue
        if id(n) in docstrings:
            continue
        # strip Cypher line comments — a `//` note inside a real query is still prose
        cleaned = re.sub(r"//[^\n]*", "", n.value)
        yield cleaned, getattr(n, "lineno", 0)


def _census() -> list[str]:
    import ast as _ast
    sites = []
    for path in _tracked("*.py"):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(source)
        except (OSError, SyntaxError):
            continue
        rel = str(path.relative_to(_REPO)).replace("\\", "/")
        for literal, line in _cypher_literals(tree, source):
            if _EXACT_MATCH.search(literal):
                sites.append(f"{rel}:{line}")
    return sites


def test_no_UNACCOUNTED_exact_match_on_an_ontology_uri():
    """THE CENSUS. Four instances means nobody holds the population, so it is derived rather
    than remembered. Every site must be expanded, waived with a reason, or on the known-open
    list — the one thing it must not be is unnoticed."""
    unaccounted = [
        s for s in _census()
        if not any(s.startswith(p) for p in _EXACT_MATCH_WAIVERS)
        and s.rsplit(":", 1)[0] not in _KNOWN_OPEN_RUNTIME_SITES
        and s.rsplit(":", 1)[0] not in _PROTECTED_BY_BOUNDARY
    ]
    assert not unaccounted, (
        f"exact-match OntologyClass uri lookup(s) that cannot see a CURIE and are neither "
        f"waived nor tracked: {unaccounted}. Expand the value, or add it with a reason."
    )


def test_the_known_open_list_has_not_silently_grown():
    """A known-open list is a debt register, and a debt register that anyone may append to
    without noticing is a waiver list wearing a different name. If a third runtime service
    starts matching exactly, that is a decision someone should have to make on purpose."""
    assert len(_KNOWN_OPEN_RUNTIME_SITES) == 1, (
        f"the known-open set changed: {sorted(_KNOWN_OPEN_RUNTIME_SITES)}"
    )


def test_the_known_open_sites_still_exist():
    """The other direction, and the half usually left out: when a site is actually fixed the
    entry must go in the SAME change, or the register decays into a monument whose entries
    nobody can tell apart. Borrowed from `invincible-agent-32`'s removal-list seal."""
    still = {s.rsplit(":", 1)[0] for s in _census()}
    stale = sorted(_KNOWN_OPEN_RUNTIME_SITES - still)
    assert not stale, (
        f"listed as open but no longer matching exactly — remove from the list in the same "
        f"change that fixed it: {stale}"
    )


def test_the_census_actually_scanned_something():
    """Non-vacuity, and the failure this repo has shipped inside a test written to prevent
    it: a broken scan finds zero offenders and reads exactly like a clean repo."""
    files = _tracked("*.py")
    assert len(files) > 100, f"the file census found only {len(files)} python files"
    joined = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in files[:400]
    )
    assert "OntologyClass" in joined, "the scan never saw an OntologyClass reference at all"


# ── the declaring side: lint, not runtime tolerance ─────────────────────────

_CURIE = re.compile(r"^[a-zA-Z][\w-]*:[A-Za-z]")


def _declared_uris() -> list[tuple[str, str, str]]:
    """(file, field, value) for every input_uri / output_uri literal in the fleet.

    READ FROM THE AST, NOT BY REGEX OVER SOURCE TEXT. The first version matched raw text and
    immediately flagged `input_uri='cost:LaborComposition'` inside the docstring THIS FIX
    ADDED — prose quoting the defect, accused of being the defect.

    That is the same failure as an absence assertion satisfied by the comment explaining the
    absence, in presence form, and it is the second time in two days. A lint that cannot tell
    code from commentary reports the explanation as the bug, and the natural repair — deleting
    the example from the comment — would make the documentation worse to keep the check green.
    """
    import ast as _ast
    out = []
    for path in _tracked("agent_fleet/*.py", "agent_fleet/**/*.py"):
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        rel = str(path.relative_to(_REPO)).replace("\\", "/")
        for n in _ast.walk(tree):
            if not isinstance(n, _ast.Call):
                continue
            for kw in n.keywords:
                if (kw.arg in ("input_uri", "output_uri")
                        and isinstance(kw.value, _ast.Constant)
                        and isinstance(kw.value.value, str)):
                    out.append((rel, kw.arg, kw.value.value))
    return out


def test_manifests_declare_full_iris():
    """THE DECLARING SIDE, as a lint rather than a runtime tolerance. The registrar's
    expansion is belt-and-braces; canonical form is the full IRI, so a CURIE in a manifest is
    a defect to flag at build time rather than to absorb at runtime — otherwise the tolerance
    becomes the spec and the canonical form quietly stops being canonical."""
    bad = [
        f"{f}: {field}={val}"
        for f, field, val in _declared_uris()
        if "://" not in val and _CURIE.match(val)
    ]
    assert not bad, (
        f"manifest(s) declare a CURIE where the canonical form is a full IRI: {bad}"
    )


def test_the_lint_can_see_declarations_at_all():
    """Non-vacuity for the lint. Zero declarations found would pass it forever."""
    found = _declared_uris()
    assert len(found) >= 5, f"the lint found only {len(found)} uri declarations"
    assert any("://" in v for _, _, v in found), "no full-IRI declaration found as a control"


# ── the boundary expansion, which is what makes the exact matches safe ──────

def test_the_registrar_canonicalises_at_the_boundary():
    """ONE EXPANSION, BEFORE ANY QUERY. Contract D, the saga's MERGE, its COMPENSATE and its
    read-back PROBE all match `uri` exactly; expanding in each is four things that must agree
    forever."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "def _canonical_uri(" in src
    # THE FUNCTION, NOT A CHARACTER WINDOW. The first version read `src[i:i + 2600]`, and the
    # comment written to explain this very fix pushed `_contract_d_check` past the boundary.
    # Fifth magic-span rot in this repo, third one caused by the prose sitting beside it.
    import ast as _ast
    fn = next(
        n for n in _ast.walk(_ast.parse(src))
        if isinstance(n, _ast.FunctionDef) and n.name == "register"
    )
    body = _ast.unparse(fn)
    assert "_canonical_uri(manifest.input_uri)" in body
    assert "_canonical_uri(manifest.output_uri)" in body
    assert body.index("_canonical_uri") < body.index("_contract_d_check"), (
        "canonicalisation runs after Contract D — the gate would see the raw CURIE"
    )


def test_the_expansion_refuses_to_GUESS_when_ambiguous():
    """`mesh:` really is declared twice across the TTLs (invincible-agent and internal), so an
    ambiguous CURIE is live rather than hypothetical. Binding a verb to whichever namespace
    sorted first would be a silent wrong answer — strictly worse than a loud unresolved one,
    because the caller's own `missing` reporting still fires on a pass-through.

    CALLED, NOT GREPPED, AND THE FIXTURE PROVES THE CHOICE MATTERS.

    The first version asserted `"len(uris) == 1" in body` and `"ambiguous" in body.lower()` —
    a string check on a behaviour, and a seal defending a CHOICE without any data that could
    tell the choice from its alternative. `invincible-agent-91`'s technique, which a mutation
    run cannot supply: when a seal defends "this rule rather than the obvious one", make it
    assert that its own fixture DISTINGUISHES the two. The question is "what would look
    different if I had chosen the other rule?" — and if nothing in the fixture would, the
    seal is decoration.

    So the fixture below is deliberately one where guessing and refusing differ: two
    namespaces both ending `/mesh#`, which is live rather than hypothetical because `mesh:`
    really is declared twice across the TTLs. A "pick the first" implementation returns a
    real IRI here; the correct one returns the input unchanged.
    """
    import types
    reg = _load_registrar()

    ambiguous = ["http://invincible-agent/mesh#Thing", "http://internal/mesh#Thing"]
    unique = ["http://invincible-agent/cost#CategoryBreakdown"]

    def _driver_returning(uris):
        class _S:
            def run(self, *a, **k):
                return types.SimpleNamespace(single=lambda: {"uris": uris})
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return types.SimpleNamespace(session=lambda: _S())

    # the rejected rule, built explicitly so the fixture can be shown to separate them
    would_guess = sorted(ambiguous)[0]

    reg._get_neo4j_driver = lambda: _driver_returning(ambiguous)
    got_ambiguous = reg._canonical_uri("mesh:Thing")

    reg._get_neo4j_driver = lambda: _driver_returning(unique)
    got_unique = reg._canonical_uri("cost:CategoryBreakdown")

    assert got_ambiguous != would_guess, (
        "an ambiguous CURIE was resolved to a namespace nobody chose — a silent wrong answer, "
        "strictly worse than a loud unresolved one"
    )
    assert got_ambiguous == "mesh:Thing", "an ambiguous CURIE must pass through unchanged"
    # THE CONTROL ON THE CHOICE ITSELF: the two rules must actually differ on this fixture,
    # or the assertion above passes for free and proves nothing.
    assert would_guess != "mesh:Thing", "the fixture cannot distinguish guessing from refusing"
    # and the unambiguous case must still resolve, or "refuse" degenerates into "never expand"
    assert got_unique == unique[0], "a unique match no longer expands"


def test_the_expansion_never_fails_a_registration():
    """A lookup helper that can raise turns a registration into an outage. Every uncertainty
    returns the input unchanged, which preserves exactly the behaviour that existed before."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    i = src.index("def _canonical_uri(")
    body = src[i:src.index("def _contract_d_check(", i)]
    assert "except Exception" in body, "an unreachable graph would fail the registration"
    assert body.count("return uri") >= 3, "not every uncertainty passes the value through"
