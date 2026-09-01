"""RESPONSE SHAPES MUST NOT BE GROUNDABLE, AND THE DECLARATION MUST MATCH USAGE.

THE DEFECT (measured 2026-09-01, one-cell PROGRAM_FINANCE user, 12/20). ADR-0019
Contract D requires BOTH ends of a verb edge to pre-exist as `owl:Class`, so every verb's
OUTPUT shape becomes an `OntologyClass` — and every `OntologyClass` is a candidate in
Engine O's `/resolve` grounding pool. A verb's output therefore competes with its own input
subject for the question that invokes it:

    "what is our burn rate"  ->  fin:BurnRateSeries   (no predicate edge: DEAD END)
                             ->  fin:PerformanceMeasurementBaseline -> finBurnRate

Right concept, wrong END of Contract D. Routing dies while `/resolve` reports success, the
class genuinely exists, and the engine is healthy. See
docs/plans/response-classes-compete-for-grounding.md.

THE FIX lives in doc-tools (`doc_tools/assets/ontology_assets.py`), which is the sole
writer of the Weaviate `OntologyClass` collection Engine O reads — so response shapes never
enter the grounding pool and every reader inherits that. One filter at the pool, not one
per reader.

THIS FILE IS THE SEAL, and it exists because the filter keys off a DECLARATION
(`rdfs:subClassOf mesh:Response`) which a human has to remember to write. A declaration
enforced by a derivation is worth more than either alone, so the derivation is computed
here from the engines' registration tables and asserted against the declared set:

  * NOTHING DECLARED A RESPONSE IS USED AS AN INPUT  — the filter cannot quietly WIDEN and
    swallow a class users legitimately ask about.
  * EVERY REGISTERED OUTPUT IS DECLARED A RESPONSE   — the filter cannot quietly NARROW and
    miss a shape someone forgot to mark.

WHY THE USAGE RULE COULD NOT BE THE FILTER ITSELF. The originally-dispatched rule was
"exclude a class that appears only as an output_uri and never as an input_uri". At the
filter's site that is not merely hard, it is impossible: classes are seeded by the prime
BEFORE any engine registers — that is Contract D's whole premise — so at sync time there
are NO verb edges, "output-only" is true of every class, and the filter would take the
entire pool. Not a widening risk, a total one. So the usage rule became this seal instead.

NEGATIVE CONTROL, and it is a real one rather than a tautology: the `_NO_VERB_BY_DESIGN`
classes (OBS element, WBS element, work package) have no verb but ARE drill-down referents
the variance tree needs resolvable. They are domain nouns, not `mesh:Response` subclasses,
so they must survive. The rule being sealed is *exists only as a response shape -> filter*,
NEVER *has no verb -> filter*.

PURE STATIC ANALYSIS — no imports of engine modules, so this cannot fail or pass for an
environment reason. Module-level string constants are resolved from the AST.

Run: uv run --frozen pytest tests/routing/test_response_shapes_are_not_groundable.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

_REPO = Path(__file__).resolve().parents[2]
_ONT = _REPO / "setup" / "ontologies"

_RESPONSE_ROOTS = (
    "http://invincible-agent/mesh#Response",
    "http://invincible-agent/mesh#Archetype",
)

# Kept in step with agent_fleet/finance_agent/main.py's set of the same name.
_FIN = "http://invincible-agent/fin#"
_NO_VERB_BY_DESIGN = {
    _FIN + "OBSElement",
    _FIN + "WBSElement",
    _FIN + "WorkPackage",
}


# ── the DECLARED set: what the TTLs say ─────────────────────────────────────

def _declared_response_shapes() -> set[str]:
    """Every class transitively under a response root, across the WHOLE ontology.

    The union of every TTL, deliberately: doc-tools evaluates this per-file, so a
    subClassOf chain that crossed file boundaries would be seen here and missed there.
    If that ever happens, this seal's own assertions are what surface it.
    """
    g = rdflib.Graph()
    for ttl in sorted(_ONT.glob("*.ttl")):
        try:
            g.parse(str(ttl), format="turtle")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{ttl.name} does not parse: {exc}")
    roots = ", ".join(f"<{r}>" for r in _RESPONSE_ROOTS)
    q = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?uri WHERE {{
        ?uri rdfs:subClassOf+ ?root .
        FILTER(?root IN ({roots}))
    }}
    """
    return {str(row.uri) for row in g.query(q)}


# ── the USAGE-DERIVED sets: what the engines actually register ───────────────

