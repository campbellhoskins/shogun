"""LangChain LLMGraphTransformer baseline for A/B comparison against Shogun pipeline.

Two modes:
  1. Schema-free:   Let the LLM discover entity/relationship types on its own.
  2. Schema-guided: Feed our typed entity types and relationship triples so the
                    LLM adheres to the same ontology Shogun uses.

Usage:
  # Schema-free extraction
  uv run python scripts/langchain_kg_baseline.py data/direct_travel_duty_of_care.md --mode free

  # Schema-guided extraction (uses Shogun's entity types + relationship triples)
  uv run python scripts/langchain_kg_baseline.py data/direct_travel_duty_of_care.md --mode guided

  # Whole-document (no chunking) — default
  uv run python scripts/langchain_kg_baseline.py data/direct_travel_duty_of_care.md --mode guided --whole

  # Chunked (split into N-char chunks before extraction)
  uv run python scripts/langchain_kg_baseline.py data/direct_travel_duty_of_care.md --mode guided --chunk-size 4000

Output is saved to data/langchain_kg_{mode}_{strategy}.json in a format that
can be compared against Shogun's ontology.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer

# Add project root to path so we can import src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.schemas import (
    ENTITY_TYPE_CLASSES,
    RELATIONSHIP_SCHEMAS,
    VALID_ENTITY_TYPES,
)


# ── Schema helpers ───────────────────────────────────────────────────────────


def get_allowed_nodes() -> list[str]:
    """Extract entity type names from our schema registry."""
    return [cls.model_fields["type"].default for cls in ENTITY_TYPE_CLASSES]


def get_allowed_relationships_as_triples() -> list[tuple[str, str, str]]:
    """Convert our RelationshipSchema registry into (source, rel, target) triples.

    LLMGraphTransformer accepts tuples to constrain which entity types can
    participate in which relationship types. If a schema has multiple valid
    source/target types, we emit one triple per combination.
    """
    triples: list[tuple[str, str, str]] = []
    for rs in RELATIONSHIP_SCHEMAS:
        sources = rs.valid_source_types or get_allowed_nodes()
        targets = rs.valid_target_types or get_allowed_nodes()
        for src in sources:
            for tgt in targets:
                triples.append((src, rs.type, tgt))
    return triples


def get_allowed_relationships_flat() -> list[str]:
    """Just the relationship type names (no triple constraints)."""
    return sorted({rs.type for rs in RELATIONSHIP_SCHEMAS})


# ── Document loading ─────────────────────────────────────────────────────────


def load_document(path: Path) -> str:
    """Load a markdown or text file."""
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, chunk_size: int, overlap: int = 200) -> list[str]:
    """Simple character-level chunking with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# ── Conversion helpers ───────────────────────────────────────────────────────


def _normalize_entity_type(raw_type: str) -> str:
    """Fix LangChain's lowercased type names back to our PascalCase types.

    LLMGraphTransformer lowercases multi-word types (e.g. 'Severitylevel')
    so we do a case-insensitive lookup against VALID_ENTITY_TYPES.
    """
    # Build case-insensitive lookup once
    if not hasattr(_normalize_entity_type, "_cache"):
        _normalize_entity_type._cache = {t.lower(): t for t in VALID_ENTITY_TYPES}
    return _normalize_entity_type._cache.get(raw_type.lower(), raw_type)


def graph_documents_to_dict(graph_docs: list) -> dict:
    """Convert LangChain GraphDocument objects to a serializable dict.

    Output matches Shogun's OntologyGraph schema so the frontend can load it
    directly: entities have id/type/name/description, relationships have
    source_id/target_id/type/description.
    """
    entities: dict[str, dict] = {}
    relationships: list[dict] = []

    for gdoc in graph_docs:
        # Nodes
        for node in gdoc.nodes:
            node_id = node.id
            if node_id not in entities:
                props = node.properties if hasattr(node, "properties") else {}
                entities[node_id] = {
                    "id": node_id,
                    "type": _normalize_entity_type(node.type),
                    "name": node.id,
                    "description": props.get("description", f"{node.type}: {node.id}"),
                    **{k: v for k, v in props.items() if k != "description"},
                }

        # Relationships
        for rel in gdoc.relationships:
            props = rel.properties if hasattr(rel, "properties") else {}
            relationships.append({
                "source_id": rel.source.id,
                "target_id": rel.target.id,
                "type": rel.type,
                "description": props.get(
                    "description",
                    f"{rel.source.id} {rel.type} {rel.target.id}",
                ),
            })

    return {
        "entities": list(entities.values()),
        "relationships": relationships,
        "metadata": {
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "entity_types": sorted({e["type"] for e in entities.values()}),
            "relationship_types": sorted({r["type"] for r in relationships}),
        },
    }


