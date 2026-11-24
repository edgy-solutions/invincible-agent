"""A probe for `tests/test_live_tests_leave_the_default_run.py`. It is never part of a run.

The name does not match `test_*.py`, so the default collection never picks it up. The seal
collects it by path, through the real `tests/conftest.py` hook, and asserts which ids that hook
keeps. There is one test per arm of the hook, and the bodies do nothing.

`test_requires_cluster_only` is the case gov's probe found on #442: a per-test `requires_*` mark
with no `live` mark on that test. Under `-m "not live"` it ran.
"""
import pytest


@pytest.mark.live
def test_live():
    pass


@pytest.mark.requires_cluster
def test_requires_cluster_only():
    pass


@pytest.mark.requires_engine_o
def test_requires_engine_o_only():
    pass


def test_plain():
    pass
