"""THE AS-OF SETTING, CHART HALF: `userDeployments.dag-tools.broker.asOf.readers`.

The dag-tools user-deployment broker stamps tickets. This key names the source types it reads a
data as-of for. Default none (today: "as-of unavailable"). A type is allowed only if the PINNED
broker image registers an as-of reader for it; `$asOfRegistered` in user-deployments.yaml is that
set, deliberately not a values key. Every refusal below is paired with its control.

Run: uv run pytest tests/test_broker_as_of_readers_chart.py -v
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
_SANDBOX = "values-sandbox.yaml"
_TPL = "templates/user-deployments.yaml"
_KEY = "userDeployments.dag-tools.broker.asOf.readers"
_ENVKEY = "DAG_TOOLS_AS_OF_READERS"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_REGISTERED_RE = re.compile(r"\{\{-?\s*\$asOfRegistered := list([^}]*)\}\}")


def _helm(chart: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", str(chart), "-f", str(chart / _SANDBOX), *extra],
        capture_output=True, text=True, timeout=300,
    )


def _render(chart: Path, *extra: str) -> str:
    r = _helm(chart, *extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _docs(out: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(out) if isinstance(d, dict)]


def _broker(out: str) -> dict:
    found = [
        d for d in _docs(out)
        if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("dag-tools-broker")
        and any(
            "dag_tools.domain_broker.main:app" in (c.get("command") or [])
            for c in d["spec"]["template"]["spec"]["containers"]
        )
    ]
    assert len(found) == 1, f"expected one dag-tools broker Deployment, found {len(found)}"
    return found[0]


def _broker_env(out: str) -> dict[str, str]:
    c = [c for c in _broker(out)["spec"]["template"]["spec"]["containers"] if c["name"] == "broker"]
    assert len(c) == 1
    return {e["name"]: e.get("value") for e in c[0]["env"]}


def _template_hash(out: str) -> str:
    t = _broker(out)["spec"]["template"]
    return hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()


def _copy_chart(tmp: Path) -> Path:
    dst = tmp / "chart"
    shutil.copytree(_CHART, dst)
    return dst


def _widen(chart: Path, registered: str) -> None:
    p = chart / _TPL
    s = p.read_text(encoding="utf-8")
    new, n = _REGISTERED_RE.subn(lambda m: m.group(0).replace(
        "list" + m.group(1), "list " + registered, 1), s)
    assert n == 1, "could not find the $asOfRegistered constant"
    p.write_text(new, encoding="utf-8")


def _strip_setting(chart: Path) -> None:
    """The chart as it was before the setting: no values block, no template lines."""
    v = chart / "values.yaml"
    s = v.read_text(encoding="utf-8")
    s2, n = re.subn(r"      # THE AS-OF SETTING.*?      asOf:\n        readers: \[\]\n", "", s, flags=re.S)
    assert n == 1, "values block not found"
    v.write_text(s2, encoding="utf-8")
    t = chart / _TPL
    s = t.read_text(encoding="utf-8")
    s2, n1 = re.subn(r"\{\{- /\* The source types the PINNED.*?\*/\}\}\n\{\{- \$asOfRegistered := list[^}]*\}\}\n",
                     "", s, flags=re.S)
    s3, n2 = re.subn(r"            \{\{- /\* One home, checked unconditionally.*?value: \{\{ join \",\" \$asOfReaders \| quote \}\}\n"
                     r"            \{\{- end \}\}\n", "", s2, flags=re.S)
    assert (n1, n2) == (1, 1), "template lines not found"
    t.write_text(s3, encoding="utf-8")


def test_default_renders_no_env_and_the_pod_template_is_unchanged(tmp_path: Path):
    out = _render(_CHART)
    assert _ENVKEY not in out
    assert "dag_tools.domain_broker.main:app" in out  # control: the broker did render
    old = _copy_chart(tmp_path)
    _strip_setting(old)
    assert "asOf" not in (old / "values.yaml").read_text(encoding="utf-8")
    assert "asOfReaders" not in (old / _TPL).read_text(encoding="utf-8")
    assert _template_hash(out) == _template_hash(_render(old)), "the default changed the pod template"


def test_unregistered_type_is_refused_at_render():
    r = _helm(_CHART, "--set", f"{_KEY}={{s3_iceberg}}")
    assert r.returncode != 0, "an unregistered type rendered"
    assert "s3_iceberg" in r.stderr and "registers no as-of reader" in r.stderr


def test_control_registered_types_render(tmp_path: Path):
    ch = _copy_chart(tmp_path)
    _widen(ch, '"s3_iceberg" "s3_delta"')
    assert _broker_env(_render(ch, "--set", f"{_KEY}={{s3_iceberg}}"))[_ENVKEY] == "s3_iceberg"
    both = _render(ch, "--set", f"{_KEY}={{s3_iceberg,s3_delta}}")
    assert _broker_env(both)[_ENVKEY] == "s3_iceberg,s3_delta"
    assert _ENVKEY not in _broker_env(_render(ch))  # widening alone changes nothing


def test_the_setting_has_one_home(tmp_path: Path):
    ch = _copy_chart(tmp_path)
    _widen(ch, '"s3_iceberg" "s3_delta"')
    r = _helm(ch, "--set", f"{_KEY}={{s3_iceberg}}",
              "--set", f"userDeployments.dag-tools.broker.env.{_ENVKEY}=x")
    assert r.returncode != 0, "a second home for the setting rendered"
    assert _ENVKEY in r.stderr


@pytest.mark.parametrize("widened", [False, True], ids=["at_this_pin", "widened"])
def test_the_env_alone_is_refused_too(tmp_path: Path, widened: bool):
    """gov, #529 review: with `asOf.readers` empty, `broker.env.DAG_TOOLS_AS_OF_READERS` alone
    must not render; otherwise it bypasses the registered-set check."""
    ch = _copy_chart(tmp_path)
    if widened:
        _widen(ch, '"s3_iceberg" "s3_delta"')
    r = _helm(ch, "--set", f"userDeployments.dag-tools.broker.env.{_ENVKEY}=s3_delta")
    assert r.returncode != 0, "the env alone rendered: a second home bypasses the registered set"
    assert f"broker.env.{_ENVKEY}" in r.stderr and "one home" in r.stderr, r.stderr[-700:]
    assert "dag_tools.domain_broker.main:app" in _render(ch)  # control: the same chart renders without it


def test_the_registered_constant_is_the_pinned_brokers_table():
    """The chart's constant is the one table the PINNED dag-tools exports, read, never typed.

    The installed package must be the pinned one first, or the comparison reads another version."""
    import tomllib
    from importlib.metadata import version

    from dag_tools.domain_broker import ticket_identity

    deps = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    pins = [d.split("==", 1)[1] for d in deps if d.startswith("edgy-dag-tools==")]
    assert len(pins) == 1, f"expected one exact edgy-dag-tools pin, got {pins}"
    assert version("edgy-dag-tools") == pins[0], "the venv's dag-tools is not the pinned one"
    s = (_CHART / _TPL).read_text(encoding="utf-8")
    m = _REGISTERED_RE.search(s)
    assert m, "$asOfRegistered not found"
    chart = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert set(ticket_identity.AVAILABLE_AS_OF_READERS), "control: the pinned table is non-empty"
    assert chart == set(ticket_identity.AVAILABLE_AS_OF_READERS), (
        f"the chart registers {sorted(chart)}, the pinned broker {sorted(ticket_identity.AVAILABLE_AS_OF_READERS)}")
