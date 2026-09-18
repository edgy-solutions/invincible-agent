"""A registered verb is COMPACT (`mesh:doThing`). A full IRI registers cleanly and reaches nothing.

MEASURED ON THE LIVE SANDBOX 2026-09-18, and found by the census rather than by any seal.

`docs_agent` registered `f"{MESH}explain"` — the full IRI — where every other engine in the fleet
passes `"mesh:<localName>"`. Nothing errored. The verb registered, reported accepted, and was
unreachable, with TWO independent wrong outcomes from the one wrong form:

  * THE RELATIONSHIP TYPE. `db.relationshipTypes()` held `//invincible-agent/mesh#explain` — the
    only IRI-shaped type among sixty-odd bare camelCase ones (`costLotBreakdown`, `finBurnRate`,
    `enumerateInstances`). The registrar strips through the first colon, which turns
    `mesh:costLotBreakdown` into `costLotBreakdown` and `http://invincible-agent/mesh#explain`
    into `//invincible-agent/mesh#explain`. Nothing queries that type, so the verb answered
    nobody.
  * THE AUTHORITY. `namespace_authority = "platform" if verb.startswith("mesh:") else "domain"`
    (ADR-0005, agent_fleet/utils/mesh_registration.py). A full IRI fails that test, so the
    platform docs verb was classified as a DOMAIN verb.

WHY NO EXISTING SEAL SAW IT, AND THIS IS THE REUSABLE PART. `registration_sites.scan` reads verb
LITERALS, and all seventeen literals in the fleet are compact and correct. `docs_agent`'s verb is
an f-string, so it landed in the `unresolved` bucket — the one the scanner reports rather than
drops, precisely so a computed call is never mistaken for an absent one. **The defect lived in
the blind spot the scanner names.** A population that reports what it cannot resolve is worth
little if nothing then goes and resolves it.

So this file resolves f-strings one hop against module-level string constants, the same move
`tests/safety/test_engine_scope_exists_in_policy.py` makes for `DOMAINS = [DOMAIN]`.

Run: uv run --frozen pytest tests/test_every_registered_verb_is_compact.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FLEET = _REPO / "agent_fleet"

#: The prefixes a verb may legitimately carry. Read from the WRITE-side table rather than listed,
#: so a new namespace does not need editing here — and so this cannot disagree with the registrar
#: about what a valid compact form is.
def _known_prefixes() -> set[str]:
    src = (_FLEET / "utils" / "mesh_registration.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "_IRI_PREFIXES" in targets and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def _verbs_in(path: Path) -> list[tuple[str, str]]:
    """(engine, verb) for every `"verb": <str>` entry, f-strings resolved one hop.

    ONE HOP, AGAINST MODULE CONSTANTS. `f"{MESH}explain"` is the exact shape that hid the defect:
    a literal-only reader sees no verb at all and reports the file clean.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                consts[node.targets[0].id] = node.value.value

    def resolve(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            out = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
                elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                    v = consts.get(part.value.id)
                    if v is None:
                        return None
                    out.append(v)
                else:
                    return None
            return "".join(out)
        return None

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "verb":
                got = resolve(v)
                if got is not None:
                    found.append((path.parent.name, got))
    return found


def _all_verbs() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for p in sorted(_FLEET.glob("*/main.py")):
        out.extend(_verbs_in(p))
    return out


def test_the_scan_finds_verbs_at_all():
    """THE FLOOR. A resolver that returned nothing would make every assertion below vacuous, and
    would pass forever — which is how the literal-only reader missed this in the first place."""
    verbs = _all_verbs()
    assert len(verbs) >= 15, f"only {len(verbs)} verbs resolved: {verbs}"
    engines = {e for e, _ in verbs}
    assert len(engines) >= 4, f"verbs found in only {len(engines)} engine(s): {sorted(engines)}"


def test_THE_RESOLVER_READS_F_STRINGS():
    """THE POINT OF THIS FILE. A literal-only reader saw seventeen correct verbs and reported the
    fleet clean while an f-string verb was live and unreachable. If this resolver ever stops
    following f-strings, the blind spot returns silently — so it is asserted directly."""
    src = "MESH = 'http://x/mesh#'\nV = [{'verb': f'{MESH}thing'}]\n"
    tmp = _REPO / "agent_fleet" / "__resolver_probe__.py"
    tmp.write_text(src, encoding="utf-8")
    try:
        got = _verbs_in(tmp)
    finally:
        tmp.unlink()
    assert got == [("agent_fleet", "http://x/mesh#thing")], (
        f"the resolver did not follow an f-string over a module constant: {got}"
    )


def test_every_registered_verb_is_COMPACT():
    """No full IRIs. The two failures are silent and independent, so neither would report."""
    prefixes = _known_prefixes()
    assert prefixes, "no prefix table found — this test cannot say what a valid verb looks like"
    offenders = [
        f"{engine}: {verb!r}"
        for engine, verb in _all_verbs()
        if not any(verb.startswith(p) for p in prefixes)
    ]
    assert not offenders, (
        "verbs that are not compact `prefix:localName` form:\n  "
        + "\n  ".join(offenders)
        + "\n\nA full IRI registers cleanly and reaches nothing: the registrar strips through the "
        "first colon, so the relationship type keeps the rest of the IRI and matches no query, "
        "and `namespace_authority` (ADR-0005) tests `startswith('mesh:')` and lands on 'domain'."
    )


def test_no_verb_is_a_full_iri_specifically():
    """The same property said the other way round, because the check above depends on the prefix
    TABLE being right and this one does not. A table that gained an `http:` entry would make the
    assertion above pass on exactly the input it exists to reject."""
    bad = [f"{e}: {v!r}" for e, v in _all_verbs() if "://" in v or v.startswith("http")]
    assert not bad, f"verbs carrying a full IRI: {bad}"
