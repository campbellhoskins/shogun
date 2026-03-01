"""Stage 3: Deterministic merge and deduplication of per-section extractions.

Merges all per-section extraction results into a single OntologyGraph,
deduplicating entities that appear across sections using exact-match strategies.

CLI usage:
    python -m src.merge <extractions.json> <chunks.json> <source_text_file> -o <ontology.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher

from src.models import (
    DocumentSection,
    Entity,
    ExtractionMetadata,
    OntologyGraph,
    Relationship,
    SectionExtraction,
    SourceAnchor,
)


def merge_extractions(
    section_extractions: list[SectionExtraction],
    source_document: str,
    sections: list[DocumentSection],
) -> OntologyGraph:
    """Merge all per-section extractions into a single OntologyGraph.

    Performs deterministic deduplication (exact ID and exact Name+Type match).
    LLM-based semantic dedup is deferred to Phase 4.

    Args:
        section_extractions: Results from per-section extraction.
        source_document: The full original document text.
        sections: The document sections from segmentation.

    Returns:
        Merged OntologyGraph with source anchoring and metadata.
    """
    # Collect all entities and relationships
    all_entities: list[Entity] = []
    all_relationships: list[Relationship] = []

    for se in section_extractions:
        all_entities.extend(se.entities)
        all_relationships.extend(se.relationships)

    # Run deduplication
    merged_entities, id_mapping, merge_count = _deduplicate_entities(all_entities)

    # Update relationship references using the ID mapping
    merged_relationships = _update_relationships(all_relationships, id_mapping)

    # Remove duplicate relationships
    merged_relationships = _deduplicate_relationships(merged_relationships)

    # Compute source offsets for entities
    _compute_source_offsets(merged_entities, source_document)

    # Build metadata
    metadata = ExtractionMetadata(
        document_char_count=len(source_document),
        section_count=len(sections),
        extraction_passes=len(section_extractions),
        final_entity_count=len(merged_entities),
        final_relationship_count=len(merged_relationships),
        deduplication_merges=merge_count,
    )

    return OntologyGraph(
        entities=merged_entities,
        relationships=merged_relationships,
        source_sections=sections,
        source_document=source_document,
        extraction_metadata=metadata,
    )


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip punctuation and whitespace."""
    # Normalize unicode
    name = unicodedata.normalize("NFKD", name)
    # Lowercase
    name = name.lower()
    # Remove punctuation except hyphens (which may be meaningful)
    name = re.sub(r"[^\w\s-]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _strip_section_prefix(entity_id: str) -> str:
    """Strip the section prefix from an entity ID (e.g., 's2_1_risk_level' -> 'risk_level')."""
    # Match pattern: s{digits and underscores}_ followed by the actual ID
    match = re.match(r"^s[\d_]+[a-z]?\d*_(.+)$", entity_id)
    if match:
        return match.group(1)
    return entity_id


def _deduplicate_entities(
    entities: list[Entity],
) -> tuple[list[Entity], dict[str, str], int]:
    """Deduplicate entities using exact-match strategies.

    Returns:
        Tuple of (merged entities, id_mapping old->canonical, merge count).
    """
    id_mapping: dict[str, str] = {}  # old_id -> canonical_id
    merge_count = 0

    # --- Tier 1: Exact ID match (after stripping section prefix) ---
    base_id_groups: dict[str, list[Entity]] = {}
    for entity in entities:
        base_id = _strip_section_prefix(entity.id)
        base_id_groups.setdefault(base_id, []).append(entity)

    # --- Tier 2: Exact Name+Type match ---
    name_type_groups: dict[tuple[str, str], list[Entity]] = {}
    for entity in entities:
        key = (_normalize_name(entity.name), entity.type.lower())
        name_type_groups.setdefault(key, []).append(entity)

    # Build unified groups: merge Tier 1 and Tier 2 groups
    # Use union-find to cluster entities that match on either criterion
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Initialize each entity as its own group
    for entity in entities:
        parent[entity.id] = entity.id

    # Union by base ID
    for group in base_id_groups.values():
        if len(group) > 1:
            for entity in group[1:]:
                union(group[0].id, entity.id)

    # Union by name+type
    for group in name_type_groups.values():
        if len(group) > 1:
            for entity in group[1:]:
                union(group[0].id, entity.id)

    # Build final groups
    groups: dict[str, list[Entity]] = {}
    for entity in entities:
        root = find(entity.id)
        groups.setdefault(root, []).append(entity)

    # Merge each group into a canonical entity
    merged: list[Entity] = []
    for root_id, group in groups.items():
        canonical = _merge_entity_group(group)
        merged.append(canonical)

        # Map all IDs in the group to the canonical ID
        for entity in group:
            if entity.id != canonical.id:
                id_mapping[entity.id] = canonical.id
                merge_count += 1

    return merged, id_mapping, merge_count


def _merge_entity_group(group: list[Entity]) -> Entity:
    """Merge a group of duplicate entities into one canonical entity."""
    if len(group) == 1:
        return group[0]

    # Pick the entity with the longest description as the base
    base = max(group, key=lambda e: len(e.description))

    # Union all attributes
    merged_attrs = {}
    for entity in group:
        for k, v in entity.attributes.items():
            if k not in merged_attrs:
                merged_attrs[k] = v
            elif isinstance(v, str) and isinstance(merged_attrs[k], str):
                # Keep the longer string value
                if len(str(v)) > len(str(merged_attrs[k])):
                    merged_attrs[k] = v

    # Pick the best source anchor (longest source_text)
    best_anchor = max(
        (e.source_anchor for e in group),
        key=lambda a: len(a.source_text),
    )

    return Entity(
        id=base.id,
        type=base.type,
        name=base.name,
        description=base.description,
        attributes=merged_attrs,
        source_anchor=best_anchor,
    )


def _update_relationships(
    relationships: list[Relationship], id_mapping: dict[str, str]
) -> list[Relationship]:
    """Update relationship source_id and target_id using the ID mapping."""
    updated = []
    for rel in relationships:
        updated.append(
            Relationship(
                source_id=id_mapping.get(rel.source_id, rel.source_id),
                target_id=id_mapping.get(rel.target_id, rel.target_id),
                type=rel.type,
                description=rel.description,
                source_sections=rel.source_sections,
            )
        )
    return updated


def _deduplicate_relationships(relationships: list[Relationship]) -> list[Relationship]:
    """Remove duplicate relationships (same source, target, type)."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[Relationship] = []
    for rel in relationships:
        key = (rel.source_id, rel.target_id, rel.type)
        if key not in seen:
            seen.add(key)
            unique.append(rel)
    return unique


def _normalize_text_for_search(text: str) -> str:
    """Normalize text for fuzzy source offset searching."""
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Normalize quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return text


def _compute_source_offsets(entities: list[Entity], source_document: str) -> None:
    """Compute source_offset for each entity by finding source_text in the document."""
    normalized_doc = _normalize_text_for_search(source_document)

    for entity in entities:
        source_text = entity.source_anchor.source_text
        if not source_text:
            continue

        # Try exact match first
        idx = source_document.find(source_text)
        if idx >= 0:
            entity.source_anchor.source_offset = idx
            continue

        # Try normalized match
        normalized_source = _normalize_text_for_search(source_text)
        idx = normalized_doc.find(normalized_source)
        if idx >= 0:
            entity.source_anchor.source_offset = idx
            continue

        # Try fuzzy match with SequenceMatcher
        if len(source_text) > 20:
            # Search in a window around where we'd expect the text
            # Use a sliding window approach on the normalized doc
            best_ratio = 0.0
            best_idx = -1
            window_size = len(normalized_source) + 50
            step = max(1, len(normalized_source) // 4)

            for start in range(0, len(normalized_doc) - len(normalized_source) + 1, step):
                window = normalized_doc[start : start + window_size]
                matcher = SequenceMatcher(None, normalized_source, window)
                ratio = matcher.ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_idx = start

            if best_ratio >= 0.85:
                entity.source_anchor.source_offset = best_idx


def _sections_from_chunks(chunks: list[dict]) -> list[DocumentSection]:
    """Reconstruct DocumentSection objects from chunks.json dicts."""
    from src.models import EnumeratedList, HierarchyEntry

    sections = []
    for c in chunks:
        enum_lists = []
        for el in c.get("enumerated_lists", []):
            enum_lists.append(EnumeratedList(**el))
        hier_path = [
            HierarchyEntry(**entry)
            for entry in c.get("hierarchical_path", [])
        ]
        sections.append(DocumentSection(
            chunk_id=c["chunk_id"],
            header=c.get("header", ""),
            section_number=c.get("section_number", ""),
            level=c.get("level", 1),
            text=c["text"],
            source_offset=c.get("source_offset", 0),
            parent_section=c.get("parent_section"),
            parent_header=c.get("parent_header"),
            hierarchical_path=hier_path,
            enumerated_lists=enum_lists,
        ))
    return sections


def _extractions_from_json(
    extractions_data: list[dict], sections: list[DocumentSection]
) -> list[SectionExtraction]:
    """Reconstruct SectionExtraction objects from extractions.json + sections."""
    section_by_chunk_id = {s.chunk_id: s for s in sections}

    results = []
    for ext in extractions_data:
        chunk_id = ext.get("chunk_id", "")
        section = section_by_chunk_id.get(chunk_id)
        if section is None:
            # Fall back to matching by section_number
            sec_num = ext.get("section_number", "")
            for s in sections:
                if s.section_number == sec_num:
                    section = s
                    break
            if section is None:
                # Create a minimal placeholder section
                section = DocumentSection(
                    chunk_id=chunk_id,
                    section_number=ext.get("section_number", ""),
                    text="",
                )

        entities = [Entity(**e) for e in ext.get("entities", [])]
        relationships = [Relationship(**r) for r in ext.get("relationships", [])]

        results.append(SectionExtraction(
            section=section,
            entities=entities,
            relationships=relationships,
        ))
    return results


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: merge extractions into a deduplicated ontology graph."""
    parser = argparse.ArgumentParser(
        prog="python -m src.merge",
        description="Stage 3: Merge per-section extractions into a single ontology graph.",
    )
    parser.add_argument(
        "extractions",
        help="Path to extractions.json (Stage 2 output).",
    )
    parser.add_argument(
        "chunks",
        help="Path to chunks.json (Stage 1 output).",
    )
    parser.add_argument(
        "source_text",
        help="Path to the original source text/markdown file.",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/ontology.json",
        help="Path to write ontology JSON (default: data/ontology.json).",
    )
    args = parser.parse_args(argv)

    with open(args.extractions, encoding="utf-8") as f:
        extractions_data = json.load(f)
    with open(args.chunks, encoding="utf-8") as f:
        chunks_data = json.load(f)
    source_text = open(args.source_text, encoding="utf-8").read()

    print(f"Loaded {len(extractions_data)} extraction results, {len(chunks_data)} chunks, {len(source_text)} chars source text")

    sections = _sections_from_chunks(chunks_data)
    section_extractions = _extractions_from_json(extractions_data, sections)
    ontology = merge_extractions(section_extractions, source_text, sections)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(ontology.model_dump(), f, indent=2, ensure_ascii=False, default=str)

    meta = ontology.extraction_metadata
    print(
        f"Wrote ontology to {args.output}: "
        f"{meta.final_entity_count} entities, "
        f"{meta.final_relationship_count} relationships "
        f"({meta.deduplication_merges} duplicates merged)"
    )


if __name__ == "__main__":
    main()
