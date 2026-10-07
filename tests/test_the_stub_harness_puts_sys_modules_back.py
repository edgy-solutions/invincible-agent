"""A DOUBLE IS INSTALLED, NOT NEGOTIATED -- AND IT DOES NOT OUTLIVE ITS MODULE.

`sys.modules` is process-global, so a test file that replaces an entry is editing every file that
runs after it. Two failures come out of that, and they are not the same failure:

  LEAKING   a double left behind makes a LATER file fail in its own name. `tests/routing` and
            `tests/planning` each passed alone and failed together, eleven tests deep, in a suite
            that mentions neither stubbing nor baml.
  DEFERRING a double installed only `if name not in sys.modules` installs NOTHING when anything
            got there first -- another file's stub OR a perfectly legitimate real import -- and
            the file's own assertions then run against an object it did not build.

MEASURED 2026-09-27 on master: the two order-dependent reds in the routing suite are the second
kind, not the first. `test_adr0019_engine_o_contract_a` is 2/2 green alone and 2/2 red in the
suite, failing with `'TypeBuilder' object has no attribute 'values'` -- its recorder handed the
REAL `baml_client.type_builder.TypeBuilder`, because
`test_an_out_of_domain_hit_is_a_candidate_not_an_authority` loads engine-o's `main.py` at module
level and that import is file-backed, legitimate, and first.

SO THE RULE THIS HARNESS EXISTS TO MAKE CHEAP, and it is the rule the adr0019 file had already
half-written for `weaviate` ("always overwrite ... other test modules install MagicMocks that
confuse the imports") without generalizing it:

  a double the test ASSERTS ON is installed unconditionally  -- it is a recorder, and yielding to
                                                                whatever ran first makes the
                                                                assertion measure a stranger
  a double that only satisfies an IMPORT may defer            -- it is an absence shim, and the
                                                                real module is strictly better

Run: uv run --frozen pytest tests/test_the_stub_harness_puts_sys_modules_back.py -v
"""
from __future__ import annotations

import ast
import importlib.machinery
import pathlib
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

from tests.conftest import (
    _is_a_test_built_double,
    restore_doubles_installed_since,
    snapshot_modules,
    stub_modules,
)

_NAME = "a_dependency_no_one_has_that_this_seal_invented"
_OTHER = "another_dependency_this_seal_invented"


@pytest.fixture(autouse=True)
def _this_seal_does_not_leak_into_its_own_next_arm():
    """⛔ A SEAL ABOUT CROSS-FILE LEAKAGE MUST NOT LEAK BETWEEN ITS OWN ARMS, and it did.

    Found while mutating the `try/finally` out of `stub_modules`: ONE arm went red for the right
    reason and THREE more went red in their own names, because the mutant left `_NAME` in
    `sys.modules` and the later arms take its absence as a premise. That is precisely the defect
    this file exists to close, reproduced inside the file, and it made a correct kill read as four.

    So the invented names are removed around every arm. The arms that assert absence still assert
    it -- the point is that a real failure now names one arm instead of four.
    """
    invented = (_NAME, _OTHER, f"{_NAME}.child")
    for name in invented:
        sys.modules.pop(name, None)
    yield
    for name in invented:
        sys.modules.pop(name, None)


# ── the predicate, with its controls on both sides ──────────────────────────────────────────
def test_A_REAL_MODULE_IS_NOT_MISTAKEN_FOR_A_DOUBLE():
    """⚠ THIS IS THE HALF THAT PREVENTS A WORSE DEFECT THAN THE ONE BEING FIXED. If the predicate
    called a real module a double, the teardown would pop it, the next file would re-import it,
    and there would be two module objects of one name -- at which point an `except SomeError`
    raised through one cannot catch the other's class. `sys` and the frozen modules are in here
    on purpose: they have NO `__file__` and would be misread by a `__file__`-only test."""
    for real in (sys, pytest, types):
        assert _is_a_test_built_double(real) is False, f"{real.__name__} read as a test double"
    import json  # file-backed, ordinary
    assert _is_a_test_built_double(json) is False


def test_A_REAL_MODULE_SERVED_BY_A_NON_MODULE_CLASS_IS_STILL_REAL():
    """⛔ THE REGRESSION CONTROL FOR THE FALSE POSITIVE THE CENSUS BELOW ACTUALLY FOUND, and the
    reason the predicate reads `__spec__` rather than asking `isinstance(obj, ModuleType)` first.

    `zipp.compat.overlay` puts a `HashableNamespace` -- not a `ModuleType` -- into
    `sys.modules["zipp.compat.overlay.zipfile"]`, carrying the real stdlib `zipfile`'s spec, file
    and `__all__`. An `isinstance` gate calls that a double and the teardown evicts a live stdlib
    alias. This arm rebuilds that shape from the import system's own spec so it does not depend on
    zipp staying installed, staying on this layout, or being imported by the time this runs."""
    import json

    class _NotAModuleAtAll:
        pass

    proxy = _NotAModuleAtAll()
    proxy.__spec__ = json.__spec__          # genuine provenance, non-module carrier
    proxy.__file__ = json.__file__
    assert _is_a_test_built_double(proxy) is False, (
        "a real module served by a class that is not ModuleType was read as a test double; the "
        "teardown would evict it"
    )


