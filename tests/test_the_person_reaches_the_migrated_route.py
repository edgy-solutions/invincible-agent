"""The person's identity survives every hop from the JWT claim to the migrated route's mint.

**WHY THIS FILE IS SOURCE-LEVEL AND NOT BEHAVIOURAL.** The migrated class-pool route mints
``Initiator(subject=user_email, kind="person")`` and refuses a blank subject with a 400 (sealed
behaviourally in ``tests/test_the_migrated_route_returns_the_same_rows.py``). Whether that mint
gets a real person depends on a chain of ten hops -- eight to the migrated route, two onto the
sibling engine-A dispatch -- and **every hop's parameter defaults to
``""``** -- so dropping the keyword at any one of them is not a TypeError, not a log line, and not
a test failure anywhere: it is a silently anonymous read. With the migration flag off that read is
served unattributed; with it on it becomes a 400 whose cause is many frames away from where the
keyword went missing.

That is a defect class no behavioural arm sees, because no behavioural arm in this repo drives the
gateway, Dagster and engine-o in one process. What CAN be checked is that each hop still hands the
value on, and that is what this file checks: the chain is walked in the AST, each hop is resolved
by NAME (a rename reds rather than quietly dropping a hop from the population), and the value each
hop passes is compared against the expression it is supposed to pass -- so forwarding a constant,
or re-defaulting to ``""`` midway, is as red as omitting the keyword.

**NOT CLAIMED HERE:** that the value is a real person. ``current_user.authz_id`` is whatever the
deployment's ``USER_ENTITLEMENT_CLAIM`` resolves to, and it is ``""`` when absent (deliberately,
so Topaz denies). This file seals the PLUMBING -- that whatever identity the edge established
arrives at the mint -- and nothing about the edge itself.

Run: uv run --frozen pytest tests/test_the_person_reaches_the_migrated_route.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# No sys.path surgery: this file imports no application module -- it reads source and parses it.
# The repo root is already importable because ``tests`` is a package and pytest prepends its
# parent, and an insert here would be pollution with no purpose, in a suite that has already paid
# for one of those (see the order-independence note in pyproject.toml's dev group).
_REPO = Path(__file__).resolve().parents[1]

GATEWAY = "src/iagent/gateway.py"
SUPERVISOR = "src/iagent/defs/dynamic_supervisor.py"
ENGINE_O = "agent_fleet/ontology_service/main.py"

#: The name every hop carries the identity under. Named once: the comment at the gateway hop says
#: this parameter CARRIES an authz_id and that the rename is an honesty follow-up, so the day that
#: follow-up lands, this constant is the single place this file changes.
FIELD = "user_email"

#: The chain, hop by hop: (label, file, enclosing function, what it hands to, accepted values).
#: A hop whose function or whose call cannot be found is a RED, not a skip -- a chain that silently
#: loses a link is the exact failure this file is here to catch, and a hop that vanishes from the
#: population takes its own assertion with it.
HOPS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("1 · the edge reads the claim",
     GATEWAY, "orchestrate", "generate_dagster_stream", ("current_user.authz_id",)),
    ("2 · into the stream generator",
     GATEWAY, "generate_dagster_stream", "_generate_dagster_stream_inner", (FIELD,)),
    ("3 · into the job launcher",
     GATEWAY, "_generate_dagster_stream_inner", "_launch_supervisor_job", (FIELD,)),
    ("4 · into the Dagster run config",
     GATEWAY, "_launch_supervisor_job", "<dict>", (FIELD,)),
    ("5 · out of the op's config",
     SUPERVISOR, "execute_subtask", "_classify_route", ("config." + FIELD,)),
    ("6 · into subject resolution",
     SUPERVISOR, "_classify_route", "_resolve_subject", (FIELD,)),
    ("7 · onto the wire to engine-o",
     SUPERVISOR, "_resolve_subject", "<dict>", (FIELD,)),
    ("8 · into the Initiator the migrated route mints",
     ENGINE_O, "_class_pool_via_mesh_sync", "Initiator", (FIELD,)),
    # The sibling chain, found by the census arm below rather than by reading: the same identity
    # also travels on the engine-A dispatch (ADR-0025 hop 2), on BOTH the fallback and specialist
    # branches. It is in the population because it is the same value serving the same purpose --
    # and because the comment at the specialist site is a FILED INSTANCE of this file's defect
    # class: the email was added to the fallback dispatch only, and the specialist dispatch went
    # out empty until a flag-on seal caught one caller threaded and another not. A defence belongs
    # to the class, not to the branch that bit someone.
    ("9 · onto the engine-A dispatch, generalist fallback branch",
     SUPERVISOR, "_call_engine_a_fallback", "<dict>", ("config." + FIELD,)),
    ("10 · onto the engine-A dispatch, specialist branch (the twin that was once empty)",
     SUPERVISOR, "execute_subtask", "<dict>", ("config." + FIELD,)),
    # Hops 11-12: the SECOND migrated route, the predicate search, behind the same flag as the class
    # pool. The identity now has a second destination, and it leaves from a function this chain
    # ALREADY visits -- which is how the next dropped hop gets missed rather than caught: hop 6
    # proves ``_classify_route`` hands the identity to ``_resolve_subject``, and hop 6 stays green
    # whether or not the classify payload carries it. Hop 11 covers the payload, and because
    # ``_classify_route`` posts to TWO endpoints, the arm below says WHICH payload -- a hop matched
    # on the wrong dict literal in the right function is this file's own neighbour defect.
    ("11 · onto the wire to /classify_predicate, the second migrated route",
     SUPERVISOR, "_classify_route", "<dict>", (FIELD,)),
    ("12 · into the Initiator the second migrated route mints",
     ENGINE_O, "_predicate_pool_via_mesh_sync", "Initiator", (FIELD,)),
    # Hop 13: the THIRD migrated route, /find_compatible_verbs behind COMPATIBLE_VERBS_VIA_MESH.
    # It also leaves from ``_classify_route`` (three call sites, all matched here). Past this hop
    # the identity travels as ``on_behalf_of``, which this file's matcher does not read: those
    # hops -- the supervisor's wrapper, ``verb_lookup``'s payload, the BFF's direct path -- are
    # sealed by name in tests/routing/test_find_compatible_verbs_via_mesh_graph.py
    # (``_THREADED``). The chain's END is sealed here, by the mint arm below. MEASURED: this hop's
    # arm passes while ANY of the three sites forwards the value, so one site dropping the keyword
    # is quiet here and red there (``test_THE_PERSON_IS_HANDED_DOWN_AT_EVERY_CALL_IN_src``).
    ("13 · into the compatible-verbs lookup, the third migrated route",
     SUPERVISOR, "_classify_route", "_find_compatible_verbs", (FIELD,)),
]

#: Sites that READ the identity without naming it under :data:`FIELD` -- ``getattr`` with a
#: default. Sealed by name, because ``getattr(config, "user_email", "")`` is strictly worse than
#: every hop above: those go red on a rename, this one returns ``""`` and the act proceeds
#: anonymously. Keyed on (file, function) so a new one is a red that names its site.
GETATTR_READERS: set[tuple[str, str]] = {(SUPERVISOR, "_redeem_caller_token")}

_TREES: dict[str, ast.Module] = {}


def _tree(rel: str) -> ast.Module:
    if rel not in _TREES:
        _TREES[rel] = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
    return _TREES[rel]


def _function(rel: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(_tree(rel)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(
        f"{rel} has no function {name!r} -- the chain lost a hop to a rename. Fix the hop's name "
        f"in HOPS after checking the identity still reaches the next hop; do not delete the hop."
    )


def _passed_values(fn: ast.AST, callee: str) -> list[tuple[int, str]]:
    """Every value handed to ``callee`` under the identity's name, inside ``fn``.

    ``callee == "<dict>"`` covers the two hops that cross a boundary as data rather than as a call
    -- the Dagster run config and the HTTP payload. A dict key and a keyword argument are the same
    act here, and treating only one of them as a hop would leave four of the ten unsealed.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if callee == "<dict>":
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == FIELD:
                        found.append((node.lineno, ast.unparse(value)))
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                # payload["user_email"] = user_email -- an assignment into a dict built earlier
                if node.slice.value == FIELD and isinstance(node.ctx, ast.Store):
                    parent_assign = getattr(node, "_assigned_value", None)
                    if parent_assign is not None:
                        found.append((node.lineno, parent_assign))
            continue
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == callee:
            for keyword in node.keywords:
                if keyword.arg == FIELD:
                    found.append((node.lineno, ast.unparse(keyword.value)))
            # hop 8 mints a positional model: Initiator(subject=..., kind="person")
            for keyword in node.keywords:
                if keyword.arg == "subject":
                    found.append((node.lineno, ast.unparse(keyword.value)))
    return found


