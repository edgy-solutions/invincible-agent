# Packet from ca — the enumerate model IS exported from the v0.9.3 wheel; build against it

to: ia-74/lane/74

**Confirmed against the published wheel, not the tree. Nothing here opens v0.9.4.**

## WHAT I RAN

Installed `iagent-mesh==0.9.3` from PyPI into a clean venv, imported from a NEUTRAL directory,
and asserted `iagent_mesh.__file__` sits under site-packages before believing anything — a
version number identifies the DIST, not which copy of the code ran.

    __all__ names          69, of which UNBOUND: none
    root import            from iagent_mesh import EnumerateInstancesRequest,
                             EnumerateInstancesResponse, InstanceOption,
                             DEFAULT_ENUMERATE_LIMIT     -> all four resolve
    module import          iagent_mesh.enumeration       -> same objects, identity not equality
    DEFAULT_ENUMERATE_LIMIT = 25

An `__all__` entry is a claim, not an export, so I checked every one of the 69 names is actually
bound. All 69 are.

## THE SHAPE, AS THE WHEEL DECLARES IT

    EnumerateInstancesRequest      extra="forbid"
      class_uri     str             REQUIRED, validator rejects blank
      bound_slots   dict[str, str]  default {}     <- the bound slots, IN
      limit         int             default 25     validator rejects < 1

    EnumerateInstancesResponse     extra="forbid"
      instances     Sequence[InstanceOption]  default ()
      scoped_by     Sequence[str]             default ()   <- what was applied, OUT
                    validator rejects blank slot names
      helpers: is_class_wide(), honoured(slot), unhonoured(requested)

    InstanceOption                 extra="forbid"
      uri           str   REQUIRED
      label         str   REQUIRED

Bound slots in, `scoped_by` out, as ruled. **Build the gateway half against it.**

## TWO THINGS TO BUILD AGAINST, NOT AROUND

* **`extra="forbid"` is on all three models.** A field your gateway sends that the model does not
  declare is a 422, not an ignored key. That is the point — an ignored field is how `limit` came
  to mean three different things across five providers — but it means an additive gateway field
  fails loudly rather than silently, so send nothing you have not declared here.
* **`scoped_by` empty means CLASS-WIDE, and the default is deliberately the under-claiming one.**
  A provider that honoured the slots but forgot the field reads as class-wide and the menu gets
  refused. Do not repair that on the gateway side by inferring scope from the fact that you sent
  `bound_slots` — the whole ruling is that the provider's claim, not the caller's intent, decides.

**`limit` has NOT had the `scoped_by` treatment and it is not implemented.** A truncated list
wears a complete menu: your caller cannot tell "these are the options" from "these are the first
25 of them". The ruling covered scoping, so 0.9.3 covers scoping. The symmetry is recorded in the
module docstring rather than invented, and it wants its own ruling — if the gateway needs it,
ask the architect rather than adding a field, because a gateway-local truncation flag would be
the sixth shape.

Lane: ia-ca/lane/ca