def test_A_HAND_BUILT_DOUBLE_IS_RECOGNISED():
    """Both shapes actually used in this repo: a bare `ModuleType` and a `MagicMock`."""
    assert _is_a_test_built_double(types.ModuleType("x")) is True
    assert _is_a_test_built_double(MagicMock()) is True


def test_THE_SPEC_CHECK_IS_AN_ISINSTANCE_AND_NOT_A_NONE_TEST():
    """⚠ WHAT MAKES THE `isinstance` LOAD-BEARING, measured rather than reasoned, because the
    first version of this arm asserted the opposite and was red within a minute.

    MEASURED: a plain `MagicMock()` RAISES AttributeError for `__spec__` (mock refuses dunders it
    was not configured for), so `getattr(obj, "__spec__", None)` yields None and a `is None` test
    would have classified it correctly. It is `MagicMock(spec=<a module>)` that answers `__spec__`
    with a child mock -- truthy, not None, not a ModuleSpec -- and only the isinstance catches it.

    NO TEST IN THIS REPO USES `Mock(spec=...)` FOR A MODULE TODAY. That is the honest state: this
    arm defends a shape the population does not yet contain, and it is cheap precisely so the
    predicate does not have to be re-derived by whoever first reaches for `spec=` to make a stub
    stricter."""
    assert getattr(MagicMock(), "__spec__", None) is None, (
        "POSITIVE CONTROL: a bare MagicMock now answers __spec__, so the two halves below no "
        "longer distinguish an isinstance check from a None check"
    )
    import json
    dressed = MagicMock(spec=json)
    got = getattr(dressed, "__spec__", None)
    assert got is not None and not isinstance(got, importlib.machinery.ModuleSpec), (
        f"POSITIVE CONTROL: MagicMock(spec=...) answered __spec__ with {got!r}; if that is now "
        "None or a real ModuleSpec this arm is testing nothing"
    )
    assert _is_a_test_built_double(dressed) is True, (
        "a spec-configured mock passed as a real module -- the predicate has been relaxed to a "
        "None or truthiness test on __spec__"
    )


def test_THE_PREDICATE_IS_RIGHT_ABOUT_THE_WHOLE_LIVE_POPULATION():
    """⚠ THE THREE ARMS ABOVE ARE A SAMPLE. This one is the census, and it is what says the
    teardown is safe to let loose on a suite rather than on four modules I thought of.

    The independent criterion is `importlib.util.find_spec`, which asks the import system where a
    name LIVES and knows nothing about this predicate's reasoning. Every entry in the live
    `sys.modules` that the import system can locate on disk must be called real; anything the
    predicate calls a double must be something `find_spec` cannot place. The set is whatever this
    process has imported by now -- several hundred entries of stdlib, site-packages and repo code
    -- so it is not a list anyone curated.

    A FALSE POSITIVE HERE IS THE SERIOUS DIRECTION: it means the teardown would evict a real
    module and hand the next file a second object of the same name.

    ⛔ AND IT FOUND ONE ON ITS FIRST RUN, which is why it exists as a census and not as a fourth
    example. The predicate's first form gated on `isinstance(obj, types.ModuleType)` and was right
    about every module I picked by hand; this arm handed it the whole live population and it called
    `zipp.compat.overlay.zipfile` -- a `HashableNamespace` wrapping the real stdlib `zipfile` -- a
    test double. `test_A_REAL_MODULE_SERVED_BY_A_NON_MODULE_CLASS_IS_STILL_REAL` holds that shape
    directly; this arm keeps looking for the next one.
    """
    import importlib.util
    misread = []
    for name, obj in list(sys.modules.items()):
        if obj is None or not _is_a_test_built_double(obj):
            continue
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, AttributeError, ValueError, TypeError):
            continue  # unplaceable: consistent with being a double
        if spec is not None and getattr(spec, "origin", None) not in (None, "built-in", "frozen"):
            misread.append((name, getattr(spec, "origin", None)))
    assert not misread, (
        "the predicate called these REAL, file-backed modules test doubles; the teardown would "
        f"evict them and break exception identity for the next file:\n{misread}"
    )
    assert len(sys.modules) > 100, (
        f"POSITIVE CONTROL FAILED: only {len(sys.modules)} modules loaded, so this census had "
        "almost nothing to be right about"
    )


