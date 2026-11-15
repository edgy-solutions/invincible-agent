---
title: A failed answer run never delivers its card, though assert_every_engine_answered's docstring says the gateway still finds it
feature: cross-cutting
lane:
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: Architect via Chris 2026-11-14 night dispatch, item 8 -- "File the bug perf found: a failed run never delivers its answer card, though the docstring says it does." Found by invincible-agent/lane/perf in its answers-off-dagster design packet, section 6.
updated: 2026-11-15
---

Read at master `9d6d8902`.

## What the docstring says

`assert_every_engine_answered` (`src/iagent/defs/dynamic_supervisor.py:4066`) fails the run when a subtask returned `engine_unreachable`. It runs after `generate_ui_payload` on purpose. Its docstring says this ordering is what lets "the gateway (which fetches that step's output value from run metadata) still find the card on a failed run", and that "red-with-honest-card is loud and correct".

## What the gateway does

The answer stream's poll loop (`src/iagent/gateway.py`, from line 10216) reads the run's status every second.

- **On `FAILURE`** (line 10240), it emits `Pipeline failed.` (`cause="dagster_run_failed"`), sets the bundle's status to `failed`, and breaks with `is_success` still false.
- **The card is fetched only when `is_success`** (line 10604). So a failed run never reads `generate_ui_payload`'s output, even though that output was recorded.
- **The `else` branch then also runs** and emits a second error, `Timeout or failed to fetch UI payload.`, with `retryable=True` and `cause="ui_payload_timeout"`. The run did not time out, so that cause is wrong, and so is retryable: a retry hits the same unreachable engine.
- **The persisted bundle** is `status='failed'` with `rendered_output=null`.

So the user gets red with a blank card and two error events. That is the outcome the docstring says the ordering exists to prevent.

## The decision this needs (owner to be named)

Does the BFF deliver the card from a failed run, marked failed?

- **If yes:** on `FAILURE`, the gateway reads `generate_ui_payload`'s output. If the output is there, it sends the card with the failure marked, and the bundle keeps the card as its `rendered_output` with `status='failed'`. If the output is not there (the run failed earlier), it says so, with one error event and the right cause.
- **If no:** the docstring is corrected to say a failed run delivers no card, and the second error event is removed or given the right cause.

Either way, the second error's `ui_payload_timeout` cause on a run that ended `FAILURE` is a defect.

The same decision is section 6 of perf's answers-off-dagster design. On that path the workflow's result is `{status: "failed", card, metadata}`, so the answer here should hold for both paths.

## A seal it needs

The test should drive a run that ends `FAILURE` after `generate_ui_payload` recorded its output, through the gateway's stream. Today's behaviour is the control: no `final_payload` event, and a `ui_payload_timeout` error. The test must go red on that and green on the decided behaviour.
