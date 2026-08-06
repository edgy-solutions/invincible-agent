"""The format fingerprint has ONE implementation, and both consumers reach the SAME one.

WHY THIS TEST EXISTS AND WHAT IT WOULD CATCH. The fingerprint is the vendor-format half of the trust
key, computed by two components that must agree exactly:

  * the extraction→review sensor, which STAMPS it on every decision record;
  * ``ReviewStarter``, which DERIVES it from the fetched artifact to choose a workflow.

If they drift, the corpus documents a decision the router did not make — and the drift is SILENT AND
SAFE: fingerprints stop matching the table, every promoted format falls to the supervised floor, and
nothing anywhere is wrong except that a governed decision has no effect. Exactly the shape that took
days to find at the `/reviews` seam, one layer down.

So the pin is not "both produce the same string for these inputs" (two implementations can agree on a
sample and diverge on the next one) — it is **both call the same object**. Sameness by identity, not
by agreement. The agreement tests below are the readable half; `test_both_consumers_resolve_to_the
_same_function_object` is the load-bearing one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.utils.format_fingerprint import format_fingerprint as _canonical  # noqa: E402
from src.iagent.format_fingerprint import format_fingerprint as _via_shim  # noqa: E402
from src.iagent.defs.extraction_review_sensor import _format_fingerprint as _via_sensor  # noqa: E402


def _review(mfr="Qorvo", doc_type="PCN"):
    """An artifact ATTESTING its doc_type was extracted. Unattested doc_types read as `unknown`
    (doc-tools defaults an unextracted one to "PCN", so the value alone proves nothing)."""
    return {"doc_type": doc_type,
            "doc_type_source": "extraction",
            "review_items": [{"field_path": "header.mfr", "value": mfr}]}


def test_both_consumers_resolve_to_the_SAME_function_object():
    """IDENTITY, not agreement — the only version of this claim that cannot rot.

    Two separate implementations can pass every value-equality test in this file and still diverge
    on the input nobody thought to write down. Asserting they are the same object makes divergence
    IMPOSSIBLE rather than untested.
    """
    assert _via_shim is _canonical, (
        "src/iagent's fingerprint is no longer the agent_fleet/utils implementation — a second copy "
        "exists, and the two will disagree on some input nobody has written a test for")


def test_the_sensor_delegates_rather_than_reimplements():
    """The sensor's wrapper must CALL the shared function, not carry its own copy.

    Checked behaviourally (patching the implementation must change the sensor's answer) rather than
    by reading the source, because a source check passes on a wrapper that imports the function and
    then ignores it.

    The sensor's import is FUNCTION-LOCAL and ABSOLUTE (`agent_fleet.utils.format_fingerprint`), so
    it re-resolves the module attribute on every call and this patch takes effect. Absolute rather
    than relative on purpose: the sensor module is loaded BY FILE PATH in several suites, where a
    relative import raises "attempted relative import with no known parent package" — the first cut
    used one and broke five previously-green tests.
    """
    import agent_fleet.utils.format_fingerprint as mod

    original = mod.format_fingerprint
    try:
        mod.format_fingerprint = lambda review: "SENTINEL/patched/v1"
        assert _via_sensor(_review(), "any-key") == "SENTINEL/patched/v1", (
            "patching the shared implementation did not change the sensor's result — the sensor "
            "computes its own fingerprint")
    finally:
        mod.format_fingerprint = original


@pytest.mark.parametrize("mfr,doc_type,expected", [
    ("Qorvo", "PCN", "qorvo/pcn/v1"),
    ("  ONSEMI  ", "PDN", "onsemi/pdn/v1"),   # trimmed + lowercased
    ("", "PCN", "unknown/pcn/v1"),            # absent mfr is NOT an error
])
def test_the_shape_is_stable(mfr, doc_type, expected):
    """The value itself is a CONTRACT, not an implementation detail: it is the key immutable
    decision records were already written against. Changing it silently re-partitions the corpus and
    orphans every accumulated promotion — a fingerprint invented later cannot be applied to records
    already written."""
    assert _canonical(_review(mfr, doc_type)) == expected


def test_degraded_input_yields_unknown_rather_than_raising():
    """BOTH callers may hand it degraded input — the sensor a partial extraction, the starter
    whatever the bucket returned. `unknown` segments cannot match a promoted format (and are barred
    from promotion outright), which is the safe direction; raising would turn a degraded artifact
    into an admission-path outage.

    CONTRACT CHANGED 2026-08-06: an absent `doc_type` used to default to `pcn`, so a wholly
    unidentified artifact keyed as `unknown/pcn/v1` — indistinguishable from a real PCN whose
    manufacturer was missing. It now yields `unknown` on BOTH segments. Updated because the
    behaviour deliberately changed, not to turn a red green: the collision this removes is precisely
    what made the doc_type segment unguardable.
    """
    assert _canonical({}) == "unknown/unknown/v1"
    assert _canonical(None) == "unknown/unknown/v1"
    # doc_type present but UNATTESTED -> not trusted (doc-tools defaults an unextracted one to
    # "PCN", so the value alone proves nothing). Attested, it is used.
    assert _canonical({"review_items": ["not-a-dict"], "doc_type": "PCN"}) == "unknown/unknown/v1"
    assert _canonical({"review_items": ["not-a-dict"], "doc_type": "PCN",
                       "doc_type_source": "extraction"}) == "unknown/pcn/v1"


def test_the_key_argument_is_ignored_and_optional():
    """It always was — the purity was there, undeclared. Pinned so nobody 'restores' a dependency on
    it: the artifact-pure property is what makes the server-side derive possible at all."""
    assert _via_sensor(_review()) == _via_sensor(_review(), "s3://bucket/some/key")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
