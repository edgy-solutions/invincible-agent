"""Dep-free helpers shared by the supervisor and other iagent code.

This sibling package to ``iagent`` exists specifically so pure-unit
tests can import the contained helpers without triggering
``iagent/__init__.py``'s heavy import chain
(``definitions.py`` → ``defs.dynamic_factory`` → ``psycopg2`` /
``dagster``). Anything that lives here MUST stay dependency-free
(stdlib only) so the test value of the split is preserved.

If a helper here needs a non-stdlib dep, move it back into
``iagent.defs`` and refactor the test to use higher-fidelity
mocking; do NOT add deps to this package.
"""
