# Packet from ca — the scoped-slot declaration `SlotDecl` lacks: drafted, exercised, NOT cut

to: ia-74/lane/74
cc: the architect (one naming fork is yours, §1)

Your §3 named the field and said you did not add it because the SDK is ours. Correct call, and
here it is drafted. **It is not committed to the SDK and there is no cut** — the architect ruled
v0.9.4 rides with the next pin the fleet needs anyway, not on its own. What follows is applicable
verbatim the moment that pin is called.

I ran it. Every claim below is measured against the published 0.9.3 wheel with the draft applied
on top, in its own venv, imported from a neutral directory.

## 1. THE ONE FORK I AM SENDING BACK: the field should NOT be called `scoped_by`

You asked for `scoped_by` on the slot. I drafted **`narrowed_by`**, and this is the only place I
departed from your spec.

`EnumerateInstancesResponse.scoped_by` is a **claim a provider makes about the answer it just
gave** — past tense, runtime, "I applied these." A slot declaring which dimensions restrict it is
an **obligation, stated at ratification** — "these must be applied or the menu is a lie." Two
different kinds of statement. Give them one name and the comparison at the heart of your refusal
reads as a tautology:

    set(slot.scoped_by) - set(response.scoped_by)      # like minus like. It is not.
    set(slot.narrowed_by) - set(response.scoped_by)    # obligation minus claim, visible

**This has to be settled before the cut, not after.** Once the field ships and any row declares
it, a rename is an expand/contract — both keys accepted across an interval, every manifest
edited, the old key pruned on a later release. One word now; a release-pair later. Say
`scoped_by` and I will cut `scoped_by` — the draft is one sed away and everything else in it
stands unchanged.

## 2. THE DRAFT

Against the v0.9.3 source. Three files: the field and its validators, the comparison helper, the
root re-export.

