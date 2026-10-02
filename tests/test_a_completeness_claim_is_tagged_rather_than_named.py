"""Ruling 1 and ruling 2, as a seal instead of as two comments that disagreed.

RULED 2026-09-26 by the architecture seat, after twelve rounds. A fact travels from the producer
**iff it is a claim about the completeness of the row set**; a fact derivable from the rows present
is withheld. Truncation-detectability is the discriminator: a count of rows *present* is derivable,
a claim about what the row set *omits* is not.

WHY THIS FILE EXISTS RATHER THAN THE TWO COMMENTS IT REPLACES. `presentation_agent/main.py` carried
the outcome twice, in opposite directions -- `methods_compared` travels (:658-661),
`suppliers_above_threshold` deliberately does not (:748) -- and the discriminator that reconciles
them lived only in prose. Both comments were right. Nothing asserted the rule.

AND WHY IT IS NOT REDUNDANT WITH CORTEX. `cortex-ui/src/components/registry/
projectedTupleParity.test.ts` already seals the discriminator from the far side, well, with a
control before its claims -- but at `:423` it pins the three keys **BY NAME**
("The three completeness-bearing counts travel, BY NAME"), so a FOURTH completeness count is
invisible to it. A floor by name covers exactly the names in it. This file derives the
**population** instead, from the producers, which is the ratchet that was missing.

THE RATCHET FOUND A FOURTH KEY ON ITS FIRST RUN, and it was a true negative worth recording:
`cost_agent/measures.py:441` has `"method": _method(formula=..., inputs=[... len(rows) ...])`.
Ruling 4 exempts method-block inputs -- the block is provenance, what the producer computed *with*,
rendered verbatim and never reconciled against rows, so a `len(rows)` inside it is a record and not
a second source. The exemption is therefore keyed on the **form the code takes** (a call supplying
the block's `formula`), derived from `_method_block_contract.BLOCK_FIELDS_IN_THE_UI`, never on the
key's name and never on a substring -- and `test_THE_PROVENANCE_EXEMPTION_IS_STRUCTURAL` fires a
positive control at it, because an exemption nothing tests is one appended name away from retiring
the arm it qualifies.

Run: uv run --frozen pytest tests/test_a_completeness_claim_is_tagged_rather_than_named.py -v
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from _method_block_contract import BLOCK_FIELDS_IN_THE_UI  # noqa: E402

#: The keyword whose presence makes a constructed value PROVENANCE rather than a second source of a
#: row-derived fact. Derived from the method-block contract so that renaming the block's fields
#: moves this exemption with them instead of silently widening it.
PROVENANCE_KEYWORD = BLOCK_FIELDS_IN_THE_UI[0]

PROJECTOR = ROOT / "agent_fleet" / "presentation_agent" / "main.py"
PRODUCERS = sorted(ROOT.glob("agent_fleet/*/measures.py"))
SDK_ENUMERATION = ROOT.parent / "iagent-mesh-sdk" / "iagent_mesh" / "enumeration.py"
CORTEX_DIR = ROOT.parent / "cortex-ui"


def _competing_measures_contract() -> Path:
    """The contract file declaring COMPETING_MEASURES, found rather than named: cortex's
    ADR-0055 archetype-package move renamed the single-file `CompetingMeasures.contract.ts` to
    `src/archetypes/competing-measures/contract.ts`, a filename the legacy `*.contract.ts` glob
    alone can no longer match (the package convention names the file exactly `contract.ts`).

    RULE A, inlined here rather than imported from a shared module (none exists in this repo):
    `src/**/*.contract.ts` UNION `src/archetypes/*/contract.ts`. Caller's job to check
    `CORTEX_DIR.is_dir()` first -- this fails loudly (never skips) if the repo is there but the
    contract is not exactly one file, since that is a real regression, not an absent sibling.
    """
    src = CORTEX_DIR / "src"
    candidates = sorted(set(src.rglob("*.contract.ts")) | set((src / "archetypes").glob("*/contract.ts")))
    matches = [
        p for p in candidates
        if 'archetype: "COMPETING_MEASURES"' in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert len(matches) == 1, (
        f"expected exactly one contract file declaring COMPETING_MEASURES under {src}, found "
        f"{[str(p) for p in matches]} out of {len(candidates)} contract file(s) scanned -- the "
        f"contract moved or was removed"
    )
    return matches[0]

#: A field nobody in twelve rounds disputed, read by the SAME extractor as the claims below. If the
#: extractor breaks, this is what says so -- rather than every assertion going quietly vacuous.
UNDISPUTED_ALLOWLISTED_FIELD = "verdict"


# ---------------------------------------------------------------------------- extraction
def _module_dict(src: str, name: str) -> dict:
    """The literal `name: Dict[...] = {...}` in `src`, as {str: str}."""
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and isinstance(node.value, ast.Dict)
        ):
            return {
                k.value: v.value
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
    raise AssertionError(f"{name} is not a module-level annotated dict literal in the projector")


def _allowlisted_envelope_fields(src: str) -> set[str]:
    """Every field in a `_PROJECTED_ARCHETYPES` passthrough tuple: archetype -> (payload_key, (...))."""
    fields: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_PROJECTED_ARCHETYPES"
            and isinstance(node.value, ast.Dict)
        ):
            for spec in node.value.values:
                if isinstance(spec, ast.Tuple) and len(spec.elts) == 2 and isinstance(spec.elts[1], ast.Tuple):
                    fields.update(
                        f.value for f in spec.elts[1].elts if isinstance(f, ast.Constant) and isinstance(f.value, str)
                    )
    return fields


def _is_provenance(value: ast.AST) -> bool:
    """A method block: a call supplying the block's own `formula`. Form, not name."""
    return isinstance(value, ast.Call) and any(kw.arg == PROVENANCE_KEYWORD for kw in value.keywords)


