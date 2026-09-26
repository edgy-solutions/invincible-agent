"""Two wire-level seals, and the second is the one that would have caught the real drop.

WHAT HAPPENED, 2026-09-03. `reference` and `verdict` were added to two finance envelopes and
arrived at no card. The reporting lane read it as a producer bug -- "report says emitted, wire
says absent" -- and asked for a seal on the measure endpoint's response body.

**THE MEASURE ENDPOINT WAS CORRECT THE WHOLE TIME.** Verified on the deployed pod: its HTTP
body carries `reference`, `verdict`, and a `series` list with `unit` and `dashed` intact. A seal
on that endpoint would have PASSED while the cards stayed wrong -- measuring the neighbour,
which is the very failure the request was trying to avoid.

The drop was `_PROJECTED_ARCHETYPES`: the projector carries the payload key plus a declared
tuple of passthrough fields and NOTHING ELSE, and that tuple predated both additions.

AND THE CONTRAST IS THE WHOLE LESSON. `favourable` shipped in the same commit and arrived fine,
because it rides inside `rows`, which pass through verbatim. So a ROW-level addition needs no
declaration and an ENVELOPE-level addition needs one -- and nothing anywhere reported the
difference. Two fields added, one silently discarded.

So: seal 1 is what was asked for and guards the engine. Seal 2 guards the seam that actually
broke, and is derived from the engine's own declaration tables rather than a remembered list.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.finance_agent import measures  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402

_STATE = build_seed()
_KW = {"fin_eac_calculation": {"method": "CPI"}}


def _envelope(fn: str) -> dict:
    """The response body `/measure/<fn>` builds, via the app itself rather than a copy of it."""
    from fastapi.testclient import TestClient
    from agent_fleet.finance_agent.main import app
    with TestClient(app) as client:
        r = client.post(f"/measure/{fn}",
                        json={"params": {"program_id": "NP-MERIDIAN", **_KW.get(fn, {})}})
    assert r.status_code == 200, f"{fn}: {r.status_code} {r.text[:200]}"
    return r.json()


# -- SEAL 1 -- the engine's own wire, as requested --------------------------------------

def test_the_measure_response_BODY_carries_every_declared_envelope_field():
    """Asserted on the real HTTP body, not on the measure function's return value.

    SERIES, REFERENCE and VERDICT are this arm's population -- THREE of the tables the
    envelope builder reads, not all of them, and the earlier wording here said "the
    declaration tables are the population" while covering three of eight. A seventh verb
    entering one of these three inherits this arm without an edit; a new TABLE does not, and
    that axis is `test_EVERY_table_the_ENVELOPE_BUILDER_reads_is_asserted_on_the_wire`.
    """
    for fn, decl in measures.SERIES.items():
        body = _envelope(fn)
        assert body.get("series") == decl, (
            f"{fn}: `series` on the wire is {body.get('series')!r}, declared {decl!r}"
        )
    for fn, ref in measures.REFERENCE.items():
        assert _envelope(fn).get("reference") == ref, f"{fn}: `reference` absent or altered"
    for fn, verdict_of in measures.VERDICT.items():
        # `_KW` HERE TOO. `_envelope` above honours it and this direct call did not, so a
        # verb with a mandatory slot raised TypeError the moment it gained a VERDICT
        # entry. Two call sites in one seal disagreeing about how to invoke a verb.
        rows = getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN", **_KW.get(fn, {}))
        expected = verdict_of(rows)
        body = _envelope(fn)
        if expected is None:
            assert "verdict" not in body, f"{fn}: emitted a null verdict key"
        else:
            assert body.get("verdict") == expected, (
                f"{fn}: verdict on the wire {body.get('verdict')!r} != {expected!r}"
            )


def test_series_entries_keep_their_unit_and_dashed_on_the_wire():
    """`dashed` and `unit` are the fields most likely to be dropped by a serializer, because
    they are OPTIONAL and per-entry. The burn card's dashed plan line depends on one of them
    reaching the card, and it was specifically doubted."""
    burn = _envelope("fin_burn_rate")["series"]
    plan = [s for s in burn if s["key"] == "planned"]
    assert plan and plan[0].get("dashed") is True, "the plan series lost `dashed` on the wire"
    assert all(s.get("unit") == "USD" for s in burn), "a burn series lost its `unit`"
    idx = _envelope("fin_performance_indices")["series"]
    assert all("unit" not in s for s in idx), (
        "a dimensionless index gained a unit -- absence is the assertion, per the contract"
    )


def test_the_SUMMARY_table_reaches_the_wire_WITH_TYPED_VALUES():
    """SEAL 1 covered SERIES, REFERENCE and VERDICT and NOT `SUMMARY` -- the table that
    produces the completeness counts. Every existing assertion on those counts calls
    `SUMMARY[fn](rows)` directly, so the one field whose whole job is to SURVIVE to the
    consumer was verified before it travelled and nowhere after. cortex's fixtures start after
    the wire and this suite stopped before it, which is a join asserted on neither side.

    ASSERTED ON THE VALUE, NOT THE KEY, and that distinction is measured rather than assumed:
    cortex-60 had a mutant survive the key-presence form of this arm, because a member written
    `methods_compared: undefined` keeps its key, satisfies `in`, and still sends their card
    down `?? rows.length`. Presence of a key is not availability of a figure.

    `main.py:651` is the hinge this arm guards: `SUMMARY[fn](rows) or {}` turns a None summary
    into an ABSENT key rather than a null one, which is precisely the state a consumer then
    invents a value for. The counts cannot currently be absent -- see
    test_eac_comparison.test_THE_PANEL_CAN_NEVER_COME_BACK_EMPTY -- but nothing between the
    two repos asserted that, and it holds for one arithmetic reason in one method.
    """
    for fn, summary_of in measures.SUMMARY.items():
        body = _envelope(fn)
        rows = getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN", **_KW.get(fn, {}))
        expected = summary_of(rows)
        assert expected is not None, (
            f"{fn}: the summary returned None, so `or {{}}` at main.py:651 dropped every "
            f"envelope key and a consumer reading the absence will invent them"
        )
        for key, value in expected.items():
            assert key in body, f"{fn}: declared summary field `{key}` never reached the wire"
            if value is None:
                continue
            assert body[key] == value, (
                f"{fn}: `{key}` on the wire is {body[key]!r}, the engine computed {value!r}"
            )
            assert isinstance(body[key], (int, float, str, bool)), (
                f"{fn}: `{key}` arrived as {type(body[key]).__name__}, not a usable figure"
            )

    # THE COMPLETENESS COUNTS BY NAME, because the loop above would still pass if the table
    # stopped declaring them. These three are the truncation detector: a consumer that counts
    # its own rows instead cannot tell a full set from a truncated one.
    eac = _envelope("fin_eac_comparison")
    for key, kind in (("methods_compared", int), ("methods_answered", int),
                      ("all_methods_answered", bool)):
        assert isinstance(eac.get(key), kind), (
            f"`{key}` is the completeness detector and arrived as {eac.get(key)!r}; absent or "
            f"untyped, the card falls back to counting the rows it was given"
        )


# -- THE POPULATION, DERIVED FROM ITS CONSUMER ------------------------------------------
#
# SEAL 1 named three tables and the SUMMARY arm above a fourth. I wrote in the 2026-09-26
# packet that closing this partition needed an exclusion REASON per table and was therefore
# not mine to invent in a shared tree. That was wrong, and cheaply so: the envelope builder
# decides which tables reach the wire, so the population AND every exclusion are derivable
# from the consumer. `EAC_FORMULA` and `EAC_METHODS` fall out because the builder never names
# them -- they are read inside the measure functions -- and that is a derivation, not a
# judgment. The reason I declined to invent was sitting in the file I had already read.


def _strip_prose(src: str) -> str:
    """Docstrings and `#` comments removed BEFORE any token search, because a name in prose
    ABOUT a mechanism reads exactly like the mechanism -- and the builder's comments discuss
    the very tables being counted. Controlled both directions below."""
    src = re.sub(r'""".*?"""', "", src, flags=re.S)
    return re.sub(r"#.*$", "", src, flags=re.M)


# The builder is addressed by the route it serves. A block that merely RESEMBLES the envelope
# cannot be the thing FastAPI dispatches.
_MEASURE_ROUTE = "/measure/"
# Asserted on the block found by route, as a cross-check that it is the block this file was
# written against -- NOT as the selector. Cutting these from three to one was measured QUIET.
_BUILDER_LANDMARKS = frozenset({"measure", "rows", "data_provenance"})


def _main_src() -> str:
    return (_ROOT / "agent_fleet" / "finance_agent" / "main.py").read_text(encoding="utf-8")


def _measures_bindings(src: str | None = None) -> tuple[frozenset[str], dict[str, str]]:
    """Every name in main.py that leads to a declaration table, DERIVED FROM ITS IMPORTS rather
    than typed here.

    cortex-60 sent this as a defect in the seal that produced their own correction to me: they
    told me to partition the CALL rather than the literal, and then matched the call with a text
    pattern, so a module doing `const ls = window.localStorage` wrote two durable keys with all
    18 green. `"measures"` was typed into this file exactly that way. MEASURED 2026-09-26, and
    the distinction matters more than the exit code: `import measures as m` DOES red today --
    but the ratchet reds saying VALUE_UNIT "no longer reaches the /measure envelope" about a
    table that still reaches it under another name. A red that sends you looking for a deleted
    line that was never deleted is barely better than a green.

    Returns (names bound to the module, {bare name: table}). main.py's try/except already binds
    the module two ways, and a third spelling must not need an edit here.
    """
    aliases: set[str] = set()
    direct: dict[str, str] = {}
    for node in ast.walk(ast.parse(src if src is not None else _main_src())):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "measures" or a.name.endswith(".measures"):
                    aliases.add(a.asname or a.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "measures":
                    aliases.add(a.asname or "measures")
            if (node.module or "").split(".")[-1] == "measures":
                for a in node.names:
                    if a.name.isupper():
                        direct[a.asname or a.name] = a.name
    assert aliases or direct, (
        "main.py binds no name to the measures module -- this file cannot find the tables at all"
    )
    return frozenset(aliases), direct


def _table_refs(node: ast.AST, bindings=None) -> set[str]:
    """Declaration tables referenced anywhere under `node`, by any spelling main.py can use:
    `<alias>.NAME`, `getattr(<alias>, "NAME")`, and a bare name imported directly.

    TOTAL OVER SPELLING, NOT OVER INDIRECTION -- a table reached through a local variable
    (`t = measures.VALUE_UNIT` then `t[fn]`) or returned by a helper is invisible here, and no
    partition of this one call site can see it. cortex-60 named the same tail on their side (a
    member name held in a variable, and a dependency writing storage on our behalf).

    AND STATING IT WAS NOT ENOUGH, WHICH IS THE POINT. I wrote that limit down and left it, and
    on 2026-09-26 fired it: a table MERGED through a local inside the accounted spread, and the
    same through a helper returning the table, both put every verb's labels on the wire with
    EXIT 0 and every arm green. A limit stated in prose reads as diligence and stops
    re-examination exactly as well as a wrong answer does. What closes the merge half is
    `_unrecognised_spread_operands`, which does not try to see through the local at all -- it
    changes the subject and refuses any operand shape it does not recognise. What remains is
    narrower and named there: a table read through a local into a LITERAL-keyed value, which
    reds via the ratchet but says the table stopped reaching the wire rather than that it
    arrived by a form nothing reads."""
    aliases, direct = bindings if bindings is not None else _measures_bindings()
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id in aliases and n.attr.isupper():
                found.add(n.attr)
        elif isinstance(n, ast.Name) and n.id in direct:
            found.add(direct[n.id])
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr":
            if len(n.args) >= 2:
                target, name = n.args[0], n.args[1]
                if (isinstance(target, ast.Name) and target.id in aliases
                        and isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    found.add(name.value)
    return found


def _spread_operands(node: ast.AST) -> list[ast.expr]:
    """Every `**` operand at any depth under `node`, not only the envelope's top level. The leak
    this exists for was nested one level in."""
    out: list[ast.expr] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            out.extend(v for k, v in zip(n.keys, n.values) if k is None)
    return out


def _operand_leaves(expr: ast.expr) -> list[ast.expr]:
    """An operand written as a conditional or an `or` contributes each branch, so each branch is
    judged on its own. `a if c else b` and `x or {}` are the two forms the builder uses."""
    if isinstance(expr, ast.IfExp):
        return _operand_leaves(expr.body) + _operand_leaves(expr.orelse)
    if isinstance(expr, ast.BoolOp):
        return [leaf for value in expr.values for leaf in _operand_leaves(value)]
    return [expr]


def _unrecognised_spread_operands(builder: ast.Dict) -> list[str]:
    """Merged operands this file cannot account for, by ENUMERATING WHAT IS RECOGNISED.

    THE SUBJECT CHANGED, and cortex-60 made the same move on their side for the same reason.
    Enumerating the dangerous forms can only ever be total over their SPELLING: `_table_refs`
    reads `measures.NAME`, `getattr(measures, "NAME")` and a direct-name import, and I wrote the
    rest down as "the irreducible tail -- a table reached through a local or returned by a helper
    is invisible". MEASURED 2026-09-26, and it was not irreducible, it was live:

        held = measures.VALUE_LABEL
        ... **({**(measures.SUMMARY[fn](rows) or {}), **held} if fn in measures.SUMMARY else {})

    put every verb's label on the wire for every verb, EXIT 0, all 25 arms green. So did the same
    thing through a helper returning the table. A limit stated in prose reads as diligence and
    stops re-examination exactly as well as a wrong answer -- which is my own §8 deferral in a
    third shape, and it was sitting in a docstring I wrote the day before.

    So: only two operand shapes are recognised -- a dict LITERAL, whose keys are partitioned
    elsewhere, and an expression reading nothing but the allowed tables. Every other shape counts
    by default, whatever it is spelled as, including a bare local and a call."""
    unrecognised: list[str] = []
    for operand in _spread_operands(builder):
        for leaf in _operand_leaves(operand):
            if isinstance(leaf, ast.Dict):
                continue
            refs = _table_refs(leaf)
            if not refs or not refs <= _ACCOUNTED_OPAQUE_SPREAD_TABLES:
                unrecognised.append(ast.unparse(leaf))
    return unrecognised


def _builder_block() -> str:
    """The `/measure/<fn>` envelope builder's own source, prose stripped.

    THE ANCHOR IS ASSERTED, NOT CONSUMED. The first form of this helper matched
    `return {\\n"measure": fn,` and returned everything AFTER it, which silently held the
    `measure` key out of the block -- and the checked excuse list below reported it as "excused
    but the builder no longer emits it". A pattern that consumes its anchor shortens the
    population by exactly the line it anchored on."""
    src = _main_src()
    # SELECTED BY ITS ANCHOR, not by position: main.py has five `return {` blocks at this
    # indent and the envelope builder is the third. A `re.search` takes the first, so the
    # pattern must carry a predicate rather than an assumption about order.
    bodies = [
        _strip_prose(m.group(1))
        for m in re.finditer(r"^    return \{\n(.*?)^    \}", src, re.S | re.M)
    ]
    matching = [b for b in bodies if '"measure": fn' in b]
    assert len(matching) == 1, (
        f"expected exactly one `return {{` block carrying the `measure` key, found "
        f"{len(matching)} of {len(bodies)} -- the envelope builder's shape moved"
    )
    return matching[0]


def _builder_dict(src: str | None = None) -> ast.Dict:
    """The `/measure/<fn>` envelope builder's return dict, selected by the ROUTE IT SERVES.

    A REGEX CANNOT SEE A COMPUTED KEY, which is why this is an AST at all: `f"extra_{fn}": ...`
    put a key on the wire from a real declaration table with all 22 arms green. cortex-60's
    correction -- PARTITION THE CALL, NOT THE LITERAL.

    AND THE SELECTOR CHANGED SUBJECT, because my answer to their next question was weaker than I
    told them. I said three landmark keys plus exactly-one-asserted answered "can the predicate
    match two". MEASURED 2026-09-26: cutting the landmark set from three keys to one is QUIET --
    nothing in this file notices, so two of the three landmarks were buying nothing, and the
    strength I claimed was unearned. Selection is now the handler decorated with the route, which
    a lookalike block elsewhere in main.py cannot be; the landmark keys are asserted afterwards as
    a cross-check on the block that was found. Controlled by
    test_the_BUILDER_SELECTOR_and_the_BINDING_RESOLVER_can_actually_FAIL, which drives this with a
    doctored source carrying a decoy dict outside the route.
    """
    tree = ast.parse(src if src is not None else _main_src())
    handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and any(
                isinstance(a, ast.Constant) and isinstance(a.value, str)
                and a.value.startswith(_MEASURE_ROUTE)
                for a in d.args
            )
            for d in node.decorator_list
        )
    ]
    assert len(handlers) == 1, (
        f"expected exactly one handler routed at {_MEASURE_ROUTE!r}, found {len(handlers)} -- "
        f"the envelope builder is no longer addressable by its route"
    )
    dicts = [
        n.value for n in ast.walk(handlers[0])
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)
    ]
    assert len(dicts) == 1, (
        f"the {_MEASURE_ROUTE!r} handler returns {len(dicts)} dict literals -- this file asserts "
        f"one envelope, and a second exit would reach the wire unasserted"
    )
    literals = {
        k.value for k in dicts[0].keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert _BUILDER_LANDMARKS <= literals, (
        f"the {_MEASURE_ROUTE!r} handler's envelope no longer carries "
        f"{sorted(_BUILDER_LANDMARKS - literals)} -- the block found by route is not the one this "
        f"file was written against"
    )
    return dicts[0]


def _classify_key(key: ast.expr, literal: set[str], computed: list[str]) -> None:
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        literal.add(key.value)
    else:
        computed.append(ast.unparse(key))


def _builder_key_forms() -> tuple[set[str], list[ast.expr], list[str]]:
    """Every key-producing element of the envelope, partitioned into (literal names, opaque
    `**` spreads, key forms this arm cannot account for). Total over the call: a literal key, a
    computed key and a spread are the only three things a dict display can contain."""
    literal: set[str] = set()
    computed: list[str] = []
    opaque: list[ast.expr] = []
    builder = _builder_dict()
    for key, value in zip(builder.keys, builder.values):
        if key is not None:
            _classify_key(key, literal, computed)
            continue
        # A `**expr` element. Any dict literal inside it contributes its own keys; an
        # expression carrying no keyed dict at all is opaque and must be accounted by name.
        contributes = False
        for node in ast.walk(value):
            if not isinstance(node, ast.Dict):
                continue
            for inner in node.keys:
                if inner is None:
                    continue
                contributes = True
                _classify_key(inner, literal, computed)
        if not contributes:
            opaque.append(value)
    return literal, opaque, computed


def _envelope_tables() -> set[str]:
    """The tables whose values reach the response body, read from the builder's AST through the
    DERIVED bindings -- `getattr(measures, "NAME")` is a Call and not an Attribute, and an
    aliased import is neither."""
    found = _table_refs(_builder_dict())
    assert found, "found no declaration tables in the envelope builder -- its shape moved"
    return found


def _wire_gap(table: str, fn: str, expected, body: dict) -> str | None:
    """PURE, so the control can drive it with a doctored body. Returns why the declared value
    did not reach `body`, or None when it did. ON THE VALUE, NOT THE KEY."""
    if table == "SUMMARY":
        for key, value in expected.items():
            if key not in body:
                return f"{fn}: declared summary field `{key}` never reached the wire"
            if body[key] != value:
                return f"{fn}: `{key}` is {body[key]!r} on the wire, {value!r} in the engine"
        return None
    key = table.lower()
    if key not in body:
        return f"{fn}: {table} declares {expected!r} and the body carries no `{key}`"
    if body[key] != expected:
        return f"{fn}: `{key}` is {body[key]!r} on the wire, {expected!r} in {table}"
    return None


def test_EVERY_table_the_ENVELOPE_BUILDER_reads_is_asserted_on_the_wire():
    """TOTAL BY CONSTRUCTION rather than by a coverage register: the population is the
    builder's own source, so a ninth table added there arrives under this arm with no edit
    here, and there is no hand-written excuse list to go stale against a table that later
    starts travelling. OUTPUT_URI, VALUE_UNIT and VALUE_LABEL reach the wire and were
    asserted nowhere before this arm.
    """
    gaps: list[str] = []
    for table in sorted(_envelope_tables()):
        decl = getattr(measures, table)
        for fn in sorted(decl):
            expected = decl[fn]
            body = _envelope(fn)
            if callable(expected):
                rows = getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN", **_KW.get(fn, {}))
                expected = expected(rows)
                if expected is None:
                    if table == "SUMMARY":
                        # NOT a silent continue: `or {}` at main.py:651 drops every key this
                        # table declares, and "summary" is never a body key, so the generic
                        # comparison below could not see it. Stated as the failure it is.
                        gaps.append(
                            f"{fn}: SUMMARY returned None, so `or {{}}` dropped every envelope "
                            f"key it declares and a consumer will invent them"
                        )
                        continue
                    # ABSENT-MEANS-SILENT, the rule main.py states at both :626 and :645:
                    # nothing to say emits no key. Asserted as an absence, not skipped.
                    if table.lower() in body:
                        gaps.append(
                            f"{fn}: {table} computed None yet `{table.lower()}` is on the wire"
                        )
                    continue
            gap = _wire_gap(table, fn, expected, body)
            if gap:
                gaps.append(gap)
    assert not gaps, "declared by the engine, and did not arrive:\n  " + "\n  ".join(gaps)


def test_every_envelope_table_emits_UNDER_ITS_OWN_LOWERCASED_NAME():
    """THE ASSUMPTION THE ARM ABOVE RESTS ON, sealed instead of trusted. `table.lower()` is
    how that arm knows which body key to compare, so a table emitting under some other key
    would be checked against a key that is absent for an unrelated reason -- a red for the
    wrong cause, or with the `in` test inverted, a green. SUMMARY is the one exception and is
    named, because it spreads its members into the envelope and owns no key of its own."""
    block = _builder_block()
    wrong = []
    for table in sorted(_envelope_tables() - {"SUMMARY"}):
        if not re.search(rf'"{table.lower()}"\s*:', block):
            wrong.append(table)
    assert not wrong, (
        f"these tables reach the envelope under some key other than their own name: {wrong} -- "
        f"the generic wire arm's `table.lower()` cannot address them"
    )


_TRAVELS_TODAY = frozenset(
    {"OUTPUT_URI", "VALUE_UNIT", "VALUE_LABEL", "SERIES", "REFERENCE", "VERDICT", "SUMMARY"}
)


def test_the_envelope_POPULATION_ONLY_GROWS():
    """THE RATCHET, and it exists because deriving a population from its consumer has one
    blind spot: a table DELETED from the builder leaves the population, and the arm above then
    iterates a smaller set and passes. The derivation cannot see its own subject being
    removed. So the seven names that travel today are written down once -- the register may
    grow without an edit here and may never shrink silently.

    MEASURED 2026-09-26, AND THEN RE-MEASURED THE SAME DAY WITH A MUTANT THAT ACTUALLY TESTS IT.
    First pass: unwiring each of the seven in turn, this ratchet was the only cover at two sites
    (OUTPUT_URI, VALUE_LABEL); both now have a declaration-side arm, and re-running those same
    single-edit mutations gives nothing covered by this ratchet alone. I wrote that up as
    "a BACKSTOP, not load-bearing -- it would catch an unwiring only if a declaration-side arm
    were deleted in the same change", and invited deleting the ratchet if that stayed true.

    THAT CONCLUSION WAS DRAWN FROM THE NEAREST MUTANT TO HAND, which is cortex-60's correction
    against their own deleted arm: they planned an arm forbidding a re-export, fired a ONE-FILE
    mutant at it, saw it red elsewhere, deleted the arm as uncovered -- and the arm was a TWO-FILE
    arm. An arm's cover has to be searched with the mutant that MATTERS, and the sentence above
    names a two-edit change while every mutant behind it edited one thing.

    Fired, two edits at once. Emptying the element (`"output_uri": {}`) while its declaration-side
    arm is disabled reds HERE and at the reach arm, because the key is still emitted and therefore
    still unaccounted -- so even that is not sole cover. REMOVING the element reds HERE AND NOWHERE
    ELSE, with the lowercased-name arm disabled as well. **This ratchet is load-bearing**, and the
    change it alone catches is: a table unwired outright in the same commit that drops its
    declaration-side arm. Do not delete it. The general form, for the next reader: a claim that an
    arm covers nothing is a claim about the mutants that were run, and a two-part arm needs a
    two-part mutant.

    AND THE MEASUREMENT IS SCOPED TO ITS MUTATION, which is the correction cortex-60 drew out of
    my own: the sentence above was measured by DELETING each wired element. It says nothing
    about a table RENAMED at the read site. That was measured separately: before the bindings
    were derived, `import measures as m` made this arm red claiming VALUE_UNIT "no longer
    reaches the envelope" while it plainly did. An alias is a renaming and not a leak, so the
    right behaviour is silence, and this arm is silent on it now -- a false red removed, not
    cover lost. The value-level arms stayed green throughout, which is what says the wire did
    not move."""
    missing = _TRAVELS_TODAY - _envelope_tables()
    assert not missing, (
        f"these tables are not READ at the /measure envelope by any form this file resolves: "
        f"{sorted(missing)}. Either the table was unwired -- then remove the name from "
        f"_TRAVELS_TODAY in the same commit and say why, since an unwired table is invisible to "
        f"a population derived from the wiring -- or it is still on the wire and now arrives "
        f"through a local or a helper, which `_table_refs` cannot see. CHECK WHICH before "
        f"editing the register: a red here named a deleted line that was never deleted once."
    )


# Keys the builder composes itself rather than reading from a declaration table. Named, and
# the arm below CHECKS the reason rather than trusting it.
_NOT_FROM_A_TABLE = frozenset({"measure", "data_provenance", "rows"})

# The tables an opaque `**` spread may draw from. SUMMARY's members are registered in
# _SUMMARY_MEMBERS below and asserted in BOTH DIRECTIONS by
# test_the_SUMMARY_MEMBERS_REGISTER_and_the_PRODUCER_agree.
#
# THAT DELEGATION USED TO NAME test_the_SUMMARY_table_reaches_the_wire_WITH_TYPED_VALUES, and
# cortex-60's lesson is what broke it: a prediction written into a comment is a mutant nobody
# has run yet, and if a sentence names a shape precisely enough to argue it is safe, it is
# precise enough to fire. Fired 2026-09-26 -- the summary producer emitting a key lifted from
# another declaration table (`VALUE_LABEL["fin_burn_rate"]`) was QUIET, and emitting a key it
# invented outright was QUIET, while the control (dropping a completeness count) went red at
# two arms. The named arm computes `expected = summary_of(rows)` and compares the wire to
# THAT: both halves of the comparison come from one producer call, so it asserts the VALUES of
# whatever members the producer names and can never refuse a member it did not expect. The
# reach arm then subtracted the same call. An exclusion computed from its own subject widens
# when its subject does.
#
# BY CONTENT, NOT BY NAME. This was a text marker, `"measures.SUMMARY" in src`, and cortex-60
# flagged the boundary while fixing the same class on their side: an accounted spread is
# accounted by NAME and not by CONTENT. Fired 2026-09-26, and it was QUIET -- merging a second
# table into that element (`{**(measures.SUMMARY[fn](rows) or {}), **measures.VALUE_LABEL}`)
# put every verb's label on the wire for every verb, with all 23 arms green, because the
# element still contained the marker. An excuse keyed on a substring excuses whatever else
# shares the line with it.
_ACCOUNTED_OPAQUE_SPREAD_TABLES = frozenset({"SUMMARY"})

# Every dict the engine declares, read from the module rather than listed. The control arm holds
# the allowance to a PROPER subset of these: widening it to all of them was measured QUIET.
_DECLARED_TABLES = frozenset(
    n for n in dir(measures) if n.isupper() and isinstance(getattr(measures, n), dict)
)

# What SUMMARY's producers emit, written down per verb. This is the whole content of the
# allowance above: the envelope merges this table opaquely, so the only thing standing between
# a producer and the wire is a register that does not move when the producer does.
_SUMMARY_MEMBERS: dict[str, frozenset[str]] = {
    "fin_eac_comparison": frozenset(
        {
            "methods_compared",
            "methods_answered",
            "all_methods_answered",
            "spread_exact",
            "spread",
            "spread_percent_of_bac",
            "lowest_eac",
            "highest_eac",
            "lowest_exact",
            "highest_exact",
            "lowest_value",
            "highest_value",
            "reference_value",
        }
    ),
}


def _rows_for(fn: str):
    return getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN", **_KW.get(fn, {}))


def _summary_register_disagreements(producers, register, rows_for) -> list[str]:
    """Every way the register and the producers can disagree, as complaints rather than as an
    assertion -- so the arm that uses it and the arm that CONTROLS it drive the same code.

    `or {}` mirrors main.py: a None summary contributes no members, which must read as every
    registered member having stopped travelling.
    """
    out: list[str] = []
    for fn in sorted(set(register) - set(producers)):
        out.append(
            f"{fn}: the register holds members for it and measures.SUMMARY declares no summary "
            f"for it, so nothing merges them onto the wire"
        )
    for fn in sorted(set(producers) - set(register)):
        out.append(
            f"{fn}: a summary is merged into the /measure envelope for it and the register holds "
            f"nothing, so every key it emits reaches the wire unasserted"
        )
    for fn in sorted(set(producers) & set(register)):
        produced = set(producers[fn](rows_for(fn)) or {})
        for key in sorted(produced - register[fn]):
            out.append(
                f"{fn}: emits {key!r}, which the register does not hold -- it is merged by an "
                f"opaque `**` spread, so it reaches the wire with nothing asserting where its "
                f"content came from. Add it and say what declares it; do NOT widen the register "
                f"to whatever the producer happens to emit, which is the comparison this exists "
                f"to break."
            )
        for key in sorted(register[fn] - produced):
            out.append(
                f"{fn}: the register holds {key!r} and the summary no longer emits it, so that "
                f"field stopped reaching the wire. The typed-values arm cannot see this: it "
                f"iterates the producer's own keys."
            )
    return out


def test_the_SUMMARY_MEMBERS_REGISTER_and_the_PRODUCER_agree():
    """A NUMBER CANNOT REFUSE ITS OWN RE-STATEMENT; A NAME CAN. That is cortex-60's line, and
    this arm is what it buys: the allowance above waves SUMMARY's content onto the wire, and
    until this existed nothing in the file could say what that content was supposed to BE.
    Both arms that touched it computed the member set by CALLING the producer, which is the
    seventh kind on my own list of guards that cannot fire -- both halves of the comparison
    share an upstream.

    Asserted in BOTH DIRECTIONS, and each direction catches a different change:

    * a member the producer emits and the register does not know -> a key reached the wire
      whose source no arm in this file asserts. Measured: a producer emitting
      `VALUE_LABEL["fin_burn_rate"]` and a producer emitting an invented literal were BOTH
      quiet before this arm.
    * a member the register holds and the producer no longer emits -> the field stopped
      travelling. The typed-values arm is blind to this by construction, because it iterates
      the producer's own keys.
    * a verb gaining or losing a summary at all -> the key sets must match, or a new verb's
      summary would merge onto the wire with nothing written down for it.

    The register is CONTENT, not shape, so it is spelled out rather than derived. Deriving it
    from `summary_of(rows)` would reproduce exactly the defect it exists to close.
    """
    assert not _summary_register_disagreements(measures.SUMMARY, _SUMMARY_MEMBERS, _rows_for), (
        "the summary register and the producer disagree:\n  "
        + "\n  ".join(
            _summary_register_disagreements(measures.SUMMARY, _SUMMARY_MEMBERS, _rows_for)
        )
    )


# The doctored producers the control arm drives the comparison with. A fake summary needs no
# rows, so each ignores its argument -- the point is the member SET, and doctoring measures.py
# to exercise this would put the subject and the instrument in the same file.
_REGISTER_MUST_REPORT = (
    ("a producer emitting a key the register does not hold",
     {"fin_x": lambda _r: {"kept": 1, "smuggled": 2}}, {"fin_x": frozenset({"kept"})},
     "smuggled"),
    ("a producer that stopped emitting a registered key",
     {"fin_x": lambda _r: {"kept": 1}}, {"fin_x": frozenset({"kept", "dropped"})},
     "dropped"),
    ("a verb whose summary is merged with nothing written down for it",
     {"fin_x": lambda _r: {"kept": 1}, "fin_y": lambda _r: {"also": 2}},
     {"fin_x": frozenset({"kept"})}, "fin_y"),
    ("a registered verb measures.py no longer declares a summary for",
     {"fin_x": lambda _r: {"kept": 1}},
     {"fin_x": frozenset({"kept"}), "fin_gone": frozenset({"kept"})}, "fin_gone"),
    ("a producer returning None, which `or {}` turns into an empty member set",
     {"fin_x": lambda _r: None}, {"fin_x": frozenset({"kept"})}, "kept"),
)


def test_the_SUMMARY_REGISTER_COMPARISON_can_actually_REPORT():
    """THE CONTROL FOR THE ARM ABOVE, and it exists because that arm's whole content is a
    comparison the real tree satisfies -- so on this tree it is green whether it compares
    anything or not. Both defects it was written to close (a producer emitting another
    declaration table's content, a producer inventing a key) were QUIET before it existed, and
    a green arm is not evidence that they are covered now.

    Five doctored producers, each with the disagreement it must be able to name. The last one
    is the shape the envelope actually depends on: `SUMMARY[fn](rows) or {}` turns a None
    summary into an ABSENT key rather than a null one, so a producer that starts returning None
    must read as every registered member having stopped travelling, not as a clean pass.
    """
    for label, producers, register, fragment in _REGISTER_MUST_REPORT:
        found = _summary_register_disagreements(producers, register, lambda _fn: None)
        assert found, f"{label}: the comparison reported nothing"
        assert any(fragment in c for c in found), (
            f"{label}: the comparison reported {found}, and none of it names {fragment!r} -- "
            f"a complaint that does not name its subject sends the next reader to the wrong "
            f"half of the pair."
        )


def test_the_SUMMARY_REGISTER_is_SPELLED_OUT_and_not_DERIVED():
    """THE ONE THING THE MUTATION PASS CANNOT REACH. The register closes the leak only while
    it is written down: replace those literals with anything computed from `summary_of(rows)`
    and the comparison becomes a call against itself again, which is exactly the state that let
    a producer put another table's content on the wire with every arm green. That edit looks
    like a tidy-up -- the same shape of change as every other one in this file's history that
    turned out to matter -- and no mutant of the register's CONTENT can object to it, because a
    derived register agrees with the producer by construction.

    So the shape is asserted from the source: every value in the register must be a set of
    string LITERALS. Read from the file rather than from the imported object, because by the
    time the object exists a comprehension has already produced a perfectly ordinary frozenset.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assigned = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "_SUMMARY_MEMBERS"
    ]
    assert len(assigned) == 1, (
        f"_SUMMARY_MEMBERS is assigned {len(assigned)} times in this file, and this arm reads "
        f"the first -- a second assignment would be invisible to it"
    )
    value = assigned[0]
    assert isinstance(value, ast.Dict) and value.keys and all(
        isinstance(k, ast.Constant) for k in value.keys
    ), (
        f"_SUMMARY_MEMBERS is written as {type(value).__name__} rather than a non-empty dict "
        f"literal with literal verb names. A computed register cannot refuse a producer."
    )
    for k, v in zip(value.keys, value.values):
        leaves = [
            n
            for n in ast.walk(v)
            if not isinstance(
                n, (ast.Call, ast.Name, ast.Load, ast.Set, ast.Constant, ast.Tuple, ast.List)
            )
        ]
        assert not leaves, (
            f"the register entry for {k.value!r} contains "
            f"{sorted({type(n).__name__ for n in leaves})} -- it must be a set of string literals "
            f"and nothing else. A comprehension here agrees with whatever the producer emits, "
            f"which is the defect this register exists to close: measured 2026-09-26, a summary "
            f"emitting `VALUE_LABEL[\"fin_burn_rate\"]` was QUIET."
        )
        strings = [n for n in ast.walk(v) if isinstance(n, ast.Constant)]
        assert strings and all(isinstance(n.value, str) for n in strings), (
            f"the register entry for {k.value!r} holds non-string or no constants"
        )


