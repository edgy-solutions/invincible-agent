"""The fleet's concrete ``iagent_mesh`` WRITER implementations.

``iagent_mesh`` declares the write Protocols (``MeshGraphWriter``, ``MeshVectorsWriter``,
``MeshOntologyWriter``, ruled 2026-09-27) and ships ONE reference implementation,
``iagent_mesh.writers.jena.JenaOntologyWriter``. The store-specific implementations this fleet
needs live here rather than in the SDK, because the SDK is a PINNED input to this repo: a writer
added to the SDK is not visible to the branch that pins it, and the registrar adoption has to land
in the same commit range as the writer it adopts.

Structural typing throughout — no inheritance from the Protocols, which are ``runtime_checkable``
and matched by method shape. That is the same posture the SDK's own read implementations and
``JenaOntologyWriter`` take, and it is what lets ``iagent_mesh.conformance`` check an
implementation it has never imported.
"""
