from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from src.pipeline import extract_ontology
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

    # Load policy
    print(f"Loading policy document: {policy_path.name}")
    policy_text = load_document(policy_path)
    print(f"  Loaded {len(policy_text):,} characters")

    # Run extraction pipeline → saves ontology to results/runs/
    print("\nRunning extraction pipeline (this calls Claude API)...")
    client = Anthropic()
    ontology = extract_ontology(policy_text, client=client, policy_name=policy_path.name)
    print(f"\nDone. {len(ontology.entities)} entities, {len(ontology.relationships)} relationships.")


if __name__ == "__main__":
    main()
