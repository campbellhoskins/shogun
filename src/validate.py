from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

from src.main import load_document
from src.parser import parse_policy
from src.graph import build_graph, serialize_graph


def structural_report(g) -> None:
    """Print structural quality metrics for the graph."""
    import networkx as nx

    print("\n=== STRUCTURAL QUALITY ===\n")

    # Basic stats
    print(f"Nodes: {g.number_of_nodes()}")
    print(f"Edges: {g.number_of_edges()}")

    if g.number_of_nodes() == 0:
        print("  Graph is empty — nothing to validate.")
        return

    # Density (0 = no edges, 1 = fully connected)
    density = nx.density(g)
    print(f"Density: {density:.3f}")

    # Orphan nodes (no edges at all)
    orphans = [n for n in g.nodes() if g.degree(n) == 0]
    print(f"Orphan nodes (no connections): {len(orphans)}")
    if orphans:
        for o in orphans:
            name = g.nodes[o].get("name", o)
            print(f"  - {name} ({g.nodes[o].get('type', '?')})")

    # Degree distribution
    degrees = [g.degree(n) for n in g.nodes()]
    avg_degree = sum(degrees) / len(degrees)
    max_degree = max(degrees)
    max_node = max(g.nodes(), key=lambda n: g.degree(n))
    max_name = g.nodes[max_node].get("name", max_node)
    print(f"Average degree: {avg_degree:.1f}")
    print(f"Most connected: {max_name} ({max_degree} connections)")

    # Weakly connected components (treating directed as undirected)
    undirected = g.to_undirected()
    components = list(nx.connected_components(undirected))
    print(f"Connected components: {len(components)}")
    if len(components) > 1:
        print("  WARNING: Graph is fragmented into disconnected clusters:")
        for i, comp in enumerate(sorted(components, key=len, reverse=True)):
            names = [g.nodes[n].get("name", n) for n in list(comp)[:5]]
            suffix = f" ... and {len(comp) - 5} more" if len(comp) > 5 else ""
            print(f"  Cluster {i+1} ({len(comp)} nodes): {', '.join(names)}{suffix}")

    # Entity type coverage
    print(f"\nEntity types represented:")
    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        t = data.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    # Relationship type coverage
    print(f"\nRelationship types used:")
    rel_counts: dict[str, int] = {}
    for _, _, data in g.edges(data=True):
        t = data.get("type", "Unknown")
        rel_counts[t] = rel_counts.get(t, 0) + 1
    for t, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")


def coverage_check(policy_text: str, ontology_graph, client: Anthropic) -> None:
    """Use Claude to compare the source document against the extracted graph."""
    print("\n=== COVERAGE CHECK (Claude-assisted) ===\n")

    graph_summary = []
    for e in ontology_graph.entities:
        graph_summary.append(f"- [{e.type}] {e.name}: {e.description}")

    graph_text = "\n".join(graph_summary)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system="""\
You are a quality assurance analyst reviewing an ontology graph extracted from a policy document.

Compare the source policy against the extracted entities and identify:
1. MISSING: Important concepts, rules, roles, thresholds, or procedures mentioned in the policy but NOT captured in the graph.
2. HALLUCINATED: Entities in the graph that do NOT appear in the source policy.
3. INCOMPLETE: Entities that exist but are missing key details (e.g., a rule without its threshold value).

Be specific. Cite the section of the policy where the missing item appears.
Format your response as a structured report.""",
        messages=[
            {
                "role": "user",
                "content": f"## Source Policy Document\n\n{policy_text}\n\n---\n\n## Extracted Entities\n\n{graph_text}",
            }
        ],
    )

    print(response.content[0].text)


def source_anchoring_report(ontology) -> None:
    """Report on the quality of source anchoring."""
    print("\n=== SOURCE ANCHORING QUALITY ===\n")

    total = len(ontology.entities)
    if total == 0:
        print("  No entities to analyze.")
        return

    anchored = sum(1 for e in ontology.entities if e.source_anchor.source_text)
    verified = 0

    if ontology.source_document:
        for entity in ontology.entities:
            if entity.source_anchor.source_text:
                if entity.source_anchor.source_text in ontology.source_document:
                    verified += 1

    print(f"Total entities: {total}")
    print(f"With source text: {anchored} ({100 * anchored / total:.1f}%)")
    if ontology.source_document:
        print(f"Source text verified in document: {verified} ({100 * verified / total:.1f}%)")

    unanchored = [e for e in ontology.entities if not e.source_anchor.source_text]
    if unanchored:
        print(f"\nEntities WITHOUT source anchoring ({len(unanchored)}):")
        for e in unanchored[:10]:
            print(f"  - {e.id} [{e.type}]: {e.name}")
        if len(unanchored) > 10:
            print(f"  ... and {len(unanchored) - 10} more")


def main() -> None:
    load_dotenv()

    project_root = Path(__file__).parent.parent

    if len(sys.argv) > 1:
        policy_path = Path(sys.argv[1])
        if not policy_path.is_absolute():
            policy_path = project_root / policy_path
    else:
        policy_path = project_root / "data" / "sample_policy.md"

    print(f"Loading: {policy_path.name}")
    policy_text = load_document(policy_path)
    print(f"  {len(policy_text):,} characters")

    print("\nParsing policy...")
    client = Anthropic()
    ontology = parse_policy(policy_text, client=client)
    print(f"  {len(ontology.entities)} entities, {len(ontology.relationships)} relationships")

    g = build_graph(ontology)

    # Structural analysis
    structural_report(g)

    # Source anchoring analysis
    source_anchoring_report(ontology)

    # Coverage analysis
    coverage_check(policy_text, ontology, client)


if __name__ == "__main__":
    main()
