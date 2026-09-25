"""THE CALLER'S CREDENTIAL IS THREADED THROUGH STATE AND MUST NEVER REACH THE STORE.

Measured 2026-09-23 against the live Postgres saver: five distinct bearer tokens, **fifteen
plaintext copies**, across three sites — `checkpoint_blobs` on the `identity` channel,
`checkpoint_blobs` on `__start__`, and `checkpoint_writes.blob`. No TTL: a thread named for
2026-09-19 was still at rest four days later.

NOTHING IN THE HOST WAS A CODING MISTAKE, which is why the fix belongs here rather than at the
call site. Threading the initiator's credential is deliberate and correct under ADR-0049
Ruling 1 — identity is an argument, and the host holds no standing credential of its own. The
host put it in a state channel, and a durable saver persists state channels. Both halves are
right; their composition is the defect. So the seam to close is the WRITE, not the threading.

THE SCRUB IS A COPY, NEVER A MUTATION, and that is the sharpest hazard in this file. `put` is
handed the live checkpoint of a run that is still executing. Redacting `channel_values` in
place would strip the credential out from under the next node, turning a storage fix into a
mid-run authorization failure — a graph that refuses at node 2 having worked at node 1.
`test_the_running_graph_still_holds_the_credential` exists for exactly that and is the arm to
read before changing anything here.

A RESUMED RUN THEREFORE HAS NO CREDENTIAL, AND THAT IS THE INTENDED BEHAVIOUR rather than a
side effect to fix later. A restored `identity` is the redaction marker, so a graph resuming
without a freshly supplied identity refuses at its own identity check. Under ADR-0049 that is
the correct answer: the host cannot re-authorize work on behalf of a caller who is no longer
present. Anyone tempted to "repair" resume by persisting the credential is reintroducing the
finding.

TWO PREDICATES, BECAUSE A KEY LIST IS A SAMPLE. Redaction fires on the declared identity
carriers (`IDENTITY_CHANNEL`, `IDENTITY_HEADERS`) **and** on anything JWT-shaped wherever it
appears, because a credential that arrives under a key nobody enumerated is exactly the case a
key list cannot see. The shape predicate over-redacts by construction — a legitimate value
whose text happens to look like a token is redacted too — and that is the trade accepted here:
this is checkpoint storage, and a redacted checkpoint field costs a re-run while a stored
credential costs an incident.
"""
from __future__ import annotations

import re
from typing import Any

#: The state channel the host threads identity through. Exported so `main.py` writes the key it
#: reads here — a second spelling in either file would be a mirror, and a mirror where only one
#: side is ever read is how a scrub goes silently blind.
IDENTITY_CHANNEL = "identity"

#: The headers that carry WHO IS ASKING. One declaration, imported by `main.py`; `authorization`
#: is the credential and the other two are identifiers, but the channel is redacted wholesale so
#: nothing about the caller is retained by the store either way.
IDENTITY_HEADERS = ("authorization", "x-originator-sub", "x-originator-email")

#: What a redacted value reads as in the store. A MARKER RATHER THAN A DELETION, because an
#: absent key and a refused key are different findings: whoever opens a checkpoint row should be
#: able to tell "this run carried no identity" from "this run's identity was not written down".
REDACTED = "<redacted: identity is never persisted — agent_fleet/graph_host/identity_scrub.py>"

#: A JSON object base64url-encodes to something starting `eyJ`, which is why that prefix is the
#: tell the seal is written against. Segments are matched permissively and the dotted tail is
#: optional so a bare first segment — a token split across a structure — is caught too.
_JWT_SHAPED = re.compile(r"eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+){0,2}")


def scrub(value: Any) -> Any:
    """Return a redacted COPY of `value`. Never mutates its argument — see the module docstring.

    Walks mappings, lists and tuples so a credential nested anywhere is reached. Unknown types
    pass through untouched: this is a redactor, not a serializer, and a type it does not
    understand is one it must not silently rewrite.
    """
    if isinstance(value, dict):
        out: dict = {}
        for key, inner in value.items():
            out[key] = _scrub_named(key, inner)
        return out
    if isinstance(value, (list, tuple)):
        scrubbed = [scrub(v) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, str):
        # A LAMBDA, NOT THE STRING — `re.sub` interprets backslashes and `\g<…>` in a replacement
        # STRING, so a marker someone later edits to contain one would be silently rewritten or
        # would raise `error: bad escape` on a production write path. The callable form removes the
        # escape layer instead of getting it right, which is the only version that stays right.
        return _JWT_SHAPED.sub(lambda _match: REDACTED, value)
    if isinstance(value, bytes):
        # Bytes reach here when a caller has already serialized something. Decoded
        # permissively: a credential hidden by an undecodable byte elsewhere in the same blob
        # would otherwise pass, and `errors="replace"` cannot fail.
        text = value.decode("utf-8", errors="replace")
        if _JWT_SHAPED.search(text):
            return REDACTED.encode("utf-8")
        return value
    return value