def test_THE_PREDICATE_IS_DERIVED_AND_NOT_A_LIST_OF_NAMES():
    """The harness used to carry `_STUBBED_GLOBALS = ("baml_client", "dagster")`. A list you have
    to append to is retired by the first file that stubs a third name, silently, because the
    restore simply stops covering it. So a double of a name nobody wrote down is still a double."""
    assert _is_a_test_built_double(types.ModuleType("a_name_no_harness_ever_listed")) is True


# ── the context manager ─────────────────────────────────────────────────────────────────────
def test_stub_modules_INSTALLS_OVER_WHAT_IS_ALREADY_THERE():
    """THE MEASURED DEFECT. `setdefault` and `if not in sys.modules` both fail here, and this is
    the arm that distinguishes the harness from what the 12 deferring files do today."""
    incumbent = types.ModuleType(_NAME)
    incumbent.marker = "the one that got there first"
    sys.modules[_NAME] = incumbent
    try:
        mine = types.ModuleType(_NAME)
        mine.marker = "my recorder"
        with stub_modules({_NAME: mine}):
            assert sys.modules[_NAME] is mine, (
                "the double deferred to the incumbent -- every assertion the caller makes about "
                "what it recorded is now a claim about somebody else's object"
            )
        assert sys.modules[_NAME] is incumbent, "the incumbent was not put back"
    finally:
        sys.modules.pop(_NAME, None)


def test_stub_modules_RESTORES_ABSENCE_AND_NOT_JUST_VALUES():
    """A name that did not exist must not exist afterwards. Restoring only the entries that HAD a
    previous value is how a double survives: `dict.update` on the way in has no inverse on the way
    out unless absence is recorded as a state."""
    assert _NAME not in sys.modules
    with stub_modules({_NAME: types.ModuleType(_NAME)}):
        assert _NAME in sys.modules
    assert _NAME not in sys.modules, "the double outlived the block that installed it"


def test_stub_modules_RESTORES_WHEN_THE_BODY_RAISES():
    """A failing test is exactly when the leak is least welcome and most likely: without the
    `finally` the first red in a stubbing file poisons every file after it."""
    with pytest.raises(ZeroDivisionError):
        with stub_modules({_NAME: types.ModuleType(_NAME)}):
            1 / 0
    assert _NAME not in sys.modules, (
        "the double outlived a block whose body RAISED -- the install is not in a try/finally, so "
        "the first red in a stubbing file poisons every file after it"
    )


def test_stub_modules_RESTORES_THE_REAL_MODULE_BY_IDENTITY():
    """Not by name, and not by re-importing: the same object goes back, because a re-import would
    be the two-module-objects defect wearing the restore's clothes."""
    import json
    real = sys.modules["json"]
    with stub_modules({"json": types.ModuleType("json")}):
        assert sys.modules["json"] is not real
    assert sys.modules["json"] is real
    assert json.dumps({"a": 1}) == '{"a": 1}', "the restored module is not usable"


# ── the parent attribute, which is half of what "installed" means ───────────────────────────
@pytest.fixture()
def real_package(tmp_path):
    """A REAL, file-backed package with a submodule, already imported. Not a fixture double: the
    arms below are about what happens when the thing being overridden is genuinely there, which a
    ModuleType cannot reproduce because it has no parent attribute to lose."""
    pkg = tmp_path / "a_real_package_for_this_seal"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub.py").write_text("WHO = 'the real one'\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        import importlib
        mod = importlib.import_module("a_real_package_for_this_seal.sub")
        yield mod
    finally:
        sys.path.remove(str(tmp_path))
        for key in [k for k in sys.modules if k.startswith("a_real_package_for_this_seal")]:
            del sys.modules[key]


def test_THE_THREE_IMPORT_FORMS_DO_NOT_AGREE(real_package):
    """⚠ THE MEASUREMENT THAT MADE `stub_modules` TOUCH THE PARENT, kept as an executable control
    rather than a sentence, because it is the premise the rest of this section rests on and it is
    a claim about CPython that I would otherwise be asserting from memory.

    A `sys.modules`-only double is seen by `from pkg.sub import name` and IGNORED by
    `import pkg.sub` and `from pkg import sub`, both of which resolve `getattr(pkg, "sub")`. So a
    double that only writes `sys.modules` is a bet on the import form the subject happens to use
    -- and engine-o's `from baml_client.type_builder import TypeBuilder` wins that bet by luck,
    not design."""
    pkg = "a_real_package_for_this_seal"
    double = types.ModuleType(f"{pkg}.sub")
    double.WHO = "my recorder"
    sys.modules[f"{pkg}.sub"] = double  # the sys.modules-ONLY install, deliberately
    ns: dict = {}
    exec(f"from {pkg}.sub import WHO", ns)
    assert ns["WHO"] == "my recorder", "the from-form stopped reading sys.modules"
    exec(f"import {pkg}.sub as s", ns)
    assert ns["s"].WHO == "the real one", (
        "`import pkg.sub` now honours a sys.modules-only double. If this is the new behaviour the "
        "parent-attribute half of stub_modules is no longer load-bearing -- verify, do not delete"
    )


