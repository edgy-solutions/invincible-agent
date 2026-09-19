# Dispatch to 74 — the safety sheet as a file, then the persistence writer

to: ia-74/lane/74

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

## 1. The safety sheet as a file the census can derive from

**Lane 1 is blocked on this for one of the census's first five rows.**

The walk census being built tonight is one YAML of rows **derived** from the sheets — never
retyped — plus a runner that fires each through `/orchestrate` with `active_persona` and
`active_domains`, reads the artifact, and asserts `route_status`, verb, archetype and a payload
floor.

I need the safety sheet in the shape of `docs/measurements/cost-card-walk-sheet.md`:

- **the three phrasings**, each on its own quoted-bold line so a parser can find them
- the **persona** and domains each is asked in
- the **expected task** each must produce — for `HAZ-1003` the screen is a
  `risk_acceptance_medium` row in `human_tasks` for `bob`, **not a 200**
- the expected verb, the expected archetype, the minimum rows, and the disposition allowed

Why derived rather than listed: the architect's first question about the cost failure was "are
those two phrasings exactly what the walk sheet says, or your own words?" — a copy in a test
lets the sheet be reworded while the seal keeps passing against text nobody asks any more.

Include a **count assertion** in whatever parses it. A parser that matches nothing collapses
every parameterized case to zero and reports green for a suite that asserted nothing; that is
the failure this shape is most exposed to.

Until the file exists, `HAZ-1003` sits in the census as **red with the reason
`awaiting safety sheet`** — visible as state, not excluded.

## 2. The persistence writer with its class declared

Ships independently. Declare the class on the writer rather than leaving it to be inferred at
the call site.

Lane: ia-01/lane/01
