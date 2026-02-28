"""Interactive testing harness for the ontology graph agent.

Shows every tool call, its input, and the result — so you can see exactly
how the agent traverses the graph to reach its answer.

Usage:
    uv run python -m src.test_agent --graph <graph_id>

Example:
    uv run python -m src.test_agent --graph 1-1
    uv run python -m src.test_agent --graph graph-1-1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import networkx as nx
from dotenv import load_dotenv
from anthropic import Anthropic

from src.build_graph import load_graph_file, list_graphs
from src.graph import build_graph
from src.agent import SYSTEM_PROMPT, TOOLS, _execute_tool
from src.models import AgentResponse


def ask_verbose(question: str, g: nx.DiGraph, client: Anthropic, max_turns: int = 15) -> AgentResponse:
    """Like agent.ask(), but prints every tool call and result."""
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

        if response.stop_reason == "tool_use":
            # Print any text the model produced before tool calls
            for block in response.content:
                if hasattr(block, "text") and block.text.strip():
                    print(f"\n  Agent thinking: {block.text.strip()}")

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    # Track entities
                    for key in ("entity_id", "source_id", "target_id"):
                        if key in tool_input:
                            referenced_entities.add(tool_input[key])

                    # Print the tool call
                    input_str = ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
                    print(f"\n  [{turn_count}] {tool_name}({input_str})")

                    result = _execute_tool(tool_name, tool_input, g)

                    # Print the result (indent and truncate long results)
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

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Final answer
            answer_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    answer_text += block.text

            print(f"\n  Turns used: {turn_count}")
            print(f"  Entities queried: {', '.join(sorted(referenced_entities)) if referenced_entities else 'none'}")

            return AgentResponse(
                answer=answer_text,
                referenced_entities=sorted(referenced_entities),
                reasoning_path=f"Completed in {turn_count} turns",
            )

    return AgentResponse(
        answer="Agent reached maximum turns.",
        referenced_entities=sorted(referenced_entities),
        reasoning_path=f"Hit max_turns ({max_turns})",
    )


def main() -> None:
    load_dotenv()

    if "--graph" not in sys.argv:
        # Show available graphs and usage
        print("Usage: uv run python -m src.test_agent --graph <graph_id>")
        print("\nAvailable graphs:")
        graphs = list_graphs()
        if not graphs:
            print("  None. Build one first: uv run python -m src.build_graph <policy> --prompt <version>")
        else:
            for g in graphs:
                print(f"  {g['graph_id']}  ({g['node_count']} nodes, {g['edge_count']} edges, policy: {g['policy_file']})")
        sys.exit(1)

    graph_idx = sys.argv.index("--graph")
    graph_id = sys.argv[graph_idx + 1]

    print(f"Loading graph: {graph_id}")
    ontology, metadata = load_graph_file(graph_id)
    g = build_graph(ontology)
    print(f"  Prompt version: v{metadata['prompt_version']}")
    print(f"  Policy: {metadata['policy_file']}")
    print(f"  {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

    # Type summary
    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        t = data.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {count}")

    client = Anthropic()

    print("\n" + "=" * 60)
    print(f"  GRAPH AGENT TEST HARNESS  [{metadata['graph_id']}]")
    print("  Ask questions. Every tool call will be shown.")
    print("  Type 'quit' to exit.")
    print("=" * 60)

    while True:
        print()
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDone.")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Done.")
            break

        print(f"\n{'─' * 50}")
        response = ask_verbose(question, g, client)
        print(f"{'─' * 50}")
        print(f"\nA: {response.answer}")


if __name__ == "__main__":
    main()