def test_stub_modules_IS_SEEN_BY_EVERY_IMPORT_FORM(real_package):
    """What the arm above costs, and the reason the parent is written at all."""
    pkg = "a_real_package_for_this_seal"
    double = types.ModuleType(f"{pkg}.sub")
    double.WHO = "my recorder"
    with stub_modules({f"{pkg}.sub": double}):
        ns: dict = {}
        for form in (f"from {pkg}.sub import WHO", f"import {pkg}.sub as s\nWHO = s.WHO",
                     f"from {pkg} import sub\nWHO = sub.WHO"):
            exec(form, ns)
            assert ns["WHO"] == "my recorder", f"the double is invisible to: {form!r}"


def test_stub_modules_PUTS_THE_PARENTS_ATTRIBUTE_BACK(real_package):
    """The inverse is the whole reason the parent may be touched. Restoring `sys.modules` while
    leaving `pkg.sub` pointing at a dead double is the 2026-09-04 defect with the halves swapped:
    the entry is right and the attribute is the lie."""
    pkg = "a_real_package_for_this_seal"
    parent = sys.modules[pkg]
    before = parent.sub
    assert before is real_package
    with stub_modules({f"{pkg}.sub": types.ModuleType(f"{pkg}.sub")}):
        assert parent.sub is not before
    assert parent.sub is before, "the real submodule is no longer reachable through its parent"
    assert sys.modules[f"{pkg}.sub"] is before


def test_stub_modules_REMOVES_AN_ATTRIBUTE_THE_PARENT_NEVER_HAD(real_package):
    """Absence is a state on the parent too. A double for a submodule that was never imported
    leaves the parent carrying an attribute the real package does not define, so the next file's
    `from pkg import never_imported` succeeds where it should raise."""
    pkg = "a_real_package_for_this_seal"
    parent = sys.modules[pkg]
    assert not hasattr(parent, "ghost")
    with stub_modules({f"{pkg}.ghost": types.ModuleType(f"{pkg}.ghost")}):
        assert parent.ghost is sys.modules[f"{pkg}.ghost"]
    assert not hasattr(parent, "ghost"), "the parent kept an attribute for a module that is gone"


def test_stub_modules_DOES_NOT_REQUIRE_THE_PARENT_TO_BE_LOADED():
    """The ordinary case in this repo: `baml_client.types` stubbed when no `baml_client` is
    imported at all. Writing the attribute must be conditional on the parent existing, not on
    the caller remembering to stub top-down."""
    with stub_modules({f"{_NAME}.child": types.ModuleType(f"{_NAME}.child")}):
        assert f"{_NAME}.child" in sys.modules
        assert _NAME not in sys.modules, "a parent was invented"
    assert f"{_NAME}.child" not in sys.modules


# ── the autouse floor, driven through the real callables ────────────────────────────────────
#
# The fixture body is three lines and calls `snapshot_modules` then
# `restore_doubles_installed_since`, which is why those are module-level functions: these arms
# run the code the suite runs. `test_THE_AUTOUSE_FIXTURE_ACTUALLY_CALLS_THE_RULE` below is what
# keeps that true -- without it, this section would be sealing a pair of functions nothing uses.
def test_THE_TEARDOWN_REMOVES_A_DOUBLE_A_MODULE_LEFT_BEHIND():
    saved = snapshot_modules()
    sys.modules[_NAME] = types.ModuleType(_NAME)
    touched = restore_doubles_installed_since(saved)
    assert _NAME not in sys.modules, (
        "a double installed during a module survived it, which is how a later file fails in its "
        "own name for something it never did"
    )
    assert _NAME in touched, f"the restore did not report touching it: {touched}"


def test_THE_TEARDOWN_PUTS_A_REPLACED_REAL_MODULE_BACK():
    saved = snapshot_modules()
    real = sys.modules["json"]
    sys.modules["json"] = types.ModuleType("json")
    restore_doubles_installed_since(saved)
    assert sys.modules["json"] is real


