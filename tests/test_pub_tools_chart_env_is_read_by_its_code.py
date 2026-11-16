"""Every variable the chart sets on pub-tools is one that pub-tools' running code reads.

WHY THIS EXISTS. Through 0.4.89 the chart set `PUBLOG_S3_BUCKET` and `DATAHUB_SERVER` on the
pub-tools user-deployment. Nothing in the image read either name. The code reads
`PUBLOG_S3_BUCKET_URL` (`publog_instance/component.yaml`) and `DATAHUB_GMS_URL`
(`datahub_lineage/component.yaml`), so both settings were silently ignored and pub-tools ran on its
defaults, which happened to equal the chart's values. A variable that nothing reads looks
configured and is not: change it, and nothing changes.

WHAT IT CHECKS. The test renders the chart twice, on bare defaults and with `values-sandbox.yaml`. It
takes every env name on the pub-tools code-location and broker containers and requires each one to
be a key of `READERS`, which names the code that reads it. A name with no reader fails, and the
failure message names it.

WHAT IT CANNOT CHECK. pub-tools' source is not in this repo, so `READERS` cites it by commit
instead of reading it. When pub-tools renames a variable, the chart and `READERS` change together.
The pub-tools citations were checked at `1aa2cbe` (the build the cluster runs, image
`sha256:ed93f7b1...`) and at `e5612fa` (pub-tools master), which read the same names. The dag-tools
citations were checked at `a99779f`, the dag-tools commit pub-tools' `uv.lock` pins.
"""

import shutil
import subprocess

import pytest
import yaml

_CHART = "helm/invincible-agent"
_DEPLOYMENTS = {"t-pub-tools": "code-location", "t-pub-tools-broker": "broker"}

_PT = "pub-tools 1aa2cbe"
_DT = "dag-tools a99779f"
_PG = (
    "Dagster's instance config (templates/dagster-instance.yaml, `env: DAGSTER_POSTGRES_*`), "
    "resolved in this pod by the run subprocess that DefaultRunLauncher starts"
)

READERS = {
    "PUBLOG_S3_BUCKET_URL": f"{_PT} pub_tools/components/publog_instance/component.yaml:22",
    "AWS_ACCESS_KEY_ID": f"{_PT} pub_tools/components/publog_instance/component.yaml:24",
    "AWS_SECRET_ACCESS_KEY": f"{_PT} pub_tools/components/publog_instance/component.yaml:25",
    "AWS_ENDPOINT_URL": f"{_PT} pub_tools/components/publog_instance/component.yaml:26",
    "AWS_DEFAULT_REGION": "botocore, through s3fs, which pub_tools/lake.py uses to stage to S3",
    "DATAHUB_GMS_URL": f"{_PT} pub_tools/components/datahub_lineage/component.yaml:23",
    "DUCKDB_MEMORY_LIMIT": f"{_PT} pub_tools/lake.py:84, pub_tools/components/publog_pipeline/component.py:588",
    "DATAHUB_TOKEN": f"{_DT} dag_tools/components/datahub_lineage/component.py:726",
    "CENTRAL_GATEWAY_URL": f"{_DT} dag_tools/domain_broker/main.py:31",
    "BROKER_URL": f"{_DT} dag_tools/domain_broker/main.py:32",
    "DAGSTER_DEFS_MODULE": f"{_DT} dag_tools/domain_broker/main.py:33",
    "DAGSTER_POSTGRES_HOST": _PG,
    "DAGSTER_POSTGRES_PORT": _PG,
    "DAGSTER_POSTGRES_DB": _PG,
    "DAGSTER_POSTGRES_USER": _PG,
    "DAGSTER_POSTGRES_PASSWORD": _PG,
}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*extra: str) -> str:
    r = subprocess.run(
        ["helm", "template", "t", _CHART, *extra],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert r.returncode == 0, f"helm template failed; every check below would pass vacuously:\n{r.stderr}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _pub_tools_env(rendered: str) -> dict[str, set[str]]:
    """`{deployment/container: {env names}}` for the pub-tools deployments in a render."""
    found: dict[str, set[str]] = {}
    for doc in yaml.safe_load_all(rendered):
        if not doc or doc.get("kind") != "Deployment":
            continue
        name = doc["metadata"]["name"]
        if name not in _DEPLOYMENTS:
            continue
        for c in doc["spec"]["template"]["spec"]["containers"]:
            assert not c.get("envFrom"), (
                f"{name}/{c['name']} uses envFrom, whose names this test cannot see"
            )
            found[f"{name}/{c['name']}"] = {e["name"] for e in c.get("env", [])}
    return found


def _unread(names: set[str]) -> list[str]:
    return sorted(n for n in names if n not in READERS)


@pytest.fixture(scope="module", params=["bare", "sandbox"])
def env(request) -> dict[str, set[str]]:
    extra = () if request.param == "bare" else ("-f", f"{_CHART}/values-sandbox.yaml")
    return _pub_tools_env(_render(*extra))


def test_both_pub_tools_containers_render_with_env(env):
    """Presence first, so the subset check below cannot pass on an empty render."""
    assert set(env) == {f"{d}/{c}" for d, c in _DEPLOYMENTS.items()}, sorted(env)
    for where, names in env.items():
        assert names, f"{where} renders with no env at all"
    assert {"PUBLOG_S3_BUCKET_URL", "DATAHUB_GMS_URL"} <= env["t-pub-tools/code-location"]
    assert "PUBLOG_S3_BUCKET_URL" in env["t-pub-tools-broker/broker"]


def test_every_variable_the_chart_sets_on_pub_tools_is_one_its_code_reads(env):
    unread = {where: _unread(names) for where, names in env.items() if _unread(names)}
    assert not unread, (
        "The chart sets variables on pub-tools that nothing in its image reads:\n"
        + "\n".join(f"  {where}: {names}" for where, names in sorted(unread.items()))
        + "\nRename them to the name the code reads, or remove them. If pub-tools started "
        "reading a new name, add it to READERS with the file and commit that reads it."
    )


def test_THE_CHECK_FAILS_ON_THE_NAMES_IT_WAS_WRITTEN_FOR():
    """The two names the chart set through 0.4.89 must be refused, beside the names that replaced them."""
    assert _unread({"PUBLOG_S3_BUCKET", "DATAHUB_SERVER", "PUBLOG_S3_BUCKET_URL", "DATAHUB_GMS_URL"}) == [
        "DATAHUB_SERVER", "PUBLOG_S3_BUCKET",
    ]
