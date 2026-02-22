"""SQLAlchemy model for the bpmn_catalog table.

This module defines the ORM representation of the BPMN workflow catalog.
The table is consumed by the dynamic factory (src/iagent/defs/dynamic_factory.py)
and written to by the FastAPI compile endpoint.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# Base class for all ORM models in this project
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""
    pass


# ---------------------------------------------------------------------------
# bpmn_catalog table
# ---------------------------------------------------------------------------
class BPMNCatalog(Base):
    """ORM model for the ``bpmn_catalog`` table.

    Stores simplified BPMN JSON payloads that describe workflows.  Each row
    is a self-contained workflow definition that the Dagster dynamic factory
    reads at startup to generate imperative ops.

    Attributes:
        workflow_id:   Unique identifier for the workflow (primary key).
        name:          Human-readable workflow name.
        bpmn_payload:  The full BPMN JSON payload (stored as JSONB).
        is_active:     Whether this workflow is currently active.
        created_at:    Timestamp of row creation (server-side default).
        updated_at:    Timestamp of last update (auto-updated on change).
    """

    __tablename__ = "bpmn_catalog"

    workflow_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    bpmn_payload = Column(JSONB, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<BPMNCatalog(workflow_id={self.workflow_id!r}, "
            f"name={self.name!r}, is_active={self.is_active})>"
        )
