from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
TEST_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")

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
                    "description": "The entity type to filter by (e.g., 'Policy', 'RiskLevel', 'Role', 'Requirement')",
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
    {
        "name": "traverse_workflow",
        "description": "Follow the FOLLOWED_BY chain from a starting entity to enumerate an ordered procedure. Returns all steps in sequence. Use this to walk through multi-step workflows like welfare check outreach or escalation procedures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_entity_id": {
                    "type": "string",
                    "description": "The ID of the first step in the procedure",
                },
            },
            "required": ["start_entity_id"],
        },
    },
    {
        "name": "find_by_attribute",
        "description": "Find entities that have a specific attribute value. Supports exact match and substring match on string attributes. Use this to find entities by operational criteria like severity level, escalation condition, or roster position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "attribute_name": {
                    "type": "string",
                    "description": "The attribute name to search (e.g., 'escalation_severity_levels', 'activation_severity_threshold', 'roster_position')",
                },
                "attribute_value": {
                    "type": "string",
                    "description": "The value to match (case-insensitive, substring match for strings)",
                },
            },
            "required": ["attribute_name", "attribute_value"],
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

    elif tool_name == "traverse_workflow":
        start_id = tool_input["start_entity_id"]
        if start_id not in g:
            return f"Entity '{start_id}' not found in graph."

        # Follow FOLLOWED_BY chain
        steps = [start_id]
        current = start_id
        visited = {start_id}
        while True:
            next_step = None
            for _, tgt, edata in g.out_edges(current, data=True):
                if edata.get("type") == "FOLLOWED_BY" and tgt not in visited:
                    next_step = tgt
                    break
            if next_step is None:
                break
            steps.append(next_step)
            visited.add(next_step)
            current = next_step

        if len(steps) == 1:
            return f"No FOLLOWED_BY chain found from '{start_id}'. This entity may not be the start of a workflow."

        lines = [f"Workflow sequence ({len(steps)} steps):\n"]
        for i, step_id in enumerate(steps, 1):
            data = g.nodes[step_id]
            name = data.get("name", step_id)
            etype = data.get("type", "?")
            lines.append(f"  Step {i}: {name} [{etype}] ({step_id})")
            # Show key typed attributes
            for attr in ("tmc_action", "action_time_target", "channel", "channel_priority_order",
                         "activation_severity_threshold", "time_constraint"):
                val = data.get(attr)
                if val not in (None, "", []):
                    lines.append(f"          {attr}: {val}")
        return "\n".join(lines)

    elif tool_name == "find_by_attribute":
        attr_name = tool_input["attribute_name"]
        attr_value = tool_input["attribute_value"].lower()
        results = []
        for node_id, data in g.nodes(data=True):
            val = data.get(attr_name)
            if val is None:
                continue
            # Match: substring for strings, membership for lists, exact for others
            matched = False
            if isinstance(val, str) and attr_value in val.lower():
                matched = True
            elif isinstance(val, list) and any(attr_value in str(v).lower() for v in val):
                matched = True
            elif str(val).lower() == attr_value:
                matched = True
            if matched:
                results.append(
                    f"- {node_id} [{data.get('type', '?')}]: {data.get('name', '?')} "
                    f"({attr_name}={val})"
                )
        return "\n".join(results) if results else f"No entities with {attr_name} matching '{tool_input['attribute_value']}'."

    return f"Unknown tool: {tool_name}"


