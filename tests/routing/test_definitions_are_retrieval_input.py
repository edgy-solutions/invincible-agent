"""A class definition is RETRIEVAL INPUT, not documentation.

Weaviate embeds ``"<label> — <definition>"`` and Engine O's hybrid search scores a user's
query against that text. So the definition is not prose a human reads; it is one side of a
similarity comparison. What reads well to a person can score badly as a discriminator, and
three authoring habits actively poison it:

1. **QUERY-SHAPED EXAMPLES.** A definition containing user questions is scored against user
   questions and wins on FORMAT rather than subject. Measured 2026-08-15: ``idp:Column``
   carried two quoted questions and the dotted identifier ``orders.amount``, and it ranked
   top for identifier-shaped queries it had no business winning — the LLM had to override
   recall on 5 of 6 disagreements, correctly.
2. **SIBLING-NAME BLEED.** A definition naming another class competes for that class's
   traffic. ``idp:Pipeline`` said "produces or transforms Datasets" and won
   "list the datasets in publog" by naming its own competitor. Removing it fixed that row.
3. **EXAMPLE IDENTIFIERS.** Dotted or coded tokens make every identifier-shaped query
   resemble the definition.

## THE SEVEREST CASE — the embedding being retrieved contains the text being embedded

`maintenance_extension.ttl`'s Work Instruction definition literally reads
*"Matrix queries: 'Show me the maintenance steps for the rotor assembly', ..."* — and
`test_classify_route.py` asserts that exact string routes to that class. **The test cannot
fail.** Its green proves the definition quotes the query, not that retrieval works.

That is the same family as the fixture supplying its own provenance, the test asserting a
value the runner set, and the seeder manufacturing the substrate it validates against: *a
system that repairs the condition it is checking is green by construction.* This is its most
literal instance — the repair is verbatim string copying.

## WHY A RATCHET RATHER THAN A HARD FAIL

The habits are a house style, not one class's mistake: 11 definitions across 8 files at the
time of writing. Failing outright would add red to a suite that is already not green and
would tempt someone to "fix" it by deleting the guard. So the baseline below is
GRANDFATHERED and the assertion is that it MUST NOT GROW. The baseline is a debt list; it
should shrink to empty.

## EXPECTATION, PRE-POSITIONED SO NOBODY MISREADS IT

When the grandfathered examples are stripped, **the matrix rows that quote themselves will
move, and some will go red.** THAT IS THIS GUARD WORKING, NOT A REGRESSION. Those rows were
passing because the definition contained the query; removing the query removes the guarantee
and leaves the real retrieval question exposed for the first time. Restoring the examples to
make the tests pass would re-create the circularity in one move — do not do it. Fix the
definition so it discriminates on SUBJECT, or accept the row's honest failure and file it.
"""
from __future__ import annotations

import pathlib
import re

import pytest

try:
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF, RDFS
except ImportError:  # pragma: no cover
    pytest.skip("rdflib not installed", allow_module_level=True)

ROOT = pathlib.Path(__file__).resolve().parents[2]
ONTOLOGIES = ROOT / "setup" / "ontologies"
MATRIX = ROOT / "tests" / "routing" / "test_classify_route.py"

_QUOTED = re.compile(r"['\"]([^'\"]{12,})['\"]")
_INTERROGATIVE = re.compile(
    r"\b(what|which|who|where|when|how|why|show me|list all|tell me|give me|describe)\b", re.I)
# Hierarchy phrasings that legitimately name another class — those are true structural
# facts ("Subtype of Dataset"), not filler, and must not be flagged.
# `[\w:]*` not `\w*` — the trailing token is often a PREFIXED IRI ("...from idp:Dataset"),
# and requiring a bare word missed every one of them, flagging true hierarchy statements as
# bleed. Found by the guard's own first run.
_STRUCTURAL = re.compile(
    r"(subclass(es)? of|subtype of|sub-type of|within an?|inside an?|part of|belongs to|"
    r"contained in|instance of|kind of|type of|extends|inherits[^.]*from)\s*[\w:]*\s*$", re.I)

# GRANDFATHERED — each entry is DEBT, not permission. Shrink to empty.
# Format: (file, class label). See the module docstring for why this is a ratchet.
KNOWN_QUERY_SHAPED: set = set()
# CLEARED 2026-08-15. All six entries were BUILD NOTES sitting in rdfs:comment, which the
# ingest's { skos:definition } UNION { rdfs:comment } lets overwrite the authored
# definition. Moving them to `#` comments removed the query-shaped text AND restored the
# real definitions in one change — the two defects were the same authoring mistake seen
# from different angles. Empty is the target state; an entry here is debt.

# CIRCULARITY debt, kept SEPARATE from the habit list above — they are different defects and
# one baseline for two checks makes the freshness guard incoherent (it said Technical Manual
# was "cleaned" because it quotes a matrix query without quoting a QUESTION). Found by this
# guard's own first run, not by the hand audit before it: the audit found one circular
# definition, the guard found three.
KNOWN_CIRCULAR: set = set()
# CLEARED 2026-08-15, and this one was the severest of the three. All three circular
# definitions were build notes ABOUT the matrix row, sitting in the slot the matrix row
# retrieves. Nobody wrote a query into a definition on purpose; the note about the test
# became the text the test finds. Verified after re-ingest that the affected rows still
# resolve — TechnicalManual conf 0.97 recall 1.54, WorkInstruction conf 0.99 recall 3.60 —
# so the circularity was never load-bearing.
KNOWN_SIBLING_BLEED = {
    ("product_structure_extension.ttl", "Approved source relationship"),
    # "a concrete tabular Dataset with rows and columns" — a descriptive use of the parent
    # class name, defensible (Table IS a Dataset) and still the phrasing that bleeds.
    # Listed as debt rather than cleaned, because touching idp definitions is on hold while
    # the extraction-layer read is in flight.
    ("idp_extension.ttl", "Table"),
}