def test_OUTPUT_URI_and_VALUE_LABEL_are_asserted_from_the_DECLARATION_SIDE():
    """THE DIRECTION TEST'S OWN CONCLUSION, ACTED ON. Unwiring each of the seven travelling
    tables showed these two are the only ones whose loss nothing but the ratchet notices -- and
    a ratchet catches SHRINKAGE only, so cortex-60's read is right: they want a declaration-side
    arm, not a better ratchet.

    Iterating the TABLE is what makes an unwiring red, because the two derivation directions
    have opposite blind spots: an arm over the declaration reds when the builder stops reading
    it and is blind to a table the builder reads that measures.py never declared; an arm over
    the builder is total on contents and blind to unwiring. This is the cheap half of that pair.

    THE SENTENCE THAT USED TO END THIS DOCSTRING IS WITHDRAWN -- "after it the ratchet covers
    nothing alone, which is the point at which a ratchet is honest rather than load-bearing".
    It was the same claim the ratchet's own docstring made, measured with the same single-edit
    mutants, and when that claim was re-measured with a two-edit mutant and struck at the
    source, it survived HERE. A correction has as many homes as the claim had. Removing a wired
    element outright while its declaration-side arm is disabled reds at the ratchet ALONE, so
    the ratchet is load-bearing and this arm does not retire it; see its docstring for the
    mutant that establishes the boundary.
    """
    for table, key in (("OUTPUT_URI", "output_uri"), ("VALUE_LABEL", "value_label")):
        decl = getattr(measures, table)
        for fn in sorted(decl):
            body = _envelope(fn)
            assert body.get(key) == decl[fn], (
                f"{fn}: {table} declares {decl[fn]!r} and the body carries "
                f"{body.get(key)!r} under `{key}`"
            )


