"""engine-docs' body store must connect with the names the pod actually carries.

Measured 2026-09-29 on the rolled fleet (rev 157): engine-docs answered every correctly resolved
subject with `502 … Unable to locate credentials`. `body_store.py` read `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY` and `S3_ENDPOINT_URL | MINIO_URL`. The pod has none of those: engines get
the shared `iagent-config` through `envFrom`, and that config carries `MINIO_ENDPOINT_URL`,
`MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`. Only the prime Job maps one set onto the other
(`prime-substrate-job.yaml`), so the writer could land every page and the reader could fetch none.

THE POD'S ENVIRONMENT IS READ FROM THE CHART, NOT RESTATED HERE. A test that typed the three names
would agree with whatever the fix typed, and pass against the next rename of either side.
`agentFleet.env` in `values-sandbox.yaml` is what `templates/configmap.yaml` renders into
`iagent-config`.

THE CONTROL DIFFERS IN EXACTLY ONE THING: the same chart environment with its object-store names
removed. It must reach the client with nothing, which proves the arm above discriminates on those
names rather than on something the stub or the host environment supplied.
"""
from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent_fleet.docs_agent.body_store import MinioBodyStore  # noqa: E402

VALUES = ROOT / "helm" / "invincible-agent" / "values-sandbox.yaml"

#: Every name the reader could fall back on. All are cleared first, so the host's own environment
#: cannot satisfy the arm.
_READER_NAMES = ("S3_ENDPOINT_URL", "MINIO_URL", "MINIO_ENDPOINT_URL", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_ACCESS_KEY", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY")


def _chart_env() -> dict:
    env = (yaml.safe_load(VALUES.read_text(encoding="utf-8"))["agentFleet"]["env"]) or {}
    return {k: str(v) for k, v in env.items() if isinstance(v, (str, int, float, bool))}


def _client_kwargs(monkeypatch, env: dict) -> dict:
    for name in _READER_NAMES:
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    seen: dict = {}

    import boto3

    def _capture(service, **kwargs):
        seen.update(kwargs, service=service)
        return object()

    monkeypatch.setattr(boto3, "client", _capture)
    MinioBodyStore()._get_client()
    return seen


def test_the_chart_environment_is_one_the_reader_can_connect_with(monkeypatch):
    env = _chart_env()
    object_store = sorted(k for k in env if k in _READER_NAMES)
    # Population check: if the chart stops carrying object-store names at all, this seal must say
    # so rather than pass on a vacuous environment.
    assert object_store, "values-sandbox.yaml agentFleet.env carries no object-store names at all"

    kw = _client_kwargs(monkeypatch, env)
    missing = [k for k in ("endpoint_url", "aws_access_key_id", "aws_secret_access_key")
               if not kw.get(k)]
    assert not missing, (
        f"engine-docs' body store would build its S3 client without {missing} from the chart's "
        f"own environment ({object_store}). That is the rev-157 `Unable to locate credentials`.")


def test_control_the_same_environment_without_its_object_store_names_reaches_nothing(monkeypatch):
    env = {k: v for k, v in _chart_env().items() if k not in _READER_NAMES}
    kw = _client_kwargs(monkeypatch, env)
    assert not kw.get("aws_access_key_id") and not kw.get("endpoint_url"), (
        "with the object-store names removed the client still got credentials, so the arm above "
        "is being satisfied by something other than the chart's names")


@pytest.mark.parametrize("names", [
    {"S3_ENDPOINT_URL": "http://s3", "AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "s"},
])
def test_the_aws_spelling_still_connects(monkeypatch, names):
    """The prime Job and any non-chart deployment set the AWS spelling; the fix must not drop it."""
    kw = _client_kwargs(monkeypatch, names)
    assert kw["endpoint_url"] == "http://s3" and kw["aws_access_key_id"] == "a"