def test_THE_TEARDOWN_LEAVES_A_REAL_IMPORT_ALONE():
    """⚠ THE ARM THAT KEEPS THE CURE FROM BEING WORSE. A module imported for the first time during
    a test is a real, file-backed module and must stay in `sys.modules`; popping it so the next
    file re-imports it makes two classes of one name. `wave` is chosen because nothing in this
    repo imports it, so the first import really happens inside the window."""
    sys.modules.pop("wave", None)
    saved = snapshot_modules()
    import wave
    assert sys.modules.get("wave") is wave
    touched = restore_doubles_installed_since(saved)
    assert sys.modules.get("wave") is wave, (
        "a genuine import was evicted by the teardown -- the next file to import it gets a "
        "second module object, and exception identity across the two stops working"
    )
    assert "wave" not in touched


def test_THE_TEARDOWN_RESTORES_A_WHOLE_SUBTREE_NOT_JUST_THE_PARENT():
    """Measured 2026-09-04: restoring the parent alone traded eleven failures for seventeen. The
    child entry stayed in `sys.modules` while the parent object that should carry it as an
    ATTRIBUTE had been swapped, so `pkg.sub.Name` resolved the submodule and then failed on the
    attribute. Comparing every key by object identity does this by construction, so this arm is
    here to keep it that way rather than to describe a fix."""
    saved = snapshot_modules()
    sys.modules[_NAME] = types.ModuleType(_NAME)
    sys.modules[_OTHER] = types.ModuleType(_OTHER)
    sys.modules[f"{_NAME}.child"] = types.ModuleType(f"{_NAME}.child")
    restore_doubles_installed_since(saved)
    for key in (_NAME, _OTHER, f"{_NAME}.child"):
        assert key not in sys.modules, f"{key} survived its module"


