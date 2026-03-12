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
    GraphListItem,
    GraphNode,
    GraphStats,
    LoadGraphRequest,
    PathRequest,
    PathResponse,
    PathStep,
    RelationshipDetail,
    Scenario,
    ScenariosResponse,
    WalkthroughRequest,
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

# Directory for preloaded graphs (single source of truth for the dropdown)
FINAL_GRAPHS_DIR = Path(__file__).parent.parent / "data" / "final_graphs"

# Module-level state (set during startup)
_ontology: OntologyGraph | None = None
_graph: nx.DiGraph | None = None
_client: Anthropic | None = None
_metrics: dict[str, dict[str, float]] = {}
_current_graph_filename: str = ""


def _compute_metrics(g: nx.DiGraph) -> dict[str, dict[str, float]]:
    """Compute centrality metrics for all nodes.

    Returns dict mapping node_id -> {importance, betweenness, pagerank, degree_centrality}.
    """
    if g.number_of_nodes() == 0:
        return {}

    # Compute raw metrics
    undirected = g.to_undirected()
    betweenness_raw = nx.betweenness_centrality(undirected)
    pagerank_raw = nx.pagerank(g, max_iter=200)
    degree_raw = nx.degree_centrality(g)

    def _min_max_normalize(values: dict[str, float]) -> dict[str, float]:
        vals = list(values.values())
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12:
            return {k: 0.5 for k in values}
        return {k: (v - lo) / (hi - lo) for k, v in values.items()}

    betweenness_norm = _min_max_normalize(betweenness_raw)
    pagerank_norm = _min_max_normalize(pagerank_raw)
    degree_norm = _min_max_normalize(degree_raw)

    result: dict[str, dict[str, float]] = {}
    for node_id in g.nodes:
        b = betweenness_norm[node_id]
        p = pagerank_norm[node_id]
        d = degree_norm[node_id]
        importance = 0.40 * b + 0.35 * p + 0.25 * d
        result[node_id] = {
            "importance": round(importance, 4),
            "betweenness": round(b, 4),
            "pagerank": round(p, 4),
            "degree_centrality": round(d, 4),
        }

    return result

app = FastAPI(title="Shogun Ontology Explorer")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


def _get_color(entity_type: str) -> str:
    return TYPE_COLORS.get(entity_type, DEFAULT_COLOR)


def _get_node_name(node_id: str) -> str:
    if _graph and node_id in _graph:
        return _graph.nodes[node_id].get("name", node_id)
    return node_id


