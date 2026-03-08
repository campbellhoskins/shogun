"""Shared base models used by both models.py and schemas.py.

Exists to break the circular import between models.py and schemas.py:
schemas.py needs SourceAnchor, and models.py needs AnyEntity from schemas.py.
"""

from __future__ import annotations

from pydantic import BaseModel


class SourceAnchor(BaseModel):
    """Provenance information linking an entity back to its source text."""

    source_text: str = ""
    source_section: str = ""
    source_offset: int = -1