def _len_derived(src: str) -> tuple[dict[str, str], dict[str, str]]:
    """(counts, provenance) -- string dict keys whose VALUE subtree calls `len`, partitioned."""
    counts: dict[str, str] = {}
    provenance: dict[str, str] = {}
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not any(
                isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "len"
                for sub in ast.walk(value)
            ):
                continue
            bucket = provenance if _is_provenance(value) else counts
            bucket.setdefault(key.value, f"{value.lineno}")
    return counts, provenance


def _producer_counts() -> tuple[dict[str, str], dict[str, str]]:
    counts: dict[str, str] = {}
    provenance: dict[str, str] = {}
    for path in PRODUCERS:
        c, p = _len_derived(path.read_bytes().decode("utf-8"))
        for k, line in c.items():
            counts.setdefault(k, f"{path.relative_to(ROOT).as_posix()}:{line}")
        for k, line in p.items():
            provenance.setdefault(k, f"{path.relative_to(ROOT).as_posix()}:{line}")
    return counts, provenance


PROJECTOR_SRC = PROJECTOR.read_bytes().decode("utf-8")
ALLOWLISTED = _allowlisted_envelope_fields(PROJECTOR_SRC)
TAGS = _module_dict(PROJECTOR_SRC, "_COMPLETENESS_BEARING")
COUNTS, PROVENANCE = _producer_counts()


# ---------------------------------------------------------------------------- the controls
def test_THE_DERIVATION_FINDS_A_POPULATION():
    """THE FLOOR. Every assertion below is about a derived set, and a derivation that returns
    nothing reports every rule satisfied forever. This is the failure cortex's own parity file was
    written after -- an extractor returning `[]` made its every later claim vacuous."""
    assert PRODUCERS, "no agent_fleet/*/measures.py producers were found at all"
    assert len(ALLOWLISTED) > 5, f"the allowlist extractor found only {len(ALLOWLISTED)} fields"
    assert UNDISPUTED_ALLOWLISTED_FIELD in ALLOWLISTED, (
        f"{UNDISPUTED_ALLOWLISTED_FIELD!r} is missing from the extracted allowlist, so the "
        f"extractor -- not the projector -- is what changed"
    )
    assert TAGS, "_COMPLETENESS_BEARING extracted empty, which would satisfy the ratchet vacuously"
    assert COUNTS, "no len()-derived producer keys were found, so the ratchet is reading nothing"


