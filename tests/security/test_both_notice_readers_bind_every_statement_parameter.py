"""Both readers of `NOTICE_PARTS_CYPHER` bind every parameter the statement names.

WHY THIS EXISTS. Rev 187 joined two changes to one statement: the paged `/notice_parts` read
(the cypher gained `$offset` and `$limit`) and gov's `/resolve_instance` gate (#39), whose
`visible_notice_ids` ran the same statement with `{"notice_id": ...}` alone. A real Neo4j refuses
a statement with an unbound parameter (`ParameterMissing`), and the route answers 503 for any
sustainment candidate. Every double in the suite reads only `params["notice_id"]`, so the merge
was green with the parameters missing (measured: the mutant passed all 62 arms of the two origin
seals). This seal asks the question a double does not: which `$names` does the TEXT need, and
did the CALL bind each one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.ontology_service import notice_parts as np_mod  # noqa: E402

#: Read FROM the statement, never retyped, so a new parameter widens this seal on its own.
_NEEDED = set(re.findall(r"\$([A-Za-z_]\w*)", np_mod.NOTICE_PARTS_CYPHER))


class _Driver:
    """Records the params of every run; answers one seeded-shaped row (visible, no origin)."""

    def __init__(self):
        self.calls: list[dict] = []

    def session(self, **kw):
        drv = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                assert cypher == np_mod.NOTICE_PARTS_CYPHER
                drv.calls.append(dict(params or {}))
                return []
        return _S()


def test_the_statement_names_the_paging_parameters():
    """Positive control: if the statement stopped paging, the two arms below would be vacuous."""
    assert {"notice_id", "offset", "limit"} <= _NEEDED, _NEEDED


def test_the_paged_read_binds_every_parameter():
    drv = _Driver()
    np_mod.read_notice_parts(drv, "PCN-1")
    assert drv.calls, "read_notice_parts never ran the statement"
    for params in drv.calls:
        assert _NEEDED <= set(params), f"unbound: {sorted(_NEEDED - set(params))}"


def test_the_resolve_instance_visibility_read_binds_every_parameter():
    drv = _Driver()
    np_mod.visible_notice_ids(drv, ["PCN-1", "PCN-2"])
    assert len(drv.calls) == 2, drv.calls
    for params in drv.calls:
        assert _NEEDED <= set(params), f"unbound: {sorted(_NEEDED - set(params))}"
