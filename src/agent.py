from __future__ import annotations

import json
from typing import Any

import networkx as nx
from anthropic import Anthropic

from src.models import AgentResponse

SYSTEM_PROMPT = """\
You are a Duty of Care Compliance Agent. You answer questions about a corporate policy by querying a structured ontology graph.

You do NOT have the raw policy document. Your ONLY source of information is the graph, which you query using the tools provided. If you cannot find information in the graph, say so — do not guess or fabricate.

## How to Work

1. Start by understanding the question and what kind of entities/relationships would hold the answer.
2. Use your tools to explore the graph. Typical workflow:
   - Use `list_entity_types` to see what types of entities exist.
   - Use `find_entities` to find entities of a relevant type, or `search_entities` to search by keyword.
   - Use `get_entity` to read full details of a specific entity.
   - Use `get_neighbors` to follow relationships from an entity to connected entities.
   - Use `find_paths` to discover how two entities are connected.
3. Follow relationships to trace through the policy logic (e.g., a risk level "requires" an approval, which "escalates_to" a role).
4. Once you have gathered enough information, provide your answer.

## Answer Guidelines

- Cite specific entity names and relationships from the graph.
- Be precise about thresholds, values, and requirements.
- If the graph does not contain information to answer the question, say "The policy graph does not contain information about this."
- Do not invent information that is not in the graph.
"""