def test_THE_PROVENANCE_EXEMPTION_IS_STRUCTURAL():
    """Ruling 4's exemption, positive-controlled. An exemption nothing fires at is one appended
    name away from retiring the arm it qualifies, so this asserts the predicate DISCRIMINATES:
    a call carrying the block's `formula` is provenance, and an otherwise identical call without
    it is not."""
    block = ast.parse("_method(formula='f', inputs=[_inp('n', len(rows))])").body[0].value
    plain = ast.parse("_summary(inputs=[_inp('n', len(rows))])").body[0].value
    assert _is_provenance(block), (
        f"a call supplying {PROVENANCE_KEYWORD!r} must read as provenance, or ruling 4's exemption "
        f"is not reaching the method blocks it was ruled for"
    )
    assert not _is_provenance(plain), (
        "a call NOT supplying the block's formula must not be exempted -- otherwise the exemption "
        "is 'any call', and every count in the fleet is provenance"
    )
    assert PROVENANCE, (
        "the exemption matched nothing in any producer. Either the method blocks moved, or this "
        "arm is excusing a population that does not exist -- both are findings, neither is green"
    )


# ------------------------------------------------------------------- ruling 1: the ratchet
def test_EVERY_COUNT_THAT_TRAVELS_IS_TAGGED():
    """RULING 1. The seal reds on an UNTAGGED COUNT, and the population of counts is derived from
    the producers rather than named here -- which is the whole difference from the cortex arm this
    complements. A fourth completeness count added to any passthrough fails this without anyone
    remembering to widen a floor."""
    travelling = {k: where for k, where in COUNTS.items() if k in ALLOWLISTED}
    untagged = {k: where for k, where in travelling.items() if k not in TAGS}
    assert not untagged, (
        "len()-derived producer keys that TRAVEL on the envelope and carry no completeness tag:\n"
        + "".join(f"  {k!r}  produced at {where}\n" for k, where in sorted(untagged.items()))
        + "Either it is a claim about the completeness of the row set -- tag it in "
        "_COMPLETENESS_BEARING with the SDK field it stands in for -- or it is derivable from the "
        "rows present, and it must be removed from the _PROJECTED_ARCHETYPES passthrough."
    )


def test_NO_TAG_NAMES_A_KEY_THAT_DOES_NOT_TRAVEL():
    """A tag on a key no passthrough carries is a claim about nothing, and it would make the
    ratchet above look better-covered than it is."""
    orphans = sorted(set(TAGS) - ALLOWLISTED)
    assert not orphans, (
        f"tagged completeness-bearing but in no _PROJECTED_ARCHETYPES passthrough: {orphans}. "
        f"A tag is a claim about a key that TRAVELS."
    )