def _load_and_activate_graph(graph_path: Path, filename: str = "") -> OntologyGraph:
    """Load an ontology JSON file and activate it as the current graph."""
    global _ontology, _graph, _metrics, _current_graph_filename

    data = json.loads(graph_path.read_text(encoding="utf-8"))

    # Handle both OntologyGraph format and raw extractions format
    if isinstance(data, dict) and "entities" in data:
        try:
            ontology = OntologyGraph(**data)
        except (ValueError, Exception):
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
            ontology = OntologyGraph(
                graph_title=data.get("graph_title", ""),
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
    else:
        raise ValueError(f"Unrecognized graph format in {graph_path}")

    _ontology = ontology
    _graph = build_graph(_ontology)
    _metrics = _compute_metrics(_graph)
    _current_graph_filename = filename or graph_path.name

    return ontology


# --- API Endpoints ---


@app.get("/api/graphs")
def list_graphs() -> list[GraphListItem]:
    """List all available graphs from data/final_graphs/."""
    if not FINAL_GRAPHS_DIR.exists():
        return []

    items = []
    for f in sorted(FINAL_GRAPHS_DIR.glob("*.json")):
        if f.name.endswith(".scenarios.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            title = data.get("graph_title", "") or f.stem
            entities = data.get("entities", data.get("nodes", []))
            relationships = data.get("relationships", [])
            items.append(GraphListItem(
                filename=f.name,
                graph_title=title,
                entity_count=len(entities),
                relationship_count=len(relationships),
            ))
        except Exception:
            continue

    return items


@app.post("/api/graphs/load")
def load_graph_endpoint(req: LoadGraphRequest) -> GraphStats:
    """Switch the active graph to a different file from data/final_graphs/."""
    if not FINAL_GRAPHS_DIR.exists():
        raise HTTPException(status_code=404, detail="final_graphs directory not found")

    graph_path = FINAL_GRAPHS_DIR / req.filename
    if not graph_path.exists() or ".." in req.filename:
        raise HTTPException(status_code=404, detail=f"Graph file '{req.filename}' not found")

    try:
        _load_and_activate_graph(graph_path, req.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load graph: {e}")

    return get_graph_stats()


@app.get("/api/graph")
def get_graph() -> GraphData:
    """Full graph data for vis-network rendering."""
    assert _graph is not None

    nodes = []
    for node_id, data in _graph.nodes(data=True):
        entity_type = data.get("type", "Unknown")
        m = _metrics.get(node_id, {})
        nodes.append(GraphNode(
            id=node_id,
            type=entity_type,
            name=data.get("name", node_id),
            description=data.get("description", ""),
            degree=_graph.degree(node_id),
            color=_get_color(entity_type),
            level=TYPE_LEVELS.get(entity_type, 5),
            group=TYPE_GROUP_MAP.get(entity_type, ""),
            importance=m.get("importance", 0.0),
            betweenness=m.get("betweenness", 0.0),
            pagerank=m.get("pagerank", 0.0),
            degree_centrality=m.get("degree_centrality", 0.0),
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
        graph_title=_ontology.graph_title if _ontology else "",
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


@app.get("/api/scenarios")
def get_scenarios() -> ScenariosResponse:
    """Load scenario sidecar JSON for the current graph."""
    if not _current_graph_filename:
        return ScenariosResponse(scenarios=[])

    sidecar_name = _current_graph_filename.replace(".json", ".scenarios.json")
    sidecar_path = FINAL_GRAPHS_DIR / sidecar_name
    if not sidecar_path.exists():
        return ScenariosResponse(scenarios=[])

    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        return ScenariosResponse(**data)
    except Exception:
        return ScenariosResponse(scenarios=[])


@app.post("/api/agent/walkthrough")
async def agent_walkthrough(req: WalkthroughRequest) -> Scenario:
    """Run the agent with full tool tracing and return a Scenario for step-through."""
    assert _graph is not None

    from src.agent import run_walkthrough

    result = await run_in_threadpool(run_walkthrough, req.prompt, _graph, _client)
    return Scenario(**result)


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


def _load_graph_cli(args: argparse.Namespace) -> OntologyGraph:
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
    return _load_and_activate_graph(graph_path)


def main():
    global _ontology, _graph, _client, _metrics

    parser = argparse.ArgumentParser(description="Shogun Ontology Explorer")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--graph", type=str, help="Path to ontology.json or extractions.json")
    group.add_argument("--latest", action="store_true", help="Load the latest pipeline run")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    args = parser.parse_args()

    # Load graph: --graph or --latest take priority, else auto-load first from final_graphs/
    if args.graph or args.latest:
        _load_graph_cli(args)
    elif FINAL_GRAPHS_DIR.exists() and list(FINAL_GRAPHS_DIR.glob("*.json")):
        graph_files = sorted((f for f in FINAL_GRAPHS_DIR.glob("*.json") if not f.name.endswith(".scenarios.json")), reverse=True)
        if not graph_files:
            print("Error: No graph files found in data/final_graphs/.", file=sys.stderr)
            sys.exit(1)
        first_graph = graph_files[0]
        print(f"Auto-loading from final_graphs: {first_graph.name}")
        _load_and_activate_graph(first_graph)
    else:
        print("Error: No --graph, --latest, or data/final_graphs/ graphs found.", file=sys.stderr)
        sys.exit(1)

    _client = Anthropic()

    assert _graph is not None
    entity_count = _graph.number_of_nodes()
    edge_count = _graph.number_of_edges()
    title = _ontology.graph_title if _ontology and _ontology.graph_title else _current_graph_filename
    print(f"Graph loaded: {title} — {entity_count} entities, {edge_count} relationships")

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