def test_EVERY_key_the_ENVELOPE_EMITS_is_ACCOUNTED_FOR():
    """THE REACH ARM, and cortex-60's criterion is what it is built against: the defect is not
    that a population is derived, it is that PRODUCTION'S REACH IS WIDER THAN THE TEST'S.
    `_envelope_tables` once matched ONE literal form, `measures.NAME`, while main.py can read a
    table any way Python allows. It now resolves the module's bindings from main.py's own
    imports (`_measures_bindings`), so an alias is not a blind spot -- but the reason that
    helper exists is measured, not assumed. Measured on this file: a table wired in as
    `getattr(measures, "VALUE_UNIT").get(fn, "x")` put `new_thing` on the wire, sourced from a
    declaration table, and every arm stayed GREEN -- it is absent from the population, so it
    is absent from the generic arm, so it is absent from `undecided`. The gap detector cannot
    report a gap it is not looking at.

    So this arm partitions what production CANNOT hide: the keys the builder literally emits.
    Every one is the lowercased name of a table in the population, a member SUMMARY spreads, or
    one of the composed keys named above -- and an unaccounted key reds whatever access form
    put it there."""
    block = _builder_block()
    emitted, opaque, computed = _builder_key_forms()
    assert emitted, "found no keys in the envelope builder -- its shape moved"

    # THE CALL, NOT THE LITERAL. cortex-60's correction: their own `useComposerDraft` computes
    # its storage key, so a literal-key partition would have missed a module already present.
    # My nine keys are literals TODAY; a key that becomes f-string composed must red here
    # rather than travel unasserted, which is exactly what it did when this was a regex.
    assert not computed, (
        f"the envelope emits {len(computed)} key(s) this file cannot account for by name: "
        f"{computed} -- a computed key reaches the wire and no arm can assert it. Give it a "
        f"literal name, or assert it where it is composed."
    )
    # AN OPAQUE SPREAD IS ACCOUNTED BY WHAT IT READS, NOT BY WHAT IT SPELLS. A spread drawing
    # on no declaration table at all is unaccounted; one drawing on a table outside the
    # allowance carries that table's keys to the wire with nothing asserting them.
    for element in opaque:
        refs = _table_refs(element)
        src = ast.unparse(element)
        assert refs, (
            f"the envelope spreads a mapping from an unaccounted source: {src!r} -- whatever "
            f"keys it carries reach the wire unasserted"
        )
        extra = refs - _ACCOUNTED_OPAQUE_SPREAD_TABLES
        assert not extra, (
            f"the envelope spreads {sorted(extra)} inside an element accounted for "
            f"{sorted(_ACCOUNTED_OPAQUE_SPREAD_TABLES)}: {src!r} -- every key those tables "
            f"carry reaches the wire, and no arm in this file addresses them"
        )

    # AND EVERY MERGED OPERAND MUST BE A SHAPE THIS FILE RECOGNISES, at any depth. The two
    # assertions above account a spread by what `_table_refs` can READ in it, which made the
    # resolver's documented tail exploitable rather than merely narrow: `**held`, one level
    # inside the accounted SUMMARY element, was QUIET. This rule is the other way round -- a
    # dict literal or an allowed-table expression, and everything else counts.
    unrecognised = _unrecognised_spread_operands(_builder_dict())
    assert not unrecognised, (
        f"the envelope merges {len(unrecognised)} operand(s) of a shape this file cannot "
        f"account for: {unrecognised} -- whatever keys they carry reach the wire unasserted. A "
        f"local or a helper return is exactly how the resolver's tail becomes a leak; give the "
        f"value literal keys, or read the table at the merge and add it to "
        f"_ACCOUNTED_OPAQUE_SPREAD_TABLES with an arm that asserts its members."
    )

    from_tables = {t.lower() for t in _envelope_tables()}

    # A TERM IN THE WRONG LAYER, REMOVED. This subtracted `- spread_by_summary`, the member
    # names SUMMARY contributes, first computed as `set(summary_of(rows) or {})` and then --
    # after that was caught as an exclusion derived from its own subject -- from the register.
    # Both were BORN DEAD. `emitted` is a STATIC read of the builder's literal keys; a summary
    # member reaches the wire at RUNTIME through an opaque `**` and is never a member of
    # `emitted` at all. Measured 2026-09-26: the intersection is empty, and the nine literal
    # keys are exactly six table-sourced plus three excused, leaving the term nothing to
    # remove. Fixing the tautology did not make it cover anything -- N9, a widened producer
    # with the register arm disabled, was QUIET with the term as shipped.
    #
    # AND HAD IT EVER FIRED IT WOULD HAVE BEEN WRONG. The only state in which it removes
    # something is a builder spelling a literal key that shares a name with a summary member,
    # and excusing that is exactly the excuse-by-NAME the operand rule above exists to refuse.
    # So the collision it would have hidden is asserted instead -- in the layer where it lives.
    # What accounts for the spread is not a subtraction here; it is
    # test_the_SUMMARY_MEMBERS_REGISTER_and_the_PRODUCER_agree, over the spread's own content.
    collides = emitted & {k for members in _SUMMARY_MEMBERS.values() for k in members}
    assert not collides, (
        f"the envelope spells {sorted(collides)} as a literal key AND merges a SUMMARY member "
        f"of the same name through the opaque `**` spread, so one key has two sources and "
        f"whichever element comes last in the builder silently wins. Rename one, or drop the "
        f"literal -- do not leave the wire deciding it by element order."
    )

    unaccounted = emitted - from_tables - _NOT_FROM_A_TABLE
    assert not unaccounted, (
        f"these keys reach the /measure envelope and no arm in this file asserts them: "
        f"{sorted(unaccounted)}. If one reads a declaration table by a form "
        f"`measures.NAME` does not match, the population cannot see it."
    )

    # THE EXCUSE LIST, CHECKED. Otherwise it can quietly absorb a table-sourced key and this
    # arm becomes the thing it was written to prevent.
    builder = _builder_dict()
    for key in sorted(_NOT_FROM_A_TABLE):
        values = [
            v for k, v in zip(builder.keys, builder.values)
            if isinstance(k, ast.Constant) and k.value == key
        ]
        assert len(values) == 1, (
            f"`{key}` is excused and the builder emits it {len(values)} times -- zero means the "
            f"excuse list has gone stale, and more than one means the excuse covers a key it "
            f"was never read against"
        )
        # ON THE AST, not on the line's text: `"measures." not in source` was a second typed-in
        # module name, so an aliased read would have been excused as a composed key.
        reads = _table_refs(values[0])
        assert not reads, (
            f"`{key}` is excused as a composed key, but its value reads {sorted(reads)}: "
            f"{ast.unparse(values[0])!r} -- it belongs in the population, not the excuse list"
        )


