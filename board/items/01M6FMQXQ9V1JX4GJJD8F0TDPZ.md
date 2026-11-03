---
title: The MCP door answers before the delegate refusal: four red tests, and a guard that may no longer fire
feature: api-sdk-mcp
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: []
ruling_ref: none; found by gov's consumer run for #210, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b. Broken by 334653ad (#187, merged at fe2ef6df): each test is green at its parent and red at that commit, run in today's venv.

- tests/test_a_delegate_cannot_read_the_case.py::test_a_delegate_is_refused_the_case_before_the_fetch
- tests/test_a_delegate_cannot_read_the_case.py::test_a_non_delegate_service_is_not_refused_as_a_delegate
- tests/test_a_delegate_cannot_read_the_case.py::test_with_the_map_unset_the_same_name_falls_through_to_the_existing_gate
- tests/test_a_case_action_record_names_who_chose_approved_released.py::test_a_delegate_is_still_refused_on_the_whole_case

`dependencies=_mcp_door()` on `GET /cases/{case_id}` refuses `svc:` first with 403 `service_token_refused`, so the tests read that where they expect `delegate_reads_artifacts_only` or the existing gate's 404.

The question to answer first: `delegate_reads_artifacts_only` is the only src site of that refusal, and the door's exemption needs an `on_behalf_of` body field, which this GET does not take. If so, the guard cannot fire for a `svc:` delegate on this route. Read from the code, not measured. Whether the fix belongs in the tests or the route is yours to read.

Fix (lane/01-five-reds): the door is the answer and the ruling holds: the dead delegate_reads_artifacts_only guard is removed from get_case (and its census row), and the tests now expect the door's 403 service_token_refused, with the fetch never made and an existing and an absent case answering identically.
