---
id:         planning-classes-have-the-same-routable-asymmetry
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0031 (instance resolution ladder); ADR-0033 (ask from the phone-book — the option source)
code-site:  agent_fleet/planning_agent/main.py (_RESOLVABLE, _enumerable, VERBS input_uri), agent_fleet/planning_agent/slots.py (_REFERENT_KIND)
summary:    MEASURED 2026-08-30 at the Engine F lane's request, FILE-NOT-FIX (engine-p is Lane 1's). The resolvable-vs-routable asymmetry Engine F found in itself exists on planning too, IN BOTH DIRECTIONS, and neither is declared. FORWARD: idp:Portfolio is the input_uri of NINE planning verbs and is NOT resolvable or enumerable — a speaker naming the portfolio has no resolver path and no menu, so the widest planning subject is the one instance nothing can pick. REVERSE: idp:Organization resolves AND enumerates while no verb takes it as input_uri and no slot declares it as a referent — a name landing on it sets a routing subject nothing serves, the resolver reports success and the question dies a hop later. Both are plausibly intentional (there is one portfolio; organizations are attribution targets rather than subjects) and BOTH ARE UNDECLARED, which is indistinguishable from oversight. Engine F now seals both directions (_NO_VERB_BY_DESIGN + _dead_end_classes, _NOT_ENUMERABLE + _unroutable_classes); the same two checks are ~15 lines on engine-p. Correction included: a first measurement said all five planning input classes were unroutable — that was a broken regex, not a finding, and the tell was the uniform extreme result.
---

# The planning classes have the same asymmetry, in both directions

**Measured 2026-08-30, at the Engine F lane's request.** Engine F found that three of its own
classes resolve and enumerate while no verb routes on them, declared them, and sealed both
directions. The question put to this lane was whether the same blindness exists on planning.

**It does — and worse, because it runs both ways.**

## The measurement

Read from `agent_fleet/planning_agent/main.py` (`_RESOLVABLE`, `_enumerable()`, `VERBS`) and
`agent_fleet/planning_agent/slots.py` (`_REFERENT_KIND`).

A class is **reachable** if a verb takes it as `input_uri` **or** a declared slot names it as a
referent. That second half matters and the first cut of this measurement missed it: a class can
be perfectly reachable as a slot referent without ever being a routing subject.

| | planning |
|---|---|
| resolvable + enumerable | Site, Capability, **Initiative**, **Project**, BusinessProcess, Technology, **Organization** |
| verb `input_uri` | **Portfolio**, Site, Capability, BusinessProcess, Technology |
| slot referents | Site, Capability, Initiative, Project, BusinessProcess, Technology |
| **DEAD END** — resolvable, neither input nor referent | **`idp:Organization`** |
| **UNRESOLVABLE** — an `input_uri` nothing can find | **`idp:Portfolio`** |

## Why each one matters

**`idp:Portfolio` — the forward gap, and it is the more interesting of the two.** It is the
`input_uri` of **nine** planning verbs — the widest planning subject — and it is **not in
`_RESOLVABLE`**, so `resolve_instance` cannot score it and `enumerate_instances` answers
`unsupported` for it. A speaker who names the portfolio has no resolver path, and an
elicitation for a portfolio-scoped slot gets no menu.

This is *probably* fine and possibly invisible: there is one portfolio, most portfolio-scoped
verbs take no instance slot, and the subject is usually implied rather than spoken. **But
"probably fine" is exactly the state that should be written down**, because the alternative
reading — that the widest subject in the model is unnameable — is a real defect wearing the
same clothes.

**`idp:Organization` — the reverse gap, the one Engine F hit.** It resolves and enumerates.
Nothing takes it as `input_uri`; no slot declares it as a referent (`_REFERENT_KIND` has
`site_id`, `capability_id`, `project_id`, `process_id`, `tech_id`, `scope_initiative_id` — no
`org_id`). So a spoken organization name **resolves successfully to a subject nothing serves**.
The resolver reports success, the router sets the subject, and the question dies one hop later
with nothing to blame.

That it is plausibly deliberate — organizations are attribution targets inside
`plan_funding_gap`'s `group_by="org"`, not things you ask *about* — is the point, not the
defence. Engine F's three were deliberate too.

## The fix, which is small and is not this lane's to make

Engine F now carries both checks and they are ~15 lines each:

* **forward** — `_unroutable_classes()`: every `input_uri` must be resolvable/enumerable, or
  listed in `_NOT_ENUMERABLE` **with a stated reason**;
* **reverse** — `_dead_end_classes()`: every resolvable class must be an `input_uri` or a slot
  referent, or listed in `_NO_VERB_BY_DESIGN` **with a stated reason**;
* both raise **at boot**, beside the seed check, so an undeclared one fails at start rather
  than at an elicitation;
* a negative control proves the two are *different* checks rather than one written twice.

**Not applied here: `agent_fleet/planning_agent/` is Lane 1's surface and this sweep is
measurement-only.** The direction is stated so the work starts from evidence: declare
`Portfolio` as deliberately-unresolvable and `Organization` as deliberately-verbless, each with
its reason, and let the checks refuse the next undeclared one.

## A correction, recorded because the tell is reusable

The first cut of this measurement reported **all five** planning input classes as unroutable
and **zero** classes as enumerable. That was a regex failing to parse `_enumerable()`, not a
finding — and **the tell was the uniform extreme result**, which is this repo's standing
signature for a broken instrument rather than a broken system
(`[[assert-on-the-claim-not-its-neighbour]]`). Reading the function instead of pattern-matching
its source produced the table above.

## Engine F's own side, fixed in the same pass

The same measurement, run from the slot side, found three `_REFERENT_KIND` entries in
`finance_agent/slots.py` — `wp_id`, `wbs_id`, `obs_id` — mapping to classes **no verb declares
a parameter for**. Inert, because `slots_for` attaches a referent only to a parameter that
exists, but an inert entry that reads as live is the remembered-list shape that module was
written to remove. Now declared in `UNATTACHED_REFERENTS` and sealed.