def test_the_wire_gap_detector_and_its_prose_stripper_can_actually_FAIL():
    """THE CONTROL, on data this file owns. A detector returning None for everything reads
    exactly like a clean wire, and a stripper that strips nothing reads exactly like one that
    works -- this file has already paid once for a token matched in prose about itself."""
    assert _wire_gap("VALUE_UNIT", "f", "USD", {"value_unit": "USD"}) is None
    assert _wire_gap("VALUE_UNIT", "f", "USD", {}), "an absent key read as present"
    assert _wire_gap("VALUE_UNIT", "f", "USD", {"value_unit": "EUR"}), "a wrong value read as right"
    assert _wire_gap("SUMMARY", "f", {"n": 3}, {"n": 3}) is None
    assert _wire_gap("SUMMARY", "f", {"n": 3}, {"n": 2}), "a wrong count read as right"
    assert _wire_gap("SUMMARY", "f", {"n": 3}, {}), "a dropped summary read as delivered"
    assert "HIDDEN" not in _strip_prose("# measures.HIDDEN_TABLE[fn]\n")
    assert "HIDDEN" not in _strip_prose('"""measures.HIDDEN_TABLE[fn]"""\n')
    assert "HIDDEN" in _strip_prose("x = measures.HIDDEN_TABLE[fn]\n"), "the stripper ate code"


# -- SEAL 2 -- the seam that actually broke ---------------------------------------------

def _projector_passthrough() -> dict:
    """Parsed from the projector's own source, because presentation_agent/main.py imports
    baml_client and cannot be imported outside its container -- the same reason
    `capability_slug` was untestable until it moved."""
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_PROJECTED_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PROJECTED_ARCHETYPES -- the projector's shape moved"
    out = {}
    for name, key, rest in re.findall(
        r'^\s*"(\w+)":\s*\("(\w+)",\s*\(([^)]*)\)\)', block.group(1), re.M
    ):
        out[name] = (key, tuple(re.findall(r'"(\w+)"', rest)))
    assert out, "parsed no entries -- the regex is stale, not the table"
    return out


def _fin_bindings() -> dict:
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
    by_output = {uri: fn for fn, uri in measures.OUTPUT_URI.items()}
    out = {}
    for cap in PRESENTATION_CAPABILITIES:
        subj = cap["subject_uri"]
        if not subj.startswith("fin:"):
            continue
        full = subj.replace("fin:", "http://invincible-agent/fin#", 1)
        fn = by_output.get(full) or by_output.get(subj)
        if fn:
            out[fn] = cap["archetype"]
    return out


def test_every_envelope_field_a_verb_declares_survives_its_archetype_passthrough():
    """THE SEAL THE MEASURE-ENDPOINT ONE COULD NOT BE.

    The projector carries `rows` plus a declared tuple and DISCARDS THE REST SILENTLY. So an
    envelope-level field is only real if its archetype declares it, and nothing connected the
    two declarations until this test.

    Derived from three sources that must agree -- the engine's declaration tables, the
    capability bindings, and the projector's own table -- so a new field, a new verb or a
    rebinding each fail here rather than at a card.
    """
    passthrough = _projector_passthrough()
    bindings = _fin_bindings()
    assert bindings, "derived no fin bindings -- the derivation is stale"

    declared_by_fn: dict = {}
    for table, field in ((measures.SERIES, "series"),
                         (measures.REFERENCE, "reference"),
                         (measures.VERDICT, "verdict")):
        for fn in table:
            declared_by_fn.setdefault(fn, set()).add(field)

    missing = []
    for fn, fields in sorted(declared_by_fn.items()):
        archetype = bindings.get(fn)
        assert archetype, f"{fn} declares {sorted(fields)} but is bound to no archetype"
        spec = passthrough.get(archetype)
        assert spec, f"{archetype} is not in the projector table -- {fn} cannot render at all"
        carried = set(spec[1])
        for f in sorted(fields - carried):
            missing.append(f"{fn} declares {f!r} -> {archetype} passthrough {spec[1]} drops it")
    assert not missing, (
        "envelope fields DISCARDED by the projector, silently:\n  " + "\n  ".join(missing)
        + "\n\nThe engine emits them and no card receives them. Add the field to that "
          "archetype's passthrough tuple, or stop emitting it."
    )


