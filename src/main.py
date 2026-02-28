from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from src.parser import parse_policy
from src.pipeline import extract_ontology
from src.graph import build_graph, serialize_graph
from src.visualizer import generate_visualization
from src.agent import ask
from src.pdf_parser import parse_pdf


def load_document(path: Path) -> str:
    """Load text from a .md/.txt file or extract structured text from a PDF.

    For PDFs, uses the structure-preserving parser that recovers heading
    hierarchy, lists, definitions, and clause numbering from font metrics.
    This produces markdown that preserves the document's inherent structure
    for optimal LLM reasoning.
    """
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    return path.read_text(encoding="utf-8")


def main() -> None:
    load_dotenv()

    # Paths
    project_root = Path(__file__).parent.parent

    # Accept a file path as CLI argument, default to sample_policy.md
    if len(sys.argv) > 1:
        policy_path = Path(sys.argv[1])
        if not policy_path.is_absolute():
            policy_path = project_root / policy_path
    else:
        policy_path = project_root / "data" / "sample_policy.md"

    graph_html_path = project_root / "output" / "graph.html"
    graph_html_path.parent.mkdir(exist_ok=True)

    # Load policy
    print(f"Loading policy document: {policy_path.name}")
    policy_text = load_document(policy_path)
    print(f"  Loaded {len(policy_text):,} characters")

    # Parse into ontology
    print("\nParsing policy into ontology graph (this calls Claude API)...")
    client = Anthropic()
    ontology = extract_ontology(policy_text, client=client, policy_name=policy_path.name)
    print(f"  Extracted {len(ontology.entities)} entities and {len(ontology.relationships)} relationships")

    # Print pipeline metadata if available
    meta = ontology.extraction_metadata
    if meta.section_count > 0:
        print(f"  Sections: {meta.section_count}")
        print(f"  Deduplication merges: {meta.deduplication_merges}")

    # Build NetworkX graph
    print("\nBuilding graph...")
    g = build_graph(ontology)
    print(f"  Graph has {g.number_of_nodes()} nodes and {g.number_of_edges()} edges")

    # Print entity type summary
    type_counts: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        t = data.get("type", "Unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    print("\n  Entity types:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {count}")

    # Generate visualization
    print(f"\nGenerating interactive visualization -> {graph_html_path}")
    generate_visualization(g, output_path=graph_html_path)
    print(f"  Open {graph_html_path} in your browser to explore the graph")

    # Interactive Q&A loop
    print("\n" + "=" * 60)
    print("  DUTY OF CARE COMPLIANCE AGENT")
    print("  Ask questions about the policy. Type 'quit' to exit.")
    print("=" * 60)

    while True:
        print()
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        print("\nThinking...")
        try:
            response = ask(question, g, client=client)
            print(f"\nAgent: {response.answer}")
            if response.reasoning_path:
                print(f"\n  Reasoning: {response.reasoning_path}")
            if response.referenced_entities:
                print(f"  Referenced: {', '.join(response.referenced_entities)}")
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    main()
