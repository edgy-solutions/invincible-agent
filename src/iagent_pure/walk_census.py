"""The walk census: sheet questions, their expectations, and what a live run must assert.

PURE. No network, no cluster, no clock. `scripts/walk_census.py` is the runner that fires these
rows at a deployed fleet; everything here can be sealed without one, which is what lets the
derivation be checked on a laptop and the *answers* be checked against a sha.

── THE DERIVATION, AND WHY IT IS TWO-DIRECTIONAL ───────────────────────────────────────────────
`docs/measurements/walk-census.yaml` stores each question's text. The sheet also stores it. That
makes the census a MIRROR of the sheet, and a mirror is the shape this tree has been bitten by:
both sides complete and correct on their own terms, with the relation between them asserted
nowhere. A row present in one and absent from the other is invisible to every per-side check.

So `reconcile` quantifies BOTH ways:

    sheet prompt with no census row   -> MISSING_ROW      (a question nobody runs)
    census row whose text has drifted -> DRIFTED          (running text nobody asks)
    census row pointing past the end  -> INDEX_OUT_OF_RANGE

and a sheet that does not exist yet yields neither — its rows are BLOCKED, which is a red with a
named reason rather than an absence. That distinction is the whole point: a skip is a test that
did not run, its reason is a claim, and the tell is a skip count that never moves.

── THE PARTITION ───────────────────────────────────────────────────────────────────────────────
Every row is in exactly one state: RUNNABLE, or BLOCKED with a reason. There is no third bucket
and nothing is dropped. `partition` raises on a row that is neither, rather than letting an
undecided row fall out of both lists and out of the census.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The prompt form a walk sheet uses, and the ONE place it is written down.
#:
#: Identical to the regex in `tests/cost/test_the_walk_sheet_resolves_to_cost_lots.py`, which has
#: parsed the cost sheet since 2026-09-11. Sharing the FORM rather than copying a list is the
#: difference between deriving a population and sampling it — and the sheets 74, 91 and 5f are
#: writing tonight are being written to this shape precisely so one parser reaches all four.
PROMPT_RE = re.compile(r'^> \*\*"(?P<q>[^"]+)"\*\*', re.MULTILINE)

#: Every disposition a row may accept. A row's `dispositions` must be a non-empty PROPER subset:
#: a row accepting all three asserts nothing about what happened and would stay green through
#: any behaviour change at all.
#: `task_requested` IS NOT `task_created`, AND THE NAME IS THE WHOLE POINT.
#:
#: The engine's payload carries a `review_request` block — kind, task_id, audience, title. That is
#: the engine ASKING for a task. The row in `human_tasks` is what the workflow engine CREATES when
#: the definition triggers on that output. They are different acts by different components, and
#: the architect split them deliberately on 2026-09-19: the card is cortex's, the task row is 74's.
#:
#: This runner reads the ARTIFACT, so it can see the request and cannot see the row. Calling the
#: observable half `task_created` would make the census assert what the WRITER decided and report
#: it as what the STORE did — a recording double, and the most confident kind of wrong. So the
#: disposition is named for what is actually observed, and the database row stays out of scope
#: rather than being faked into it.
DISPOSITIONS = ("drawn", "slot_required", "task_requested")

#: Where a card's rows live, per archetype. `DELTA_SET` calls them `effects` — its contract's
#: word, not a synonym chosen here. Sealed against engine-cost's own table so the two cannot
#: drift; see `tests/test_the_walk_census_is_derived_from_the_sheets.py`.
#:
#: ⚠ THE THREE FINANCE ARCHETYPES BELOW WERE MISSING, AND THEIR ABSENCE SCORED AS A FLEET
#: DEFECT. Added 2026-09-19 (lane 91) after the lexical baseline filed three finance rows under
#: "0 row(s) under None" and a partition headed "FOUR finance rows fail on payload shape or row
#: count". They did not. `judge` looked the archetype up here, got `None`, counted zero, and
#: printed a floor failure — and `None` in that message is the KEY it never found, not an
#: archetype the fleet failed to produce.
#:
#: MEASURED AGAINST THE LIVE FLEET at `c0005142`, all three drawn with the right archetype and
#: exactly their floor: VARIANCE_TREE 1 row, SHORTFALL_GRID 18, COMPETING_MEASURES 3 (the last
#: carrying `lowest_value`/`highest_value`, the pair its contract reads). Engine-fin's own wire
#: returns the same counts from a deterministic offline seed, so both ends agree and the gap
#: was only ever here.
#:
#: HOW IT SURVIVED A SEAL THAT EXISTS FOR EXACTLY THIS. `test_the_row_key_map_agrees_with_
#: engine_costs_own_table` compares `set(theirs) & set(ROW_KEY)` — the OVERLAP. It asserts the
#: shared archetypes agree and is SILENT about an archetype missing from this table altogether,
#: which is the only way the bug could happen. The guard ran, its premise held, and it answered
#: a weaker question than the one it was written for. The new seal beside it asks the question
#: this table actually has to satisfy: every archetype any census row puts a floor on is keyed.
ROW_KEY = {
    "CONTRIBUTION_RANKING": "rows",
    "MULTI_SERIES": "rows",
    "DELTA_SET": "effects",
    "STEP_LADDER": "steps",
    "KNOWLEDGE_DOCUMENT": "sections",
    # ── ENGINE F (FINANCE). Keys confirmed twice over: against the live post-projector
    # payloads, and against the projector's own `_PROJECTED_ARCHETYPES`, which is the
    # authority on which key a projected card carries.
    "VARIANCE_TREE": "rows",
    "SHORTFALL_GRID": "rows",
    "COMPETING_MEASURES": "rows",
}

MISSING_ROW = "MISSING_ROW"
DRIFTED = "DRIFTED"
INDEX_OUT_OF_RANGE = "INDEX_OUT_OF_RANGE"


#: WHICH FRONTEND ASKS, and it is part of the question's identity rather than transport detail.
#:
#: MEASURED 2026-09-19, after this census spent a run reporting a healthy fleet as broken. The
#: same question, same persona, same domains, differing ONLY in this field:
#:
#:     frontend_id=None                -> KNOWLEDGE_DOCUMENT  source=refused
#:     frontend_id='cortex'            -> KNOWLEDGE_DOCUMENT  source=refused
#:     frontend_id='cortex-ui-desktop' -> CONTRIBUTION_RANKING  source=registered
#:
#: `live_view_requires_registration` — "the archetype decision is valid only against the render
#: menu of the client that will render it" (ADR-0017 amendment, on `InterviewRequest`). A caller
#: that registered no menu gets the labelled default, and a live view is REFUSED there. That
#: refusal is correct; asking without a frontend and then scoring the archetype is not.
#:
#: A walk sheet describes what a PERSON SEES IN THE BROWSER, so the census must ask as the
#: browser does or it is not walking the sheet. Declared in the census file, never defaulted
#: silently here — a row asserting an archetype against an unstated menu asserts nothing.
DEFAULT_FRONTEND = "cortex-ui-desktop"


@dataclass(frozen=True)
class CensusRow:
    id: str
    sheet: str
    sheet_index: int
    question: str
    user: str
    persona: str
    domains: tuple[str, ...]
    frontend_id: str
    expect_verb: str | None
    expect_archetype: str | None
    min_rows: int
    dispositions: tuple[str, ...]
    expect_task: dict[str, Any] | None = None
    #: How many option chips the refusal must offer. The sheet's expectation for a
    #: mandatory-slot ask is a MENU, not a text box — an ask with an empty menu is a
    #: refusal the walker cannot answer, which is a worse outcome than a wrong card.
    expect_options: int = 0
    blocked: str = ""

    @property
    def runnable(self) -> bool:
        return not self.blocked


class CensusError(ValueError):
    """The census is malformed. Names the row, because a census that cannot be read is worse
    than one that is red — it reports nothing and looks like nothing was wrong."""


def _row(raw: dict, frontend_id: str) -> CensusRow:
    rid = raw.get("id") or "<unnamed row>"
    for k in ("sheet", "sheet_index", "question", "user", "persona", "domains", "dispositions"):
        if raw.get(k) is None:
            raise CensusError(f"{rid}: missing required field {k!r}")

    disp = tuple(raw["dispositions"])
    if not disp:
        raise CensusError(
            f"{rid}: `dispositions` is empty. A row must say what it accepts; an empty list "
            f"reads as 'not decided yet' and behaves as 'accepts nothing'."
        )
    unknown = [d for d in disp if d not in DISPOSITIONS]
    if unknown:
        raise CensusError(f"{rid}: unknown disposition(s) {unknown}; vocabulary is {list(DISPOSITIONS)}")
    if set(disp) == set(DISPOSITIONS):
        raise CensusError(
            f"{rid}: accepts every disposition, which asserts nothing — the row would stay "
            f"green through any behaviour change. Name the one or two that are correct."
        )
    return CensusRow(
        id=rid,
        sheet=raw["sheet"],
        sheet_index=int(raw["sheet_index"]),
        question=raw["question"],
        user=raw["user"],
        persona=raw["persona"],
        domains=tuple(raw["domains"]),
        frontend_id=raw.get("frontend_id") or frontend_id,
        expect_verb=raw.get("expect_verb"),
        expect_archetype=raw.get("expect_archetype"),
        min_rows=int(raw.get("min_rows") or 0),
        dispositions=disp,
        expect_task=raw.get("expect_task"),
        expect_options=int(raw.get("expect_options") or 0),
        blocked=(raw.get("blocked") or "").strip(),
    )


def load_rows(census_path: Path) -> list[CensusRow]:
    """Every census row, validated.

    FAIL LOUD ON NONE, for the reason every loader in this tree states: an empty list hands the
    caller a green light and nothing to run, which is the failure mode with no symptom.
    """
    import yaml

    doc = yaml.safe_load(census_path.read_text(encoding="utf-8")) or {}
    frontend_id = (doc.get("frontend_id") or "").strip()
    if not frontend_id:
        raise CensusError(
            f"{census_path} declares no `frontend_id`. The archetype a question comes back as "
            f"depends on the render menu of the client that asked: an unregistered caller is "
            f"REFUSED a live view and gets KNOWLEDGE_DOCUMENT. A census without one scores every "
            f"archetype against a menu it never named, which is how this file spent a run "
            f"reporting a healthy fleet as broken."
        )
    raw_rows = doc.get("rows") or []
    rows = [_row(r, frontend_id) for r in raw_rows]
    if not rows:
        raise CensusError(
            f"no rows in {census_path}. An empty census runs nothing and reports success, "
            f"which is indistinguishable from a fleet where every question works."
        )
    seen: dict[str, int] = {}
    for r in rows:
        if r.id in seen:
            raise CensusError(f"duplicate row id {r.id!r}")
        seen[r.id] = 1
    return rows


def sheet_prompts(sheet_path: Path) -> list[str]:
    """The prompts a sheet declares, in order. Missing file -> empty, which is NOT an error;
    a sheet that does not exist yet is the `blocked` case and is reported as such."""
    if not sheet_path.is_file():
        return []
    return PROMPT_RE.findall(sheet_path.read_text(encoding="utf-8"))


@dataclass
class Reconciliation:
    problems: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, id_or_sheet, detail)
    checked_sheets: set[str] = field(default_factory=set)
    compared: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def reconcile(rows: list[CensusRow], repo_root: Path) -> Reconciliation:
    """Check census against sheets, BOTH DIRECTIONS.

    A one-directional check is the trap here. Comparing every census row against its sheet
    proves nothing about a prompt the sheet gained — that prompt simply has no row, and a
    per-row loop cannot see what it is not iterating over.
    """
    out = Reconciliation()
    by_sheet: dict[str, list[CensusRow]] = {}
    for r in rows:
        by_sheet.setdefault(r.sheet, []).append(r)

    for sheet, sheet_rows in by_sheet.items():
        prompts = sheet_prompts(repo_root / sheet)
        if not prompts:
            # Sheet absent (or empty). Every row on it must SAY so; a row claiming to derive
            # from a file that is not there, without a reason, is the silent case.
            for r in sheet_rows:
                if r.runnable:
                    out.problems.append((
                        "NO_SHEET", r.id,
                        f"sheet {sheet} has no parsable prompts and the row declares no "
                        f"`blocked` reason — it would run against retyped text presented as "
                        f"derived",
                    ))
            continue

        out.checked_sheets.add(sheet)
        for r in sheet_rows:
            if r.sheet_index >= len(prompts):
                out.problems.append((
                    INDEX_OUT_OF_RANGE, r.id,
                    f"sheet_index {r.sheet_index} but {sheet} declares {len(prompts)} prompt(s)",
                ))
                continue
            if prompts[r.sheet_index] != r.question:
                out.problems.append((
                    DRIFTED, r.id,
                    f"census asks {r.question!r}; {sheet}[{r.sheet_index}] asks "
                    f"{prompts[r.sheet_index]!r}",
                ))
            out.compared += 1

        covered = {r.sheet_index for r in sheet_rows}
        for i, prompt in enumerate(prompts):
            if i not in covered:
                out.problems.append((
                    MISSING_ROW, sheet,
                    f"prompt {i} ({prompt!r}) has no census row — it is asked on the sheet and "
                    f"run by nobody",
                ))
    return out


#: States an answer can be in. `INSTRUMENT` is first-class and separate from `none` on purpose:
#: see `judge`.
PASS, FAIL = "PASS", "FAIL"


def routing_of(result: dict) -> dict:
    """The routing projection, read from the `route_decision` EVENT.

    MEASURED against a live fleet on 2026-09-19, and the first version of this was wrong.
    `final_payload` carries exactly two keys — `components` and `presentation_provenance` — and
    NO routing at all; routing arrives as its own SSE event. Reading it off the final payload
    returned `{}`, every row reported `verb ''`, and that read as a fleet which had stopped
    routing. The fleet was routing correctly the entire time, at 0.92 to the right engine.

    **A broken matcher returns zero, and zero reads as a finding.** That is why `judge` reports
    an absent projection as an instrument failure rather than as a verb that was empty.
    """
    for ev in reversed(result.get("events") or []):
        if ev.get("event") == "route_decision" and isinstance(ev.get("data"), dict):
            return ev["data"]
    final = result.get("final") or {}
    if isinstance(final.get("routing"), dict):
        return final["routing"]
    for ev in reversed(result.get("events") or []):
        d = ev.get("data")
        if isinstance(d, dict) and isinstance(d.get("routing"), dict):
            return d["routing"]
    return {}


def _camel_to_snake(s: str) -> str:
    """camelCase -> snake_case, and ALL-CAPS left alone.

    Without the guard, `UNKNOWN` becomes `u_n_k_n_o_w_n`, because every character is an
    uppercase boundary. It printed that way in a real census red and made a legible finding
    ("the verb is UNKNOWN") read as a corrupted one.
    """
    if s.isupper():
        return s.lower()
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def verb_names(routing: dict) -> set[str]:
    """Every spelling of the verb an answer used.

    The wire carries `mesh:costSupplierConcentration`; the engine's own function — and the name
    a walk sheet uses — is `cost_supplier_concentration`, visible as the last segment of
    `handled_by.endpoint_url`. Asserting against ONE spelling fails on naming convention rather
    than on behaviour, so both are offered and a row matches either.
    """
    out: set[str] = set()
    iri = ((routing.get("action") or {}).get("iri")) or ""
    if iri:
        local = iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        out.add(local)
        out.add(_camel_to_snake(local))
    url = ((routing.get("handled_by") or {}).get("endpoint_url")) or ""
    if url:
        out.add(url.rstrip("/").rsplit("/", 1)[-1])
    return {x for x in out if x}


def _review_request(result: dict) -> dict:
    """The engine's `review_request` block, wherever it rides.

    Searched rather than addressed at one key, because the walk sheet captured it on the engine's
    own `/measure/...` response and the artifact may nest it. An absent block returns {} and the
    caller treats that as "no task was asked for" — which is a claim about the REQUEST only.
    """
    def walk(o):
        if isinstance(o, dict):
            rr = o.get("review_request")
            if isinstance(rr, dict) and rr:
                return rr
            for v in o.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(o, list):
            for v in o:
                found = walk(v)
                if found:
                    return found
        return {}
    return walk(result.get("final") or {}) or walk(result.get("events") or [])


def components_of(result: dict) -> list[dict]:
    final = result.get("final") or {}
    return [c for c in (final.get("components") or []) if isinstance(c, dict)]


def judge(row: CensusRow, result: dict) -> tuple[str, list[str]]:
    """Compare one answer against one row. Returns (PASS|FAIL, reasons).

    THE INSTRUMENT SPEAKS FIRST. If there is no routing projection, this says so and says it is
    an instrument failure — because "the runner could not see where the question went" and "the
    question went nowhere" are different facts, and only one of them is about the fleet.
    """
    why: list[str] = []
    routing = routing_of(result)
    comps = components_of(result)
    status = routing.get("route_status") or ""
    verbs = verb_names(routing)

    if not routing:
        # AND NOTHING ELSE IS SAID. Continuing would add "archetype [] lacks X" and
        # "disposition 'none'" — findings about the fleet, derived from an answer this runner
        # could not read. An instrument that cannot see reports that it cannot see; it does not
        # also report what it failed to observe. (This seal's own fixture caught the first
        # version doing exactly that.)
        return FAIL, [
            "NO route_decision EVENT — the runner could not read where this question went. "
            "This is an INSTRUMENT failure, not a routing failure; do not read it as a miss."
        ]

    # WHAT ACTUALLY HAPPENED, decided before it is judged. A runner that only checks whether the
    # expected thing happened cannot report what did, and "not drawn" is a far poorer finding
    # than "asked for a slot".
    archetypes = [c.get("archetype") or "" for c in comps]

    # AN ABSTAIN IS AN `ELICITATION` COMPONENT, not an event. Measured 2026-09-19; the first
    # version looked for an event carrying `outcome: slot_required`, found none, and scored a
    # correct refusal as "drawn" — the refusal is a card, which is exactly why it looked like one.
    # (Ruled earlier this week: the abstain is ELICITATION, not a new archetype.)
    elicit = next((c for c in comps if (c.get("archetype") or "") == "ELICITATION"), None)
    asked = elicit is not None and (elicit.get("disposition") == "ask" or bool(elicit.get("slot")))

    # A REVIEW REQUEST IN THE PAYLOAD, which is the engine asking for a task — see DISPOSITIONS.
    requested = _review_request(result)

    if asked:
        actual = "slot_required"
    elif requested:
        actual = "task_requested"
    elif comps:
        actual = "drawn"
    else:
        actual = "none"

    if row.expect_task and requested:
        want_kind = row.expect_task.get("kind")
        got_kind = requested.get("kind")
        if want_kind and got_kind != want_kind:
            why.append(f"review_request kind {got_kind!r} != {want_kind!r}")
        want_aud = row.expect_task.get("audience")
        got_aud = requested.get("audience")
        if want_aud and got_aud != want_aud:
            why.append(f"review_request audience {got_aud!r} != {want_aud!r}")
    if actual not in row.dispositions:
        why.append(f"disposition {actual!r}, row accepts {list(row.dispositions)}")

    if asked and row.expect_options:
        opts = elicit.get("options") or []
        if len(opts) < row.expect_options:
            why.append(
                f"elicitation offers {len(opts)} option(s), sheet expects {row.expect_options} "
                f"(option_source={elicit.get('option_source')!r}, "
                f"free_text_reason={elicit.get('free_text_reason')!r}) — an ask with an empty "
                f"menu is one the walker cannot answer from the card"
            )

    if row.expect_verb and routing and row.expect_verb not in verbs:
        why.append(f"verb {sorted(verbs)} lacks {row.expect_verb!r}")

    if row.expect_archetype:
        if row.expect_archetype not in archetypes:
            why.append(f"archetype {archetypes} lacks {row.expect_archetype!r}")
        elif row.min_rows:
            key = ROW_KEY.get(row.expect_archetype)
            comp = next(c for c in comps if c.get("archetype") == row.expect_archetype)
            payload = comp.get("payload") if isinstance(comp.get("payload"), dict) else comp
            if key is None:
                # THE INSTRUMENT SPEAKS FIRST, the same way it does for a missing routing
                # projection above — and for the same reason, learned the same way.
                #
                # This branch used to fall through to the count below, where `payload.get(None)`
                # is None, `n` is 0, and the row was filed as "0 row(s) under None, floor is N".
                # THAT SENTENCE IS A STATEMENT ABOUT THE FLEET AND ITS SUBJECT WAS THIS TABLE.
                # Three finance rows carried it into a saved baseline, under a heading that said
                # they failed on payload shape; all three had drawn correctly at exactly their
                # floor. A reader cannot tell the two apart from that message, because the only
                # difference is whether `None` is a key or a card — and it reads as a card.
                #
                # Reported and NOT counted: an unkeyed archetype means this runner does not know
                # where the rows live, so it has no basis for a number and must not print one.
                why.append(
                    f"NO ROW_KEY ENTRY for archetype {row.expect_archetype!r} — the runner "
                    f"cannot tell where this card's rows live, so its floor of {row.min_rows} "
                    f"was never tested. This is an INSTRUMENT failure, not an empty card; the "
                    f"card may be perfectly full. Add the archetype to ROW_KEY."
                )
            else:
                got = payload.get(key)
                n = len(got) if isinstance(got, list) else 0
                if n < row.min_rows:
                    why.append(f"{n} row(s) under {key!r}, floor is {row.min_rows}")

    if status and status not in ("matched", "slot_required") and not asked:
        why.append(f"route_status={status!r}")
    if routing.get("fallback"):
        why.append(f"fell back: {routing.get('fallback_reason') or 'unstated'}")

    return (FAIL if why else PASS), why


def partition(rows: list[CensusRow]) -> tuple[list[CensusRow], list[CensusRow]]:
    """(runnable, blocked). Every row lands in exactly one; nothing is dropped."""
    runnable = [r for r in rows if r.runnable]
    blocked = [r for r in rows if not r.runnable]
    if len(runnable) + len(blocked) != len(rows):
        raise CensusError("a row fell out of both partitions")
    return runnable, blocked
