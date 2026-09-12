"""The ``iagent`` package — DELIBERATELY EMPTY. Import the module you want.

This file used to read::

    from .definitions import defs

which meant importing ANY leaf of this package booted the entire Dagster
definitions graph. ``iagent.service_urls`` imports only ``logging`` and ``os``,
yet ``from iagent.service_urls import cortex_bff_base_url`` pulled in Dagster,
Definitions, and every asset module behind them.

THAT COUPLING IS WHAT BROKE THE STANDALONE CI JOB. A test that stubs ``dagster``
in ``sys.modules`` and then loads a module reaching for a cheap ``iagent`` helper
got its stub handed to the REAL ``iagent.definitions``::

    ImportError: cannot import name 'Definitions' from 'dagster' (unknown location)

``(unknown location)`` is the tell for a ``types.ModuleType`` with no
``__file__`` — somebody's stub — NOT for a missing distribution. dagster was
declared in response and the relock moved 262 packages to 262; dagster was never
missing. See tests/test_every_import_is_a_declared_dependency.py for the
retraction.

THERE IS NO ``defs`` EXPORT HERE, AND THERE CANNOT USEFULLY BE ONE. ``defs`` is
already the name of a SUBPACKAGE (``iagent/defs/``), so the attribute
``iagent.defs`` is claimed by the import system the moment anything imports
``iagent.defs.*`` — which ``iagent.definitions`` itself does, to collect assets.
The old eager line won that collision only by BINDING ORDER: it rebound the
attribute after the submodule imports had set it. A lazy ``__getattr__`` cannot
reproduce that, because ``__getattr__`` is consulted only when normal attribute
lookup FAILS, and here it succeeds with the subpackage. Reintroducing the export
would therefore be a shim that silently returns a module where callers expect a
``Definitions``.

So the graph is reached by its real name:

    iagent.definitions.defs     the Definitions object
    iagent.defs                 the subpackage of op/asset modules

Nothing in this repo spelled it ``from iagent import defs``, and no entrypoint
loads the bare package: the user-code deployment runs ``dagster api grpc -m
iagent.definitions``, the Procfile runs ``dagster webserver -m
iagent.definitions``, and the projector runs ``python -m iagent.projector``.
Every one of them names a MODULE.

Sealed by tests/test_a_leaf_import_does_not_boot_dagster.py.
"""
