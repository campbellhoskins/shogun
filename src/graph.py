from __future__ import annotations

import networkx as nx

from src.models import OntologyGraph
from src.schemas import get_typed_attributes


def build_graph(ontology: OntologyGraph) -> nx.DiGraph:
    """Build a NetworkX directed graph from an OntologyGraph."""
    g = nx.DiGraph()

    # Store source document and sections on the graph for agent access
    g.graph["source_document"] = ontology.source_document
    g.graph["source_sections"] = [s.model_dump() for s in ontology.source_sections]

    for entity in ontology.entities:
        # Stringify attribute values for NetworkX compatibility
        # Filter out keys that collide with our explicit node attributes
        reserved = {"type", "name", "description", "source_text", "source_section", "source_offset"}
        typed_attrs = get_typed_attributes(entity)
        attrs = {k: str(v) for k, v in typed_attrs.items() if k not in reserved}
        g.add_node(
            entity.id,
            type=entity.type,
            name=entity.name,
            description=entity.description,
            source_text=entity.source_anchor.source_text,
            source_section=entity.source_anchor.source_section,
            source_offset=entity.source_anchor.source_offset,
            **attrs,
        )

    for rel in ontology.relationships:
        # Only add edge if both nodes exist
        if g.has_node(rel.source_id) and g.has_node(rel.target_id):
            g.add_edge(
                rel.source_id,
                rel.target_id,
                type=rel.type,
                description=rel.description,
            )

    return g


def get_source_text(g: nx.DiGraph, entity_id: str) -> str:
    """Get the source document text that an entity was extracted from."""
    if entity_id not in g:
        return f"Entity '{entity_id}' not found."

    data = g.nodes[entity_id]
    source_text = data.get("source_text", "")
    source_section = data.get("source_section", "")

    if not source_text:
        return "No source text available for this entity."

    result = f"Source section: {source_section}\n"
    result += f'Verbatim source text: "{source_text}"'
    return result


def get_section_text(g: nx.DiGraph, section_number: str) -> str:
    """Get the full text of a document section."""
    sections = g.graph.get("source_sections", [])
    for section in sections:
        if section.get("section_number") == section_number:
            header = section.get("header", "")
            text = section.get("text", "")
            return f"Section {section_number}: {header}\n\n{text}"
    return f"Section '{section_number}' not found."


def serialize_graph(g: nx.DiGraph) -> str:
    """Serialize the full graph to a text representation for LLM context."""
    lines = ["=== ONTOLOGY GRAPH ===", "", "## Entities"]

    for node_id, data in g.nodes(data=True):
        attrs = {k: v for k, v in data.items() if k not in ("type", "name", "description")}
        attr_str = f" | Attributes: {attrs}" if attrs else ""
        lines.append(f"- [{data.get('type', '?')}] {data.get('name', node_id)} (id: {node_id}): {data.get('description', '')}{attr_str}")

    lines.append("")
    lines.append("## Relationships")

    for src, tgt, data in g.edges(data=True):
        src_name = g.nodes[src].get("name", src)
        tgt_name = g.nodes[tgt].get("name", tgt)
        lines.append(f"- {src_name} --[{data.get('type', '?')}]--> {tgt_name}: {data.get('description', '')}")

    return "\n".join(lines)


def query_neighbors(g: nx.DiGraph, node_id: str, depth: int = 1) -> nx.DiGraph:
    """Get a subgraph of nodes within `depth` hops of `node_id`."""
    if node_id not in g:
        return nx.DiGraph()

    nodes = {node_id}
    frontier = {node_id}

    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            next_frontier.update(g.successors(n))
            next_frontier.update(g.predecessors(n))
        nodes.update(next_frontier)
        frontier = next_frontier

    return g.subgraph(nodes).copy()


def query_by_type(g: nx.DiGraph, entity_type: str) -> list[str]:
    """Get all node IDs of a given entity type."""
    return [n for n, d in g.nodes(data=True) if d.get("type") == entity_type]
