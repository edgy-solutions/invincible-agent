# Lane 1, 2026-09-28 — item 3 measured on the deployed payload, and the delta the dispatch asked for **cannot be computed**

**Lane:** `invincible-agent/master` · **Item:** overnight dispatch 3 (after-half) · **Subject:** engine-o
`/resolve` at revision 155, payload `ec055c49` · **Seal: CONFIRMED live. Delta: NOT COMPUTABLE.**

The dispatch asked for "recall across MAINTENANCE three fires before/after; report the delta." The
after half is measured below and the seal holds. **The before half was never taken, and the window for
taking it closed when the fleet moved to the payload sha.** That is reported as a gap rather than
filled with the nearest available number.

---

## 1. The seal: a MESH class reached by a DOCS caller — CONFIRMED, three fires

| fire | `resolved_uri` | confidence | candidates | excluded |
| --- | --- | --- | --- | --- |
| 1 | `http://invincible-agent/mesh#DocPage` | 0.97 | 1, all from the `mesh` graph | 9 |
| 2 | `http://invincible-agent/mesh#DocPage` | 0.97 | 1, all from the `mesh` graph | 9 |
| 3 | `http://invincible-agent/mesh#DocPage` | **0.99** | 1, all from the `mesh` graph | 9 |

A **MESH-graph URI returned to a caller scoped to `DOCS`** is exactly what the fix exists to permit:
`main.py:1163` records that a read filtered to `domain == "DOCS"` *structurally cannot* return the
archetype and system classes, because they carry `domain == "MESH"` in the index. It now returns one.

**The three fires are three fires, not one read printed three times.** Fire 3's confidence differs
(0.99 against 0.97). That difference is the only evidence I have that repeating the call repeated the
*work*; identical rows across three fires would have been consistent with a cached response, which is
the failure the "three fires" instruction exists to catch.

## 2. MAINTENANCE recall: the MESH append displaced nothing

| fire | `resolved_uri` | confidence | candidates | excluded |
| --- | --- | --- | --- | --- |
| 1–3 (identical) | IOF `…/MaintenanceReferenceOntology/Equipment` | 0.98 | **2** — `Procedure`, `Equipment`, both IOF maintenance classes | 8 |

The worry the dispatch's "recall across MAINTENANCE" encodes is that widening the scan's scope to
include MESH would dilute a 13k-row domain's candidate pool. **Measured: it does not.** No MESH class
appears in the MAINTENANCE pool at all; both surviving candidates are maintenance classes. The three
fires are byte-identical here, which — by the argument just made about fire 3 above — means this row
is weaker evidence than the DOCS row, not stronger.

## 3. Cold starts: 0 of 6, and the negative is worth something only because of a code read

Pre-fix, the recorded reading was **9/9 `COLD START DETECTED`** in engine-o's own stdout for docs
questions (`2026-09-26-docs-walk-…`, row 1). Across these six fires: **zero.**

⛔ **A grep returning 0 with a positive control also returning 0 cannot tell "it did not happen" from
"the marker no longer exists."** Both readings are the absence of a string. What makes the negative
mean anything is the third reading:

| check | result |
| --- | --- |
| does the deployed code still emit the marker? | **Yes** — `main.py:2540`, inside `/resolve`, prints `WEAVIATE COLD START DETECTED` |
| is my pattern able to match that string? | **Yes** — `COLD START DETECTED` is a substring of it |
| is the source I read the code that ran? | **Yes** — `git diff ec055c49..HEAD -- …/main.py` is empty and the file is not dirty |
| did my fires reach the pod I read the log of? | **Yes** — exactly **6** `POST /resolve` in that pod's log |

Only with those four does "0 cold starts" become a measurement instead of a missing string.

---

## 4. ⛔ The delta is NOT COMPUTABLE, and substituting one would have been easy

No before-reading of the candidate pool exists. `2026-09-27-overnight-the-docs-empty-document-…:255`
says so in as many words — *"Item 3's recall delta across MAINTENANCE (three fires before/after) is not
run."* The before had to be taken while the pre-fix code was the deployed code, and it is not any more.

**The subject moved before its baseline was taken.** Recovering it now would mean rolling the fleet
back to roll #5's sha to measure it, which is a large, risky action to obtain a number, and nothing
authorises it. So the delta is not reported.

What *can* be said, on one instrument and labelled as the partial it is:

| | before | after |
| --- | --- | --- |
| cold starts on docs questions, engine-o stdout | **9/9** (earlier revision) | **0/3** |
| candidate pool for a DOCS caller | **no reading exists** | 1 candidate, 9 excluded |
| candidate pool for a MAINTENANCE caller | **no reading exists** | 2 candidates, 8 excluded |

The cold-start row is a legitimate before/after because both halves were read from the *same
instrument* — engine-o's stdout — even though the revisions differ. The two pool rows have no before
at all, and averaging, inferring or reasoning one out of the cold-start row would be a comparison of
two populations by a number neither of them measured.

---

## 5. A finding that is not item 3's: a confidence score over a pool of one

The DOCS path resolved at **0.97–0.99 confidence from a candidate pool of one.** Nine of ten
candidates were removed ahead of the classifier by gate `productive_option`, disposal `removed`.

**A classifier handed one option cannot discriminate, so its confidence is not a measure of anything
it chose.** The number reads as strong agreement and is arithmetically compatible with there having
been no decision to make. This is the shape of "a winner may not be an answer": scoring which class
won hides whether there was a contest. The MAINTENANCE path is barely different — 2 of 10 survive.

Whether `productive_option` *should* remove nine of ten is the gate owner's question, not mine, and I
am not filing it as a defect. What I am recording is that **the confidence figure on this path should
not be cited as evidence of resolution quality** until someone reads what the pool looked like before
the gate.

---

## 6. Instrument defects in this measurement, both mine

- **I matched on a `"domain"` key inside `candidates` and got 0, and nearly wrote that down.**
  Candidates carry `uri`, `label`, `description` and `score` — there is no `domain` field. The zero was
  the matcher, not the data. Domain has to be derived from the URI namespace instead.
- **My namespace splitter assumed a `#` fragment.** MESH URIs have one (`…/mesh#DocPage`); the IOF
  maintenance URIs do not, so for those rows it printed the *class name* as though it were the graph
  name — `by-graph={'Equipment': 1}`. A figure that was meaningless for half the population and
  looked exactly like data for all of it.

## 7. What I did **not** verify

- **That the DOCS pool would have been empty before the fix.** I never fired the pre-fix build; the
  claim that the fix is what put `DocPage` in reach rests on reading `main.py:1150-1169`, not on a
  measurement of the old code.
- **Anything about the other five docs-domain questions.** Two queries, six fires. The seal holds for
  the query I sent, which is not a census of the docs path.
- **What the pool looks like upstream of `productive_option`.** I read what survived the gate, not
  what entered it.
