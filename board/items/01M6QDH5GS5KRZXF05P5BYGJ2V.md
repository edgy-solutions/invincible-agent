---
title: The can_decide:<option> rail for obsolescence resolution, validator only (ADR-0065 provisional)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect via Chris 11-06 (obsolescence as a process; gov's rails, validator only until Lane 1's workflow row lands)
updated: 2026-11-06
---

The brief, verbatim: "Rails for obsolescence_resolution: roles (who may approve LTB / redesign) as groups + capability rows; `can_decide: <option>` rail with ratified_by: owner; contract files get a `classification` field validated against levels.yaml. Validator only until Lane 1's workflow row lands."

This item is the rail. It is modelled on the level rail (#268):

- `policy/option_deciders.yaml` has one row per option, with `grant_to_groups`, `granted_by`, `reason` and `ratified_by` (a seat). It ships empty, and no option is named in code or in the seed.
- The grantor seed is `policy/grantors/option_deciders.yaml`.
- `validate_policy` checks the rail when it is present, and refuses a `can_decide:` capability row so the rail is the one home.

Gov's readings are raised with the architect in `2026-11-06-packet-to-architect-from-gov-obsolescence-rails-can-decide-built-validator-only-four-forks.md`. They are: a role is a group named in the rail, not a second mechanism; and an option is keyed alone, not per workflow.

What waits for Lane 1's `obsolescence_resolution` row: checking that each option is registered, and one row per option.
