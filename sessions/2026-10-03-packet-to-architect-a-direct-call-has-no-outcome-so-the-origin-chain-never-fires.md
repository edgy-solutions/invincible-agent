# Packet: a direct_call has no outcome, so origin_record's chain never fires

to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-03
re: your svc:case-runner ruling. That is built on `lane/01-origin-writer` (09685368): the client, the
executor token (only without a user token), `/internal/origin/write` gated to svc:case-runner with the steward as
on_behalf_of, and the accept step as `direct_call` with capability `origin.write`. All five mutants red.

## The gap
`main.py`'s `direct_call` branch (~2332) appends `{step_id, kind, status: SUCCESS, result}` and sets NO
`disposition`. `_disposition_of` therefore yields `outcome = None`, and
`policy/decisions/origin_record_chaining.yaml` (`matches: [outcome]`, rows `written` / `write_refused`) never
fires. Two origin-case tests go red on that branch:
`test_A_STEWARD_ACCEPTS_AND_THE_CONFIRMED_ORIGIN_GOES_TO_ITS_WRITER` and `test_A_REFUSED_WRITE_IS_NOT_A_RESOLUTION`.
No existing direct_call chains on its result (`promote_answer_artifact`'s `publish_artifact` has no chaining
decision), so there is nothing to copy. This is a question about how every direct_call produces an outcome.

## Recommendation: an opt-in field, so nothing that exists changes
The workflow definition gains `outcome_from: <response field>` on `direct_call` steps. When it is declared, the
branch sets `disposition = result[outcome_from]`, and a missing field is a TerminalError naming it, never a silent
`None`. When it is undeclared, behaviour is exactly as today. origin_record's accept step declares
`outcome_from: status`, and the route already returns `written|write_refused`. That is a schema addition
(ADR-0039's committed schema plus its drift test), which is why it is yours.

## State
- `lane/01-seam` is held at 26d4143e (items C, D, A: the event JSON door, the mapping table, and the
  doc-tools stage route that opens the promotion task at `review`). It is green and merges for roll #16
  once ca's sha lands.
- Item B waits on `lane/01-origin-writer` for this ruling. Origin cases park after acceptance until then.
- Two lesser notes on B: the case-runner token is minted per call, not cached; and two mutants fail by
  validation error and IndexError rather than by assertion, each isolated to its intended tests.

Lane: ia-01/lane/01