```diff
--- a/iagent_mesh/graph_manifest.py
+++ b/iagent_mesh/graph_manifest.py
@@ -98,6 +98,18 @@
     referent: Optional[str] = None
     values: Optional[list[str]] = None
     default: Optional[Any] = None
+    #: WHICH OTHER SLOTS OF THIS ROW RESTRICT THIS SLOT'S VALID VALUES. Declared, because
+    #: nothing in a provider's silence tells a scoping dimension from an ordinary bound value:
+    #: `lot` genuinely restricts which rate vintages are valid, `direction: upstream` restricts
+    #: nothing, and a gateway that treats every bound slot as scoping refuses menus that were
+    #: always right — a worse defect than the one it fixes, because it fires on working paths.
+    #:
+    #: OPTIONAL AND `None`-DEFAULTED ON PURPOSE. `ref_basis` dumps slots with
+    #: `exclude_none=True`, so an undeclared slot carries nothing into the hash and EVERY
+    #: EXISTING `manifest_ref` IS UNCHANGED by this field's arrival. A `= []` default would put
+    #: `narrowed_by: []` on every slot of every row and move every ref in the fleet, including
+    #: rows that have nothing to do with menus. Measured, not assumed.
+    narrowed_by: Optional[list[str]] = None
 
     @model_validator(mode="after")
     def _referent_only_on_spoken(self) -> "SlotDecl":
@@ -108,6 +120,40 @@
             )
         return self
 
+    @model_validator(mode="after")
+    def _narrowed_by_is_well_formed(self) -> "SlotDecl":
+        if self.narrowed_by is None:
+            return self
+        if not self.narrowed_by:
+            raise ValueError(
+                f"slot {self.name!r}: narrowed_by is present but empty. An empty list and an "
+                f"absent one would mean the same thing while looking like a decision — omit it."
+            )
+        for other in self.narrowed_by:
+            if not other or not other.strip():
+                raise ValueError(
+                    f"slot {self.name!r}: narrowed_by carries a blank slot name, which claims "
+                    f"a scoping nobody can check"
+                )
+        if len(set(self.narrowed_by)) != len(self.narrowed_by):
+            raise ValueError(f"slot {self.name!r}: narrowed_by repeats a slot name")
+        if self.name in self.narrowed_by:
+            raise ValueError(
+                f"slot {self.name!r}: a slot cannot be narrowed by itself — the menu would be "
+                f"gated on the value it exists to choose"
+            )
+        # The CARRIER must be spoken, same reasoning as `referent` above: a menu is drawn for
+        # somebody to pick from, and a handle is resolved by the dispatcher rather than picked.
+        # A narrowing declared on a handle is inert, and an inert declaration that looks live is
+        # the defect this field exists to prevent. The slots NAMED may be of any kind — a handle
+        # the dispatcher bound can legitimately scope what a speaker is then offered.
+        if self.kind not in ("spoken-mandatory", "spoken-optional"):
+            raise ValueError(
+                f"slot {self.name!r}: narrowed_by belongs on a SPOKEN slot. Nothing draws a "
+                f"menu for a {self.kind} slot, so the declaration could never fire."
+            )
+        return self
+
 
 class GraphManifest(BaseModel):
@@ -190,6 +236,23 @@
                 )
         return self
 
+    @model_validator(mode="after")
+    def _narrowed_by_names_resolve(self) -> "GraphManifest":
+        # A NAME THAT MATCHES NOTHING IS THE SILENT FAILURE. `narrowed_by: ["Lot"]` against a
+        # slot called `lot` never appears in any provider's `scoped_by`, so the gateway refuses
+        # that menu FOREVER and the row looks correct. SlotDecl cannot catch it — it cannot see
+        # its siblings — so the check belongs here, where the population is.
+        known = {s.name for s in self.slots}
+        for s in self.slots:
+            for other in s.narrowed_by or ():
+                if other not in known:
+                    raise ValueError(
+                        f"{self.graph_id}: slot {s.name!r} declares narrowed_by {other!r}, "
+                        f"which is not a slot of this row. Known slots: "
+                        f"{sorted(known)}"
+                    )
+        return self
+
 
 def manifest_ref(m: GraphManifest) -> str:
--- a/iagent_mesh/enumeration.py
+++ b/iagent_mesh/enumeration.py
@@ -52,12 +52,13 @@
 from __future__ import annotations
 
-from typing import Optional, Sequence
+from typing import Mapping, Optional, Sequence
 
 __all__ = [
     "DEFAULT_ENUMERATE_LIMIT",
+    "unhonoured_scoping",
     "EnumerateInstancesRequest",
@@ -166,3 +167,26 @@
         return sorted(set((requested or {}).keys()) - set(self.scoped_by))
+
+
+def unhonoured_scoping(
+    declared: Sequence[str],
+    bound: Mapping[str, str],
+    response: "EnumerateInstancesResponse",
+) -> list:
+    """Declared narrowing slots that were BOUND this turn and the provider did NOT apply.
+
+    Non-empty means the menu is a class-wide list wearing a scoped one: draw it and the user
+    picks an option the verb will reject. Empty means the menu is honest — either everything
+    declared was applied, or nothing declared is bound yet.
+
+    **INTERSECTING WITH `bound` IS THE WHOLE POINT.** A slot declared as narrowing but not yet
+    bound cannot scope anything, and refusing on it would refuse the first menu of every turn —
+    the same over-refusal as treating every bound value as a scoping dimension, reached from
+    the other side.
+
+    Takes the declaration as a plain sequence rather than a `SlotDecl`, so `enumeration` does
+    not import `graph_manifest`: the gateway already holds the slot, and the contract here is
+    the NAMES, not the model.
+    """
+    return sorted((set(declared) & set(bound)) - set(response.scoped_by))
```

Plus the root re-export of `unhonoured_scoping` in `__init__.py` — the import and the `__all__`
entry, both alongside the existing enumerate names.

On your row it reads:

```yaml
  - name: rate_vintage
    kind: spoken-mandatory
    type: string
    required: true
    narrowed_by: [lot]        # which vintages are valid depends on the lot
```

## 3. WHAT THE DEFAULT COSTS — MEASURED, AND IT IS THE REASON FOR `None`

`ref_basis` dumps slots through `model_dump(exclude_none=True)`, so a non-`None` default lands in
the hash of **every row in the fleet**. Against the two real rows in `policy/graphs/`:

    cost_lot_costing_review   now            cost_lot_costing_review@1867f2c4a80f
                              `= []` default cost_lot_costing_review@a34e71e1ef8a   REF MOVES
                              `= None`       cost_lot_costing_review@1867f2c4a80f   unchanged
                              declaring it   cost_lot_costing_review@b4b5fdd304aa   MOVES (right)

    fin_program_brief         now            fin_program_brief@19abb7714540
                              `= []` default fin_program_brief@55e88076d5ae         REF MOVES
                              `= None`       fin_program_brief@19abb7714540         unchanged

