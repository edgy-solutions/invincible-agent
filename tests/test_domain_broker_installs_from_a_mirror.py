"""The domain broker's start-time pip install must be pointable at a mirror, for a closed network.

The broker runs stock python:3.12-slim and pip-installs at every start: fastapi, httpx, pydantic,
hypercorn from the index, and the iagent-mesh SDK from its tag tarball. Through chart 0.4.64 the
tarball URL was hard-coded to github.com and the index was always PyPI, so a deployment with no
internet route retried github.com until the startup probe gave up (seen at work, 2026-10-22).

Modelled on topazSeed.policySource.git: a mirror URL plus an optional CA Secret, and deliberately
no skip-verify knob (no --trusted-host). The SDK VERSION still comes from meshSdkVersion alone,
which tests/test_lock_coherence.py ties to the engines' pin, so a mirror cannot skew it.

Run: uv run pytest tests/test_domain_broker_installs_from_a_mirror.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

_CHART = "helm/invincible-agent"
_MIRROR = "https://mirror.example.invalid/artifactory/generic/iagent-mesh-sdk"
_INDEX = "https://mirror.example.invalid/artifactory/api/pypi/pypi/simple"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _broker(*sets: str) -> str:
    args = ["helm", "template", "t", _CHART]
    for s in sets:
        args += ["--set", s]
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"helm template failed: {r.stderr[-2000:]}"
    docs = [d for d in r.stdout.split("\n---") if re.search(r"^kind: Deployment$", d, re.M)
            and re.search(r"^  name: t-domain-broker$", d, re.M)]
    assert len(docs) == 1, f"expected one domain-broker Deployment, got {len(docs)}"
    return docs[0]


def _version() -> str:
    values = open(f"{_CHART}/values.yaml", encoding="utf-8").read()
    return re.search(r"^\s*meshSdkVersion:\s*[\"']?(v\d+\.\d+\.\d+)", values, re.M).group(1)


def _sdk_requirement(doc: str) -> str:
    reqs = re.findall(r'"iagent-mesh @ ([^"]+)"', doc)
    assert len(reqs) == 1, f"expected one iagent-mesh requirement, got {reqs!r}"
    return reqs[0]


def test_by_default_the_sdk_comes_from_the_github_tag_tarball():
    # Control: the default is unchanged, so the sandbox renders as before.
    assert _sdk_requirement(_broker()) == (
        f"https://github.com/edgy-solutions/iagent-mesh-sdk/archive/refs/tags/{_version()}.tar.gz")


@pytest.mark.parametrize("base", [_MIRROR, _MIRROR + "/"])
def test_a_mirror_base_url_replaces_github_and_keeps_the_pinned_version(base):
    doc = _broker(f"domainBroker.meshSdkBaseUrl={base}")
    assert _sdk_requirement(doc) == f"{_MIRROR}/{_version()}.tar.gz"
    assert "github.com" not in doc, "a mirrored broker still names github.com"


def _sdk_line(doc: str) -> list[str]:
    return re.findall(r'"iagent-mesh[^"]*"', doc)


def test_index_source_installs_the_pinned_version_by_name():
    doc = _broker("domainBroker.meshSdkSource=index", f"domainBroker.pip.indexUrl={_INDEX}")
    assert _sdk_line(doc) == [f'"iagent-mesh=={_version().removeprefix("v")}"']
    assert "github.com" not in doc, "an index-sourced broker still names github.com"


def test_an_unknown_source_refuses_to_render():
    r = subprocess.run(["helm", "template", "t", _CHART, "--set", "domainBroker.meshSdkSource=git"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0 and "meshSdkSource must be url or index" in r.stderr


def test_by_default_pip_reads_pypi_and_trusts_the_image_bundle():
    doc = _broker()
    assert "PIP_INDEX_URL" not in doc and "PIP_CERT" not in doc


def test_a_pip_index_url_reaches_pip():
    doc = _broker(f"domainBroker.pip.indexUrl={_INDEX}")
    assert re.search(r"- name: PIP_INDEX_URL\n\s+value: \"" + re.escape(_INDEX) + '"', doc), doc


def test_a_ca_secret_is_mounted_and_named_to_pip():
    doc = _broker("domainBroker.pip.caSecretName=mirror-ca")
    assert re.search(r"- name: PIP_CERT\n\s+value: \"/etc/pip-ca/ca.crt\"", doc)
    assert re.search(r"- name: pip-ca\n\s+mountPath: /etc/pip-ca\n\s+readOnly: true", doc)
    assert re.search(r"- name: pip-ca\n\s+secret:\n\s+secretName: \"mirror-ca\"", doc)


def test_there_is_no_way_to_turn_tls_verification_off():
    doc = _broker(f"domainBroker.meshSdkBaseUrl={_MIRROR}", f"domainBroker.pip.indexUrl={_INDEX}",
                  "domainBroker.pip.caSecretName=mirror-ca")
    for knob in ("--trusted-host", "PIP_TRUSTED_HOST", "--no-check-certificate"):
        assert knob not in doc