def test_row_level_fields_need_NO_declaration_and_that_is_why_favourable_survived():
    """The contrast, pinned, because it is what made the drop invisible.

    `favourable` was added in the same commit as `reference` and `verdict` and arrived at the
    card, because rows pass through verbatim. Anyone reasoning "the other field arrived, so the
    payload is fine" was reasoning from a real observation about a different mechanism.
    """
    key, carried = _projector_passthrough()["MULTI_SERIES"]
    assert key == "rows", "MULTI_SERIES no longer projects `rows` -- this test's premise moved"
    tree = measures.fin_variance_analysis(_STATE, program_id="NP-MERIDIAN")[0]
    assert "favourable" in tree, "the tree stopped emitting a verdict"
    assert "favourable" not in carried, (
        "`favourable` is declared as a passthrough field -- it is a ROW field and needs no "
        "declaration; listing it here would suggest row additions require one, which is the "
        "confusion that hid this bug"
    )


# ── THE ARCHETYPE AXIS, widened 2026-09-05 ────────────────────────────────────────────
#
# The seal above derives its population from THIS ENGINE's declaration tables, so it covers
# every archetype a fin: verb produces and NOTHING ELSE. ELICITATION is produced by the
# supervisor's ask path, not by a measure verb, so it sat outside the population entirely — and
# a whole archetype with no projector entry fell through to KNOWLEDGE_DOCUMENT silently, which
# is the same drop as `reference`/`verdict` one level up: not a field discarded, a card.
#
# So the axis is now derived from CORTEX'S CONTRACTS — every archetype the frontend declares it
# can draw — rather than from what this engine happens to emit. That is the population the
# projector actually has to cover.

# `_CORTEX_DIR`, NOT `_CORTEX`. THIS NAME WAS BOUND TWICE AT MODULE LEVEL -- here to the repo
# DIRECTORY and again ~280 lines below to a single .ts FILE. Python resolved it last-wins, so
# `_CORTEX` was the FILE everywhere, `_CORTEX.is_dir()` was permanently False, and the
# contract-file scan below it NEVER RAN -- a test that stopped testing without failing.
#
# Found on merge 2026-09-18 by generalising lane/91's own
# `test_THIS_FILE_DEFINES_ITS_TABLES_EXACTLY_ONCE` across the whole tree: a textual merge with
# no conflict is not a semantic merge, and a duplicate top-level binding is a collision git
# cannot see.
_CORTEX_DIR = _ROOT.parent / "cortex-ui"


def _cortex_declared_archetypes() -> dict:
    """archetype -> set(required field names), parsed from cortex's *.contract.ts."""
    out = {}
    if not _CORTEX_DIR.is_dir():
        return out
    for p in _CORTEX_DIR.rglob("*.contract.ts"):
        src = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'archetype:\s*"([A-Z_]+)"', src)
        if not m:
            continue
        fields = re.search(r"fields:\s*\{(.*?)\n  \}", src, re.S)
        req = set()
        if fields:
            for fname, body in re.findall(r"(\w+):\s*\{([^}]*)\}", fields.group(1)):
                if "required: true" in body:
                    req.add(fname)
        out[m.group(1)] = req
    return out


def _flat_archetypes() -> dict:
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_FLAT_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    if not block:
        return {}
    out = {}
    for name, groups in re.findall(r'^\s*"(\w+)":\s*\((.*?)\),\n', block.group(1), re.S | re.M):
        out[name] = tuple(re.findall(r'"(\w+)"', groups))
    return out


def test_ELICITATION_is_projected_and_carries_the_field_its_contract_REQUIRES():
    """The specific regression: an ask with no menu drew as KNOWLEDGE_DOCUMENT.

    Pinned on the REQUIRED field rather than the whole list, because the optional ones are
    absent-means-something and asserting their presence would forbid a legitimate ask.
    """
    flat = _flat_archetypes()
    assert "ELICITATION" in flat, (
        "ELICITATION has no projector entry — an archetype with no path falls through to "
        "KNOWLEDGE_DOCUMENT by construction, which is a whole card lost silently"
    )
    declared = _cortex_declared_archetypes()
    if "ELICITATION" not in declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    missing = declared["ELICITATION"] - set(flat["ELICITATION"])
    assert not missing, (
        f"ELICITATION's projector does not carry {sorted(missing)}, which cortex's contract "
        f"marks required — the card mounts and cannot say what it is asking for"
    )


def test_an_ask_with_NO_MENU_is_still_projectable():
    """⛔ THE CASE THAT MOTIVATED A SECOND TABLE, and the one a list projector rejects.

    `options` is legitimately EMPTY whenever no provider could enumerate the slot — the producer
    says why in `free_text_reason`, and "which program? I could not list them" is a complete
    ask. The list projector returns None on an empty payload, which is correct for a grid and
    exactly wrong here: it would reject the asks that most need to render.

    So ELICITATION must NOT be in the list-projected table, and this asserts that separation
    rather than trusting it.
    """
    passthrough = _projector_passthrough()
    assert "ELICITATION" not in passthrough, (
        "ELICITATION is in _PROJECTED_ARCHETYPES, whose projector requires a NON-EMPTY list "
        "under its payload key. An ask with no menu has none, so every menu-less ask would "
        "silently degrade — the failure this separation exists to prevent."
    )
    flat = _flat_archetypes()
    assert "options" not in flat["ELICITATION"][:1], (
        "`options` is declared REQUIRED for ELICITATION; an ask with no menu is legitimate"
    )


def test_every_archetype_cortex_can_draw_has_SOME_projector_path():
    """The widened axis. Reported per archetype so a gap names itself.

    An archetype cortex declares and the backend cannot project is a card that will never
    render — and it degrades to KNOWLEDGE_DOCUMENT rather than erroring, so nothing goes red.
    Archetypes served by a hardened BAML renderer are legitimately absent from both tables, so
    those are listed rather than asserted: this fails only for an archetype with NO path at all.
    """
    declared = _cortex_declared_archetypes()
    if not declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    projected = set(_projector_passthrough()) | set(_flat_archetypes())
    hardened = {"CHART_WIDGET", "KNOWLEDGE_DOCUMENT", "PROCESS_TOPOLOGY",
                "HAZARD_DECLARATION", "ASSET_STATE_METRIC", "GROUPED_REVIEW",
                "APPROVAL_TASK", "WORKFLOW_OBSERVATION", "INSTANCES_BY_PROPERTY",
                "DECISION_RECORD", "CANVAS_SEED"}
    orphans = sorted(set(declared) - projected - hardened)
    assert not orphans, (
        f"{len(orphans)} archetype(s) cortex declares with NO backend projection path: "
        f"{orphans}. Each degrades to KNOWLEDGE_DOCUMENT silently. Add a projector entry, or "
        f"add it to the hardened-renderer set in this test if a BAML renderer serves it."
    )


# ═══════════════════════════════════════════════════════════════════════════
# THE VOID PATH ITSELF — because it had NEVER EXECUTED
# ═══════════════════════════════════════════════════════════════════════════

def test_THE_SKIP_PATH_ACTUALLY_WORKS(monkeypatch):
    """A VOID PATH THAT ONLY EXECUTES WHERE THE VOID IS NEEDED IS UNTESTED BY CONSTRUCTION.

    This file called `pytest.skip(...)` in two places and never imported pytest. Every lane has
    cortex-ui checked out beside the repo, so that branch had **never once run** — and on a CI
    runner, where cortex-ui is absent, it raised `NameError: name 'pytest' is not defined`.
    **A test written to VOID instead FAILED, and only in the condition the void exists for.**
    It took down all three jobs of the first full suite run in 22 days.

    So the branch is forced here, on a machine that HAS cortex-ui, by making the parser return
    what it returns when the sibling repo is missing. Without this the import is fixed until the
    next person writes a skip the same way, and nothing in the suite can tell.

    WHAT THIS CANNOT DISTINGUISH: a skip that fires for the right reason from one that fires for
    any reason. It asserts the mechanism raises Skipped rather than NameError — which is the
    failure that actually happened — not that the condition was correctly judged.
    """
    # DERIVED IN TWO HOPS, because one hop stopped being enough on 2026-09-15. The original
    # filter was "a test whose own body names pytest.skip" — and three new tests skip through a
    # HELPER (`_mirrors`) instead, so the population silently lost them. **A derivation that
    # stops at the direct case reads as complete and is a sample.**
    #
    # Hop 1: every module-level function whose body names `pytest.skip(` — helpers included.
    # Hop 2: every zero-argument test that names one of those, transitively.
    src = Path(__file__).read_text(encoding="utf-8")
    # NAMED VIA chr(10), NOT AN ESCAPE. A backslash-n written into a patch script run
    # through a heredoc collapses into a real newline and splits the string literal — the
    # same collapse that has cost this lane three times. Name the character.
    _NL = chr(10)
    bodies = {}
    for b in src.split(_NL + 'def '):
        name, _, rest = b.partition('(')
        if name and name.replace('_', '').isalnum():
            bodies[name] = (rest, b)

    skipping = {n for n, (_, b) in bodies.items() if 'pytest.skip(' in b}
    # Transitive closure: a helper that calls a skipping helper also skips.
    for _ in range(len(bodies)):
        grown = skipping | {
            n for n, (_, b) in bodies.items() if any(s + '(' in b for s in skipping)
        }
        if grown == skipping:
            break
        skipping = grown

    skippers = []
    for name in sorted(skipping):
        if not name.startswith('test_'):
            continue          # a helper is reached THROUGH its test, not called directly
        if name == 'test_THE_SKIP_PATH_ACTUALLY_WORKS':
            continue          # names pytest.skip itself; calling it would recurse
        if bodies[name][0].split(')', 1)[0].strip():
            continue          # takes fixtures - not directly callable
        skippers.append(name)
    assert len(skippers) >= 4, (
        f"expected at least the four known skipping tests, derived {skippers} — the derivation "
        f"is stale, and a shrinking population is how this seal goes quiet rather than red"
    )

    # ⚠ THE POPULATION IS DERIVED; THE FORCING IS NOT, AND THAT IS THE SEAM.
    # This seal finds every skipping test by reading the source — which it did, immediately, for
    # the mirror seal added 2026-09-15 — but each skip has its OWN condition, and neutralising
    # one says nothing about another. The list below is therefore a hand-kept part inside a
    # derived seal, and the failure mode is loud on purpose: a new skip whose condition is not
    # neutralised here runs to completion and this test FAILS with "DID NOT RAISE", naming it.
    #
    # Loud is the requirement. A forcing mechanism that silently missed a condition would report
    # the skip path tested when it had never run — the exact defect this seal exists to catch,
    # one level up.
    monkeypatch.setattr(sys.modules[__name__], "_cortex_declared_archetypes", lambda: {})
    monkeypatch.setattr(sys.modules[__name__], "_CORTEX", Path("no-such-sibling-repo.ts"))
    monkeypatch.setattr(sys.modules[__name__], "_CONTRACT_FILE", Path("no-such-contract.ts"))
    for name in skippers:
        fn = getattr(sys.modules[__name__], name)
        with pytest.raises(pytest.skip.Exception):
            fn()