def _scrub_named(key: Any, value: Any) -> Any:
    """Redact by DECLARED NAME first, then fall through to the shape predicate.

    The name arm is what makes the whole `identity` channel disappear rather than only the
    token inside it; the shape arm is what catches the token that never passed through a name
    anyone listed.
    """
    if isinstance(key, str):
        lowered = key.lower()
        if lowered == IDENTITY_CHANNEL:
            return {h: REDACTED for h in IDENTITY_HEADERS}
        if lowered in IDENTITY_HEADERS:
            return REDACTED
    return scrub(value)


def scrub_channel(channel: str, value: Any) -> Any:
    """Redact a value whose channel NAME is the key — the shape `put_writes` hands us.

    `put` passes `{channel: value}` mappings, so the name arm sees `identity` as a dict key;
    `put_writes` passes `(channel, value)` pairs, where the same name is positional and would
    otherwise be invisible to a mapping walk.
    """
    return _scrub_named(channel, value)


def scrub_checkpoint(checkpoint: Any) -> Any:
    """A shallow copy of the checkpoint with `channel_values` redacted.

    Shallow on purpose: `channel_versions` and `versions_seen` carry no caller data and
    rewriting them risks changing what the saver believes about ordering. Only the payload is
    touched, and `scrub` already guarantees the nested copy.
    """
    if not isinstance(checkpoint, dict):
        return scrub(checkpoint)
    out = dict(checkpoint)
    if "channel_values" in out:
        out["channel_values"] = scrub(out["channel_values"])
    return out


def scrub_writes(writes: Any) -> Any:
    """Redact a `Sequence[tuple[channel, value]]`, keeping the channel names intact.

    The names are not secret and they are how anyone reading the store later knows a write
    happened at all. Dropping them would hide the redaction as well as the credential.
    """
    try:
        return [(channel, scrub_channel(channel, value)) for channel, value in writes]
    except (TypeError, ValueError):
        # A writes shape this does not recognise is redacted wholesale rather than passed
        # through. An unrecognised shape is the one case where "leave it alone" is the wrong
        # default: the whole point is that nothing unexamined reaches the store.
        return scrub(writes)


def scrubbing_saver_class(base: type) -> type:
    """Subclass `base`, overriding only the four write entry points.

    A SUBCLASS RATHER THAN A WRAPPER, because LangGraph isinstance-checks the checkpointer —
    measured: a `__getattr__`-delegating wrapper is refused by `compile()` with
    "Expected an instance of `BaseCheckpointSaver`". Subclassing the CONCRETE saver also means
    every method this file does not name is inherited verbatim, so the forwarding surface is a
    census by construction instead of a hand-written list that ages badly.

    All four of `put`/`aput`/`put_writes`/`aput_writes` are overridden even though a given
    saver implements only one pair. Covering the pair a saver does not use costs nothing, and a
    scrub that depends on which pair the runtime happens to call is a scrub with a hole in it.
    """

    class _ScrubbingSaver(base):  # type: ignore[misc, valid-type]
        #: Read by the seal to assert a saver is scrubbing without invoking it.
        scrubs_identity = True

        def put(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            return super().put(config, scrub_checkpoint(checkpoint), scrub(metadata),
                               new_versions)

        async def aput(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
            return await super().aput(config, scrub_checkpoint(checkpoint), scrub(metadata),
                                      new_versions)

        def put_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            return super().put_writes(config, scrub_writes(writes), task_id, task_path)

        async def aput_writes(self, config, writes, task_id, task_path=""):  # type: ignore[no-untyped-def]
            return await super().aput_writes(config, scrub_writes(writes), task_id, task_path)

    _ScrubbingSaver.__name__ = f"Scrubbing{base.__name__}"
    _ScrubbingSaver.__qualname__ = _ScrubbingSaver.__name__
    return _ScrubbingSaver