def _definitions():
    out = []
    for f in sorted(ONTOLOGIES.glob("*.ttl")):
        g = Graph()
        try:
            g.parse(f, format="turtle")
        except Exception:  # a malformed TTL is another test's problem
            continue
        labels = {}
        for c in g.subjects(RDF.type, OWL.Class):
            lab = next(g.objects(c, RDFS.label), None)
            labels[str(c)] = str(lab) if lab else str(c).split("#")[-1]
        names = set(labels.values())
        for c in g.subjects(RDF.type, OWL.Class):
            com = next(g.objects(c, RDFS.comment), None)
            if com:
                out.append((f.name, labels[str(c)], str(com), names))
    return out


def _sibling_bleed(text: str, me: str, names: set) -> list:
    hits = []
    for n in names:
        if n == me or n not in text:
            continue
        for m in re.finditer(re.escape(n), text):
            if not _STRUCTURAL.search(text[max(0, m.start() - 45):m.start()]):
                hits.append(n)
                break
    return hits


def test_no_new_query_shaped_examples_in_definitions():
    """Habit 1. A definition made of questions is scored against questions."""
    new = []
    for fname, label, text, _ in _definitions():
        quoted = [q for q in _QUOTED.findall(text) if _INTERROGATIVE.search(q)]
        if quoted and (fname, label) not in KNOWN_QUERY_SHAPED:
            new.append(f"{fname} :: {label} -> {quoted[0][:60]!r}")
    assert not new, (
        "New query-shaped example(s) in a class definition. The definition is retrieval "
        "input: a quoted user question makes the class win on FORMAT rather than subject. "
        "Describe what the class IS.\n  " + "\n  ".join(new)
    )


def test_no_new_sibling_name_bleed_in_definitions():
    """Habit 2. Naming another class competes for that class's traffic. Hierarchy
    statements ("Subtype of Dataset") are excluded — those are true and load-bearing."""
    new = []
    for fname, label, text, names in _definitions():
        bleed = _sibling_bleed(text, label, names)
        if bleed and (fname, label) not in KNOWN_SIBLING_BLEED:
            new.append(f"{fname} :: {label} -> names {sorted(set(bleed))}")
    assert not new, (
        "New sibling-class name(s) in a definition, outside a hierarchy statement. This is "
        "how idp:Pipeline won 'list the datasets in publog' — by naming idp:Dataset.\n  "
        + "\n  ".join(new)
    )


def test_no_definition_quotes_a_routing_matrix_query():
    """THE CIRCULARITY GUARD, and the sharpest of the three.

    If a class definition contains a string the routing matrix asserts on, that matrix row
    cannot fail: the embedding being retrieved contains the text being embedded. Its green
    proves the definition quotes the query, nothing more.

    Grandfathered entries are listed in KNOWN_CIRCULAR; this test only forbids NEW ones,
    and a new one is a strictly worse defect than an ordinary query-shaped example because
    it silently converts a real test into a tautology.
    """
    if not MATRIX.exists():
        pytest.skip("routing matrix not present")
    src = MATRIX.read_text(encoding="utf-8")
    i = src.find("TEST_CASES")
    queries = {q.strip().lower()
               for q in re.findall(r'query\s*=\s*"([^"]{12,})"', src[i:] if i >= 0 else src)}
    assert queries, "no matrix queries parsed — this guard would be measuring nothing"

    new = []
    for fname, label, text, _ in _definitions():
        low = text.lower()
        for q in queries:
            if q in low and (fname, label) not in KNOWN_CIRCULAR:
                new.append(f"{fname} :: {label} quotes matrix query {q[:56]!r}")
    assert not new, (
        "A class definition quotes a routing-matrix query verbatim. That row can no longer "
        "fail — the test asserts retrieval finds a definition that CONTAINS the query.\n  "
        + "\n  ".join(new)
    )


def test_the_grandfathered_baseline_is_still_accurate():
    """A ratchet whose baseline has gone stale is a ratchet nobody can trust.

    If an entry has been CLEANED, this fails and asks for it to be removed from the list —
    so the debt list shrinks deliberately rather than rotting into a permanent exemption.
    """
    stale = []
    defs = {(f, l): t for f, l, t, _ in _definitions()}
    for key in sorted(KNOWN_QUERY_SHAPED):
        text = defs.get(key)
        if text is None:
            stale.append(f"{key[0]} :: {key[1]} — class no longer exists")
        elif not [q for q in _QUOTED.findall(text) if _INTERROGATIVE.search(q)]:
            stale.append(f"{key[0]} :: {key[1]} — CLEANED, remove it from KNOWN_QUERY_SHAPED")
    assert not stale, "grandfather list is out of date:\n  " + "\n  ".join(stale)
