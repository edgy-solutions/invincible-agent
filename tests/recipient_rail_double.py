"""A double for Topaz at `can_read_recipient`, answering from the SHIPPED rail.

The rows are read from `policy/recipient_readers.yaml` through the sync's own loader
(`recipient_reader_sync.load_readers`), never typed in a test, so a test that uses this double is
tied to the file the Job syncs: change a shipped row and the test follows it, drop a reader and the
test that expected him goes red.

    rail = install(monkeypatch)                    # the shipped rows, every consumer patched
    rail = install(monkeypatch, path=tmp_yaml)     # an overlay's rows
    rail.down = True                               # Topaz unreachable: the call RAISES
    rail.calls                                     # [(owner, scope, caller_id), ...]

The double speaks the real function's contract: a missing argument is False, a transport failure
RAISES (it never answers False for "Topaz is down").
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
_RAIL = _REPO / "policy" / "recipient_readers.yaml"
for _p in (str(_REPO / "policy" / "sync"), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import recipient_reader_sync as _rrs  # noqa: E402


def rail_rows(path: Path | None = None) -> dict[tuple[str, str], tuple[str, ...]]:
    """{(owner, scope): (reader emails)} from a rail file, through the sync's loader. A malformed
    row is an error here too: a double built over a file the sync would refuse proves nothing."""
    raw = yaml.safe_load(Path(path or _RAIL).read_text(encoding="utf-8"))
    rows, errors = _rrs.load_readers(raw)
    assert errors == [], errors
    return {(r.owner, r.scope): tuple(r.grant_to) for r in rows}


class Rail:
    def __init__(self, rows: dict[tuple[str, str], tuple[str, ...]] | None = None):
        self.rows = rail_rows() if rows is None else dict(rows)
        self.down = False                    # Topaz unreachable for EVERY owner
        self.down_owners: set[str] = set()   # ... or only for these owners' questions
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, owner, scope, caller_id, **_k) -> bool:
        self.calls.append((owner, scope, caller_id))
        if self.down or owner in self.down_owners:
            raise ConnectionError("topaz is down")
        if not owner or not scope or not caller_id:
            return False
        return caller_id in self.rows.get((owner, scope), ())

    def readers(self, owner: str, scope: str) -> tuple[str, ...]:
        return self.rows.get((owner, scope), ())


def install(monkeypatch, rail: Rail | None = None, *, path: Path | None = None) -> Rail:
    """Patch the real function and every engine module that bound it at import."""
    rail = rail or Rail(rail_rows(path) if path else None)
    monkeypatch.setattr("agent_fleet.utils.recipient_readers.can_read_recipient", rail)
    from agent_fleet.cost_agent import main as cost_main
    from agent_fleet.finance_agent import main as fin_main
    monkeypatch.setattr(cost_main, "can_read_recipient", rail)
    monkeypatch.setattr(fin_main, "can_read_recipient", rail)
    return rail
