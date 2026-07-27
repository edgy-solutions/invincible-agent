"""Integration positive-control for the CROSS-SERVICE STRING CONTRACTS.

The class that nearly bit the M2 rename (see docs/plans/cross-repo-string-contracts.md): Restate service
names, HTTP routes, and task-kind values are stringly-typed, consumed in N places, verified jointly in ZERO
per-engine tests — so a rename that updates the producer but not a consumer passes every unit test while the
loop is broken. This asserts producer + consumer agree, IN-REPO (engine-a + engine-o + cortex-bff). The
cortex-ui side is a separate repo — covered by the doc, not here. Pure file reads, no deps.

Run:  python tests/test_cross_repo_contracts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
RA = _REPO / "agent_fleet" / "restate_analyst"
EO = _REPO / "agent_fleet" / "ontology_service"
BFF = _REPO / "src" / "iagent" / "gateway.py"


def _txt(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# (canonical value, producer file, [consumer files]) — the value must appear in the producer AND every consumer.
CONTRACTS = [
    # Restate service names: engine-a defines/mounts; cortex-bff calls by URL.
    ("GroupedReview",  RA / "grouped_review_workflow.py", [BFF]),
    ("ReviewStarter",  RA / "review_starter.py",          [BFF, RA / "main.py"]),
    ("DispatchItem",   RA / "dispatch_driver.py",         [RA / "main.py"]),
    # Task-kind contract: engine-a mints; cortex-bff matches (the M2 near-miss).
    ('"grouped_review"', RA / "grouped_review_workflow.py", [BFF]),
    # HTTP routes: engine-o defines; engine-a / cortex-bff call.
    ("/write_item_state",       EO / "main.py", [RA / "dispatch_driver.py"]),
    ("/resolve_instance",       EO / "main.py", [RA / "review_composer.py"]),
    ("/instances_by_property",  EO / "main.py", [BFF]),
]

# Old pcn-named surfaces that must NOT survive anywhere in the mechanism (deletion test, code layer).
FORBIDDEN = [
    "PcnGroupedReview", "PcnReviewStarter", "PcnDispatchItem",
    "pcn_grouped_review", "write_pcn_disposition_state", "pcn_parts_by_state",
    "resolve_pcn_instance",
]
MECHANISM = [BFF, RA / "main.py", RA / "grouped_review_workflow.py", RA / "dispatch_driver.py",
             RA / "review_starter.py", RA / "review_composer.py", RA / "dispatch_plan.py",
             EO / "main.py"]


def test_producer_consumer_agree() -> None:
    for value, producer, consumers in CONTRACTS:
        assert value in _txt(producer), f"PRODUCER missing {value!r} in {producer.name}"
        for c in consumers:
            assert value in _txt(c), f"CONSUMER missing {value!r} in {c.name} (contract drift!)"


def test_no_pcn_named_surface_in_mechanism() -> None:
    for f in MECHANISM:
        t = _txt(f)
        for bad in FORBIDDEN:
            assert bad not in t, f"pcn-named surface {bad!r} still in {f.name} (deletion-test regression)"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
