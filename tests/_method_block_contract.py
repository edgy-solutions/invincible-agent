"""The `method` block's shape, declared ONCE, for every engine that emits one.

WHY THIS FILE EXISTS AND NOT A PACKET. Two engines produce CONTRIBUTION_RANKING payloads that
want a method block, and a shape agreed in prose is a shape that drifts: each side reads the
sentence, each side picks a reasonable reading, and the disagreement is invisible until a card
draws one of them wrong. Worse, an invariant BETWEEN two declarations is invisible to every
per-declaration check -- both engines' seals can be complete on their own side while a field
name differs between them. So the shape lives here, in one importable module, and each engine's
seal asserts ITS OWN producers against this, not against its own restatement of it.

WHAT IS DECIDED HERE, AND WHO DECIDED EACH. Recorded because a shape with no attribution is one
nobody can reopen without reopening all of it:

  * `inputs` is a LIST of `{name, value, unit?}`. The architecture seat's order, verbatim:
    "inputs as {name, value, unit?}". A list and not a mapping because the ORDER is part of the
    account -- the names appear in the order the formula uses them, and a reader recomputing the
    figure reads down the list. The consumer accepts either shape (see `readMethod`), so only
    the producer can make it readable.

  * A UNIT KEY IS ABSENT WHEN NO UNIT IS STATED -- never `"unit": None`. lane/ca's SDK
    convention for this field, from their packet of 2026-09-25 on `iagent_mesh/models.py`:
    "`unit=None` means *no unit stated*, not dimensionless; a blank unit is refused."
    `"unit": None` is REFUSED here rather than tolerated, because tolerating it is how one
    absent-state quietly becomes two -- "absent or null, and nobody knows which the producer
    meant".

    ⛔ THIS BULLET PREVIOUSLY SAID "ABSENT MEANS DIMENSIONLESS", CITING A COMMENT ABOUT A
    DIFFERENT FIELD. The quotation was accurate and the referent exists -- but
    `agent_fleet/finance_agent/measures.py:163` is establishing the convention for a CHART
    SERIES' `unit` ("THE UNIT BELONGS TO THE SERIES", line 146), where absent really does mean
    dimensionless because CPI and SPI render as bare ratios. Two different fields on two
    different structures share the name `unit`, and this file carried one's semantic to the
    other. Nothing on the wire changes -- the key is omitted either way -- but the CLAIM did:
    "dimensionless" is a positive assertion that a quantity is a pure ratio, and it is false of
    a lot number, which is not a quantity at all. A renderer licensed to print a bare ratio
    wherever the key is absent would have been reading a statement the producer never made.
    Assert the WEAKER of two readings when only one of them is attested for the field in hand.

  * `bound` is a NUMBER or None. The order, verbatim: "bound float|None". This NARROWS what
    lane/74 shipped in 546e6be, which sent one sentence naming the bound and who chose it. The
    narrowing loses that sentence, and the loss is real -- see BOUND, WHAT IT COSTS below.

  * `value` IS A STRING, and the order did not say. A field needs one type or every consumer
    formats per row, so leaving it open would have had two engines each invent a default -- the
    shape of defect where three providers each invented the same limit and there was no fleet
    default to agree with. It is a string because of what the CONSUMER does with it, measured
    rather than preferred: `formatLeaf` renders a number with JavaScript's `String()`, and
    `String(31221216.00)` is "31221216" -- the cents are gone, silently, on a money figure the
    block exists to make checkable. A Decimal is not JSON either. So the producer stringifies,
    and the one type is the one that survives the consumer.

  * `bound_defaulted` and `producer_sha` are OURS BEYOND THE UI, deliberately. They are on the
    wire and `readMethod` ignores both. They stay because the wire contract is not the card:
    a reader that branches on "who chose this bound" needs the flag, and it cannot be recovered
    from a rendered sentence.

BOUND, WHAT IT COSTS. `bound: 0.3` renders through `formatLeaf` as the bare string "0.3" -- no
name, no attribution. The name is recoverable, and not by guessing: a bounded measure states its
bound among its own `inputs` (it IS an input to the comparison the formula describes), and the
envelope carries the labelled `threshold` / `threshold_defaulted` pair beside the block. So
three places state one bound, all from the same local, and `check_bound_agrees` asserts they
cannot disagree. What is NOT recoverable in the card is the attribution, because
`bound_defaulted` is dropped by the consumer. That is a cortex-side change, named in the packet.

WHAT THIS FILE IS NOT. It is not a runtime validator wired into any engine. Each engine builds
its own block and guards its own invariants at the producer -- the order says "Fix your side; ca
fixes theirs", which means two implementations of one shape, not one implementation. Any engine
that wants these checks at runtime can import them; none does today, and saying so is cheaper
than a reader assuming the shape is enforced where it is only tested.

THE CONSUMER IS THE SOURCE FOR ITS OWN HALF. `parse_ts_interface` reads cortex's TypeScript
rather than restating it, because a restated interface is a second source of truth that goes
stale without anything going red.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: The fields the consumer's own `MethodBlock` interface declares. Not typed here -- the TS
#: types are POST-`formatLeaf` (`bound: string | null` is what the card holds after formatting,
#: not what the wire carries), so comparing our wire types to them would demand the producer
#: send a string bound and contradict the order. The KEYS are the contract; the types are not.
BLOCK_FIELDS_IN_THE_UI = ("formula", "inputs", "bound")

#: On the wire, ignored by `readMethod`. Each with the reason it is carried anyway, because a
#: field in neither list is UNDECIDED and must fail rather than be waved through.
BLOCK_FIELDS_BEYOND_THE_UI = {
    "bound_defaulted": (
        "a reader that BRANCHES on who chose the bound needs the flag; it cannot be recovered "
        "from a rendered number, and the card no longer carries the sentence that said it"
    ),
    "producer_sha": (
        "the attestation of WHICH build computed the figures; absent (not 'unknown') when the "
        "image was not stamped, so a reader can tell not-attested from attested-as-this"
    ),
}

#: Every field a block may carry, and exactly those.
BLOCK_FIELDS = tuple(BLOCK_FIELDS_IN_THE_UI) + tuple(BLOCK_FIELDS_BEYOND_THE_UI)

INPUT_REQUIRED = ("name", "value")

#: Optional, and the OMISSION is a statement about what was NOT said -- see the unit convention
#: in the module docstring. `readMethod` drops this field today; it is on the wire because a card
#: showing "31221216" beside "5" with no units cannot tell dollars from a count.
INPUT_OPTIONAL = {
    "unit": (
        "absent means NO UNIT STATED (lane/ca's SDK convention for this field, 2026-09-25) -- "
        "NOT dimensionless, which is the convention for a chart series' unit and a different "
        "field; the consumer's MethodInput has no unit field and readMethod drops it, so this "
        "is on the wire ahead of the card"
    ),
}

INPUT_FIELDS = tuple(INPUT_REQUIRED) + tuple(INPUT_OPTIONAL)

#: Where the consumer's half of this contract lives, relative to the cortex-ui checkout.
UI_CONTRACT_FILE = "src/lib/cardExport.ts"
UI_BLOCK_INTERFACE = "MethodBlock"
UI_INPUT_INTERFACE = "MethodInput"


def check_block(block: Any) -> list[str]:
    """Every way `block` departs from the declared shape, as sentences. Empty means it conforms.

    Returns reasons rather than raising, so a seal can report ALL of a block's departures in one
    failure instead of the first one -- and so a caller iterating a population of blocks can
    partition them.
    """
    if not isinstance(block, dict):
        return [f"a method block must be a mapping, got {type(block).__name__}"]

    bad: list[str] = []
    for field in BLOCK_FIELDS_IN_THE_UI:
        if field not in block:
            bad.append(f"missing {field!r}, which the consumer's {UI_BLOCK_INTERFACE} requires")
    for field in sorted(set(block) - set(BLOCK_FIELDS)):
        bad.append(
            f"undeclared field {field!r}: it is neither in the consumer's interface nor in "
            "BLOCK_FIELDS_BEYOND_THE_UI with a reason, so nothing says what it means"
        )

    formula = block.get("formula")
    if not isinstance(formula, str) or not formula.strip():
        bad.append(
            f"formula={formula!r}: readMethod drops a block WHOLE when its formula trims empty, "
            "so this ships a card reading 'method not supplied' about a method that exists"
        )

    bad.extend(check_inputs(block.get("inputs")))

    if "bound" in block:
        bound = block["bound"]
        if bound is not None and not isinstance(bound, (int, float)):
            bad.append(
                f"bound={bound!r} is {type(bound).__name__}; the shape is float|None. A string "
                "bound was lane/74's first form and it is what this reconciliation narrowed"
            )
        if isinstance(bound, bool):  # bool is an int, and a boolean bound is not a bound
            bad.append(f"bound={bound!r} is a boolean, which is not a numeric bound")

    if ("bound" in block and block.get("bound") is None) != (
        block.get("bound_defaulted") is None
    ):
        bad.append(
            f"bound={block.get('bound')!r} and bound_defaulted="
            f"{block.get('bound_defaulted')!r} disagree about whether this measure HAS a bound; "
            "a flag with no bound, or a bound with no word on who chose it, is the "
            "half-stated disclosure the block exists to end"
        )
    return bad


def check_inputs(inputs: Any) -> list[str]:
    """Every way `inputs` departs from a list of {name, value, unit?}."""
    if not isinstance(inputs, list):
        return [
            f"inputs must be a LIST of {{name, value, unit?}}, got {type(inputs).__name__}. "
            "readMethod accepts a mapping too, which is why only the producer can make the "
            "order -- part of the account -- survive"
        ]
    bad: list[str] = []
    for i, item in enumerate(inputs):
        where = f"inputs[{i}]"
        if not isinstance(item, dict):
            bad.append(f"{where} is {type(item).__name__}, not a mapping; readMethod SKIPS it")
            continue
        for field in sorted(set(item) - set(INPUT_FIELDS)):
            bad.append(f"{where} carries undeclared field {field!r}")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            bad.append(
                f"{where}.name={name!r}: readMethod's `str` returns '' for a non-string and the "
                "input is then dropped, so this row vanishes from the card without an error"
            )
        if "value" not in item:
            bad.append(f"{where} has no 'value'")
        else:
            value = item["value"]
            if value is not None and not isinstance(value, str):
                bad.append(
                    f"{where}.value={value!r} is {type(value).__name__}, not a string. "
                    "formatLeaf renders a number with String(), which drops the cents off "
                    "money -- see the value decision in this module's docstring"
                )
        if "unit" in item:
            unit = item["unit"]
            if unit is None:
                bad.append(
                    f"{where} carries \"unit\": None. The convention is NO UNIT KEY AT ALL when "
                    "no unit is stated; a null unit makes two spellings of one absent-state"
                )
            elif not isinstance(unit, str) or not unit.strip():
                bad.append(f"{where}.unit={unit!r} is not a stated unit; omit the key instead")
    return bad


def check_bound_agrees(
    block: Any, *, envelope_threshold: Any, bound_input_name: str
) -> list[str]:
    """One bound stated in three places must be one number.

    The block's numeric `bound`, the input row that NAMES it, and the envelope's labelled
    `threshold` are three declarations of one local. Each is checkable on its own and their
    AGREEMENT is checkable in none of them -- which is the class of invariant that stays broken
    longest, because every per-declaration seal is green while it is.
    """
    bad: list[str] = []
    if not isinstance(block, dict):
        return ["no block to check a bound against"]
    bound = block.get("bound")
    if bound is None:
        return [f"block has no bound to agree with envelope threshold {envelope_threshold!r}"]

    named = [
        i for i in (block.get("inputs") or [])
        if isinstance(i, dict) and i.get("name") == bound_input_name
    ]
    if len(named) != 1:
        bad.append(
            f"{len(named)} inputs are named {bound_input_name!r}; a bounded measure states its "
            "bound among its inputs exactly once, because that row is the only place the "
            "bound's NAME reaches the card once `bound` is a bare number"
        )
    else:
        stated = named[0].get("value")
        if stated is None or float(stated) != float(bound):
            bad.append(
                f"the input named {bound_input_name!r} states {stated!r} and bound is {bound!r}"
            )

    if envelope_threshold is None or float(envelope_threshold) != float(bound):
        bad.append(
            f"the envelope's threshold is {envelope_threshold!r} and the block's bound is "
            f"{bound!r}; both are projected and a card can show them side by side"
        )
    return bad


def parse_ts_interface(source: str, name: str) -> dict[str, str]:
    """`{field: declared type}` for one exported TypeScript interface, read from the source.

    Read rather than restated: a mirror of an interface in Python goes stale with nothing going
    red, and this file's whole purpose is to have one source per side of the contract. A
    field-name mismatch is what this catches -- cortex renaming `value`, or GAINING `unit`,
    which would be the good news this seal should report rather than hide.
    """
    body = re.search(
        r"export interface " + re.escape(name) + r" \{(.*?)^\}", source, re.S | re.M
    )
    if body is None:
        raise AssertionError(
            f"no `export interface {name}` in the consumer's source. Either it was renamed -- "
            "in which case this contract has already drifted -- or the checkout is not the one "
            "this seal thinks it is reading"
        )
    fields: dict[str, str] = {}
    for line in body.group(1).splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("//") or line.startswith("*") or line.startswith("/*"):
            continue
        field, _, declared = line.partition(":")
        fields[field.strip().rstrip("?")] = declared.strip()
    return fields


def ui_block_fields(source: str) -> dict[str, str]:
    return parse_ts_interface(source, UI_BLOCK_INTERFACE)


def ui_input_fields(source: str) -> dict[str, str]:
    return parse_ts_interface(source, UI_INPUT_INTERFACE)


def partition_against_the_ui(
    declared: tuple[str, ...],
    ui_fields: dict[str, str],
    beyond: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Split `declared` into (in the UI, beyond it with a reason, UNDECIDED).

    The third bucket is the point. A field in neither list is one nobody has decided about, and
    a partition that quietly drops it reports a conformance it never checked.
    """
    in_ui = [f for f in declared if f in ui_fields]
    with_reason = [f for f in declared if f not in ui_fields and beyond.get(f)]
    undecided = [f for f in declared if f not in ui_fields and not beyond.get(f)]
    return in_ui, with_reason, undecided


def bound_from(value: Optional[Any]) -> Optional[float]:
    """A Decimal / str / int bound as the float the shape declares, None passed through."""
    return None if value is None else float(value)
