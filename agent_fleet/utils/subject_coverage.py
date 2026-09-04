"""Does every class this engine makes findable lead to a verb, and vice versa?

Two questions, opposite directions, both failing SILENTLY and neither visible from the other:

    dead end      a class the engine can RESOLVE that no verb ROUTES on
    unroutable    a class a verb routes on that the engine can neither resolve nor enumerate

EXTRACTED FROM finance_agent 2026-09-04, unchanged in behaviour, because the second engine to
need it did not have it and on that evidence the third will not either. Engine COST grounds a
question to `cost#CostCategory` at 0.96, that class has zero verbs, routing falls through to the
generalist, and the answer comes back wearing the caller's persona — three weeks after the
class shipped. Engine P does not have the check either, and it predates finance. So this is not
"one engine forgot": it is a check that exists once and is needed everywhere.

WHY IT RAISES RATHER THAN WARNS, which is the whole design and the part a runbook step cannot
carry. Both failures produce a WORKING SYSTEM that answers wrongly:

  * A dead end: the resolver reports success, the router sets a subject, and the question dies
    one hop later with nothing to blame. Every probe is green. `/health` is green. The only
    symptom is an answer from somewhere else entirely, and by then the class has been in the
    pool for weeks and nobody connects the two.
  * An unroutable subject: the verb registers, `/health` is green, and the symptom is an
    elicitation offering FREE TEXT where it should have offered a menu — because the provider
    answered `unsupported`, which reads to the ask as a considered refusal rather than an
    absent capability.

A warning in a startup log is indistinguishable from the hundred other startup lines, and
nothing downstream goes red. **The choice this forces — register a verb, or declare the class a
drill-down referent WITH A REASON — is cheap at build time and expensive at demo time**, and it
is a choice, not a bug: a class that exists only to be drilled INTO is legitimate, it just has
to say so.

Both sets are DERIVED from the engine's own tables. Nothing here is a list to keep in sync.
"""
from __future__ import annotations

from typing import Iterable, Optional, Set


def dead_end_classes(
    *,
    resolvable: Iterable[str],
    verb_subjects: Iterable[str],
    no_verb_by_design: Iterable[str] = (),
) -> list[str]:
    """Classes this engine can find but no verb serves, minus the ones declared deliberate.

    ⛔ `verb_subjects` MUST BE EVERY SUBJECT, not each verb's primary one. An engine that
    registers a verb against an additional subject (`also_askable_of` in finance) has widened
    the served set, and reading only the primary would report a class as a dead end while a
    verb routes on it — a false red, which is the worse direction for a check that raises.
    """
    return sorted(set(resolvable) - set(verb_subjects) - set(no_verb_by_design))


def unroutable_classes(
    *,
    verb_subjects: Iterable[str],
    resolvable: Iterable[str],
    not_enumerable: Iterable[str] = (),
) -> list[str]:
    """Classes a verb routes on that can be neither resolved nor enumerated.

    The reverse of :func:`dead_end_classes`. That one asks "does every findable subject lead
    somewhere?"; this asks "can every verb's subject be found?" A gap here has no symptom at
    the engine at all — it appears only when a speaker omits the slot.
    """
    return sorted(set(verb_subjects) - set(resolvable) - set(not_enumerable))


def assert_subject_coverage(
    *,
    component: str,
    resolvable: Iterable[str],
    verb_subjects: Iterable[str],
    no_verb_by_design: Iterable[str] = (),
    not_enumerable: Iterable[str] = (),
    resolvable_name: str = "the resolvable set",
    by_design_name: str = "_NO_VERB_BY_DESIGN",
    not_enumerable_name: str = "_NOT_ENUMERABLE",
) -> None:
    """Raise if either direction has an undeclared gap. Call it from the engine's lifespan.

    RAISES, deliberately — see the module docstring. An engine that cannot answer for one of
    its own classes should not come up, because every downstream signal will say it did.

    The message names the classes and BOTH REPAIRS, since the right one is a judgement the
    check cannot make: a class may legitimately exist only as a drill-down referent, and in
    that case the fix is to say so rather than to invent a verb for it.
    """
    dead = dead_end_classes(
        resolvable=resolvable, verb_subjects=verb_subjects,
        no_verb_by_design=no_verb_by_design,
    )
    if dead:
        raise RuntimeError(
            f"{component} resolves classes that no verb routes on, and they are not "
            f"declared: {', '.join(dead)} — register a verb on them, or add them to "
            f"{by_design_name} with the reason"
        )

    unroutable = unroutable_classes(
        verb_subjects=verb_subjects, resolvable=resolvable,
        not_enumerable=not_enumerable,
    )
    if unroutable:
        raise RuntimeError(
            f"{component} registers verbs on classes it can neither resolve nor enumerate: "
            f"{', '.join(unroutable)} — add them to {resolvable_name}, or to "
            f"{not_enumerable_name} with a stated reason"
        )
