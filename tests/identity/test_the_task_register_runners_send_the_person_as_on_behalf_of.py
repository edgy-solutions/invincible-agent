"""The two runners that post `/internal/human_tasks/register` send the person as `on_behalf_of`.

The gateway takes `requested_by` from the service token, so a runner that put a person in
`requested_by` would be refused (or, worse, recorded as the service). Each body is asserted AS SENT:
the request the runner hands to `requests.post`, not the function that builds it.

Run: uv run pytest tests/identity/test_the_task_register_runners_send_the_person_as_on_behalf_of.py -q
"""
from __future__ import annotations

import pytest

pytest.importorskip("restate")

from tests.test_a_case_runs_from_trigger_to_terminal import main  # noqa: E402,F401
import dispatch_driver  # noqa: E402  -- the executor's own (flat) module identity

PERSON = "approver.of-record@example.invalid"


class _Resp:
    status_code, text = 200, ""

    def json(self):
        return {"recipients": []}

    def raise_for_status(self):
        return None


def _capture(monkeypatch, module):
    posts = []
    monkeypatch.setattr(module, "mint_service_token", lambda **_: "svc-token-stub")
    monkeypatch.setattr(module.requests, "post",
                        lambda url, json=None, headers=None, **k: posts.append((url, json)) or _Resp())
    return posts


def test_the_workflow_register_sends_the_person_as_on_behalf_of_and_no_requested_by(monkeypatch):
    posts = _capture(monkeypatch, main)
    main._register_human_task("wf-1", {"id": "wf-1:s1", "audience": "aud:x", "requested_by": PERSON})
    [(url, body)] = posts
    assert url.endswith("/internal/human_tasks/register")
    assert body["on_behalf_of"] == PERSON and "requested_by" not in body, body


def test_the_dispatch_register_sends_the_person_as_on_behalf_of_and_no_requested_by(monkeypatch):
    posts = _capture(monkeypatch, dispatch_driver)
    dispatch_driver._mint_dispatch_task({
        "task_key": "n-1:p-1", "audience": "aud:x", "requested_by": PERSON, "disposition": "d",
        "mpn": "m"})
    [(url, body)] = posts
    assert url.endswith("/internal/human_tasks/register")
    assert body["on_behalf_of"] == PERSON and "requested_by" not in body, body