# Define the tools the agent can use to query the graph
TOOLS = [
    {
        "name": "list_entity_types",
        "description": "List all entity types in the graph and how many of each exist. Use this first to understand what kinds of information the graph contains.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "find_entities",
        "description": "Find all entities of a given type. Returns their IDs, names, and descriptions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "description": "The entity type to filter by (e.g., 'PolicyRule', 'RiskLevel', 'Role')",
                },
            },
            "required": ["entity_type"],
        },
    },
    {
        "name": "search_entities",
        "description": "Search for entities by keyword across names, descriptions, and attributes. Use this when you don't know the exact entity type or want to find something by content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Keyword to search for (case-insensitive)",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_entity",
        "description": "Get full details of a specific entity: its type, name, description, all attributes, and all relationships (incoming and outgoing).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The ID of the entity to retrieve",
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_neighbors",
        "description": "Get all entities connected to a given entity within a specified number of hops. Shows the relationship types and directions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The ID of the starting entity",
                },
                "depth": {
                    "type": "integer",
                    "description": "How many hops to traverse (1 = direct neighbors, 2 = neighbors of neighbors). Default 1.",
                    "default": 1,
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "find_paths",
        "description": "Find all paths between two entities in the graph. Shows the chain of relationships connecting them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "The ID of the starting entity",
                },
                "target_id": {
                    "type": "string",
                    "description": "The ID of the target entity",
                },
            },
            "required": ["source_id", "target_id"],
        },
    },
    {
        "name": "get_graph_summary",
        "description": "Get a high-level summary of the entire graph: total nodes, edges, entity types, and relationship types. Use this to orient yourself.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _execute_tool(tool_name: str, tool_input: dict, g: nx.DiGraph) -> str:
    """Execute a graph query tool and return the result as a string."""

    if tool_name == "list_entity_types":
        type_counts: dict[str, int] = {}
        for _, data in g.nodes(data=True):
            t = data.get("type", "Unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        lines = [f"- {t}: {count} entities" for t, count in sorted(type_counts.items(), key=lambda x: -x[1])]
        return "\n".join(lines) if lines else "Graph is empty."

    elif tool_name == "find_entities":
        entity_type = tool_input["entity_type"]
        results = []
        for node_id, data in g.nodes(data=True):
            if data.get("type", "").lower() == entity_type.lower():
                results.append(f"- {node_id}: {data.get('name', '?')} — {data.get('description', '')}")
        return "\n".join(results) if results else f"No entities of type '{entity_type}' found."

    elif tool_name == "search_entities":
        keyword = tool_input["keyword"].lower()
        results = []
        for node_id, data in g.nodes(data=True):
            searchable = f"{node_id} {data.get('name', '')} {data.get('description', '')} {' '.join(str(v) for v in data.values())}".lower()
            if keyword in searchable:
                results.append(f"- {node_id} [{data.get('type', '?')}]: {data.get('name', '?')} — {data.get('description', '')}")
        return "\n".join(results) if results else f"No entities matching '{tool_input['keyword']}' found."

    elif tool_name == "get_entity":
        entity_id = tool_input["entity_id"]
        if entity_id not in g:
            return f"Entity '{entity_id}' not found in graph."
        data = dict(g.nodes[entity_id])
        # Build full entity view
        lines = [
            f"ID: {entity_id}",
            f"Type: {data.get('type', '?')}",
            f"Name: {data.get('name', '?')}",
            f"Description: {data.get('description', '')}",
        ]
        attrs = {k: v for k, v in data.items() if k not in ("type", "name", "description")}
        if attrs:
            lines.append("Attributes:")
            for k, v in attrs.items():
                lines.append(f"  {k}: {v}")

        # Outgoing relationships
        out_edges = list(g.out_edges(entity_id, data=True))
        if out_edges:
            lines.append("Outgoing relationships:")
            for _, tgt, edata in out_edges:
                tgt_name = g.nodes[tgt].get("name", tgt)
                lines.append(f"  --[{edata.get('type', '?')}]--> {tgt_name} ({tgt}): {edata.get('description', '')}")

        # Incoming relationships
        in_edges = list(g.in_edges(entity_id, data=True))
        if in_edges:
            lines.append("Incoming relationships:")
            for src, _, edata in in_edges:
                src_name = g.nodes[src].get("name", src)
                lines.append(f"  <--[{edata.get('type', '?')}]-- {src_name} ({src}): {edata.get('description', '')}")

        return "\n".join(lines)

    elif tool_name == "get_neighbors":
        entity_id = tool_input["entity_id"]
        depth = tool_input.get("depth", 1)
        if entity_id not in g:
            return f"Entity '{entity_id}' not found in graph."

        # BFS to find neighbors
        nodes = {entity_id}
        frontier = {entity_id}
        for _ in range(depth):
            next_frontier = set()
            for n in frontier:
                next_frontier.update(g.successors(n))
                next_frontier.update(g.predecessors(n))
            nodes.update(next_frontier)
            frontier = next_frontier

        # Build result — show all nodes and edges in the subgraph
        subgraph = g.subgraph(nodes)
        lines = [f"Neighborhood of '{entity_id}' (depth={depth}): {len(nodes)} entities\n"]
        lines.append("Entities:")
        for nid in nodes:
            ndata = g.nodes[nid]
            marker = " (start)" if nid == entity_id else ""
            lines.append(f"  - {nid} [{ndata.get('type', '?')}]: {ndata.get('name', '?')}{marker}")

        lines.append("\nRelationships:")
        for src, tgt, edata in subgraph.edges(data=True):
            src_name = g.nodes[src].get("name", src)
            tgt_name = g.nodes[tgt].get("name", tgt)
            lines.append(f"  {src_name} --[{edata.get('type', '?')}]--> {tgt_name}")

        return "\n".join(lines)

    elif tool_name == "find_paths":
        source_id = tool_input["source_id"]
        target_id = tool_input["target_id"]
        if source_id not in g:
            return f"Source entity '{source_id}' not found."
        if target_id not in g:
            return f"Target entity '{target_id}' not found."

        # Find paths in both directions (treating as undirected for path finding)
        undirected = g.to_undirected()
        try:
            paths = list(nx.all_simple_paths(undirected, source_id, target_id, cutoff=5))
        except nx.NetworkXNoPath:
            return f"No path found between '{source_id}' and '{target_id}'."

        if not paths:
            return f"No path found between '{source_id}' and '{target_id}'."

        lines = [f"Found {len(paths)} path(s):\n"]
        for i, path in enumerate(paths[:5], 1):  # Limit to 5 paths
            lines.append(f"Path {i}:")
            for j in range(len(path) - 1):
                src, tgt = path[j], path[j + 1]
                src_name = g.nodes[src].get("name", src)
                tgt_name = g.nodes[tgt].get("name", tgt)
                # Check edge direction
                if g.has_edge(src, tgt):
                    edata = g.edges[src, tgt]
                    lines.append(f"  {src_name} --[{edata.get('type', '?')}]--> {tgt_name}")
                elif g.has_edge(tgt, src):
                    edata = g.edges[tgt, src]
                    lines.append(f"  {src_name} <--[{edata.get('type', '?')}]-- {tgt_name}")
                else:
                    lines.append(f"  {src_name} --- {tgt_name}")
            lines.append("")

        return "\n".join(lines)

    elif tool_name == "get_graph_summary":
        type_counts: dict[str, int] = {}
        for _, data in g.nodes(data=True):
            t = data.get("type", "Unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        rel_counts: dict[str, int] = {}
        for _, _, data in g.edges(data=True):
            t = data.get("type", "Unknown")
            rel_counts[t] = rel_counts.get(t, 0) + 1

        lines = [
            f"Total entities: {g.number_of_nodes()}",
            f"Total relationships: {g.number_of_edges()}",
            "",
            "Entity types:",
        ]
        for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {count}")
        lines.append("")
        lines.append("Relationship types:")
        for t, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {count}")

        return "\n".join(lines)

    return f"Unknown tool: {tool_name}"


def ask(question: str, g: nx.DiGraph, client: Anthropic | None = None, max_turns: int = 15) -> AgentResponse:
    """Ask a question by letting the agent iteratively query the graph via tool use."""
    if client is None:
        client = Anthropic()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": question},
    ]

    referenced_entities: set[str] = set()
    turn_count = 0

    while turn_count < max_turns:
        turn_count += 1

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Check if the model wants to use tools
        if response.stop_reason == "tool_use":
            # Process all tool calls in this response
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    # Track entity IDs that are queried
                    if "entity_id" in tool_input:
                        referenced_entities.add(tool_input["entity_id"])
                    if "source_id" in tool_input:
                        referenced_entities.add(tool_input["source_id"])
                    if "target_id" in tool_input:
                        referenced_entities.add(tool_input["target_id"])

                    result = _execute_tool(tool_name, tool_input, g)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Model is done — extract the final text answer
            answer_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    answer_text += block.text

            return AgentResponse(
                answer=answer_text,
                referenced_entities=sorted(referenced_entities),
                reasoning_path=f"Completed in {turn_count} turns",
            )

    # If we hit max_turns, return whatever we have
    return AgentResponse(
        answer="Agent reached maximum number of turns without producing a final answer.",
        referenced_entities=sorted(referenced_entities),
        reasoning_path=f"Hit max_turns ({max_turns})",
    )