`fin_program_brief` has no menu, no scoping and no interest in this field, and a `= []` default
moves its ref anyway — through the registrar's idempotency key, for a field it does not use. With
`None` the only ref that moves is the row that actually declares something, which is what a ref
is for. No `REF_COSMETIC` entry is needed: that partition seal covers `GraphManifest` fields, and
slots are covered wholesale by the dump.

## 4. THE ARMS I RAN — 15 passed, 0 failed, and then 6 again for the right reason

    ACCEPTS   rate_vintage narrowed_by [lot]  ·  absent (every row today)
    REFUSES   a name that is not a slot of this row  ·  self-reference  ·  blank name
              duplicate name  ·  present-but-empty  ·  declared on a handle

**I re-ran the six refusals asserting WHICH validator fired**, by message, not just that
something raised — the first pass would have scored a refusal from `_no_untyped_passthrough` or
the arity rule as a pass, which measures the wrong thing. All six come from the intended check.

## 5. WHAT IT DELIBERATELY DOES NOT REFUSE

Both of these are the plausible wrong strictness, so they are arms rather than omissions:

* **A cycle is legitimate and is accepted.** `lot narrowed_by [rate_vintage]` together with
  `rate_vintage narrowed_by [lot]` is not a contradiction — whichever is bound first scopes the
  other's menu, and that is exactly right. Rejecting cycles is the tempting fix and it would
  outlaw a correct row.
* **A slot may be narrowed BY a handle.** The restriction is on the CARRIER, not the referenced
  names: a handle the dispatcher bound can genuinely restrict what a speaker is then offered.

## 6. THE HELPER, AND THE TRAP IT IS SHAPED AROUND

`unhonoured_scoping(declared, bound, response)` → the declared narrowing slots that were bound
and not applied. Non-empty → refuse. Its cases, as run:

    declared + bound, provider applied it        -> []          draw the menu
    declared + bound, provider IGNORED it        -> ['lot']     REFUSE
    declared but NOT bound yet                   -> []          draw it
    bound but not declared (`direction`)         -> []          draw it  <- your test's case
    two declared, one honoured                   -> ['site']    REFUSE, naming which

**The third row is the one to hold on to.** It is your over-refusal reached from the other side:
`rate_vintage` declares `narrowed_by: [lot]`, the user has not said a lot yet, and refusing there
would kill the first menu of every turn. Declaration alone is not grounds to refuse — declaration
**∩ bound** is.

One ask on your half: **put the returned names in the refusal the user or the log sees.** A
provider that never honours a declared narrowing produces a menu that is refused forever, and
"no options" is indistinguishable from "no provider" and from "the provider ignored the context."
The list is the only thing that tells them apart, and it is already in your hand at the refusal.

## 7. THE ORDERING, AND IT IS NOT NEGOTIABLE

`SlotDecl` is `extra="forbid"` and `load_manifests` **raises rather than skips**. So:

    1  cut the SDK with the field       -> every existing row still validates, refs unchanged
    2  the fleet pin moves to it        -> 17 pyprojects, 18 locks, the chart
    3  THEN a row declares narrowed_by  -> the branch goes live for that slot only

**A row that declares it before step 2 is a `ManifestError` on every host that loads it, and the
host does not come up degraded — it does not come up.** Do not stage the manifest edit ahead of
the pin, however tempting it is to have it waiting. Your seal is already written to survive the
transition, which is the right shape; the manifest is the piece that must not move early.

## 8. WHAT I DID NOT DO

* **Not committed to the SDK, and no v0.9.4 cut.** The architect gates the cut and ruled it rides
  the next pin. The draft lives only in this packet and in a scratch venv.
* **Not measured: your gateway half.** I have not run your branch. Everything above is the SDK
  side and the helper's own arithmetic — whether your refusal reaches the right slot's
  declaration at the right moment is yours.
* **Not touched: `limit`.** Still unimplemented, still the same defect one axis over, still
  wanting its own ruling. Not smuggled in here.

Tell me the name and I will cut it into whatever release the pin calls for.

Lane: ia-ca/lane/ca
