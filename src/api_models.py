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
    level: int = 5
    group: str = ""
    importance: float = 0.0
    betweenness: float = 0.0
    pagerank: float = 0.0
    degree_centrality: float = 0.0


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    type: str
    description: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    source_document: str
    graph_title: str = ""
    type_colors: dict[str, str]
    entity_groups: list[str] = []


# --- GET /api/graphs ---


class GraphListItem(BaseModel):
    filename: str
    graph_title: str
    entity_count: int
    relationship_count: int


class LoadGraphRequest(BaseModel):
    filename: str


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


# --- POST /api/cascade ---


class CascadeRequest(BaseModel):
    event_node_id: str
    max_depth: int = 10


class CascadeStep(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    depth: int
    parent_node_id: str | None = None
    edge_type: str = ""


class CascadeResponse(BaseModel):
    event_name: str
    steps: list[CascadeStep]
    node_ids: list[str]
    edge_keys: list[str]


# --- GET /api/scenarios ---


class ScenarioLogLine(BaseModel):
    type: str  # query, traverse, attr, decision, warning, dim
    text: str


class ScenarioStep(BaseModel):
    title: str
    description: str
    highlight_nodes: list[str]
    highlight_edges: list[str]
    focus_node: str | None = None
    log: list[ScenarioLogLine]


class Scenario(BaseModel):
    id: str
    name: str
    steps: list[ScenarioStep]


class ScenariosResponse(BaseModel):
    scenarios: list[Scenario]


# --- POST /api/agent/walkthrough ---


class WalkthroughRequest(BaseModel):
    prompt: str
