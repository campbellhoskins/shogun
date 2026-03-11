"""Interactive testing harness for the ontology graph agent.

Shows every tool call, its input, and the result — so you can see exactly
how the agent traverses the graph to reach its answer.

Usage:
    uv run python -m src.agent_repl --graph <path/to/ontology.json>
    uv run python -m src.agent_repl --latest

Example:
    uv run python -m src.agent_repl --graph data/final_graphs/shogun_pipeline_v1.json
    uv run python -m src.agent_repl --latest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import networkx as nx
import os

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
TEST_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")

from src.graph import build_graph
from src.agent import SYSTEM_PROMPT, TOOLS, _execute_tool
from src.models import AgentResponse, OntologyGraph


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
            model=TEST_MODEL,
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


def _load_ontology(args: Any) -> tuple[OntologyGraph, str]:
    """Load an OntologyGraph from CLI arguments.

    Returns (ontology, label) where label is used for display.
    """
    if args.latest:
        from src.results import load_latest_ontology
        ontology = load_latest_ontology()
        return ontology, "latest pipeline run"

    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"Error: File not found: {graph_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))

    # Handle wrapped format (e.g. legacy build_graph output with "ontology" key)
    if "ontology" in data and isinstance(data["ontology"], dict):
        data = data["ontology"]

    ontology = OntologyGraph(**data)
    return ontology, str(graph_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.agent_repl",
        description="Interactive agent REPL for querying ontology graphs",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--graph", type=str, help="Path to ontology JSON file")
    group.add_argument("--latest", action="store_true", help="Load the latest pipeline run")
    args = parser.parse_args()

    print(f"Loading graph: {args.graph or 'latest'}")
    ontology, label = _load_ontology(args)
    g = build_graph(ontology)
    print(f"  Source: {label}")
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
    print(f"  GRAPH AGENT REPL  [{label}]")
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