def test_EVERY_pytest_SKIP_IN_THIS_FILE_HAS_ITS_IMPORT():
    """THE GENERAL FORM, cheap and derived. A file naming `pytest.skip` without importing pytest
    is a void that becomes a NameError in exactly the environment it was written for.

    Scanned from the source rather than trusted to review, because the defect is invisible on
    every machine where the branch does not fire.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    if "pytest." in src:
        assert re.search(r"^import pytest$", src, re.M), (
            "this file calls into pytest and never imports it — the skip path raises NameError "
            "in the only condition it exists to handle"
        )


# -- SEAL 4 -- the join that was missing, from the other direction -----------------------
#
# The passthrough seal above asks "does a field this verb declares survive its archetype".
# It cannot ask "does this archetype have a verb at all", and that is how COMPETING_MEASURES
# sat in the projector from 2026-09-11 to 2026-09-15 with a component, a contract, a glyph
# and a contract header naming its first consumer BY NAME — claimed by no backend row, so the
# verb its passthrough was written for rendered as nothing.
#
# The registrar's unrenderable-output refusal, from the other end: an archetype nothing binds
# is registered and drawable by nobody.

# ── R-080: THE RULES BELOW ARE LIFTED SO THEY CAN BE EXERCISED WITH THEIR LISTS EMPTY ────────
#
# Three registers in this file decide staleness by WALKING THEIR OWN LIST, and a loop over an
# empty collection cannot fail. Each therefore stops being a test at the exact moment its list
# reaches zero — which is the state every one of them is aimed at.
#
# **A fixture that cannot fail is an accident; a ratchet that cannot fail is a success
# condition.** Measured on the sibling seal the day its list emptied: the whole computation
# replaced by `[]`, suite still green.
#
# So the rule lives in a function, and every test that uses it also calls it with data it owns,
# BOTH DIRECTIONS. The second direction is the one that is easy to skip: a rule that flagged
# everything would satisfy the real assertion too, for the wrong reason.


def _no_longer(entries, live):
    """Excused entries that are not in `live` any more — the rule under both set-shaped
    registers here: the mirror gap register and the archetype excuse list."""
    return sorted(set(entries) - set(live))


def _residue_faults(residue: dict, declared, arriving) -> list[str]:
    """Every way an entry in a per-row residue list can have gone stale: the contract stopped
    declaring the field, the field started arriving on the envelope, or the reason is too thin
    to be one."""
    out: list[str] = []
    for name, why in residue.items():
        if name not in declared:
            out.append(f"{name}: excused but the contract no longer declares it")
        if name in arriving:
            out.append(f"{name}: now arrives on the envelope; delete its entry rather than "
                       f"leave a resolved divergence reading as an open one")
        if not why or len(why) <= 40:
            out.append(f"{name}: excused without a usable reason")
    return out


def _both_directions_or_the_rule_is_untested():
    """THE FIXTURE ARM every register below calls. Proves the two rules can FLAG and can
    ABSTAIN, using data this file owns, whatever the real lists happen to hold today."""
    assert _no_longer({("gone", "x")}, {("live", "y")}) == [("gone", "x")], (
        "the staleness rule does not flag an entry that has stopped being live; with a register "
        "empty, nothing in its real assertion can fail"
    )
    assert _no_longer({("live", "y")}, {("live", "y")}) == [], (
        "the staleness rule flags an entry that is STILL live, which would demand deleting an "
        "exemption that is still doing work"
    )
    assert _residue_faults({"f": "r" * 50}, declared={"f"}, arriving=set()) == []
    assert _residue_faults({"f": "r" * 50}, declared=set(), arriving=set())
    assert _residue_faults({"f": "r" * 50}, declared={"f"}, arriving={"f"})
    assert _residue_faults({"f": "too thin"}, declared={"f"}, arriving=set())


#: Archetypes in the projector with no BACKEND capability row, each with the reason it needs
#: none. NOT a convenience list — every entry is a claim, and every claim was checked.
#:
#: All five are bound in cortex-ui's `DERIVED_BINDINGS`
#: (`src/registry/assembleCapabilities.ts`), read 2026-09-15. Their subjects are `mesh:`
#: vocabulary rather than an engine namespace, and this backend's table advertises the subjects
#: ITS OWN engines produce. Two mirrors of one binding set, split by who owns the subject.
#:
#: ⚠ THE SPLIT IS OBSERVED, NOT RATIFIED. Nobody has written down that `mesh:` subjects are the
#: frontend's to bind; it is what the two files DO. Recorded as the reason because it is the
#: true one, and flagged because a reason describing a pattern is weaker than one citing a
#: decision.
_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR = {
    "CANVAS_SEED": "mesh:CanvasSeedResult -> mesh:CanvasSeed, in DERIVED_BINDINGS",
    "INTERVAL_TIMELINE": "mesh:IntervalSchedule and mesh:ContributionSequence, in DERIVED_BINDINGS",
    "MATRIX_GRID": "mesh:MaturityMatrix -> mesh:MatrixGrid, in DERIVED_BINDINGS",
    "PERIOD_SERIES": "mesh:PeriodCostSeries -> mesh:PeriodSeries, in DERIVED_BINDINGS",
    "THRESHOLD_GRID": "mesh:LoadThresholdGrid -> mesh:ThresholdGrid, in DERIVED_BINDINGS",
}


def test_every_archetype_in_the_projector_is_CLAIMED_or_EXCUSED_BY_NAME():
    """PARTITIONED, not filtered: every archetype the projector can draw is either claimed by a
    backend capability row or carries a written reason it is not.

    A name in neither set FAILS. That is the whole mechanism — an archetype quietly added to
    the projector and bound by nobody is the state this seal exists to end, and it is the state
    COMPETING_MEASURES was in for four days.
    """
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    projected = set(_projector_passthrough())
    claimed = {c["archetype"] for c in PRESENTATION_CAPABILITIES}
    excused = set(_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR)

    orphans = sorted(projected - claimed - excused)
    assert not orphans, (
        "these archetypes are in the projector's table, claimed by no capability row, and "
        f"carry no stated reason: {orphans}\n"
        "An archetype nothing binds is registered and drawable by nobody. Either add a "
        "capability row whose `archetype` is this name, or add it to "
        "_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR WITH the binding that covers it."
    )

    # AND THE EXCLUSION LIST IS NOT A DRAWER. An entry for an archetype the projector no longer
    # carries is a stale excuse that keeps excusing nothing — the same shape as a tombstone for
    # a row the seed does not ship, which keeps deleting nothing.
    stale = _no_longer(excused, projected)
    assert not stale, f"excused archetypes no longer in the projector: {stale}"
    _both_directions_or_the_rule_is_untested()

    # A REASON IS REQUIRED TO BE ONE. An empty string satisfies the partition and says nothing,
    # which is how every exclusion list rots.
    for name, why in _ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR.items():
        assert why and len(why) > 20, f"{name} is excused without a usable reason"


def test_the_partition_can_actually_FAIL():
    """THE CONTROL. A partition over two sets passes by construction unless something can fall
    outside both — so a name in neither must be shown to fall out."""
    projected = set(_projector_passthrough())
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    claimed = {c["archetype"] for c in PRESENTATION_CAPABILITIES}
    excused = set(_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR)
    assert (projected | {"AN_ARCHETYPE_NOBODY_DECLARED"}) - claimed - excused, (
        "a name in neither set does not fall out of the partition; the seal above cannot fail"
    )


# -- SEAL 5 -- the cross-repo mirror, for the subjects THIS engine owns -------------------

_CORTEX = _ROOT.parent / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"


def _expand(uri: str) -> str:
    """Compact and expanded spellings are the SAME binding, and this repo has already paid for
    forgetting it: six `fin:` rows were refused by Contract D because the subject was emitted
    COMPACT. A diff over unexpanded URIs reports every cost row as a mismatch — measured, it
    reported seven — and a prefix absent from the map passes through verbatim, so the row
    registers, reports accepted, and never matches.
    """
    # THE PRIVATE NAME ON PURPOSE. `_IRI_PREFIXES_FOR_LOOKUP` is the ONE map the module
    # expands with, and a second copy transcribed into this seal would agree with itself
    # while disagreeing with the code — which is the defect this whole file is about.
    from agent_fleet.presentation_agent.capabilities import (
        _IRI_PREFIXES_FOR_LOOKUP as PREFIXES,
    )

    for p, full in PREFIXES.items():
        if uri.startswith(p):
            return full + uri[len(p):]
    return uri


_MESH = "http://invincible-agent/mesh#"
_SAFETY = "http://internal/sustainment/safety#"

#: THE 18 ROWS THAT WERE ALREADY OUT OF STEP WHEN THE MIRROR WAS RATIFIED (2026-09-15).
#:
#: A DEBT REGISTER, NOT AN EXCLUSION LIST, and the difference is enforced below: an entry that
#: STOPS being a mismatch FAILS this seal. It can only shrink, and a lane that fixes a row must
#: delete its line in the same commit. That is what keeps it from becoming the drawer every
#: exclusion list turns into.
#:
#: OWNING LANE IS ATTRIBUTED BY SUBJECT NAMESPACE, and that is a heuristic, not a record: the
#: `mesh:` rows are the planning/cortex vocabulary and the `safety:` rows are the safety lane's.
#: Nobody signed for them — **a citation is not a signature** — so Lane 1 routes, and this
#: comment says how the guess was made rather than presenting it as an assignment.
_MIRROR_GAPS_AT_RATIFICATION = {
    # FRONTEND BINDS, BACKEND DOES NOT ADVERTISE — 15, all mesh: vocabulary.
    # Drawable by a registered frontend; the mesh advertises nothing, so nothing routes to them.
    (_MESH + "CanvasSeedResult", _MESH + "CanvasSeed"),
    (_MESH + "ContributionSequence", _MESH + "IntervalTimeline"),
    (_MESH + "DecisionArtifact", _MESH + "DecisionRecord"),
    (_MESH + "EffectSet", _MESH + "DeltaSet"),
    (_MESH + "FundingGapSet", _MESH + "ShortfallGrid"),
    (_MESH + "HumanApprovalTask", _MESH + "ApprovalTask"),
    (_MESH + "InstancesByProperty", _MESH + "InstancesByProperty"),
    (_MESH + "IntervalSchedule", _MESH + "IntervalTimeline"),
    (_MESH + "LoadThresholdGrid", _MESH + "ThresholdGrid"),
    (_MESH + "MaturityMatrix", _MESH + "MatrixGrid"),
    (_MESH + "PartObsolescenceReviewBatch", _MESH + "GroupedReview"),
    (_MESH + "PeriodCostSeries", _MESH + "PeriodSeries"),
    (_MESH + "SlotElicitation", _MESH + "AskCard"),
    (_MESH + "WithheldPanel", _MESH + "NamedHole"),
    (_MESH + "WorkflowObservation", _MESH + "WorkflowObservation"),
    # ── THE THREE SAFETY ROWS ARE GONE FROM THIS REGISTER, 2026-09-19 ────────────────────────
    #
    # `safety:DeferralRiskCard`, `safety:OrphanedHazardSet` and `safety:RiskAssessmentDraft` were
    # backend-only at ratification: Engine S advertised them to the mesh and cortex bound none, so
    # no component could ever be chosen for them. cortex-ui `df702ca` bound all three, they
    # stopped being gaps, and **the ratchet reddened until their lines were deleted** — the first
    # time it has fired, and the entire reason it exists.
    #
    # ⚠ THE FIXER DID NOT KNOW THIS REGISTER EXISTED, and that is the interesting part rather
    # than a complaint. A debt register in ONE lane's test file records defects owned by OTHER
    # lanes, so the commit that fixes one cannot be expected to delete the entry. **The ratchet is
    # the only thing that notices a fix landing in a lane that never read the list** — without it
    # three CLOSED gaps would read as OPEN to everyone who checked the list instead of the
    # mirrors. That is a second argument for the ratchet beside the vacuum one, and it applies to
    # every cross-lane register in the fleet. (Lane 91, routed to R-080.)
    #
    # WHAT THE GAP COST WHILE IT WAS OPEN, measured rather than inferred: `draft a risk assessment
    # for HAZ-1003` routed MATCHED to mesh:draftRiskAssessment and came back
    # `presentation_source: "unrenderable"` — "no registered capability's contract is satisfied by
    # this payload" — with "No content available." A correct route and an empty card.
    #
    # And the rows went into the WRONG MENU first: the presentation agent's table writes
    # `__system_default__`, while cortex's menu is written by the browser POST and is the one
    # `select_archetype("cortex-ui-desktop", ...)` reads. That table's own header had predicted
    # exactly this — "a fix aimed one menu to the left".
    #
    # Deleted in the commit that OBSERVED the fix, not the one that made it: the fix is cortex's,
    # this register is ours, and the two live in different repos.
    #
    # Fifteen entries remain, all `mesh:` subjects the frontend binds alone.
}


def _mirrors() -> tuple[set, set]:
    """The two mirrors, both sides expanded. Skips where cortex-ui is not a sibling."""
    if not _CORTEX.is_file():
        pytest.skip("cortex-ui is not a sibling on disk; the cross-repo half cannot run here")

    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    back = {
        (_expand(c["subject_uri"]), _expand(c["object_uri"]))
        for c in PRESENTATION_CAPABILITIES
    }
    front = {
        (_expand(s), _expand(o))
        for s, o in re.findall(
            r'subject_uri:\s*"([^"]+)",\s*\n\s*object_uri:\s*"([^"]+)"',
            _CORTEX.read_text(encoding="utf-8"),
        )
    }
    assert len(back) >= 20 and len(front) >= 30, (
        f"a mirror parsed to almost nothing (back={len(back)}, front={len(front)}); "
        f"a mirror check over an empty set agrees perfectly"
    )
    return back, front


def test_the_two_MIRRORS_agree_FLEET_WIDE():
    """RATIFIED 2026-09-15, and no longer scoped to `fin:`.

    **`PRESENTATION_CAPABILITIES` is the declaration the mesh advertises** — the presentation
    agent registers every row of it at lifespan through `register_presentation_to_mesh` — and
    cortex-ui's `DERIVED_BINDINGS` is the mirror. **Every row must appear in both, and a row in
    one only is a defect regardless of prefix.**

    ⚠ READ THIS BEFORE CONCLUDING `capabilities.py` IS RETIRED. `capability_registry.union_menu`
    carries a prominent note — *"WHY NOT `capabilities.py` … every row it held is now DERIVED on
    the UI side"* — which reads like the file is out of the live path. It is not. That note is
    about the **anonymous fallback MENU**, which reads the runtime registry instead of this
    table. Mesh registration is a different consumer and still reads it. Two consumers, one
    file, opposite conclusions if you stop at the first comment you find.

    ── WHAT THIS CATCHES, MEASURED ──────────────────────────────────────────────────────────
    `fin:EstimateAtCompletionComparison` was in the frontend mirror and not this one for four
    days: bound, drawable, contract and glyph in place, and **never advertised by the engine
    that produces it**. Each mirror was complete on its own side, so no per-repo check could
    see it. **A mirror check is the only instrument that sees a row present in one master and
    absent from the other.**
    """
    back, front = _mirrors()
    gaps = (front - back) | (back - front)
    new = sorted(gaps - _MIRROR_GAPS_AT_RATIFICATION)
    assert not new, (
        "these bindings are declared in ONE mirror only and are not in the ratification "
        "register:\n  "
        + "\n  ".join(f"{s} -> {o}" for s, o in new)
        + "\n\nA row the backend advertises and the frontend does not bind is registered with "
        "no component that will ever be chosen for it. A row the frontend binds and the "
        "backend does not advertise is drawable and unroutable. Add the missing side, or — if "
        "this is a deliberate staging step — add it to _MIRROR_GAPS_AT_RATIFICATION and route "
        "it, remembering the register only ever shrinks."
    )


def test_the_mirror_register_ONLY_SHRINKS():
    """THE RATCHET, and it is what makes the register a debt rather than a drawer.

    An entry that has stopped being a mismatch must be DELETED, not left standing. A register
    that keeps excusing rows nobody needs excused is how an exclusion list stops being read —
    the same shape as a tombstone for a row the seed no longer ships, which keeps deleting
    nothing while reading as deliberate.
    """
    back, front = _mirrors()
    gaps = (front - back) | (back - front)
    fixed = _no_longer(_MIRROR_GAPS_AT_RATIFICATION, gaps)
    assert not fixed, (
        "these are registered as known mirror gaps and are no longer gaps:\n  "
        + "\n  ".join(f"{s} -> {o}" for s, o in fixed)
        + "\n\nDelete them from _MIRROR_GAPS_AT_RATIFICATION in the commit that fixed them. "
        "The register only shrinks; an entry left behind reads as an open defect to everyone "
        "who checks the list instead of the mirrors."
    )
    _both_directions_or_the_rule_is_untested()


def test_the_mirror_check_can_actually_FAIL():
    """THE CONTROL. Two sets compared against a register that already contains every
    difference will pass no matter what the sets say, unless a difference outside the register
    can exist."""
    back, front = _mirrors()
    invented = ("http://invincible-agent/mesh#NoSuchSubject", "http://invincible-agent/mesh#X")
    assert invented not in _MIRROR_GAPS_AT_RATIFICATION
    gaps = ((front | {invented}) - back) | (back - (front | {invented}))
    assert gaps - _MIRROR_GAPS_AT_RATIFICATION, (
        "a one-sided binding outside the register does not surface; the seal above cannot fail"
    )

_CONTRACT_FILE = (_ROOT.parent / "cortex-ui" / "src" / "components" / "planning"
                  / "CompetingMeasures.contract.ts")


# -- SEAL 6 -- the field-name join, which is the half that renders blanks ----------------
#
# Binding an archetype is not the same as feeding it. `COMPETING_MEASURES`' passthrough was
# written the same day the archetype was, from the engine's summary keys — and the engine emits
# the low/high pair under TWO names, saying beside them that `lowest_eac` is a coined summary
# name with "no claim to stay". The allowlist kept the one the contract does NOT read.
#
# So the row could have been bound and the card would have drawn a blank high and low, with the
# engine's tests green (it emits the field), the contract's tests green (it declares it), and
# the projector's own shape test green (the tuple parses). **Every endpoint verified, the join
# asserted nowhere.**

#: Contract envelope fields this engine supplies PER ROW rather than on the envelope, with the
#: reason. Checked 2026-09-15: `scope_label` is on the rows of every finance verb and on the
#: envelope of none — the response assembler builds `value_unit`, `value_label`, `series`,
#: `reference` and `verdict` at envelope level and has never built this one.
#:
#: ⚠ WHAT THIS DOES NOT CLAIM: that a card reads it from the rows and is therefore fine. That is
#: unchecked. It is listed as a KNOWN DIVERGENCE with its scope, not as a resolved one — the
#: difference between a residue named and a residue excused.
_CONTRACT_FIELDS_SUPPLIED_PER_ROW = {
    "scope_label": (
        "on the rows of every finance verb, on the envelope of none; the assembler in "
        "finance_agent/main.py builds value_unit/value_label/series/reference/verdict at "
        "envelope level and never this one. Fleet-wide, not specific to this verb."
    ),
}


def test_every_field_the_COMPETING_MEASURES_contract_reads_ARRIVES():
    """CROSS-REPO, AND THE ONE THAT WOULD HAVE CAUGHT THE BLANK CARD.

    Reads the frontend contract's own envelope list — not a copy of it kept here, which would
    agree with itself — and checks each name against BOTH the projector's allowlist and a LIVE
    payload from the verb. A field must be emitted AND survive the passthrough; either alone
    renders nothing and looks correct from that side.
    """
    if not _CONTRACT_FILE.is_file():
        pytest.skip("cortex-ui is not a sibling on disk; the cross-repo half cannot run here")

    text = _CONTRACT_FILE.read_text(encoding="utf-8")
    block = text.split("COMPETING_MEASURES_ENVELOPE_FIELDS")[1].split("]")[0]
    declared = set(re.findall(r'"(\w+)",', block))
    assert len(declared) >= 8, (
        "parsed almost nothing from the contract — the export moved, and an empty expectation "
        "is satisfied by any payload at all"
    )

    from fastapi.testclient import TestClient

    from agent_fleet.finance_agent.main import app

    passthrough = set(_projector_passthrough()["COMPETING_MEASURES"][1])
    with TestClient(app) as client:
        payload = client.post(
            "/measure/fin_eac_comparison", json={"params": {"program_id": "NP-MERIDIAN"}}
        ).json()

    expected = declared - set(_CONTRACT_FIELDS_SUPPLIED_PER_ROW)

    dropped = sorted(expected - passthrough)
    assert not dropped, (
        f"the contract reads {dropped} and the projector's allowlist drops them — the card "
        f"draws blanks while the engine, the contract and the tuple's own shape test all pass"
    )
    unemitted = sorted(expected - set(payload))
    assert not unemitted, (
        f"the contract reads {unemitted} and the payload carries no such key — declared by the "
        f"consumer and emitted by nobody, which is what `reference_value` was until today"
    )

    # THE RESIDUE IS NOT A DRAWER EITHER. An entry for a field the contract stopped declaring
    # is a standing excuse for nothing, and one that starts arriving on the envelope should be
    # deleted from here rather than left reading as a known gap.
    faults = _residue_faults(_CONTRACT_FIELDS_SUPPLIED_PER_ROW, declared, set(payload))
    # NAMED VIA chr(10), NEVER WRITTEN AS AN ESCAPE. A backslash-n in a patch script run
    # through a heredoc collapses into a real newline and splits the literal — which is
    # exactly what happened writing this line, and it is the eighth time in this repo.
    _NL = chr(10)
    assert not faults, (_NL + "  ").join(
        ["the per-row residue list has gone stale:"] + faults
    )
    _both_directions_or_the_rule_is_untested()


def test_every_prefix_EITHER_mirror_USES_can_actually_be_EXPANDED():
    """⚠ THE SILENT FAILURE MODE OF THE MIRROR CHECK ABOVE, closed before it fires.

    `_expand` returns an unrecognised URI **verbatim**. That is the documented behaviour of the
    prefix table and the reason this repo has been bitten before: *an unknown prefix passes
    through, so the row registers, reports accepted, and never matches.*

    Applied to a mirror check, it is worse than a missed expansion. Two sides holding the same
    binding under an unmappable prefix — one compact, one full — **diff as a MISMATCH that is
    not one**; two sides holding different bindings that happen to share a compact spelling can
    **diff as agreement**. Either way the seal reports confidently and wrongly, and nothing in
    it looks broken.

    ── THIS IS NOT HYPOTHETICAL, AND THE EVIDENCE WAS A RED TEST — SINCE FIXED ──────────────
    When this guard was written (2026-09-15) `tests/planning/test_lookup_prefixes_are_derived.py`
    was failing on master with exactly this: *"only the WRITER knows ['docs:']"* — a namespace the
    writer put on the wire that `_IRI_PREFIXES_FOR_LOOKUP` could not expand. **The map the mirror
    check depends on was known-incomplete, and a seal in another lane knew it before I did.**

    ⚠ **THAT GAP IS CLOSED.** The 2026-09-18 merge brought the fix: `docs:` is in the map and that
    seal passes. Recorded in the PAST TENSE deliberately — a docstring that keeps saying a test is
    red after someone fixed it is a stale claim wearing evidence's clothes, and precision makes it
    MORE believed, not less. **The guard is not retired with the instance**: the map can go
    incomplete again the next time a namespace is added, and this is what notices.

    Measured 2026-09-15: the prefixes actually used across both mirrors are `cost:`, `fin:`,
    `mesh:`, `safety:` — **all four mappable**, so the mirror result stands today. This test is
    what makes that a CHECKED fact rather than a lucky one, and it goes red on the day a `docs:`
    subject is bound while the map still lacks it.
    """
    back, front = _mirrors()

    from agent_fleet.presentation_agent.capabilities import (
        _IRI_PREFIXES_FOR_LOOKUP as PREFIXES,
    )

    # Read the RAW spellings, not the expanded pairs — an expanded URI cannot show the defect,
    # because passing through verbatim is exactly what it looks like when it works.
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    raw = {c["subject_uri"] for c in PRESENTATION_CAPABILITIES}
    raw |= {c["object_uri"] for c in PRESENTATION_CAPABILITIES}
    for s, o in re.findall(
        r'subject_uri:\s*"([^"]+)",\s*\n\s*object_uri:\s*"([^"]+)"',
        _CORTEX.read_text(encoding="utf-8"),
    ):
        raw |= {s, o}

    compact = {u.split(":", 1)[0] + ":" for u in raw if not u.startswith("http")}
    assert compact, "no compact URI in either mirror — this guard has gone vacuous"
    unmappable = sorted(compact - set(PREFIXES))
    assert not unmappable, (
        f"these prefixes are USED in a binding and cannot be expanded: {unmappable}\n"
        f"_expand returns them verbatim, so the same binding spelled compact on one side and "
        f"full on the other diffs as a mismatch that is not one — and two different bindings "
        f"sharing a compact spelling diff as agreement. Add them to "
        f"_IRI_PREFIXES_FOR_LOOKUP; see tests/planning/test_lookup_prefixes_are_derived.py, "
        f"which has been reporting `docs:` missing from that very map."
    )


# A source this file never ships, written to drive the two derivations. The decoy function carries
# every landmark key and is NOT routed; the decoy module `other` is not measures.
_DOCTORED_MAIN = """
import measures as m
from agent_fleet.finance_agent.measures import VALUE_UNIT as VU
import entities as other


