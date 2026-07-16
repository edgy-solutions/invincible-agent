"""Lenient per-item apply for the DataHub asset sync (resource facts).

THE BUG THIS PINS (work seed, 2026-07-16): at 9,363 real datasets ONE
URN drew a 400 from topaz's object API; the all-or-crash apply killed
the seed Job with a bare 'Client error 400' naming nothing, and the
five git-asserted syncs after it never ran that tick. Leniency is
correct here and ONLY here: DataHub INFORMS (facts), git ASSERTS — an
unrepresentable upstream fact is skipped LOUDLY (named + topaz's
reason), stays deny-by-default, retries next tick; a broken human
assertion still refuses whole.

Run:  PYTHONPATH=policy/sync pytest tests/test_datahub_sync_lenient.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from topaz_sync import DirObject, DirRelation, TopazClient  # noqa: E402
from datahub_topaz_sync import AssetRecord, readback_assets, sync_assets  # noqa: E402


def _reject(item_desc: str) -> httpx.HTTPStatusError:
    resp = httpx.Response(
        400,
        text='{"code":3,"message":"value length must be at most 256 characters"}',
        request=httpx.Request("POST", "http://topaz/api/v3/directory/object"),
    )
    return httpx.HTTPStatusError(f"400 while writing {item_desc}", request=resp.request, response=resp)


class _RejectingTopaz:
    """In-memory directory that REJECTS writes touching ids containing
    'REJECT' — simulating topaz's id validation at apply time."""

    def __init__(self):
        self.objects: set = set()
        self.relations: set = set()

    def _guard(self, *ids: str):
        for i in ids:
            if "REJECT" in i:
                raise _reject(i)

    def set_object(self, obj, display_name=""):
        self._guard(obj.id)
        self.objects.add(obj)

    def set_relation(self, rel):
        self._guard(rel.object_id, rel.subject_id)
        self.relations.add(rel)

    def delete_object(self, obj, with_relations=True):
        self.objects.discard(obj)

    def delete_relation(self, rel):
        self.relations.discard(rel)

    def list_objects(self, obj_type):
        return [o for o in self.objects if o.type == obj_type]

    def list_relations(self, object_type, relation):
        return [
            r for r in self.relations
            if r.object_type == object_type and r.relation == relation
        ]

    def check(self, object_type, object_id, relation, subject_id):
        # Model the manifest's permission evaluation: can_read = reader | owner.
        wanted = ("owner", "reader") if relation == "can_read" else (relation,)
        return any(
            r.object_type == object_type and r.object_id == object_id
            and r.relation in wanted and r.subject_id == subject_id
            for r in self.relations
        )


GOOD = AssetRecord(urn="urn:li:dataset:(a,good,PROD)", owners=("alice",))
BAD = AssetRecord(urn="urn:li:dataset:(a,REJECT-me,PROD)", owners=("alice",))


def test_one_rejected_urn_does_not_kill_the_rest():
    client = _RejectingTopaz()
    plan, report = sync_assets(client, [GOOD, BAD])
    # The good dataset + its owner relation landed.
    assert DirObject("dataset", GOOD.urn) in client.objects
    assert any(r.object_id == GOOD.urn for r in client.relations)
    # The bad one was rejected — named, reasoned, tracked for readback.
    assert report.count >= 1
    assert any(BAD.urn in item for item, _ in report.rejected)
    assert all("256 characters" in reason for _, reason in report.rejected)
    assert BAD.urn in report.rejected_dataset_urns


def test_rejected_owner_user_is_collected_not_fatal():
    client = _RejectingTopaz()
    bad_owner = AssetRecord(urn="urn:li:dataset:(a,ok,PROD)", owners=("REJECT-svc",))
    plan, report = sync_assets(client, [GOOD, bad_owner])
    assert DirObject("dataset", GOOD.urn) in client.objects
    assert "REJECT-svc" in report.rejected_owner_ids


def test_readback_excludes_rejected_but_verifies_the_rest():
    """Rejected items are known-and-named skips, not silent apply
    failures — counting them as readback FAILs would turn every
    reported skip into a spurious exit-4."""
    client = _RejectingTopaz()
    plan, report = sync_assets(client, [GOOD, BAD])
    checked, failures = readback_assets(
        client, [GOOD, BAD],
        skip_urns=report.rejected_dataset_urns,
        skip_owners=report.rejected_owner_ids,
    )
    assert failures == 0
    assert checked == 1  # GOOD's one owner verified; BAD excluded


def test_readback_without_skips_still_fails_loud():
    """The exclusion must not weaken the control: an UNREPORTED missing
    relation (apply lied) still fails the readback."""
    client = _RejectingTopaz()
    sync_assets(client, [GOOD])
    client.relations.clear()  # simulate an inert apply
    checked, failures = readback_assets(client, [GOOD])
    assert failures == 1


def test_network_errors_still_crash():
    """Leniency covers HTTP-status rejections ONLY — a dead directory
    mid-apply must abort the run, not degrade into 9k 'skips'."""
    class _DeadTopaz(_RejectingTopaz):
        def set_object(self, obj, display_name=""):
            raise httpx.ConnectError("directory unreachable")

    client = _DeadTopaz()
    try:
        sync_assets(client, [GOOD])
    except httpx.ConnectError:
        pass
    else:
        raise AssertionError("ConnectError must propagate, not be skipped")


def test_enriched_error_names_offender_and_reason():
    """TopazClient errors must NAME the item and carry topaz's body —
    the work crash was a bare '400 Bad Request' naming nothing."""
    class _Transport(httpx.BaseTransport):
        def handle_request(self, request):
            return httpx.Response(400, text='{"message":"value length must be at most 256 characters"}')

    client = TopazClient("http://topaz")
    client._client._transport = _Transport()
    try:
        client.set_object(DirObject("dataset", "urn:li:dataset:too-long"))
    except httpx.HTTPStatusError as e:
        assert "urn:li:dataset:too-long" in str(e)
        assert "256 characters" in str(e)
    else:
        raise AssertionError("400 must raise")
