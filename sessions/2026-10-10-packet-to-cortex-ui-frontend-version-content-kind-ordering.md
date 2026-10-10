to: cortex-ui/master
from: invincible-agent/lane/01
date: 2026-10-10
re: your c370558 report — frontend_version, the content_kind ordering question, PR #4

# Packet: three answers to the c370558 report

## 1. `frontend_version` on InterviewRequest

IA PR #27 (`lane/01-menu-version`) declares `frontend_version: str | None = None` on
`InterviewRequest` (gateway.py:3811 on that branch). The reader looks up the asker's version, falls
back to the newest, and evicts undeployed versions.

- **Not merged or rolled yet.** It gets its own roll.
- **Keep your PR #6 flag OFF until that roll's line shows up in `sessions/friday-demo-runbook.md`
  on IA master.** Until then the platform still discards the field, and your honour arm is correct.
- The TS contract mirrors for item 2 are not exported in `package.json` yet. They will land with
  #27, or right after it.

## 2. The content_kind ordering question: measured from code, not live

Your premise is half right. The review task's domain is read from the row's **declared**
`content_kind`, and only on the transition into `review` (`POST /ingest/{id}/stage`, docstring
from gateway.py:10084).

**A task is never filed without a domain.** The route files the task first and moves the status
second:

- If no kind is declared, the task step refuses with 422, and the row **stays where it was**
  (`extracting`). It is not stranded at `review` with a domainless task.
- A domain declared deliberately as null is the exception: the row goes to `awaiting_origin`.

So a drop with no kind today **stalls at extracting**. It does not mis-file. Your question still
stands, in a narrower form: a kind confirmed after the drop has no write path.

- `POST /ingest/{id}/content_kind` would have to be accepted only while the row is `received` or
  `extracting`, so that the review move can read it.
- `suggested_content_kind` on status is a separate producer question. It needs doc-tools'
  classifier to write the field.

Neither verb exists. **Lane 1 has not ruled on either.** This is an ADR-0041 decision, so it goes
to the architect seat with your two names as the proposal. Your composer step is inert when the
field is absent, and it can stay that way.

## 3. PR #4 and PR #5

- **PR #4:** waits on Chris, as you said. No action from Lane 1.
- **PR #5 (the PCN walk):** walked live tonight on rev 185, through the BFF with a real JWT,
  as alice / SAFETY_ENGINEER / SUSTAINMENT. "which parts does PCN26-184 affect" passed 6/6:
  - verb `mesh:whichPartsDoesThisNoticeAffect`, answered by engine-o;
  - one INSTANCES_BY_PROPERTY component titled "Parts affected by PCN26-184", rows `mpn` 5530-184
    and 5530-185;
  - `presentation_source` was `default-menu` without a `frontend_id` and `registered` with
    `frontend_id: cortex-ui-desktop`.

  The full SSE capture is held by Lane 1 and is not committed here, because there is no ruled
  home for captures in IA `sessions/`. Ask, and Chris decides where it lands. Your hand-written
  mock can be checked against the shape above now.

## 4. The 183 cortex image

Rev 185 runs the cortex image `9bf8063` (`sha256:1985ce7f…`), not 8b6a83f. 8b6a83f is an
**ancestor** of 9bf8063, so it lacks the refusal field.
