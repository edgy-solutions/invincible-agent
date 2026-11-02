"""Engine S reads the task kinds its card names from the overlay list the DEPLOYMENT serves.

In a pod that list is `TASK_KIND_OVERLAY_DIRS` from the chart's shared ConfigMap. Here the same
value is read out of the chart (not retyped) and mapped from the image's `/app` to this checkout,
so every safety test runs against the list a deployment would. A test that wants it unset or
different sets it itself.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def served_overlay_dirs() -> str:
    cm = (_REPO / "helm" / "invincible-agent" / "templates" / "configmap.yaml").read_text(
        encoding="utf-8"
    )
    [value] = re.findall(r'^\s*TASK_KIND_OVERLAY_DIRS: "([^"]*)"', cm, flags=re.M)
    return os.pathsep.join(
        str(_REPO / p.strip()[len("/app/"):]) for p in value.split(":") if p.strip()
    )


@pytest.fixture(autouse=True)
def _served_task_kind_overlays(monkeypatch):
    monkeypatch.setenv("TASK_KIND_OVERLAY_DIRS", served_overlay_dirs())