def not_the_route():
    return {"measure": 1, "rows": 2, "data_provenance": 3, "decoy": other.DECOY}


@app.post("/measure/{fn}")
def run_measure(fn):
    held = m.VALUE_LABEL
    return {
        "measure": fn,
        "rows": rows,
        "data_provenance": prov,
        "by_alias": m.VALUE_UNIT[fn],
        "by_getattr": getattr(m, "SERIES")[fn],
        "by_direct_name": VU[fn],
        "from_another_module": other.NOT_A_TABLE,
        "through_a_local": held[fn],
    }
"""


def test_the_BUILDER_SELECTOR_and_the_BINDING_RESOLVER_can_actually_FAIL():
    """THE CONTROL cortex-60's mutation showed was missing, and it was missing for everything I
    added the day before.

    Their suggestion was not "does the control red when the subject breaks" but "does it red when
    the DERIVATION quietly widens" -- their own control passed under the drift it was named for.
    Run against this file on 2026-09-26, mutating the SEAL and leaving main.py pristine:

    | widening of the derivation                            | before this arm |
    | ----------------------------------------------------- | --------------- |
    | the alias resolver reverted to the typed-in "measures" | **QUIET**       |
    | direct `from ...measures import NAME` bindings dropped | **QUIET**       |
    | the alias guard dropped, so any `X.UPPER` counts       | **QUIET**       |
    | the opaque-spread allowance widened to every table     | **QUIET**       |
    | the three landmark keys cut to one                     | **QUIET**       |

    Five of the six mutations I could think of. Only removing the landmark filter entirely reded,
    through the exactly-one assertion -- which is why the selector now keys on the ROUTE and the
    landmarks are a cross-check.

    Everything below is driven by a doctored source, so it holds whatever main.py happens to
    spell today."""
    aliases, direct = _measures_bindings(_DOCTORED_MAIN)

    # DERIVED, NOT TYPED. Reverting to `frozenset({"measures"})` reds here.
    assert "m" in aliases, (
        f"the resolver did not bind the alias in `import measures as m`: {sorted(aliases)} -- it is "
        f"reading a name from somewhere other than the subject's imports"
    )
    assert "measures" not in aliases, (
        "the resolver bound the name `measures` against a source that never imports it under that "
        "name -- the module name is typed in somewhere"
    )
    assert direct == {"VU": "VALUE_UNIT"}, (
        f"the resolver did not bind `from ...measures import VALUE_UNIT as VU`: {direct} -- a table "
        f"imported by name reads as a bare local and is invisible to the population"
    )

    # SELECTED BY ROUTE. A landmark-keyed selector matches the decoy too and reds on count.
    builder = _builder_dict(_DOCTORED_MAIN)
    keys = {k.value for k in builder.keys if isinstance(k, ast.Constant)}
    assert "by_alias" in keys and "decoy" not in keys, (
        f"the selector picked a block that is not the routed handler: {sorted(keys)}"
    )

    # EVERY SPELLING, AND NOTHING FROM ANOTHER MODULE. Dropping the alias guard admits
    # `other.NOT_A_TABLE` and `DECOY` and reds here.
    refs = _table_refs(builder, (aliases, direct))
    assert refs == {"VALUE_UNIT", "SERIES"}, (
        f"the resolver read {sorted(refs)} from the doctored builder, expected "
        f"['SERIES', 'VALUE_UNIT'] -- alias, getattr and direct-name spellings must all count, and "
        f"an uppercase attribute on another module must not"
    )

    # THE TAIL, ASSERTED AS THE TAIL RATHER THAN STATED IN PROSE. cortex-60 wrote their
    # equivalent limit into a comment as "⚠ THE IRREDUCIBLE TAIL", then found it was not
    # irreducible -- a limit stated in prose reads as diligence and stops re-examination as
    # effectively as a wrong answer does. So the blind spot is a live assertion: `held[fn]`,
    # where `held = m.VALUE_LABEL`, contributes NOTHING. If that ever changes this arm reds and
    # says so, which is the only way a shrinking tail gets noticed. The MERGE consequence of
    # this tail is closed elsewhere and not by widening this function -- see
    # `_unrecognised_spread_operands` and the operand cases below.
    assert "VALUE_LABEL" not in refs, (
        "the resolver now sees a table reached through a local variable. That is an improvement, "
        "and it means the documented tail has shrunk: update `_table_refs`'s docstring and this "
        "assertion together, because the tail is what tells a reader what is NOT covered"
    )

    # AND THE ALLOWANCE MUST STAY A CHOICE. Widening it to every declared table was QUIET: an
    # allowance that admits everything is not an allowance, and the arm keyed on it then asserts
    # nothing. Checked here rather than at module scope, because a collection error gives no
    # failing arm NAME -- cortex-60's correction against their own marker grep this round.
    assert _ACCOUNTED_OPAQUE_SPREAD_TABLES, (
        "the opaque-spread allowance is empty -- no spread can be accounted at all"
    )
    assert _ACCOUNTED_OPAQUE_SPREAD_TABLES < _DECLARED_TABLES, (
        f"the opaque-spread allowance {sorted(_ACCOUNTED_OPAQUE_SPREAD_TABLES)} is not a PROPER "
        f"subset of the declared tables {sorted(_DECLARED_TABLES)} -- it excuses every spread"
    )


# Sources whose selection MUST fail, one per assertion in `_builder_dict`. The landmark
# cross-check was measured QUIET under its own removal -- a guard no mutation can red is dead
# weight described as a check, so each assertion now has a source that fires it.
_SELECTOR_MUST_REJECT = {
    "no routed handler at all": (
        "\ndef run_measure(fn):\n"
        '    return {"measure": fn, "rows": rows, "data_provenance": prov}\n',
        "addressable by its route",
    ),
    "two handlers on the route": (
        '\n@app.post("/measure/{fn}")\n'
        "def run_measure(fn):\n"
        '    return {"measure": fn, "rows": rows, "data_provenance": prov}\n\n\n'
        '@app.get("/measure/{fn}/raw")\n'
        "def run_measure_raw(fn):\n"
        '    return {"measure": fn, "rows": rows, "data_provenance": prov}\n',
        "addressable by its route",
    ),
    "two envelopes out of the one handler": (
        '\n@app.post("/measure/{fn}")\n'
        "def run_measure(fn):\n"
        "    if fn:\n"
        '        return {"measure": fn, "rows": rows, "data_provenance": prov}\n'
        '    return {"measure": fn, "rows": [], "data_provenance": None}\n',
        "asserts one envelope",
    ),
    "routed handler that is not the envelope": (
        '\n@app.post("/measure/{fn}")\n'
        "def run_measure(fn):\n"
        '    return {"measure": fn, "rows": rows}\n',
        "no longer carries",
    ),
}


# Builders whose merged operands the file must accept, and ones it must refuse. Written as
# single-line pieces because a doctored source is CONTENT, and content that carries escapes or
# quotes through a second layer of the same language is how I lost an afternoon: the nested
# triple-quote terminated its own container and the decoys were parsed as live code.
_ROUTED = '@app.post("/measure/{fn}")\ndef run_measure(fn):\n'
_HEAD = '    return {\n        "measure": fn,\n        "rows": rows,\n        "data_provenance": prov,\n'
_TAIL = "    }\n"


def _doctored_builder(*lines: str) -> str:
    return _ROUTED + _HEAD + "".join(f"        {l}\n" for l in lines) + _TAIL


_OPERANDS_ACCEPTED = {
    "no merge at all": _doctored_builder('"value_unit": measures.VALUE_UNIT[fn],'),
    "a dict literal, merged conditionally": _doctored_builder(
        '**({"value_unit": measures.VALUE_UNIT[fn]} if fn in measures.VALUE_UNIT else {}),'
    ),
    "the accounted table, called, or-ed and merged": _doctored_builder(
        "**(measures.SUMMARY[fn](rows) or {} if fn in measures.SUMMARY else {}),"
    ),
}

_OPERANDS_REFUSED = {
    "a bare local": (_doctored_builder("**held,"), "held"),
    "a helper's return": (_doctored_builder("**_grab(),"), "_grab()"),
    "a local merged INSIDE the accounted element": (
        _doctored_builder("**({**(measures.SUMMARY[fn](rows) or {}), **held} if fn else {}),"),
        "held",
    ),
    # THE `or` BRANCH, WHICH HAD A CONSEQUENCE AND NOTHING EXERCISED IT. cortex-60 sent back
    # the variant that found it: not only a guard kept after its subject was replaced, but a
    # BRANCH WHOSE ACCEPTING SIDE NOTHING EVER RUNS. Dropping `_operand_leaves`'s BoolOp arm is a
    # no-op on the tree as it stands -- the whole `call or {}` reads SUMMARY either way -- so the
    # obvious mutation was QUIET and read as "no cover needed". Put a table on the OTHER side of
    # the same `or` and it is a silent leak. A branch is exercised by the case that distinguishes
    # it, not by the case that happens to run through it.
    "a table on the far side of an `or`": (
        _doctored_builder("**(measures.SUMMARY[fn](rows) or held),"),
        "held",
    ),
    "a helper's return, one level in": (
        _doctored_builder("**({**(measures.SUMMARY[fn](rows) or {}), **_grab()} if fn else {}),"),
        "_grab()",
    ),
    "a table outside the allowance, one level in": (
        _doctored_builder(
            "**({**(measures.SUMMARY[fn](rows) or {}), **measures.VALUE_LABEL} if fn else {}),"
        ),
        "measures.VALUE_LABEL",
    ),
    "something from outside the engine entirely": (
        _doctored_builder("**request.query_params,"),
        "request.query_params",
    ),
    "a local merged beside literal keys, so the element CONTRIBUTES": (
        _doctored_builder('**{"note": 1, **held},'),
        "held",
    ),
}


def test_the_OPERAND_RULE_accepts_only_the_shapes_it_recognises():
    """The control for the change of subject, in both directions.

    A rule that refuses everything is as useless as one that refuses nothing, and only the
    accepted half can tell them apart -- so today's three real operand shapes are asserted to
    pass, and seven forms of indirection are asserted to be NAMED, not merely counted. The last
    case is the one the previous accounting could not have caught at all: an element carrying a
    literal key was never classified opaque, so nothing looked inside it.

    The refusals assert the reported SOURCE TEXT rather than just a non-empty list, because a
    refusal for the wrong reason credits a rule that never looked at the operand in question --
    and the two `**held` cases differ only in depth, so a list that is merely non-empty cannot
    distinguish them."""
    for label, src in _OPERANDS_ACCEPTED.items():
        assert _unrecognised_spread_operands(_builder_dict(src)) == [], (
            f"{label}: the operand rule refuses a shape the builder uses today -- it would red "
            f"on main.py as it stands, which makes it noise rather than a seal"
        )
    for label, (src, expected) in _OPERANDS_REFUSED.items():
        refused = _unrecognised_spread_operands(_builder_dict(src))
        assert expected in refused, (
            f"{label}: the operand rule reported {refused} and not {expected!r} -- a merge this "
            f"file cannot read reaches the wire, which is the shape that was QUIET on "
            f"2026-09-26 while every arm was green"
        )


def test_the_BUILDER_SELECTOR_REJECTS_what_it_must():
    """Each assertion in `_builder_dict` fired by a source written for it.

    MEASURED 2026-09-26: before this arm existed, deleting the landmark cross-check outright was
    QUIET. The cross-check had BEEN the selector until the route replaced it, and once it stopped
    selecting, nothing was left that could tell whether it still did anything. A guard whose
    removal changes no result is dead weight described as a check -- it gets a control or it goes.

    Each case asserts the MESSAGE, not just the raise: a rejection for the wrong reason credits an
    assertion that never fired. That is cortex-60's correction against their own wrong-reason
    detector, applied one level in."""
    for label, (src, fragment) in _SELECTOR_MUST_REJECT.items():
        with pytest.raises(AssertionError) as caught:
            _builder_dict(src)
        assert fragment in str(caught.value), (
            f"{label}: the selector rejected this source for the wrong reason -- expected a "
            f"message carrying {fragment!r}, got {str(caught.value)[:160]!r}"
        )