def _annotate_subscript_assignments(tree: ast.Module) -> None:
    """Attach the assigned value to ``d["k"] = v`` targets so a dict FILLED after construction is
    visible as a hop. Without this, hop 7 -- the payload that actually crosses to engine-o -- is
    invisible, because it is written as an assignment rather than a literal.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    target._assigned_value = ast.unparse(node.value)  # type: ignore[attr-defined]


for _rel in (GATEWAY, SUPERVISOR, ENGINE_O):
    _annotate_subscript_assignments(_tree(_rel))


# -- the population is real --------------------------------------------------------------------


def test_the_CHAIN_is_not_empty_and_every_hop_names_a_file_that_exists() -> None:
    """Without this, a HOPS list emptied by a bad edit would make every arm below vacuous."""
    assert len(HOPS) >= 10, f"the chain has shrunk to {len(HOPS)} hops -- was ten when measured"
    for label, rel, *_ in HOPS:
        assert (_REPO / rel).exists(), f"hop {label!r} names a file that is gone: {rel}"


# -- each hop hands the identity on, and hands on the right thing -------------------------------


@pytest.mark.parametrize("hop", HOPS, ids=[h[0] for h in HOPS])
def test_the_hop_PASSES_the_identity_onward(hop: tuple[str, str, str, str, tuple[str, ...]]) -> None:
    label, rel, caller, callee, accepted = hop
    fn = _function(rel, caller)
    passed = _passed_values(fn, callee)
    assert passed, (
        f"hop {label!r}: {rel}::{caller} no longer hands {FIELD!r} to {callee} at all.\n"
        f"Every parameter in this chain defaults to '' , so this omission raises nothing, logs "
        f"nothing, and turns the migrated route's read into an anonymous one (or a 400 with the "
        f"flag on). If the identity now travels another way, update this hop -- do not delete it."
    )
    bad = [(line, value) for line, value in passed if value not in accepted]
    assert not bad, (
        f"hop {label!r}: {rel}::{caller} hands {callee} a value that is not the caller's own "
        f"identity: {bad!r} (accepted: {accepted!r}). Forwarding a constant or a re-default is the "
        f"same defect as omitting the keyword, and it is harder to see."
    )


@pytest.mark.parametrize("hop", HOPS, ids=[h[0] for h in HOPS])
def test_no_hop_LAUNDERS_the_identity_into_a_literal(
    hop: tuple[str, str, str, str, tuple[str, ...]]
) -> None:
    """The arm above compares against an allowlist of expressions, which would also pass if the
    allowlist itself were widened to a literal. This one is independent of it: whatever a hop
    passes, it must not be a constant. Deny-by-default for the plumbing.
    """
    label, rel, caller, callee, _ = hop
    for line, value in _passed_values(_function(rel, caller), callee):
        assert not (value.startswith(("'", '"')) or value in {"None", "''", '""'}), (
            f"hop {label!r} passes the literal {value} at {rel}:{line} -- an identity that does "
            f"not come from the caller is not the caller's identity"
        )


# -- the mechanism that makes the arms above necessary -----------------------------------------


@pytest.mark.parametrize(
    "hop", [h for h in HOPS if h[4] == (FIELD,)], ids=[h[0] for h in HOPS if h[4] == (FIELD,)]
)
def test_the_hop_can_OMIT_the_identity_silently_which_is_why_this_file_exists(
    hop: tuple[str, str, str, str, tuple[str, ...]]
) -> None:
    """Every hop that forwards its OWN ``user_email`` parameter must have one, and that parameter's
    default is what makes omission silent.

    THIS ARM GOING RED IS GOOD NEWS in one specific way: if a hop's parameter becomes required (no
    default), omission at that hop becomes a TypeError, the runtime catches it, and the
    source-level arms above are no longer the only detector for that hop. Read the diff before
    relaxing anything -- the other direction, a default appearing where there was none, is the
    defect.
    """
    label, rel, caller, _, _ = hop
    fn = _function(rel, caller)
    args = fn.args
    params = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    names = [a.arg for a in params]
    assert FIELD in names, (
        f"hop {label!r}: {rel}::{caller} forwards {FIELD!r} but does not take it -- it is "
        f"reading the value from somewhere this file does not know about"
    )
    defaults = dict(zip([a.arg for a in args.kwonlyargs], args.kw_defaults))
    positional = list(args.posonlyargs) + list(args.args)
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        defaults[arg.arg] = default
    default = defaults.get(FIELD)
    assert default is not None and isinstance(default, ast.Constant) and default.value == "", (
        f"hop {label!r}: {rel}::{caller} no longer defaults {FIELD!r} to the empty string "
        f"(found {ast.unparse(default) if default is not None else 'no default'}). If it is now "
        f"REQUIRED, omission at this hop is caught at runtime -- say so here and keep the arms."
    )


# -- the census: no forwarding path outside the sealed chain ------------------------------------


#: The orchestrator tree. The census below walks THIS, not a list of filenames.
#:
#: It was two named files when first written, and a mutant proved that a hole: a second forwarding
#: path added in a NEW module under ``src/iagent/`` left the seal fully green, because the census's
#: population was two strings somebody had typed. An allowlist's population is every name that
#: could be ADDED, so the population is now derived by walking the tree -- and it costs nothing:
#: the whole orchestrator side holds exactly the nine sites sealed here.
ORCHESTRATOR_TREE = "src/iagent"


def _orchestrator_modules() -> list[str]:
    root = _REPO / ORCHESTRATOR_TREE
    mods = sorted(
        p.relative_to(_REPO).as_posix()
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    assert mods, f"{ORCHESTRATOR_TREE} has no modules -- the census would be vacuous"
    return mods


def _all_identity_sites(rel: str) -> set[tuple[str, str, str]]:
    """Every place in a file that hands the identity on, as (file, enclosing function, callee)."""
    enclosing: dict[int, str] = {}
    tree = _tree(rel)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                enclosing.setdefault(id(node), fn.name)
    sites: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == FIELD:
                    sites.add((rel, enclosing.get(id(node), "<module>"),
                               ast.unparse(node.func).split(".")[-1]))
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == FIELD:
                    sites.add((rel, enclosing.get(id(node), "<module>"), "<dict>"))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            # The census must reach as far as the hop matcher does. It did NOT when first written:
            # it saw dict LITERALS only, so hop 7 -- the payload that actually crosses to engine-o,
            # written as payload["user_email"] = ... -- was invisible to the census while the hop
            # arm found it. The bidirectional assert below is what surfaced that, and it stays
            # bidirectional for exactly this reason: a census narrower than its subject reports a
            # clean population it never looked at.
            if isinstance(node.slice, ast.Constant) and node.slice.value == FIELD:
                sites.add((rel, enclosing.get(id(node), "<module>"), "<dict>"))
    return sites


def _getattr_readers(rel: str) -> set[str]:
    """Functions that pull the identity off an object by NAME-AS-STRING rather than as an attribute.

    This is a second matcher and not a widening of the first, because it answers a different
    question: the first asks who hands the identity ON, this asks who can read it and get ``""``
    instead. ``getattr(config, "user_email", "")`` survives the field being renamed, deleted, or
    never set, and the caller cannot tell any of those from a genuinely anonymous request.
    """
    enclosing: dict[int, str] = {}
    tree = _tree(rel)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                enclosing.setdefault(id(node), fn.name)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == FIELD
        ):
            found.add(enclosing.get(id(node), "<module>"))
    return found


def test_the_identity_is_read_by_NAME_AS_STRING_only_where_this_file_says_so() -> None:
    """A ``getattr`` read is the one shape that defeats every other arm here.

    The hop arms go red when a hop stops passing the identity or passes the wrong thing, and they
    go red on a rename because they resolve names. A ``getattr`` with a default goes red on
    nothing: rename the field and it silently yields ``""``, which downstream is indistinguishable
    from an unauthenticated caller -- and on the engine-A path an empty caller email is fail-CLOSED
    denied at Topaz, so the symptom is a denial with no trace of the identity that was lost.

    The one sealed reader claims a launcher for a caller token. It is listed, not forbidden,
    because deciding it is not this file's job -- being UNLISTED is.
    """
    found = {(rel, fn) for rel in _orchestrator_modules() for fn in _getattr_readers(rel)}
    assert found == GETATTR_READERS, (
        f"getattr readers of {FIELD!r} changed.\n  new (unsealed): {sorted(found - GETATTR_READERS)}"
        f"\n  gone (seal is stale): {sorted(GETATTR_READERS - found)}\n"
        "A new one needs a decision: either read the attribute directly so a rename is loud, or "
        "list it here with why a silent empty identity is acceptable at that site."
    )


def test_the_ORCHESTRATION_SIDE_forwards_the_identity_only_along_the_sealed_chain() -> None:
    """A SECOND path to the migrated route is the way this seal goes stale while staying green: the
    sealed hops keep passing the identity, and a new caller reaches ``/resolve`` without one. The
    population therefore comes from the files rather than from HOPS, and a site this file has not
    sealed is a red that names it.
    """
    sealed = {(rel, caller, callee) for _, rel, caller, callee, _ in HOPS if rel != ENGINE_O}
    found: set[tuple[str, str, str]] = set()
    for rel in _orchestrator_modules():
        found |= _all_identity_sites(rel)
    unsealed = found - sealed
    assert not unsealed, (
        "the gateway or supervisor forwards the caller's identity somewhere this file does not "
        f"seal: {sorted(unsealed)}.\nEach one is either a new hop (add it to HOPS) or a second "
        "route to a mint (which needs its own chain). Both are decisions; neither is a default."
    )
    assert sealed <= found, (
        f"a sealed hop no longer forwards the identity at all: {sorted(sealed - found)}"
    )


def test_HOP_11_lands_in_the_POST_PAYLOAD_and_not_in_one_of_the_seven_other_dicts() -> None:
    """WHICH dict literal hop 11 matched, asserted separately from the fact that one did.

    The hop matcher accepts any dict in the enclosing function carrying the identity's key. The
    reason that is too wide here is MEASURED, and it is not the reason first written down: the guess
    was that ``_classify_route`` posts to two endpoints, and it does not -- ``/resolve`` and
    ``/find_compatible_verbs`` are posted from helpers, so there is exactly one payload. What the
    function does hold is EIGHT dict literals, six of them the 12-to-17-key diagnostic dicts it
    RETURNS to its caller.

    Those returned dicts are the live hazard, because they are where an identity would plausibly be
    added for a reason that is not threading: one ``"user_email": user_email`` entry in a telemetry
    dict turns hop 11 green, leaves hops 5, 6 and the unsealed-sites census green, and sends the
    classify payload out anonymous -- a 400 from engine-o with the flag on, an unattributed mesh read
    with it off. So the population is the dicts, and the assertion is which one.
    """
    fn = _function(SUPERVISOR, "_classify_route")

    posts: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "post"):
            continue
        url = ast.unparse(node.args[0]) if node.args else "<no url>"
        payload = next((kw.value for kw in node.keywords if kw.arg == "json"), None)
        posts[url] = {
            k.value for k in (payload.keys if isinstance(payload, ast.Dict) else [])
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }

    classify = [u for u in posts if "/classify_predicate" in u]
    assert len(classify) == 1, (
        f"expected exactly one POST to /classify_predicate in _classify_route, found {classify} "
        f"among {sorted(posts)}"
    )
    assert FIELD in posts[classify[0]], (
        f"the /classify_predicate payload does not carry {FIELD!r}; its keys are "
        f"{sorted(posts[classify[0]])}. Engine-o's predicate search is behind "
        "ONTOLOGY_CLASS_POOL_VIA_MESH and refuses a blank subject, so this omission is a 400 with "
        "the flag on and an unattributed read with it off -- and hop 11 cannot tell you which of "
        "this function's dicts it matched."
    )

    # THE ANCHOR: the arm only discriminates while there is something to discriminate FROM. If the
    # payload becomes the function's only dict, hop 11 is already exact and this arm is a second
    # green saying the same thing -- which is worth knowing rather than carrying.
    others = [
        d.lineno for d in ast.walk(fn)
        if isinstance(d, ast.Dict) and d.keys and d is not None
    ]
    assert len(others) >= 2, (
        f"_classify_route now holds {len(others)} non-empty dict literals. Hop 11 matches any of "
        "them, so with only the payload left this arm adds nothing over hop 11; delete it rather "
        "than keeping a green that cannot fail."
    )


#: Every function in engine-o that mints an Initiator. MEASURED, not assumed, and widened by the
#: arm at the bottom of this file refusing to pass until the new mint is named here -- which is how
#: the second entry arrived: the predicate search's mint reddened that census on the commit that
#: introduced it, at main.py:1778, before any of this file's ten hops noticed a thing.
#:
#: This set is also the population of the mint arm just below, so naming a route here buys it both
#: the subject assertion and the kind assertion rather than only the one the hop table covers.
#:
#: Keyed route -> the PARAMETER that carries the identity into it. The third entry arrived the
#: same way as the second, but only after it shipped: lane/74's 6b17ab11 added the mint and was
#: pushed without this file in its consequence set, so the census was red on a pushed sha. Its
#: parameter is ``on_behalf_of`` because the gateway names the person that way on the wire, and
#: the mint takes a stripped copy of it -- which is why the arm below accepts a local derived
#: from the parameter alone, and nothing else.
EXPECTED_MINTS: dict[str, str] = {
    "_class_pool_via_mesh_sync": FIELD,
    "_predicate_pool_via_mesh_sync": FIELD,
    "_compat_rows_via_mesh_sync": "on_behalf_of",
}

#: Mints OUTSIDE the chain, each one admitted only because it declares ``kind="service"`` as a
#: literal, so the SDK's ``require_person`` refuses every read made with it. Arrived with master's
#: universal-referent leg (``_POOL_READ_INITIATOR``, module level, a Jena CONSTRUCT whose route
#: carries no caller identity -- its comment says so and calls the refusal the designed branch).
#: Lane 1's 09-29 merge census named this mint as red (c). It is not a hop: no identity reaches
#: it. An entry here is a refused read, never an anonymous one; the arm below checks the kind.
REFUSED_MINTS: dict[str, str] = {"<module>": "_POOL_READ_INITIATOR"}


# -- the terminal: what the identity is FOR ----------------------------------------------------


@pytest.mark.parametrize("route", sorted(EXPECTED_MINTS))
def test_the_MINT_declares_a_person_and_takes_its_subject_from_the_chain(route: str) -> None:
    """Hops 8 and 12 are the only hops whose failure is loud, because both migrated routes refuse a
    blank subject with a 400 (sealed behaviourally in the two parity files). What is sealed HERE is
    that the subject is the threaded value rather than a constant, and that the kind is declared --
    never sniffed from the subject's spelling, which is the rule ``Initiator`` exists to carry.

    PARAMETRIZED OVER THE MINT CENSUS rather than named at one route, and that is a repair of this
    arm rather than an extension of it: written for the class pool, it hard-coded that route's name,
    so the second route's mint would have been checked for its SUBJECT by hop 12 and not at all for
    its KIND. The declared kind is the whole of what distinguishes a person's read from a service's,
    and a defence of it belongs to every mint rather than to the one that existed when it was
    written. Widening ``EXPECTED_MINTS`` now costs whoever adds a third route both assertions.
    """
    fn = _function(ENGINE_O, route)
    mints = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "Initiator"
    ]
    assert len(mints) == 1, f"expected exactly one Initiator mint in {route}, got {len(mints)}"
    param = EXPECTED_MINTS[route]
    params = [a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]
    assert param in params, f"{route} no longer takes {param!r} -- the chain has no way in"
    kwargs = {kw.arg: ast.unparse(kw.value) for kw in mints[0].keywords}
    subject = kwargs.get("subject")
    if subject != param:
        # A LOCAL DERIVED FROM THE PARAMETER ALONE, assigned once: `person = (p or "").strip()`.
        # Any other name it reads -- a constant table, a second argument, an env var -- would make
        # the subject something the chain did not thread.
        assigns = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == subject for t in n.targets)
        ]
        read = {n.id for a in assigns for n in ast.walk(a.value) if isinstance(n, ast.Name)}
        assert len(assigns) == 1 and read == {param}, (
            f"{route} mints its Initiator with subject={subject!r} rather than the threaded "
            f"{param!r} or a local derived from it alone (assignments: "
            f"{[ast.unparse(a) for a in assigns]}) -- the chain sealed above then ends in nothing"
        )
    assert kwargs.get("kind") == "'person'", (
        f"the mint declares kind={kwargs.get('kind')!r}. A read on behalf of a person must say so "
        "at the mint; anything else here is either a service read wearing a person's subject or a "
        "kind inferred from that subject, and inference is the rule this field replaces."
    )


def test_the_ENGINE_mints_an_Initiator_only_where_this_file_seals_the_chain() -> None:
    """The chain's value is the mint at its end, so a mint the chain does not reach is the defect
    this file cannot otherwise see.

    A new mesh-backed route that constructs its own ``Initiator`` from something other than the
    threaded identity would leave all ten hops green and still read the store anonymously. That
    makes this the arm that must go red when a route is added, which is the point: the population
    comes from the engine's own source, so the new route names itself here.
    """
    minters: dict[str, list[int]] = {}
    tree = _tree(ENGINE_O)
    enclosing: dict[int, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                enclosing.setdefault(id(node), fn.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "Initiator":
            minters.setdefault(enclosing.get(id(node), "<module>"), []).append(node.lineno)
    assert set(minters) == set(EXPECTED_MINTS) | set(REFUSED_MINTS), (
        f"the set of Initiator mints in {ENGINE_O} changed: { {k: v for k, v in minters.items()} }\n"
        f"  expected exactly: {sorted(set(EXPECTED_MINTS) | set(REFUSED_MINTS))}\n"
        "A new mint is a new identity boundary. Add its chain to HOPS and name it here; do not "
        "widen this set on its own, because a mint nothing threads is an anonymous read that every "
        "other arm in this file reports as healthy."
    )


@pytest.mark.parametrize("where", sorted(REFUSED_MINTS))
def test_a_mint_OUTSIDE_the_chain_is_a_SERVICE_and_so_is_refused_every_time(where: str) -> None:
    """The partition's other half. A mint no chain reaches is admitted by the arm above ONLY as a
    refused read: its ``kind`` must be the literal ``"service"``, assigned to the name recorded
    here. Flip it to ``"person"`` and the read is attributed to a subject nobody threaded, which is
    the anonymous read this file exists to catch -- so that flip reds here, by name."""
    name = REFUSED_MINTS[where]
    tree = _tree(ENGINE_O)
    found = [
        n.value for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        and isinstance(n.value, ast.Call) and ast.unparse(n.value.func).split(".")[-1] == "Initiator"
    ] if where == "<module>" else []
    assert len(found) == 1, f"expected one module-level `{name} = Initiator(...)`, found {len(found)}"
    kinds = [k.value for k in found[0].keywords if k.arg == "kind"]
    assert len(kinds) == 1 and isinstance(kinds[0], ast.Constant) and kinds[0].value == "service", (
        f"{name} is minted outside the chain with kind={[ast.unparse(k) for k in kinds]}: only a "
        "literal 'service' makes an unthreaded mint a refused read rather than an anonymous one"
    )
