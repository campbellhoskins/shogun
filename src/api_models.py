"""Pydantic response models for the frontend API.

These are presentation-layer models optimized for the React frontend,
separate from the core domain models in src/models.py.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# --- GET /api/graph ---


class GraphNode(BaseModel):
    id: str
    type: str
    name: str
    description: str
    degree: int
    color: str


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    type: str
    description: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    source_document: str
    type_colors: dict[str, str]


# --- GET /api/graph/stats ---


class GraphStats(BaseModel):
    source_document: str
    entity_count: int
    relationship_count: int
    entity_types: dict[str, int]


# --- GET /api/entity/{entity_id} ---


class RelationshipDetail(BaseModel):
    direction: str  # "outgoing" or "incoming"
    relationship_type: str
    entity_id: str
    entity_name: str
    entity_type: str
    description: str


class EntityDetail(BaseModel):
    id: str
    type: str
    name: str
    description: str
    attributes: dict[str, Any]
    source_text: str
    source_section: str
    source_offset: int
    relationships: list[RelationshipDetail]


# --- GET /api/search ---


class EntitySummary(BaseModel):
    id: str
    type: str
    name: str
    description: str


# --- POST /api/paths ---


class PathRequest(BaseModel):
    source_id: str
    target_id: str
    max_hops: int = 5


class PathStep(BaseModel):
    from_id: str
    from_name: str
    relationship_type: str
    direction: str  # "forward" or "backward"
    to_id: str
    to_name: str


class PathResponse(BaseModel):
    paths: list[list[PathStep]]
    source_name: str
    target_name: str


# --- POST /api/agent/ask ---


class AgentQuestion(BaseModel):
    question: str


class AgentAnswer(BaseModel):
    answer: str
    referenced_entities: list[EntitySummary]
    reasoning_path: str
