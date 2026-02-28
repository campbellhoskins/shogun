from __future__ import annotations

from pathlib import Path

import networkx as nx
from pyvis.network import Network

# Color palette by entity type
TYPE_COLORS = {
    "PolicyRule": "#4A90D9",
    "RiskLevel": "#E74C3C",
    "ApprovalRequirement": "#F39C12",
    "InsuranceRequirement": "#2ECC71",
    "VaccinationRequirement": "#9B59B6",
    "Destination": "#1ABC9C",
    "Role": "#E67E22",
    "Person": "#D35400",
    "Vendor": "#3498DB",
    "Procedure": "#8E44AD",
    "IncidentCategory": "#C0392B",
    "CommunicationRequirement": "#16A085",
    "Equipment": "#7F8C8D",
}

DEFAULT_COLOR = "#95A5A6"


def generate_visualization(g: nx.DiGraph, output_path: str | Path = "graph.html") -> str:
    """Generate an interactive Pyvis HTML visualization of the graph."""
    net = Network(
        height="800px",
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
    )

    # Physics settings for a good layout
    net.set_options("""
    {
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.4
            },
            "solver": "forceAtlas2Based",
            "stabilization": {
                "iterations": 200
            }
        },
        "nodes": {
            "font": {
                "size": 14,
                "face": "Inter, system-ui, sans-serif"
            },
            "borderWidth": 2,
            "borderWidthSelected": 4
        },
        "edges": {
            "arrows": {
                "to": {"enabled": true, "scaleFactor": 0.8}
            },
            "color": {
                "color": "#555577",
                "highlight": "#FFD700"
            },
            "font": {
                "size": 10,
                "color": "#888888",
                "face": "Inter, system-ui, sans-serif",
                "align": "middle"
            },
            "smooth": {
                "type": "cubicBezier",
                "roundness": 0.3
            }
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
        }
    }
    """)

    # Add nodes
    for node_id, data in g.nodes(data=True):
        entity_type = data.get("type", "Unknown")
        color = TYPE_COLORS.get(entity_type, DEFAULT_COLOR)
        name = data.get("name", node_id)
        description = data.get("description", "")

        # Build tooltip
        skip_keys = {"type", "name", "description", "source_text", "source_section", "source_offset"}
        attrs = {k: v for k, v in data.items() if k not in skip_keys}
        attr_lines = "".join(f"<br><b>{k}:</b> {v}" for k, v in attrs.items())

        # Add source text info
        source_text = data.get("source_text", "")
        source_section = data.get("source_section", "")
        source_info = ""
        if source_text:
            truncated = source_text[:200] + "..." if len(source_text) > 200 else source_text
            source_info = f"<br><br><b>Source (Section {source_section}):</b><br><i>{truncated}</i>"

        title = f"<b>{name}</b><br><i>{entity_type}</i><br>{description}{attr_lines}{source_info}"

        # Scale node size by degree
        degree = g.degree(node_id)
        size = max(15, min(40, 15 + degree * 3))

        net.add_node(
            node_id,
            label=name,
            title=title,
            color=color,
            size=size,
            shape="dot",
        )

    # Add edges
    for src, tgt, data in g.edges(data=True):
        rel_type = data.get("type", "")
        description = data.get("description", "")
        title = f"<b>{rel_type}</b><br>{description}"

        net.add_edge(src, tgt, label=rel_type, title=title)

    output_path = Path(output_path)
    net.save_graph(str(output_path))

    # Read and return the HTML content
    return output_path.read_text(encoding="utf-8")