# ── Main ─────────────────────────────────────────────────────────────────────


async def run_extraction(
    doc_path: Path,
    mode: str,
    chunk_size: int | None,
    use_triples: bool,
    node_properties: bool,
) -> dict:
    """Run LLMGraphTransformer extraction and return results dict."""

    model_name = os.getenv("TEST_MODEL", "claude-haiku-4-5-20251001")
    print(f"Using model: {model_name}")

    llm = ChatAnthropic(model=model_name, temperature=0)

    # Build transformer kwargs
    kwargs: dict = {"llm": llm}

    if mode == "guided":
        allowed_nodes = get_allowed_nodes()
        print(f"Schema-guided mode: {len(allowed_nodes)} entity types")
        kwargs["allowed_nodes"] = allowed_nodes

        if use_triples:
            triples = get_allowed_relationships_as_triples()
            print(f"  {len(triples)} relationship triples (source, rel, target)")
            kwargs["allowed_relationships"] = triples
        else:
            flat_rels = get_allowed_relationships_flat()
            print(f"  {len(flat_rels)} relationship types (flat)")
            kwargs["allowed_relationships"] = flat_rels

    else:
        print("Schema-free mode: LLM discovers types on its own")

    if node_properties:
        kwargs["node_properties"] = True
        kwargs["relationship_properties"] = True
        print("  Properties: autonomous (LLM decides)")

    transformer = LLMGraphTransformer(**kwargs)

    # Load and optionally chunk the document
    text = load_document(doc_path)
    print(f"Document: {doc_path.name} ({len(text):,} chars)")

    if chunk_size:
        chunks = chunk_text(text, chunk_size)
        documents = [
            Document(
                page_content=chunk,
                metadata={"source": doc_path.name, "chunk_index": i},
            )
            for i, chunk in enumerate(chunks)
        ]
        strategy = "chunked"
        print(f"  Chunked into {len(documents)} segments ({chunk_size} chars each)")
    else:
        documents = [Document(page_content=text, metadata={"source": doc_path.name})]
        strategy = "whole_doc"
        print("  Processing as whole document (no chunking)")

    # Run extraction
    print("\nExtracting knowledge graph...")
    t0 = time.time()
    graph_docs = await transformer.aconvert_to_graph_documents(documents)
    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s")

    # Convert to comparable format
    result = graph_documents_to_dict(graph_docs)
    result["metadata"]["mode"] = mode
    result["metadata"]["strategy"] = strategy
    result["metadata"]["chunk_size"] = chunk_size
    result["metadata"]["model"] = model_name
    result["metadata"]["extraction_time_seconds"] = round(elapsed, 2)
    result["metadata"]["document"] = doc_path.name

    # Summary
    meta = result["metadata"]
    print(f"\nResults:")
    print(f"  Entities:      {meta['entity_count']}")
    print(f"  Relationships: {meta['relationship_count']}")
    print(f"  Entity types:  {meta['entity_types']}")
    print(f"  Rel types:     {meta['relationship_types']}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="LangChain LLMGraphTransformer baseline for ontology extraction"
    )
    parser.add_argument("document", type=Path, help="Path to markdown/text document")
    parser.add_argument(
        "--mode",
        choices=["free", "guided"],
        default="free",
        help="'free' = schema-free, 'guided' = use Shogun entity/relationship types",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="If set, chunk the document into segments of this size (chars)",
    )
    parser.add_argument(
        "--triples",
        action="store_true",
        default=True,
        help="Use (source, rel, target) triples instead of flat relationship list (default: True)",
    )
    parser.add_argument(
        "--no-triples",
        action="store_true",
        help="Use flat relationship type list instead of triples",
    )
    parser.add_argument(
        "--properties",
        action="store_true",
        help="Let the LLM extract node/relationship properties autonomously",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output path (default: auto-generated in data/)",
    )

    args = parser.parse_args()

    if not args.document.exists():
        print(f"Error: {args.document} not found")
        sys.exit(1)

    use_triples = not args.no_triples
    strategy = "chunked" if args.chunk_size else "whole_doc"

    result = asyncio.run(
        run_extraction(
            doc_path=args.document,
            mode=args.mode,
            chunk_size=args.chunk_size,
            use_triples=use_triples,
            node_properties=args.properties,
        )
    )

    # Save output
    if args.output:
        out_path = args.output
    else:
        out_path = PROJECT_ROOT / "data" / f"langchain_kg_{strategy}_schema_{args.mode}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