def ask(
    question: str,
    g: nx.DiGraph,
    client: Anthropic | None = None,
    max_turns: int = 15,
    verbose: bool = True,
) -> AgentResponse:
    """Ask a question by letting the agent iteratively query the graph via tool use.

    When verbose=True (default), prints every tool call, result, and reasoning
    step to the console so the user can follow the agent's traversal live.
    """
    if client is None:
        client = Anthropic()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": question},
    ]

    referenced_entities: set[str] = set()
    turn_count = 0

    if verbose:
        print(f"\n{'─' * 60}")
        print(f"  Question: {question}")
        print(f"{'─' * 60}")

    while turn_count < max_turns:
        turn_count += 1

        response = client.messages.create(
            model=TEST_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Check if the model wants to use tools
        if response.stop_reason == "tool_use":
            # Print any reasoning text the model produced before tool calls
            if verbose:
                for block in response.content:
                    if hasattr(block, "text") and block.text.strip():
                        print(f"\n  Thinking: {block.text.strip()}")

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
                    if "start_entity_id" in tool_input:
                        referenced_entities.add(tool_input["start_entity_id"])

                    # Print the tool call
                    if verbose:
                        input_str = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
                        print(f"\n  [{turn_count}] {tool_name}({input_str})")

                    result = _execute_tool(tool_name, tool_input, g)

                    # Print the result (truncate long output)
                    if verbose:
                        result_lines = result.split("\n")
                        if len(result_lines) > 20:
                            for line in result_lines[:18]:
                                print(f"      {line}")
                            print(f"      ... ({len(result_lines) - 18} more lines)")
                        else:
                            for line in result_lines:
                                print(f"      {line}")

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

            if verbose:
                print(f"\n  Turns used: {turn_count}")
                print(f"  Entities queried: {', '.join(sorted(referenced_entities)) if referenced_entities else 'none'}")
                print(f"{'─' * 60}")

            return AgentResponse(
                answer=answer_text,
                referenced_entities=sorted(referenced_entities),
                reasoning_path=f"Completed in {turn_count} turns",
            )

    # If we hit max_turns, return whatever we have
    if verbose:
        print(f"\n  Hit max turns ({max_turns})")
        print(f"{'─' * 60}")

    return AgentResponse(
        answer="Agent reached maximum number of turns without producing a final answer.",
        referenced_entities=sorted(referenced_entities),
        reasoning_path=f"Hit max_turns ({max_turns})",
    )


# --- Live Walkthrough ---


@dataclass
class ToolCallRecord:
    """Record of a single tool call during agent execution."""
    tool_name: str
    tool_input: dict[str, Any]
    result: str
    entity_ids: list[str] = field(default_factory=list)


def _compute_highlights_for_tool(
    tool_name: str, tool_input: dict[str, Any], result: str, g: nx.DiGraph
) -> tuple[list[str], list[str], str | None]:
    """Compute highlight nodes, edges, and focus node for a tool call."""
    nodes: list[str] = []
    edges: list[str] = []
    focus: str | None = None

    if tool_name == "get_entity":
        eid = tool_input.get("entity_id", "")
        if eid in g:
            focus = eid
            nodes.append(eid)
            for _, tgt in g.out_edges(eid):
                nodes.append(tgt)
                edges.append(f"{eid}->{tgt}")
            for src, _ in g.in_edges(eid):
                nodes.append(src)
                edges.append(f"{src}->{eid}")

    elif tool_name == "get_neighbors":
        eid = tool_input.get("entity_id", "")
        depth = tool_input.get("depth", 1)
        if eid in g:
            focus = eid
            visited = {eid}
            frontier = {eid}
            for _ in range(depth):
                next_f: set[str] = set()
                for n in frontier:
                    next_f.update(g.successors(n))
                    next_f.update(g.predecessors(n))
                visited.update(next_f)
                frontier = next_f
            nodes = list(visited)
            for src, tgt in g.subgraph(visited).edges():
                edges.append(f"{src}->{tgt}")

    elif tool_name == "find_paths":
        src_id = tool_input.get("source_id", "")
        tgt_id = tool_input.get("target_id", "")
        if src_id in g:
            nodes.append(src_id)
            focus = src_id
        if tgt_id in g:
            nodes.append(tgt_id)
        # Extract entity IDs from result lines (format: "entity_name (entity_id)")
        for match in re.finditer(r"\(([a-z_]+)\)", result):
            eid = match.group(1)
            if eid in g and eid not in nodes:
                nodes.append(eid)

    elif tool_name in ("search_entities", "find_entities", "find_by_attribute"):
        # Result lines: "- entity_id [Type]: Name — Description"  or  "- entity_id: Name — Desc"
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                # Extract ID (first word after "- ")
                eid = line[2:].split(":")[0].split("[")[0].split(" ")[0].strip()
                if eid in g:
                    nodes.append(eid)
                    if focus is None:
                        focus = eid

    elif tool_name == "traverse_workflow":
        start_id = tool_input.get("start_entity_id", "")
        if start_id in g:
            focus = start_id
            # Follow FOLLOWED_BY chain to get all workflow nodes
            current = start_id
            visited = {start_id}
            while True:
                next_step = None
                for _, tgt, edata in g.out_edges(current, data=True):
                    if edata.get("type") == "FOLLOWED_BY" and tgt not in visited:
                        next_step = tgt
                        break
                if next_step is None:
                    break
                edges.append(f"{current}->{next_step}")
                visited.add(next_step)
                current = next_step
            nodes = list(visited)

    return nodes, edges, focus


def _make_step_title(tool_name: str, tool_input: dict[str, Any], g: nx.DiGraph) -> str:
    """Generate a human-readable step title from a tool call."""
    if tool_name == "get_entity":
        eid = tool_input.get("entity_id", "?")
        name = g.nodes[eid].get("name", eid) if eid in g else eid
        return f"Inspect: {name}"
    elif tool_name == "get_neighbors":
        eid = tool_input.get("entity_id", "?")
        name = g.nodes[eid].get("name", eid) if eid in g else eid
        depth = tool_input.get("depth", 1)
        return f"Explore neighborhood: {name} (depth {depth})"
    elif tool_name == "search_entities":
        return f"Search: \"{tool_input.get('keyword', '?')}\""
    elif tool_name == "find_entities":
        return f"Find all: {tool_input.get('entity_type', '?')}"
    elif tool_name == "find_paths":
        src = tool_input.get("source_id", "?")
        tgt = tool_input.get("target_id", "?")
        src_name = g.nodes[src].get("name", src) if src in g else src
        tgt_name = g.nodes[tgt].get("name", tgt) if tgt in g else tgt
        return f"Find paths: {src_name} \u2192 {tgt_name}"
    elif tool_name == "list_entity_types":
        return "Survey entity types"
    elif tool_name == "get_graph_summary":
        return "Graph overview"
    elif tool_name == "traverse_workflow":
        eid = tool_input.get("start_entity_id", "?")
        name = g.nodes[eid].get("name", eid) if eid in g else eid
        return f"Traverse workflow from: {name}"
    elif tool_name == "find_by_attribute":
        attr = tool_input.get("attribute_name", "?")
        val = tool_input.get("attribute_value", "?")
        return f"Find by {attr} = \"{val}\""
    return tool_name


def _tool_call_to_log_lines(
    tool_name: str, tool_input: dict[str, Any], result: str, g: nx.DiGraph
) -> list[dict[str, str]]:
    """Convert a tool call + result into color-coded log lines."""
    lines: list[dict[str, str]] = []

    # Tool invocation line
    if tool_name == "get_entity":
        eid = tool_input["entity_id"]
        lines.append({"type": "query", "text": f"> TOOL: get_entity(\"{eid}\")"})
        if eid in g:
            data = g.nodes[eid]
            lines.append({"type": "attr", "text": f"  Type: {data.get('type', '?')}"})
            lines.append({"type": "attr", "text": f"  Name: {data.get('name', '?')}"})
            desc = data.get("description", "")
            if desc:
                lines.append({"type": "dim", "text": f"  {desc[:120]}{'...' if len(desc) > 120 else ''}"})
            # Show relationships as traversals
            out = list(g.out_edges(eid, data=True))
            if out:
                for _, tgt, edata in out[:8]:
                    tgt_name = g.nodes[tgt].get("name", tgt)
                    lines.append({"type": "traverse", "text": f"  -[{edata.get('type', '?')}]-> {tgt_name}"})
                if len(out) > 8:
                    lines.append({"type": "dim", "text": f"  ... +{len(out) - 8} more outgoing"})
            in_ = list(g.in_edges(eid, data=True))
            if in_:
                for src, _, edata in in_[:6]:
                    src_name = g.nodes[src].get("name", src)
                    lines.append({"type": "traverse", "text": f"  <-[{edata.get('type', '?')}]- {src_name}"})
                if len(in_) > 6:
                    lines.append({"type": "dim", "text": f"  ... +{len(in_) - 6} more incoming"})
        else:
            lines.append({"type": "warning", "text": f"  Entity '{eid}' not found"})

    elif tool_name == "get_neighbors":
        eid = tool_input["entity_id"]
        depth = tool_input.get("depth", 1)
        lines.append({"type": "query", "text": f"> TOOL: get_neighbors(\"{eid}\", depth={depth})"})
        # Count entities from result
        entity_lines = [l for l in result.split("\n") if l.strip().startswith("- ")]
        rel_lines = [l for l in result.split("\n") if "--[" in l]
        lines.append({"type": "traverse", "text": f"  {len(entity_lines)} entities, {len(rel_lines)} relationships in neighborhood"})
        # Show a few relationships
        for rl in rel_lines[:6]:
            lines.append({"type": "traverse", "text": f"  {rl.strip()}"})
        if len(rel_lines) > 6:
            lines.append({"type": "dim", "text": f"  ... +{len(rel_lines) - 6} more relationships"})

    elif tool_name == "search_entities":
        kw = tool_input["keyword"]
        lines.append({"type": "query", "text": f"> TOOL: search_entities(\"{kw}\")"})
        found = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]
        for f in found[:5]:
            lines.append({"type": "attr", "text": f"  FOUND: {f[2:][:100]}"})
        if len(found) > 5:
            lines.append({"type": "dim", "text": f"  ... +{len(found) - 5} more results"})
        if not found:
            lines.append({"type": "warning", "text": f"  No results for \"{kw}\""})

    elif tool_name == "find_entities":
        etype = tool_input["entity_type"]
        lines.append({"type": "query", "text": f"> TOOL: find_entities(\"{etype}\")"})
        found = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]
        for f in found[:5]:
            lines.append({"type": "attr", "text": f"  {f[2:][:100]}"})
        if len(found) > 5:
            lines.append({"type": "dim", "text": f"  ... +{len(found) - 5} more"})
        if not found:
            lines.append({"type": "warning", "text": f"  No entities of type '{etype}'"})

    elif tool_name == "find_paths":
        src = tool_input["source_id"]
        tgt = tool_input["target_id"]
        lines.append({"type": "query", "text": f"> TOOL: find_paths(\"{src}\" -> \"{tgt}\")"})
        path_count = result.count("Path ")
        if path_count > 0:
            lines.append({"type": "traverse", "text": f"  Found {path_count} path(s)"})
            # Show path steps
            for line in result.split("\n"):
                line = line.strip()
                if "--[" in line or "<--[" in line:
                    lines.append({"type": "traverse", "text": f"  {line[:120]}"})
        else:
            lines.append({"type": "warning", "text": f"  No paths found"})

    elif tool_name == "list_entity_types":
        lines.append({"type": "query", "text": "> TOOL: list_entity_types()"})
        type_lines = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]
        for tl in type_lines[:8]:
            lines.append({"type": "attr", "text": f"  {tl[2:]}"})
        if len(type_lines) > 8:
            lines.append({"type": "dim", "text": f"  ... +{len(type_lines) - 8} more types"})

    elif tool_name == "get_graph_summary":
        lines.append({"type": "query", "text": "> TOOL: get_graph_summary()"})
        for line in result.split("\n")[:6]:
            if line.strip():
                lines.append({"type": "attr", "text": f"  {line.strip()}"})

    elif tool_name == "traverse_workflow":
        start_id = tool_input.get("start_entity_id", "?")
        lines.append({"type": "query", "text": f"> TOOL: traverse_workflow(\"{start_id}\")"})
        step_lines = [l for l in result.split("\n") if l.strip().startswith("Step ")]
        for sl in step_lines[:8]:
            lines.append({"type": "traverse", "text": f"  {sl.strip()}"})
        if len(step_lines) > 8:
            lines.append({"type": "dim", "text": f"  ... +{len(step_lines) - 8} more steps"})
        if not step_lines:
            lines.append({"type": "warning", "text": f"  No workflow chain found from '{start_id}'"})

    elif tool_name == "find_by_attribute":
        attr = tool_input.get("attribute_name", "?")
        val = tool_input.get("attribute_value", "?")
        lines.append({"type": "query", "text": f"> TOOL: find_by_attribute(\"{attr}\", \"{val}\")"})
        found = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]
        for f in found[:5]:
            lines.append({"type": "attr", "text": f"  FOUND: {f[2:][:100]}"})
        if len(found) > 5:
            lines.append({"type": "dim", "text": f"  ... +{len(found) - 5} more results"})
        if not found:
            lines.append({"type": "warning", "text": f"  No matches for {attr}=\"{val}\""})

    return lines