def test_THE_AUTOUSE_FIXTURE_ACTUALLY_CALLS_THE_RULE():
    """Without this, every arm above could pass while nothing in the suite ran the harness at all
    -- a feature whose only caller is a test of the feature. Read off the shipped conftest."""
    src = (pathlib.Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    i = src.index("def _no_module_leaves_a_double_behind(")
    body = src[i:src.index("\n# ", i)]
    assert "snapshot_modules()" in body and "restore_doubles_installed_since(saved)" in body, (
        f"the autouse fixture no longer calls the rule these arms exercise:\n{body}"
    )
    assert "autouse=True" in src[max(0, i - 200):i], (
        "the teardown is no longer autouse, so it protects only the files that ask for it -- and "
        "the class this closes is precisely a file that did not think to ask"
    )


# ── the population, ratcheted ───────────────────────────────────────────────────────────────
#: Files that install a double only when the name is ABSENT. Each one is a bet on collection
#: order. They are allowed to stay because the names they defer on are absence SHIMS (an import
#: must succeed; nothing asserts on what the shim recorded) -- the distinction in this module's
#: docstring. Measured 2026-09-27: 6 by `sys.modules.setdefault`, 7 by an `if`-guard, one both.
_DEFERRING_FILES = frozenset({
    "tests/routing/test_a_menu_on_the_wire_can_be_answered.py",
    "tests/routing/test_adr0019_contracts.py",
    "tests/routing/test_adr0019_engine_o_contract_a.py",
    "tests/routing/test_b2_ingest_sandboxrtx.py",
    "tests/routing/test_b3a_ingest_helmet_40051.py",
    "tests/routing/test_the_pool_reaches_the_universal_referent.py",
    "tests/test_a_hole_is_drawn_only_for_the_disposition_that_means_one.py",
    "tests/test_ontology_routing.py",
    "tests/test_predicate_hybrid_search.py",
    "tests/test_registration_retries_and_readiness_sees_it.py",
    "tests/test_routing_fallback.py",
    "tests/test_tier3_urn_propagation.py",
})

#: The guard must be CODE, not a sentence about the guard. BOTH alternatives carry the `^[^#]*`
#: prefix: the first version anchored only the `if` arm, and `tests/conftest.py` promptly matched
#: on a COMMENT that says how many files use `sys.modules.setdefault` -- the file that provides
#: the harness reporting itself as a member of the population it exists to shrink.
_DEFERRAL = re.compile(
    r"^[^#]*(?:sys\.modules\.setdefault|\bif .*not in sys\.modules)", re.M
)


def test_THE_DEFERRAL_MATCHER_READS_CODE_AND_NOT_PROSE():
    """⚠ POSITIVE CONTROL FOR THE RATCHET'S MATCHER, in both directions, because the population
    below is only as good as this pattern and I got this pattern wrong three times on the way here:
    once by counting the file that defers in two spellings twice; once with `[^\\n]` inside a grep
    bracket -- which is the complement of `{\\, n}`, so it silently dropped every guard whose
    subject contains the letter n and reported 10 where the answer was 12; and once by anchoring
    only one of the two alternatives, so a comment COUNTING the deferrers registered as one.

    Two of those three read as a population that had changed rather than as a matcher that was
    wrong, which is the whole reason this arm is not a comment."""
    assert _DEFERRAL.search('    if "baml_client" not in sys.modules:\n')
    assert _DEFERRAL.search("    if name not in sys.modules:\n"), "the letter n is not a delimiter"
    assert _DEFERRAL.search("    sys.modules.setdefault(name, MagicMock())\n")
    assert not _DEFERRAL.search("    'dagster not in sys.modules' would pass\n"), "prose matched"
    assert not _DEFERRAL.search("    assert _NAME not in sys.modules\n"), "an assertion matched"
    assert not _DEFERRAL.search("# 6 files use `sys.modules.setdefault`, 7 an `if`-guard\n"), (
        "a comment about the guards matched -- this is the form tests/conftest.py tripped on"
    )


def test_NO_NEW_FILE_BETS_ON_COLLECTION_ORDER():
    """A MEASURED RATCHET, and the only thing that stops this class coming back.

    The 12 files above were measured, not remembered. A new file appearing here is not
    automatically wrong -- an absence shim may defer -- but it is a DECISION, and the point of the
    ratchet is that the decision gets made in the open rather than by whoever copies the nearest
    file. If your double is something the test asserts on, use `stub_modules` and delete the
    guard; if it is a shim, add the path here and say why in the commit message.

    THIS FILE IS EXCLUDED FROM ITS OWN SCAN, stated rather than quietly arranged: its docstring
    quotes the guard in order to explain it, and it installs nothing conditionally.
    """
    here = pathlib.Path(__file__).resolve()
    repo = here.parents[1]
    found = {
        p.relative_to(repo).as_posix()
        for p in (repo / "tests").rglob("*.py")
        if p.resolve() != here
        and _DEFERRAL.search(p.read_text(encoding="utf-8", errors="replace"))
    }
    assert found, "POSITIVE CONTROL FAILED: the matcher found no deferring file at all"
    assert found == set(_DEFERRING_FILES), (
        f"the deferring population moved.\n  new: {sorted(found - set(_DEFERRING_FILES))}\n"
        f"  gone: {sorted(set(_DEFERRING_FILES) - found)}"
    )


# ── no file writes sys.modules without putting it back ──────────────────────────────────────
#: THE SECOND RATCHET, derived the same way as the first: scan the CODE of every file under
#: tests/ (an AST, not a grep, so a docstring that quotes `sys.modules[x] = y` is not a write).
#: A WRITE is any of `sys.modules[k] = v`, `del sys.modules[k]`, and `.setdefault/.update/.pop/
#: .popitem/.clear` on `sys.modules` or on a name bound to it (`mods = sys.modules`).
#: `monkeypatch.setitem/delitem`, `stub_modules` and `patch.dict` are not writes here: they ARE
#: the restore, and they are not spelled as a write.
#:
#: A WRITE IS COVERED when ANY of these holds -- each is a form that puts the prior value back:
#:   shim      it is `.setdefault(...)` or sits under `if <name> not in sys.modules`: an absence
#:             shim, which `_DEFERRING_FILES` above already pins as a population;
#:   finally   it sits in the `finalbody` of a `try`, or in the body of a `try` whose `finalbody`
#:             writes `sys.modules`;
#:   yielded   it sits AFTER the first `yield` of a fixture (the teardown half);
#:   fixture   its key is a plain name or string that a fixture of the same file mentions AND whose
#:             post-`yield` half writes `sys.modules` -- the form for a module that is loaded by
#:             path inside a helper which no fixture wraps. The key must be a NAME or a literal:
#:             an attribute such as `spec.name` names nothing a reader can check, so it is refused.
#: Everything else is an N file. Undecided (unparseable) counts as N, never as clean.
_WRITING_METHODS = {"setdefault", "update", "pop", "popitem", "clear"}
#: NO EXEMPTION LIST. The one candidate was `_install_stubs` in test_predicate_hybrid_search.py:
#: it installed the stubs, and the restore lived in its two callers. It is removed. Those callers
#: now do the install inside the `try` whose `finally` puts it back, where this matcher can SEE the
#: restore. A list of excused files is a place to append the next one, so there is none, and the
#: population must be empty.
#:
#: KNOWN LIMIT of the `fixture` rule, stated rather than hidden. Another fixture covers a key when
#: its WHOLE text mentions the key and its teardown writes `sys.modules`, not only when its
#: teardown restores THAT key. It has to be the whole text, because the restore fixtures here
#: record their keys before the `yield` and put them back in a loop over a variable. So a helper's
#: bare write of `_K` passes beside a fixture that mentions `_K` but restores only `_J`. No file
#: does that today.


def _is_sys_modules(node, aliases):
    return (
        isinstance(node, ast.Attribute) and node.attr == "modules"
        and isinstance(node.value, ast.Name) and node.value.id in ("sys", "_sys")
    ) or (isinstance(node, ast.Name) and node.id in aliases)


def _unrestored_writes(source: str) -> list[tuple[int, str]]:

    tree = ast.parse(source)
    aliases = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and _is_sys_modules(n.value, set())
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

    def key_and_node(n):
        """(node, key-expression) when `n` is a sys.modules write, else None."""
        if isinstance(n, (ast.Assign, ast.AugAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(t, ast.Subscript) and _is_sys_modules(t.value, aliases):
                    return n, t.slice
        elif isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and _is_sys_modules(t.value, aliases):
                    return n, t.slice
        elif (
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in _WRITING_METHODS and _is_sys_modules(n.func.value, aliases)
        ):
            return n, (n.args[0] if n.args else None)
        return None

    writes = [kn for kn in map(key_and_node, ast.walk(tree)) if kn]

    def func_of(n):
        while n in parent:
            n = parent[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n
        return None

    def is_fixture(f):
        return f is not None and any(
            "fixture" in ast.unparse(d) for d in f.decorator_list
        )

    def first_yield(f):
        ys = [y.lineno for y in ast.walk(f) if isinstance(y, (ast.Yield, ast.YieldFrom))]
        return min(ys) if ys else None

    def in_finalbody(n):
        while n in parent:
            q = parent[n]
            if isinstance(q, ast.Try) and n in q.finalbody:
                return True
            n = q
        return False

    def inside_a_try_whose_finally_writes(n):
        while n in parent:
            q = parent[n]
            if isinstance(q, ast.Try) and n in (q.body + q.orelse + [h for h in q.handlers]):
                if any(key_and_node(x) for fb in q.finalbody for x in ast.walk(fb)):
                    return True
            n = q
        return False

    def under_an_absence_guard(n):
        while n in parent:
            q = parent[n]
            if isinstance(q, ast.If) and n in q.body and re.search(
                r"\bnot in (?:_?sys\.modules|" + "|".join(sorted(aliases) or ["$^"]) + r")\b",
                ast.unparse(q.test),
            ):
                return True
            n = q
        return False

    # fixtures whose teardown half writes sys.modules, with their full text
    restoring_fixtures = []
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_fixture(f):
            y = first_yield(f)
            if y is not None and any(
                key_and_node(x) and x.lineno > y for x in ast.walk(f)
            ):
                teardown = "\n".join(
                    ast.unparse(x) for x in ast.walk(f) if key_and_node(x) and x.lineno > y
                )
                restoring_fixtures.append((f, ast.unparse(f), teardown))

    def covered_by_a_fixture(n, key):
        if key is None:
            return False
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            pat = re.escape(repr(key.value)) + "|" + re.escape('"' + key.value + '"')
        elif isinstance(key, ast.Name):
            pat = r"\b" + re.escape(key.id) + r"\b"
        else:
            return False
        # another fixture covers by its whole text; the write's OWN fixture covers only by the
        # keys its teardown half (after the yield) puts back
        return any(
            re.search(pat, teardown if func_of(n) is f else text)
            for f, text, teardown in restoring_fixtures
        )

    bad = []
    for n, key in writes:
        f = func_of(n)
        y = first_yield(f) if f is not None else None
        if (
            (isinstance(n, ast.Call) and n.func.attr == "setdefault")
            or under_an_absence_guard(n)
            or in_finalbody(n)
            or inside_a_try_whose_finally_writes(n)
            or (is_fixture(f) and y is not None and n.lineno > y)
            or covered_by_a_fixture(n, key)
        ):
            continue
        bad.append((n.lineno, ast.unparse(n)[:80]))
    return sorted(bad)


def test_THE_RESTORE_MATCHER_READS_CODE_AND_TELLS_A_RESTORE_FROM_A_BARE_WRITE():
    """POSITIVE CONTROL FOR THE RATCHET BELOW, in both directions, because `[]` from a matcher
    that matches nothing reads exactly like a population that is clean."""
    bare = _unrestored_writes
    # a bare write, a bare pop, a bare del, and one through an alias: all four are N
    assert len(bare("import sys\nsys.modules['a'] = 1\n")) == 1
    assert len(bare("import sys\nsys.modules.pop('a', None)\n")) == 1
    assert len(bare("import sys\ndel sys.modules['a']\n")) == 1
    assert len(bare("import sys\nm = sys.modules\nm['a'] = 1\n")) == 1, "an alias hid a write"
    # prose is not code: a docstring, a comment and a string that SAY it are not writes
    assert not bare('import sys\n"""sys.modules[\'a\'] = 1"""\n# sys.modules.pop("a")\nx = "del sys.modules[1]"\n')
    # the forms that ARE a restore
    assert not bare("import sys\ntry:\n    sys.modules['a'] = 1\nfinally:\n    sys.modules.pop('a', None)\n")
    assert not bare("import sys\ndef f():\n    sys.modules.setdefault('a', 1)\n"), "an absence shim"
    assert not bare("import sys\nif 'a' not in sys.modules:\n    sys.modules['a'] = 1\n")
    assert not bare("import sys\nimport pytest\n@pytest.fixture\ndef f():\n    sys.modules['a'] = 1\n    yield\n    sys.modules.pop('a', None)\n")
    assert not bare(
        "import sys\nimport pytest\n_K = 'k'\n"
        "def load():\n    sys.modules[_K] = 1\n"
        "@pytest.fixture(autouse=True)\ndef back():\n    yield\n    sys.modules.pop(_K, None)\n"
    ), "a fixture that restores the SAME key covers a write made in a helper"
    # ...and the forms that look like one and are not
    assert bare(
        "import sys\nimport pytest\n_K = 'k'\n_J = 'j'\n"
        "def load():\n    sys.modules[_J] = 1\n"
        "@pytest.fixture(autouse=True)\ndef back():\n    yield\n    sys.modules.pop(_K, None)\n"
    ), "a fixture restoring a DIFFERENT key must not cover this one"
    assert bare(
        "import sys\nimport pytest\n"
        "def load(spec):\n    sys.modules[spec.name] = 1\n"
        "@pytest.fixture(autouse=True)\ndef back(spec):\n    yield\n    sys.modules.pop(spec.name, None)\n"
    ), "an attribute key names nothing a reader can check"
    assert bare("import sys\ntry:\n    sys.modules['a'] = 1\nfinally:\n    pass\n"), "a finally that restores nothing"
    assert bare("import sys\ndef f():\n    sys.modules['a'] = 1\n    yield\n"), "a generator that never restores"
    # the safe spellings are not writes at all
    assert not bare("import sys\ndef t(monkeypatch):\n    monkeypatch.setitem(sys.modules, 'a', 1)\n    monkeypatch.delitem(sys.modules, 'b', raising=False)\n")


def test_NO_FILE_WRITES_SYS_MODULES_WITHOUT_A_RESTORE():
    """THE SECOND MEASURED RATCHET, derived and not listed. Measured 2026-10-07 on lane/gov:
    32 files under tests/ wrote `sys.modules` with no restore -- doubles, popped real
    modules, and modules loaded by path and registered under a private name for good. Each was
    converted to `monkeypatch.setitem/delitem`, `stub_modules`, a try/finally, or a module-scoped
    fixture that puts the recorded prior state back. The last residue, `_install_stubs` (an install whose
    restore lived in its two callers), was removed, and the callers now install inside their own
    try/finally. The population is empty, and no list
    excuses a file from it.

    THE CONFTEST AUTOUSE FIXTURE IS NOT THE REASON THIS IS ALLOWED TO BE EMPTY. It restores only
    objects with no `ModuleSpec`, so it never undid a path-loaded real module, a popped real
    module, or an import-time install -- the three shapes that were left behind.

    EXCLUDED FROM THE SCAN, stated: `tests/conftest.py` (it IS the restore) and this file (it
    writes `sys.modules` on purpose to test the restore, and quotes the forms in strings)."""
    here = pathlib.Path(__file__).resolve()
    repo = here.parents[1]
    scanned = 0
    found: dict[str, list[int]] = {}
    for p in sorted((repo / "tests").rglob("*.py")):
        if p.resolve() in (here, (repo / "tests" / "conftest.py").resolve()):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        scanned += 1
        try:
            bad = _unrestored_writes(text)
        except SyntaxError:
            found[p.relative_to(repo).as_posix()] = [-1]  # undecided is a failure, never clean
            continue
        if bad:
            found[p.relative_to(repo).as_posix()] = [ln for ln, _ in bad]
    assert scanned > 100, f"POSITIVE CONTROL FAILED: the scan saw {scanned} files"
    assert not found, (
        "a file writes sys.modules and does not put it back. Use monkeypatch.setitem/delitem,\n"
        "`stub_modules`, a try/finally, or a fixture that restores after its yield:\n"
        + "\n".join(f"  {f}: lines {ln}" for f, ln in sorted(found.items()))
    )
