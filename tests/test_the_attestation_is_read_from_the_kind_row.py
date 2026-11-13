"""`promotion._declared_attestation` reads the content-kind row's `attestation` (SDK v0.9.18), not a
stub (Job 23, architect 2026-11-10).

Nothing here monkeypatches `_declared_attestation`: the registry is composed for real from
`CONTENT_KIND_OVERLAY_DIRS`. Mode names come from `promotion.ATTESTATION_*`; the undeclared answer
is `promotion.ATTESTATION_DEFAULT`, read, never restated. Production code names no kind; this seal
may (the lab rows for pcn and pdn are what the deployment declares).

  a. the lab overlay's pcn and pdn resolve to `self`, through the real registry.
  b. a kind that declares nothing keeps the default; unregistered kind and empty name likewise.
  c. CONTROL: a row that differs from a declaring-`self` row only in saying `second_party`
     resolves to `second_party`, and its attestation block serves the dropper as excluded.
  d. a malformed declaration is the 503 `attestation_undeclarable`, never `self`.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/test_the_attestation_is_read_from_the_kind_row.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.iagent import content_kinds, promotion

LAB = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "openddil-lab" / "content_kinds"


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    content_kinds._REGISTRATIONS_CACHE = None
    yield
    content_kinds._REGISTRATIONS_CACHE = None


def _row(tmp_path, kind: str, attestation: str | None) -> None:
    """A row copied from the lab's pcn row, renamed, with `attestation` set to `attestation`
    (or removed when None): the rows of one population differ only in that field."""
    out = []
    for line in (LAB / "pcn.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("attestation:"):
            continue
        out.append(f"kind: {kind}" if line.startswith("kind:") else line)
    if attestation is not None:
        out.insert(next(i for i, l in enumerate(out) if l.startswith("passes:")),
                   f"attestation: {attestation}")
    (tmp_path / f"{kind}.yaml").write_text("\n".join(out) + "\n", encoding="utf-8")


def _use(monkeypatch, d) -> None:
    monkeypatch.setenv(content_kinds._OVERLAY_DIRS_ENV, str(d))


def test_a_the_lab_overlays_pcn_and_pdn_resolve_to_self(monkeypatch):
    _use(monkeypatch, LAB)
    for kind in ("pcn", "pdn"):
        assert promotion._declared_attestation(kind) == promotion.ATTESTATION_SELF
        assert promotion.attestation_for(kind) == promotion.ATTESTATION_SELF


def test_b_an_undeclared_kind_keeps_the_default(monkeypatch, tmp_path):
    _row(tmp_path, "ctl-undeclared", None)
    _use(monkeypatch, tmp_path)
    assert content_kinds.by_kind("ctl-undeclared") is not None
    assert promotion._declared_attestation("ctl-undeclared") is None
    for kind in ("ctl-undeclared", "not-registered-at-all", ""):
        assert promotion.attestation_for(kind) == promotion.ATTESTATION_DEFAULT


def test_c_control_only_the_declared_mode_differs(monkeypatch, tmp_path):
    _row(tmp_path, "ctl-self", promotion.ATTESTATION_SELF)
    _row(tmp_path, "ctl-second", promotion.ATTESTATION_SECOND_PARTY)
    _use(monkeypatch, tmp_path)
    assert promotion.attestation_for("ctl-self") == promotion.ATTESTATION_SELF
    assert promotion.attestation_for("ctl-second") == promotion.ATTESTATION_SECOND_PARTY
    payload = {"dropped_by": {"authz_id": "drop-0"}}
    assert promotion.attestation_block("ctl-self", payload)["excluded"] == []
    assert promotion.attestation_block("ctl-second", payload)["excluded"] == ["drop-0"]


def test_d_a_malformed_declaration_is_503_not_self(monkeypatch):
    class Row:
        attestation = "two_party"

    monkeypatch.setattr(content_kinds, "by_kind", lambda k: Row())
    with pytest.raises(promotion.PromotionRefused) as ei:
        promotion.attestation_for("anything")
    assert (ei.value.error, ei.value.status) == ("attestation_undeclarable", 503)