def _module_string_consts(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings — the IRI prefixes (FIN, MESH, IDP)."""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                out[tgt.id] = node.value.value
    return out


def _resolve(node: ast.AST, consts: dict[str, str]) -> str | None:
    """Resolve `"literal"` and `PREFIX + "literal"`. Anything else is unresolvable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve(node.left, consts)
        right = _resolve(node.right, consts)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


def _endpoint_uris() -> tuple[set[str], set[str]]:
    """(inputs, outputs) harvested from every `input_uri`/`output_uri` in the fleet.

    Catches BOTH shapes without knowing about either: the `VERBS` table entries
    (dict keys) and the hand-written provider registrations (call keywords).
    """
    inputs: set[str] = set()
    outputs: set[str] = set()
    roots = [_REPO / "agent_fleet", _REPO / "src" / "iagent"]
    for root in roots:
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts or ".venv" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            consts = _module_string_consts(tree)
            for node in ast.walk(tree):
                # call keywords: register_engine_to_mesh(input_uri=..., output_uri=...)
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg in ("input_uri", "output_uri"):
                            val = _resolve(kw.value, consts)
                            if val and val.startswith("http"):
                                (inputs if kw.arg == "input_uri" else outputs).add(val)
                # dict entries: {"input_uri": FIN + "Program", ...}
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and k.value in ("input_uri", "output_uri"):
                            val = _resolve(v, consts)
                            if val and val.startswith("http"):
                                (inputs if k.value == "input_uri" else outputs).add(val)
    return inputs, outputs


# ── non-vacuity: a seal that measures nothing passes trivially ──────────────

def test_the_harvest_actually_found_endpoints():
    """Guard against the whole file going green because the AST scan found nothing —
    the failure mode every derived assertion in this repo has to rule out first."""
    inputs, outputs = _endpoint_uris()
    assert len(inputs) >= 10, f"only {len(inputs)} input_uri found; the scan is broken"
    assert len(outputs) >= 10, f"only {len(outputs)} output_uri found; the scan is broken"


def test_the_declared_set_is_non_empty():
    declared = _declared_response_shapes()
    assert len(declared) >= 30, f"only {len(declared)} declared response shapes"


# ── THE SEAL, both directions ───────────────────────────────────────────────

def test_no_declared_response_shape_is_used_as_an_INPUT():
    """CANNOT QUIETLY WIDEN. A class the filter removes from the grounding pool must
    never be something a verb operates ON — that would make a legitimate subject
    unaskable, which is a worse bug than the one being fixed."""
    declared = _declared_response_shapes()
    inputs, _ = _endpoint_uris()
    overlap = sorted(declared & inputs)
    assert not overlap, (
        "these classes are declared response shapes AND used as a verb's input_uri, so "
        "filtering them from the grounding pool would make a real subject unaskable: "
        + ", ".join(overlap)
    )


def test_every_registered_OUTPUT_is_a_declared_response_shape():
    """CANNOT QUIETLY NARROW. An output nobody marked stays in the grounding pool and
    keeps competing with its own subject — the original defect, still live."""
    declared = _declared_response_shapes()
    _, outputs = _endpoint_uris()
    unmarked = sorted(outputs - declared)
    assert not unmarked, (
        "these classes are registered as a verb's output_uri but are NOT declared "
        "rdfs:subClassOf mesh:Response (or mesh:Archetype), so they still compete for "
        "grounding: " + ", ".join(unmarked)
    )


def test_NO_VERB_BY_DESIGN_classes_survive_the_filter():
    """THE NEGATIVE CONTROL, and it is real rather than tautological. These have no verb
    but ARE drill-down referents the variance tree needs resolvable. The rule is
    'exists only as a response shape -> filter', never 'has no verb -> filter'."""
    declared = _declared_response_shapes()
    caught = sorted(_NO_VERB_BY_DESIGN & declared)
    assert not caught, (
        "the filter would remove no-verb-by-design drill-down referents: " + ", ".join(caught)
    )


def test_the_negative_control_classes_actually_EXIST():
    """Otherwise the control above passes because the names are stale — a control that
    tests nothing is worse than none, because it reads as coverage."""
    g = rdflib.Graph()
    for ttl in sorted(_ONT.glob("*.ttl")):
        try:
            g.parse(str(ttl), format="turtle")
        except Exception:  # noqa: BLE001
            continue
    all_classes = {str(s) for s in g.subjects(rdflib.RDF.type, rdflib.OWL.Class)}
    missing = sorted(_NO_VERB_BY_DESIGN - all_classes)
    assert not missing, f"_NO_VERB_BY_DESIGN names classes that do not exist: {missing}"
