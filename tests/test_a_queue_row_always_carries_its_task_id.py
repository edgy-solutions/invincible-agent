"""A queue row served by `GET /me/human_tasks` always carries its `task_id` (ingest-v1 1.10.1).

The column is NOT NULL, the writer and the register body require it, and every producer supplies it
(docs/measurements/2026-11-16-humantask-task-id-census.md), so the response model says so: a row with
no task_id, or a null one, is a validation error, never a row served with a hole in it.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.iagent.ingest_api import HumanTask

ROW = {
    "id": 1, "kind": "access_request", "task_id": "access-abc", "workflow_id": None, "audience": "a",
    "status": "pending", "title": "t", "summary": "s", "requested_by": "r", "subject_ref": None,
    "payload": None, "created_at": 1, "workflow_service": None, "promise_name": None, "case_id": None,
    "declaration": {"kind": "access_request", "declared": True, "archetype": None, "badge": None,
                    "title": None, "accepts": ["approved"], "reason_required": []},
}


def test_control_a_row_with_its_task_id_validates():
    assert HumanTask.model_validate(ROW).task_id == "access-abc"


def test_a_row_with_no_task_id_is_a_validation_error():
    row = {k: v for k, v in ROW.items() if k != "task_id"}
    with pytest.raises(ValidationError) as ei:
        HumanTask.model_validate(row)
    assert "task_id" in str(ei.value)


def test_a_row_with_a_null_task_id_is_a_validation_error():
    with pytest.raises(ValidationError):
        HumanTask.model_validate({**ROW, "task_id": None})


def test_the_published_schema_requires_task_id_and_does_not_allow_null():
    schema = HumanTask.model_json_schema()
    assert "task_id" in schema["required"]
    assert schema["properties"]["task_id"].get("type") == "string"
    assert "anyOf" not in schema["properties"]["task_id"]