def run_walkthrough(
    prompt: str, g: nx.DiGraph, client: Anthropic | None = None, max_turns: int = 15
) -> dict:
    """Run the agent with full tool tracing and return a Scenario-shaped dict.

    The returned dict matches the Scenario model shape so the frontend can
    render it with the same step controls as scripted scenarios.
    """
    if client is None:
        client = Anthropic()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    trace: list[ToolCallRecord] = []
    referenced_entities: set[str] = set()
    turn_count = 0
    final_answer = ""

    while turn_count < max_turns:
        turn_count += 1

        response = client.messages.create(
            model=TEST_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    if "entity_id" in tool_input:
                        referenced_entities.add(tool_input["entity_id"])
                    if "source_id" in tool_input:
                        referenced_entities.add(tool_input["source_id"])
                    if "target_id" in tool_input:
                        referenced_entities.add(tool_input["target_id"])

                    result = _execute_tool(tool_name, tool_input, g)
                    trace.append(ToolCallRecord(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        result=result,
                        entity_ids=[eid for eid in referenced_entities],
                    ))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            for block in response.content:
                if hasattr(block, "text"):
                    final_answer += block.text
            break

    if not final_answer:
        final_answer = "Agent reached maximum turns without a final answer."

    # Convert trace into Scenario steps
    steps: list[dict] = []
    for record in trace:
        h_nodes, h_edges, focus = _compute_highlights_for_tool(
            record.tool_name, record.tool_input, record.result, g
        )
        log_lines = _tool_call_to_log_lines(
            record.tool_name, record.tool_input, record.result, g
        )
        steps.append({
            "title": _make_step_title(record.tool_name, record.tool_input, g),
            "description": f"Agent called {record.tool_name} to explore the graph.",
            "highlight_nodes": h_nodes,
            "highlight_edges": h_edges,
            "focus_node": focus,
            "log": log_lines,
        })

    # Final answer step
    answer_lines: list[dict[str, str]] = [
        {"type": "decision", "text": "> AGENT CONCLUSION:"},
    ]
    for line in final_answer.split("\n"):
        if line.strip():
            answer_lines.append({"type": "decision", "text": f"  {line.strip()}"})

    steps.append({
        "title": "Agent Conclusion",
        "description": "The agent has completed its graph traversal and reached a conclusion.",
        "highlight_nodes": [eid for eid in referenced_entities if eid in g],
        "highlight_edges": [],
        "focus_node": None,
        "log": answer_lines,
    })

    # Truncate prompt for scenario name
    name = prompt[:60] + ("..." if len(prompt) > 60 else "")

    return {
        "id": "live-walkthrough",
        "name": f"Live: {name}",
        "steps": steps,
    }
