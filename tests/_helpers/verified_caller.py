"""Establish a VERIFIED caller for engine O in a test (the body no longer carries identity).

Engine O binds identity and grants from `iagent_mesh.transport_auth.current_caller()` and the
directory (`_held_domains_of`), never from the request body (order 11-19). A test that used to
name the person in the body now names them here.

`TestClient` runs the SDK dependency, which re-publishes the request's own caller to the
contextvar and so overwrites anything a test set there; the seam is therefore engine O's reference
to `current_caller` (`main._current_caller`), which this helper replaces. The real RS256 path is
exercised in tests/routing/test_engine_o_binds_the_verified_caller.py.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Union

from iagent_mesh.transport_auth import CallerIdentity

from agent_fleet.ontology_service.caller_binding import GrantCache


class VerifiedCaller:
    """`.subject` is who the next request is; `.held` is the directory's answer per subject."""

    def __init__(self, subject: str, held: Mapping[str, Iterable[str]]):
        self.subject = subject
        self.held = {k: tuple(v) for k, v in held.items()}
        self.directory_calls: list[str] = []

    def as_(self, subject: str) -> "VerifiedCaller":
        self.subject = subject
        return self

    def identity(self) -> CallerIdentity:
        return CallerIdentity(self.subject, True, "verified")

    def held_of(self, subject: str):
        self.directory_calls.append(subject)
        return self.held.get(subject, ())


def install(monkeypatch, eo, subject: str,
            held: Union[Mapping[str, Iterable[str]], Iterable[str]]) -> VerifiedCaller:
    """Make engine O see `subject` as the verified caller. `held` is `{subject: domains}`, or a
    bare iterable of domains meaning that subject only. The grant cache is replaced by an
    uncached one so a test never reads another test's directory answer."""
    if not isinstance(held, Mapping):
        held = {subject: tuple(held)}
    caller = VerifiedCaller(subject, held)
    monkeypatch.setattr(eo, "_current_caller", lambda: caller.identity())
    monkeypatch.setattr(eo, "_held_domains_of", caller.held_of)
    monkeypatch.setattr(eo._caller_binding, "_DEFAULT_CACHE", GrantCache(ttl_s=0))
    return caller
