"""Merge additional relationships into an existing ontology and save.

Usage:
    uv run python -m src.merge_relationships <ontology.json> <relationships.json> -o <output.json>

Example:
    uv run python -m src.merge_relationships results/runs/latest/ontology.json data/cross_section.json -o ontology_merged.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.llm import deduplicate_relationships
from src.models import OntologyGraph, Relationship


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.merge_relationships",
        description="Merge additional relationships into an existing ontology.",
    )
    parser.add_argument("ontology", help="Path to ontology JSON file.")
    parser.add_argument("relationships", help="Path to relationships JSON (must have a 'relationships' key).")
    parser.add_argument("-o", "--output", required=True, help="Path to write merged ontology JSON.")
    args = parser.parse_args(argv)

    # Load ontology
    ontology_data = json.loads(Path(args.ontology).read_text(encoding="utf-8"))
    if "ontology" in ontology_data and isinstance(ontology_data["ontology"], dict):
        ontology_data = ontology_data["ontology"]
    ontology = OntologyGraph(**ontology_data)
    print(f"Loaded ontology: {len(ontology.entities)} entities, {len(ontology.relationships)} relationships")

    # Load new relationships
    rel_data = json.loads(Path(args.relationships).read_text(encoding="utf-8"))
    raw_rels = rel_data.get("relationships", rel_data if isinstance(rel_data, list) else [])
    new_rels = [Relationship(**r) for r in raw_rels]
    print(f"Loaded {len(new_rels)} new relationships")

    # Deduplicate and merge
    combined, dupes = deduplicate_relationships(ontology.relationships, new_rels)
    added = len(combined) - len(ontology.relationships)
    ontology.relationships = combined
    ontology.extraction_metadata.final_relationship_count = len(combined)
    print(f"Merged: {added} added, {dupes} duplicates skipped, {len(combined)} total")

    # Write
    Path(args.output).write_text(
        json.dumps(ontology.model_dump(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"Wrote merged ontology to {args.output}")


if __name__ == "__main__":
    main()
