"""Build and save an ontology graph from a policy document.

Saves the graph with versioning metadata so it can be loaded later
without re-parsing.

Usage:
    uv run python -m src.build_graph <policy_path> --prompt <version>

Example:
    uv run python -m src.build_graph data/231123_Duty_of_Care_Policy.pdf --prompt 1

This creates: output/graphs/graph-1-1.json (prompt v1, instance 1)
If graph-1-1 already exists, it creates graph-1-2, etc.

To list saved graphs:
    uv run python -m src.build_graph --list
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

from src.main import load_document
from src.parser import parse_policy
from src.graph import build_graph
from src.models import OntologyGraph

GRAPHS_DIR = Path(__file__).parent.parent / "output" / "graphs"


def get_next_instance(prompt_version: int) -> int:
    """Find the next available instance number for a prompt version."""
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(GRAPHS_DIR.glob(f"graph-{prompt_version}-*.json"))
    if not existing:
        return 1
    # Extract instance numbers
    instances = []
    for p in existing:
        parts = p.stem.split("-")
        if len(parts) == 3 and parts[2].isdigit():
            instances.append(int(parts[2]))
    return max(instances, default=0) + 1


def save_graph(
    ontology: OntologyGraph,
    prompt_version: int,
    policy_path: str,
    parse_time: float,
    node_count: int,
    edge_count: int,
) -> Path:
    """Save an ontology graph with metadata."""
    instance = get_next_instance(prompt_version)
    filename = f"graph-{prompt_version}-{instance}.json"
    filepath = GRAPHS_DIR / filename

    data = {
        "metadata": {
            "graph_id": f"graph-{prompt_version}-{instance}",
            "prompt_version": prompt_version,
            "instance": instance,
            "policy_file": policy_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "parse_time_seconds": round(parse_time, 1),
            "node_count": node_count,
            "edge_count": edge_count,
            "entity_count": len(ontology.entities),
            "relationship_count": len(ontology.relationships),
        },
        "ontology": ontology.model_dump(),
    }

    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return filepath


def load_graph_file(graph_id: str) -> tuple[OntologyGraph, dict]:
    """Load a saved graph by its ID (e.g., 'graph-1-1' or just '1-1')."""
    if not graph_id.startswith("graph-"):
        graph_id = f"graph-{graph_id}"

    filepath = GRAPHS_DIR / f"{graph_id}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Graph not found: {filepath}")

    data = json.loads(filepath.read_text(encoding="utf-8"))
    ontology = OntologyGraph(**data["ontology"])
    metadata = data["metadata"]
    return ontology, metadata


def list_graphs() -> list[dict]:
    """List all saved graphs with their metadata."""
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    graphs = []
    for filepath in sorted(GRAPHS_DIR.glob("graph-*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            graphs.append(data["metadata"])
        except (json.JSONDecodeError, KeyError):
            continue
    return graphs


def main() -> None:
    load_dotenv()

    if "--list" in sys.argv:
        graphs = list_graphs()
        if not graphs:
            print("No saved graphs found.")
            return
        print(f"{'ID':<15} {'Prompt':<8} {'Nodes':<7} {'Edges':<7} {'Policy':<40} {'Created'}")
        print("-" * 110)
        for g in graphs:
            created = g["created_at"][:19].replace("T", " ")
            print(
                f"{g['graph_id']:<15} "
                f"v{g['prompt_version']:<7} "
                f"{g['node_count']:<7} "
                f"{g['edge_count']:<7} "
                f"{g['policy_file']:<40} "
                f"{created}"
            )
        return

    if len(sys.argv) < 2 or "--prompt" not in sys.argv:
        print("Usage: uv run python -m src.build_graph <policy_path> --prompt <version>")
        print("       uv run python -m src.build_graph --list")
        sys.exit(1)

    policy_path = Path(sys.argv[1])
    if not policy_path.is_absolute():
        policy_path = Path.cwd() / policy_path

    prompt_idx = sys.argv.index("--prompt")
    prompt_version = int(sys.argv[prompt_idx + 1])

    print(f"Policy: {policy_path.name}")
    print(f"Prompt version: v{prompt_version}")

    policy_text = load_document(policy_path)
    print(f"  {len(policy_text):,} characters")

    print("\nParsing policy into ontology graph...")
    client = Anthropic()
    t0 = time.time()
    ontology = parse_policy(policy_text, client=client)
    parse_time = time.time() - t0

    g = build_graph(ontology)
    node_count = g.number_of_nodes()
    edge_count = g.number_of_edges()

    print(f"  {node_count} nodes, {edge_count} edges ({parse_time:.1f}s)")

    # Type summary
    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        t = data.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {count}")

    # Save
    filepath = save_graph(
        ontology=ontology,
        prompt_version=prompt_version,
        policy_path=policy_path.name,
        parse_time=parse_time,
        node_count=node_count,
        edge_count=edge_count,
    )
    print(f"\nSaved: {filepath.name}")


if __name__ == "__main__":
    main()
