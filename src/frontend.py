"""FastAPI backend for the Shogun Ontology Explorer frontend.

Serves the React SPA and provides REST API endpoints for graph
exploration, entity search, path finding, and agent Q&A.

Usage:
    uv run python -m src.frontend --graph path/to/ontology.json
    uv run python -m src.frontend --latest
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.agent import ask
from src.api_models import (
    AgentAnswer,
    AgentQuestion,
    CascadeRequest,
    CascadeResponse,
    CascadeStep,
    EntityDetail,
    EntitySummary,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphStats,
    PathRequest,
    PathResponse,
    PathStep,
    RelationshipDetail,
)
from src.graph import build_graph
from src.models import OntologyGraph

load_dotenv()

# Entity type -> color mapping (21 schema types, grouped by domain)
TYPE_COLORS: dict[str, str] = {
    # Group 1: Core Policy (indigo/blue)
    "Policy": "#818cf8",
    "PolicySection": "#6366f1",
    "PolicyRule": "#60a5fa",
    "PolicyException": "#a78bfa",
    # Group 2: Actors & Stakeholders (orange/amber)
    "TravelerRole": "#f97316",
    "Stakeholder": "#fb923c",
    "ServiceProvider": "#fbbf24",
    # Group 3: Travel Options & Context (teal/cyan/emerald)
    "TransportationMode": "#2dd4bf",
    "ClassOfService": "#34d399",
    "Accommodation": "#4ade80",
    "BusinessContext": "#22d3ee",
    "TravelEvent": "#f43f5e",
    "GeographicScope": "#38bdf8",
    # Group 4: Financial (yellow/lime)
    "ExpenseCategory": "#eab308",
    "ReimbursementLimit": "#a3e635",
    "PaymentMethod": "#facc15",
    "PriorityOrder": "#d9f99d",
    # Group 5: Compliance (pink/rose/violet)
    "Constraint": "#e879f9",
    "Requirement": "#f472b6",
    "Consequence": "#fb7185",
}
DEFAULT_COLOR = "#6b7280"

# Entity type -> hierarchy level (for hierarchical LR layout)
TYPE_LEVELS: dict[str, int] = {
    "TravelEvent": 0,
    "Policy": 1,
    "PolicySection": 2,
    "PolicyRule": 3,
    "PolicyException": 3,
    "Constraint": 4,
    "Requirement": 4,
    "Consequence": 4,
    "ReimbursementLimit": 4,
    # All leaf entity types at level 5
    "TravelerRole": 5,
    "Stakeholder": 5,
    "ServiceProvider": 5,
    "TransportationMode": 5,
    "ClassOfService": 5,
    "Accommodation": 5,
    "BusinessContext": 5,
    "GeographicScope": 5,
    "ExpenseCategory": 5,
    "PaymentMethod": 5,
    "PriorityOrder": 5,
}

# Entity type -> group name
TYPE_GROUP_MAP: dict[str, str] = {
    "Policy": "Core Policy",
    "PolicySection": "Core Policy",
    "PolicyRule": "Core Policy",
    "PolicyException": "Core Policy",
    "TravelerRole": "Actors & Stakeholders",
    "Stakeholder": "Actors & Stakeholders",
    "ServiceProvider": "Actors & Stakeholders",
    "TransportationMode": "Travel Options",
    "ClassOfService": "Travel Options",
    "Accommodation": "Travel Options",
    "BusinessContext": "Travel Options",
    "TravelEvent": "Travel Options",
    "GeographicScope": "Travel Options",
    "ExpenseCategory": "Financial",
    "ReimbursementLimit": "Financial",
    "PaymentMethod": "Financial",
    "PriorityOrder": "Financial",
    "Constraint": "Compliance",
    "Requirement": "Compliance",
    "Consequence": "Compliance",
}

# Ordered list of groups for legend display
ENTITY_GROUPS: list[str] = [
    "Core Policy",
    "Actors & Stakeholders",
    "Travel Options",
    "Financial",
    "Compliance",
]

# Module-level state (set during startup)
_ontology: OntologyGraph | None = None
_graph: nx.DiGraph | None = None
_client: Anthropic | None = None

app = FastAPI(title="Shogun Ontology Explorer")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


def _get_color(entity_type: str) -> str:
    return TYPE_COLORS.get(entity_type, DEFAULT_COLOR)


def _get_node_name(node_id: str) -> str:
    if _graph and node_id in _graph:
        return _graph.nodes[node_id].get("name", node_id)
    return node_id


# --- API Endpoints ---


@app.get("/api/graph")
def get_graph() -> GraphData:
    """Full graph data for vis-network rendering."""
    assert _graph is not None

    nodes = []
    for node_id, data in _graph.nodes(data=True):
        entity_type = data.get("type", "Unknown")
        nodes.append(GraphNode(
            id=node_id,
            type=entity_type,
            name=data.get("name", node_id),
            description=data.get("description", ""),
            degree=_graph.degree(node_id),
            color=_get_color(entity_type),
            level=TYPE_LEVELS.get(entity_type, 5),
            group=TYPE_GROUP_MAP.get(entity_type, ""),
        ))

    edges = []
    for src, tgt, data in _graph.edges(data=True):
        edges.append(GraphEdge(
            from_id=src,
            to_id=tgt,
            type=data.get("type", ""),
            description=data.get("description", ""),
        ))

    return GraphData(
        nodes=nodes,
        edges=edges,
        source_document=_graph.graph.get("source_document", ""),
        type_colors=TYPE_COLORS,
        entity_groups=ENTITY_GROUPS,
    )


@app.get("/api/graph/stats")
def get_graph_stats() -> GraphStats:
    """Summary statistics for the top bar."""
    assert _graph is not None

    type_counts: dict[str, int] = Counter()
    for _, data in _graph.nodes(data=True):
        type_counts[data.get("type", "Unknown")] += 1

    return GraphStats(
        source_document=_graph.graph.get("source_document", ""),
        entity_count=_graph.number_of_nodes(),
        relationship_count=_graph.number_of_edges(),
        entity_types=dict(type_counts.most_common()),
    )


@app.get("/api/entity/{entity_id}")
def get_entity(entity_id: str) -> EntityDetail:
    """Full entity details with all relationships."""
    assert _graph is not None

    if entity_id not in _graph:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    data = _graph.nodes[entity_id]

    # Collect attributes (everything except reserved keys)
    reserved = {"type", "name", "description", "source_text", "source_section", "source_offset"}
    attributes = {k: v for k, v in data.items() if k not in reserved}

    # Collect relationships
    relationships = []

    for _, target, edge_data in _graph.out_edges(entity_id, data=True):
        target_data = _graph.nodes[target]
        relationships.append(RelationshipDetail(
            direction="outgoing",
            relationship_type=edge_data.get("type", ""),
            entity_id=target,
            entity_name=target_data.get("name", target),
            entity_type=target_data.get("type", ""),
            description=edge_data.get("description", ""),
        ))

    for source, _, edge_data in _graph.in_edges(entity_id, data=True):
        source_data = _graph.nodes[source]
        relationships.append(RelationshipDetail(
            direction="incoming",
            relationship_type=edge_data.get("type", ""),
            entity_id=source,
            entity_name=source_data.get("name", source),
            entity_type=source_data.get("type", ""),
            description=edge_data.get("description", ""),
        ))

    return EntityDetail(
        id=entity_id,
        type=data.get("type", "Unknown"),
        name=data.get("name", entity_id),
        description=data.get("description", ""),
        attributes=attributes,
        source_text=data.get("source_text", ""),
        source_section=data.get("source_section", ""),
        source_offset=data.get("source_offset", -1),
        relationships=relationships,
    )


@app.get("/api/search")
def search_entities(q: str = Query(..., min_length=1)) -> list[EntitySummary]:
    """Search entities by keyword across name, description, and attributes."""
    assert _graph is not None

    query = q.lower()
    results = []

    for node_id, data in _graph.nodes(data=True):
        # Build searchable text
        searchable = " ".join([
            node_id,
            data.get("name", ""),
            data.get("description", ""),
            *[str(v) for v in data.values()],
        ]).lower()

        if query in searchable:
            results.append(EntitySummary(
                id=node_id,
                type=data.get("type", "Unknown"),
                name=data.get("name", node_id),
                description=data.get("description", ""),
            ))

    return results


@app.post("/api/paths")
def find_paths(req: PathRequest) -> PathResponse:
    """Find all paths between two entities."""
    assert _graph is not None

    if req.source_id not in _graph:
        raise HTTPException(status_code=404, detail=f"Source entity '{req.source_id}' not found")
    if req.target_id not in _graph:
        raise HTTPException(status_code=404, detail=f"Target entity '{req.target_id}' not found")

    # Use undirected graph for pathfinding (relationships are bidirectional for discovery)
    undirected = _graph.to_undirected()

    try:
        raw_paths = list(nx.all_simple_paths(
            undirected, req.source_id, req.target_id, cutoff=req.max_hops
        ))
    except nx.NetworkXError:
        raw_paths = []

    # Convert to PathStep chains (limit to 5 paths)
    result_paths: list[list[PathStep]] = []
    for path in raw_paths[:5]:
        steps = []
        for i in range(len(path) - 1):
            from_id = path[i]
            to_id = path[i + 1]

            # Determine actual edge direction and type
            if _graph.has_edge(from_id, to_id):
                edge_data = _graph.edges[from_id, to_id]
                direction = "forward"
            elif _graph.has_edge(to_id, from_id):
                edge_data = _graph.edges[to_id, from_id]
                direction = "backward"
            else:
                edge_data = {}
                direction = "forward"

            steps.append(PathStep(
                from_id=from_id,
                from_name=_get_node_name(from_id),
                relationship_type=edge_data.get("type", "related"),
                direction=direction,
                to_id=to_id,
                to_name=_get_node_name(to_id),
            ))
        result_paths.append(steps)

    return PathResponse(
        paths=result_paths,
        source_name=_get_node_name(req.source_id),
        target_name=_get_node_name(req.target_id),
    )


@app.post("/api/cascade")
def cascade_from_event(req: CascadeRequest) -> CascadeResponse:
    """BFS from an event node following outgoing edges to find all reachable nodes."""
    assert _graph is not None

    if req.event_node_id not in _graph:
        raise HTTPException(status_code=404, detail=f"Node '{req.event_node_id}' not found")

    event_data = _graph.nodes[req.event_node_id]
    event_name = event_data.get("name", req.event_node_id)

    # BFS following outgoing edges
    visited: set[str] = {req.event_node_id}
    steps: list[CascadeStep] = [
        CascadeStep(
            node_id=req.event_node_id,
            node_name=event_name,
            node_type=event_data.get("type", "Unknown"),
            depth=0,
            parent_node_id=None,
            edge_type="",
        )
    ]
    edge_keys: list[str] = []
    frontier = [(req.event_node_id, 0)]

    while frontier:
        current_id, depth = frontier.pop(0)
        if depth >= req.max_depth:
            continue

        for _, target, edge_data in _graph.out_edges(current_id, data=True):
            if target not in visited:
                visited.add(target)
                target_data = _graph.nodes[target]
                steps.append(CascadeStep(
                    node_id=target,
                    node_name=target_data.get("name", target),
                    node_type=target_data.get("type", "Unknown"),
                    depth=depth + 1,
                    parent_node_id=current_id,
                    edge_type=edge_data.get("type", ""),
                ))
                edge_keys.append(f"{current_id}->{target}")
                frontier.append((target, depth + 1))

    return CascadeResponse(
        event_name=event_name,
        steps=steps,
        node_ids=list(visited),
        edge_keys=edge_keys,
    )


@app.post("/api/agent/ask")
async def agent_ask(req: AgentQuestion) -> AgentAnswer:
    """Send a question to the reasoning agent."""
    assert _graph is not None

    response = await run_in_threadpool(ask, req.question, _graph, _client)

    # Resolve referenced entity IDs to summaries
    referenced = []
    for eid in response.referenced_entities:
        if _graph and eid in _graph:
            data = _graph.nodes[eid]
            referenced.append(EntitySummary(
                id=eid,
                type=data.get("type", ""),
                name=data.get("name", eid),
                description=data.get("description", ""),
            ))

    return AgentAnswer(
        answer=response.answer,
        referenced_entities=referenced,
        reasoning_path=response.reasoning_path,
    )


# --- Static File Serving ---


# Static file serving for the React SPA
# Note: must come after all /api routes since mount() takes priority
if FRONTEND_DIR.exists():
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA files or fall back to index.html for client routing."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file() and ".." not in full_path:
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# --- CLI Entry Point ---


def _load_graph(args: argparse.Namespace) -> OntologyGraph:
    """Load an OntologyGraph from CLI arguments."""
    if args.latest:
        from src.results import load_latest_ontology
        print("Loading latest pipeline run...")
        return load_latest_ontology()

    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"Error: File not found: {graph_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading graph from {graph_path}...")
    data = json.loads(graph_path.read_text(encoding="utf-8"))

    # Handle both OntologyGraph format and raw extractions format
    if isinstance(data, dict) and "entities" in data:
        try:
            return OntologyGraph(**data)
        except (ValueError, Exception) as e:
            # Fall back to entity-by-entity validation for legacy ontology files
            # with old entity types that don't match the current schema
            print(f"Strict load failed ({e}), falling back to entity-level validation...")
            from src.models import Relationship, ExtractionMetadata
            from src.schemas import validate_entity
            entities = []
            relationships = []
            for e_data in data.get("entities", []):
                if "attributes" in e_data and isinstance(e_data["attributes"], dict):
                    attrs = e_data.pop("attributes")
                    for k, v in attrs.items():
                        if k not in e_data:
                            e_data[k] = v
                entity, _ = validate_entity(e_data)
                if entity is not None:
                    entities.append(entity)
            for r in data.get("relationships", []):
                relationships.append(Relationship(**r))
            return OntologyGraph(
                entities=entities,
                relationships=relationships,
                source_document=data.get("source_document", str(graph_path)),
                source_sections=[],
                extraction_metadata=ExtractionMetadata(
                    section_count=0,
                    final_entity_count=len(entities),
                    final_relationship_count=len(relationships),
                ),
            )
    elif isinstance(data, list):
        # Extractions format — flatten entities and relationships
        from src.models import Relationship, ExtractionMetadata
        from src.schemas import validate_entity
        entities = []
        relationships = []
        for section in data:
            for e in section.get("entities", []):
                # Flatten legacy attributes dict
                if "attributes" in e and isinstance(e["attributes"], dict):
                    attrs = e.pop("attributes")
                    for k, v in attrs.items():
                        if k not in e:
                            e[k] = v
                entity, _ = validate_entity(e)
                if entity is not None:
                    entities.append(entity)
            for r in section.get("relationships", []):
                relationships.append(Relationship(**r))
        return OntologyGraph(
            entities=entities,
            relationships=relationships,
            source_document=str(graph_path),
            extraction_metadata=ExtractionMetadata(
                section_count=len(data),
                final_entity_count=len(entities),
                final_relationship_count=len(relationships),
            ),
        )
    else:
        print(f"Error: Unrecognized graph format in {graph_path}", file=sys.stderr)
        sys.exit(1)


def main():
    global _ontology, _graph, _client

    parser = argparse.ArgumentParser(description="Shogun Ontology Explorer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--graph", type=str, help="Path to ontology.json or extractions.json")
    group.add_argument("--latest", action="store_true", help="Load the latest pipeline run")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    args = parser.parse_args()

    # Load graph
    _ontology = _load_graph(args)
    _graph = build_graph(_ontology)
    _client = Anthropic()

    entity_count = _graph.number_of_nodes()
    edge_count = _graph.number_of_edges()
    print(f"Graph loaded: {entity_count} entities, {edge_count} relationships")

    # Check frontend build
    if not FRONTEND_DIR.exists():
        print(f"\nWarning: Frontend not built. Run: cd frontend && npm install && npm run build")
        print(f"API will still be available at http://localhost:{args.port}/api/\n")

    # Auto-open browser
    if not args.no_browser:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()

    # Start server
    import uvicorn
    print(f"\nStarting server at http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