def test_EVERY_TAG_NAMES_A_REAL_SDK_FIELD():
    """The tag's vocabulary is the SDK's, READ from it rather than restated here. Ruling 2 exists
    so this fleet has one vocabulary for the fact; a tag naming a field the SDK does not have would
    be a second vocabulary wearing the first one's clothes."""
    assert SDK_ENUMERATION.exists(), f"the SDK is not checked out beside this repo at {SDK_ENUMERATION}"
    legal: set[str] = set()
    for node in ast.walk(ast.parse(SDK_ENUMERATION.read_bytes().decode("utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == "EnumerateInstancesResponse":
            legal = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    assert {"completeness", "total_available"} <= legal, (
        f"EnumerateInstancesResponse no longer declares the completeness vocabulary; it has {sorted(legal)}. "
        f"If the SDK renamed these, the tags and ruling 2's exemption both move with it."
    )
    bogus = {k: v for k, v in TAGS.items() if v not in legal}
    assert not bogus, f"tags naming no field of EnumerateInstancesResponse: {bogus}"


# ------------------------------------------------------- ruling 2: the exemption's premise
def test_THE_MIGRATION_EXEMPTION_PREMISE_STILL_HOLDS():
    """RULING 2, AMENDED 2026-09-26 TO EXPIRE ON THE OBSTACLE RATHER THAN ON A VERSION.

    `methods_compared` and its siblings keep their engine-specific names, instead of migrating to
    the SDK's `completeness`/`total_available`, for exactly as long as those fields are UNAVAILABLE
    on this envelope surface. The trigger's first form was "until SDK v0.9.4 lands" and was
    withdrawn: a version number is a NAME, 0.9.4 can land carrying nothing relevant, and an
    exemption keyed on a name excuses whatever is given that name.

    THIS ARM IS THE EXEMPTION'S EXPIRY. It reds the day a completeness field becomes available
    envelope-side, and the red means: migrate the tagged keys, then delete this arm.
    """
    sdk_names = {"completeness", "total_available"}
    already = sdk_names & ALLOWLISTED
    assert not already, (
        f"{sorted(already)} is now carried on the envelope, so ruling 2's exemption has EXPIRED. "
        f"Migrate {sorted(TAGS)} onto the SDK vocabulary and remove this arm -- the grandfathering "
        f"was only ever waiting for this."
    )
    imported = {
        alias.name
        for node in ast.walk(ast.parse(PROJECTOR_SRC))
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("iagent_mesh")
        for alias in node.names
    }
    assert not (sdk_names & imported), (
        f"the projector now imports the completeness vocabulary {sorted(sdk_names & imported)}; "
        f"the exemption's premise no longer holds"
    )


def test_METHODS_ANSWERED_IS_NOT_DERIVABLE_FROM_THE_ROWS_THE_CARD_HOLDS():
    """The justification for ONE of the three tags, made checkable instead of argued.

    `methods_answered` is `len([... for r in rows if r.get("eac_exact") is not None])`
    (finance_agent/measures.py). That is a predicate over rows -- so on its face it is the
    `suppliers_above_threshold` shape and should be WITHHELD. It is not, for a reason the
    projector's comment never stated: `eac_exact` IS NOT IN THE CARD'S ROW CONTRACT, so the card
    cannot run the producer's predicate over the rows it holds, truncated or not.

    THE DAY `eac_exact` JOINS THE ROW CONTRACT THIS TAG BECOMES WRONG. This arm reds then.
    """
    if not CORTEX_DIR.is_dir():
        pytest.skip("cortex-ui is not checked out beside this repo")
    contract = _competing_measures_contract().read_bytes().decode("utf-8")
    assert "methods_answered" in contract, (
        "the CompetingMeasures contract no longer mentions methods_answered, so this arm is "
        "reading the wrong file and its absence check below proves nothing"
    )
    assert "eac_exact" not in contract, (
        "`eac_exact` is now declared on the CompetingMeasures row contract. `methods_answered` is "
        "therefore DERIVABLE by the card from the rows it holds, which makes it the "
        "suppliers_above_threshold shape: withhold it from the passthrough and drop its tag."
    )


@pytest.mark.parametrize("key,expected", sorted({"all_methods_answered": "completeness"}.items()))
def test_A_TRISTATE_CLAIM_IS_NOT_TAGGED_AS_A_COUNT(key, expected):
    """RULING 6's shape, as a tag. `all_methods_answered` is `len(exact) == len(rows)` -- a
    comparison, not a count -- so it stands in for `completeness` and not for `total_available`.
    Tagging a tri-state claim as a count is how "the producer never said" becomes indistinguishable
    from "the producer said no", which is the distinction the SDK's three-value Literal exists for.
    """
    assert TAGS.get(key) == expected, (
        f"{key!r} is tagged {TAGS.get(key)!r}; it is a completeness CLAIM, not a population count, "
        f"and must stand in for {expected!r}"
    )
