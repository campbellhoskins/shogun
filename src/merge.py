"""Stage 3: Merge and LLM-based deduplication of per-section extractions.

Merges all per-section extraction results into a single OntologyGraph.
Groups entities by type and uses an LLM to identify semantic duplicates
(e.g., "John" and "John Smith" as the same Person entity).

CLI usage:
    python -m src.merge <extractions.json> <chunks.json> <source_text_file> -o <ontology.json>
    python -m src.merge <extractions.json> <chunks.json> <source_text_file> --no-dedup
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher

import os

from anthropic import Anthropic
from dotenv import load_dotenv

from src.models import (
    DocumentSection,
    ExtractionMetadata,
    OntologyGraph,
    Relationship,
    SectionExtraction,
    SourceAnchor,
    StageUsage,
)
from src.schemas import (
    BaseEntitySchema,
    get_typed_attributes,
    validate_entity,
)

load_dotenv()
_DEFAULT_MODEL = os.environ.get("_DEFAULT_MODEL", "claude-haiku-4-5-20251001")


# ---------------------------------------------------------------------------
# Debug mode
# ---------------------------------------------------------------------------

_DEBUG = False


def _dbg(header: str, body: str = "") -> None:
    if not _DEBUG:
        return
    print(f"\n[DEBUG] {header}")
    if body:
        print("=" * 60)
        print(body)
        print("=" * 60)


# ---------------------------------------------------------------------------
# LLM semantic dedup prompts (from data/merge.txt)
# ---------------------------------------------------------------------------

SEMANTIC_DEDUP_SYSTEM_PROMPT = """\
You are a knowledge graph entity deduplication specialist. Your task is to identify entities that refer to the same real-world concept but were extracted with different IDs during a section-by-section extraction process.

<context>
Entities have already been deduplicated by exact ID match. You are now receiving the consolidated list of unique entities. Some of these entities are semantic duplicates — they represent the same real-world thing but were assigned slightly different IDs during extraction from different sections.

Analyze every entity and identify pairs where two or more entities refer to the same real-world concept. For each duplicate, determine which entity ID should be the canonical ID (the one to keep) and which should be remapped to it.
</context>

<rules>
DUPLICATE DETECTION:
- Name Match with Variation: Names that differ only in abbreviation, punctuation, suffix, or formality (e.g., "Statement of Work (SOW)" vs "SOW", "Direct Travel, Inc." vs "Direct Travel", "SAFE" vs "SAFE Response").
- Description Overlap: Descriptions that describe the same real-world thing — same function, role, and purpose — even if worded differently.
- Type Consistency: Candidates must have the same or compatible entity type. Different types (e.g., "Organization" vs "Service") means NOT duplicates.
- Contextual Role: Entities occupying the same structural role in the document (e.g., both are "the travel management company providing services").

CANONICAL ID SELECTION (in priority order):
1. Prefer the more descriptive and specific ID (e.g., "statement_of_work" over "sow").
2. Prefer the ID appearing in more sections (higher appears_in count).
3. Prefer the ID using full naming conventions (e.g., "direct_travel_inc" over "direct_travel").

NOT DUPLICATES — do not merge:
- Parent entity and its child/component (e.g., "Platform" vs "Risk Intelligence Platform" — related but different scope).
- Entities that are merely associated (e.g., an organization and its agreement).
- Entities with different types representing genuinely different concepts (e.g., a "Service" and an "Obligation" about that service).
- Entities sharing keywords but describing fundamentally different things.
</rules>

<critical_anti_merge_rules>
NUMBERED OR LEVELED ENTITIES: Entities that represent different
levels, tiers, or ranks within a classification system are NEVER
duplicates, even though they share the same type and similar
descriptions.
  - severity_level_1 through severity_level_4 are FOUR DISTINCT entities
  - alert_level_3_sms and alert_level_4_sms are DISTINCT

CHANNEL-SPECIFIC ENTITIES: Entities of the same type that differ
by communication channel are NEVER duplicates:
  - alert_level_3_sms and alert_level_3_email are DISTINCT

PARAMETERIZED INSTANCES: If two entities have the same type but
different values in any typed attribute field (level, channel,
severity_level, classification, escalation_severity_levels),
they are NOT duplicates regardless of name or description similarity.
</critical_anti_merge_rules>

<output-format>
Return a JSON object with key "remappings" containing an array of remapping objects. Each object has exactly three fields:

{
  "remappings": [
    {
      "old_id": "the entity ID to retire",
      "new_id": "the canonical entity ID to remap to",
      "reason": "brief explanation of why these are the same entity"
    }
  ]
}

If no duplicates are found, return: {"remappings": []}

Do NOT return the full entity list. Do NOT return entities that do not need remapping.
</output-format>"""

SEMANTIC_DEDUP_USER_PROMPT = """\
Below is the consolidated entity list after exact-ID deduplication. Identify any remaining semantic duplicates and return only the remapping instructions.

<entities>
{ENTITY_LIST}
</entities>"""


# ---------------------------------------------------------------------------
# Pass 1: Exact ID deduplication (deterministic)
# ---------------------------------------------------------------------------


def _merge_entity_group(group: list[BaseEntitySchema]) -> BaseEntitySchema:
    """Merge a group of entities that share the same (id, type) pair.

    Picks the entity with the longest description as canonical, then merges
    source_anchors, appears_in, descriptions, and typed attributes from all
    members.
    """
    # Sort by description length descending — longest is most complete
    group.sort(key=lambda e: len(e.description), reverse=True)
    canonical = group[0]

    # Collect all unique source_anchors (dedup by source_text)
    seen_texts: set[str] = set()
    all_anchors: list[SourceAnchor] = []
    for e in group:
        # From source_anchors list
        for a in e.source_anchors:
            if a.source_text and a.source_text not in seen_texts:
                seen_texts.add(a.source_text)
                all_anchors.append(a)
        # From primary source_anchor
        if e.source_anchor.source_text and e.source_anchor.source_text not in seen_texts:
            seen_texts.add(e.source_anchor.source_text)
            all_anchors.append(SourceAnchor(
                source_text=e.source_anchor.source_text,
                source_section=e.source_anchor.source_section,
                source_offset=e.source_anchor.source_offset,
            ))

    # Union all appears_in sections
    all_sections: set[str] = set()
    for e in group:
        all_sections.update(e.appears_in)

    # Keep only the longest description (already sorted by length descending)
    combined_description = canonical.description

    # Build merged entity dict
    entity_dict: dict = {
        "id": canonical.id,
        "type": canonical.type,
        "name": canonical.name,
        "description": combined_description,
        "source_anchor": (all_anchors[0] if all_anchors else canonical.source_anchor).model_dump(),
        "source_anchors": [a.model_dump() for a in all_anchors],
        "appears_in": sorted(all_sections),
    }

    # Merge typed attributes from all entities (non-empty preferred; conflicts become lists)
    all_typed: dict[str, list] = defaultdict(list)
    for e in group:
        for k, v in get_typed_attributes(e).items():
            if v is not None and v != "" and v != []:
                all_typed[k].append(v)

    for k, values in all_typed.items():
        unique_values = []
        for v in values:
            if v not in unique_values:
                unique_values.append(v)
        if len(unique_values) == 1:
            entity_dict[k] = unique_values[0]
        else:
            # Concatenate all unique values with semicolons instead of storing
            # as a list (which violates Pydantic str field types).
            entity_dict[k] = "; ".join(str(v) for v in unique_values)

    # Validate via typed schema
    entity, warnings = validate_entity(entity_dict)
    if warnings:
        for w in warnings:
            _dbg(f"  [exact_id_dedup WARN] {w}")
    if entity is not None:
        return entity

    # Fallback: return canonical with merged anchors/sections
    canonical.source_anchors = all_anchors
    canonical.appears_in = sorted(all_sections)
    canonical.description = combined_description
    return canonical


def _exact_id_dedup(
    entities: list[BaseEntitySchema],
) -> tuple[list[BaseEntitySchema], int]:
    """Pass 1: Merge entities with identical (id, type) pairs.

    This is a cheap deterministic pass that runs before LLM-based dedup.
    Entities extracted from different sections often share the exact same ID
    (e.g., 'client' appearing in SEC-00, SEC-03, SEC-07). These are merged
    by combining descriptions, source anchors, and typed attributes.

    Returns:
        Tuple of (deduplicated entity list, number of merges performed).
    """
    groups: dict[tuple[str, str], list[BaseEntitySchema]] = defaultdict(list)
    for e in entities:
        groups[(e.id, e.type)].append(e)

    deduped: list[BaseEntitySchema] = []
    merge_count = 0

    for (eid, etype), group in groups.items():
        if len(group) == 1:
            entity = group[0]
            # Ensure source_anchors populated from primary source_anchor
            if not entity.source_anchors and entity.source_anchor.source_text:
                entity.source_anchors = [SourceAnchor(
                    source_text=entity.source_anchor.source_text,
                    source_section=entity.source_anchor.source_section,
                    source_offset=entity.source_anchor.source_offset,
                )]
            deduped.append(entity)
            continue

        merge_count += len(group) - 1
        merged = _merge_entity_group(group)
        deduped.append(merged)

    return deduped, merge_count


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def merge_extractions(
    section_extractions: list[SectionExtraction],
    source_document: str,
    sections: list[DocumentSection],
    client: Anthropic | None = None,
    cross_section_relationships: list[Relationship] | None = None,
    model: str | None = None,
) -> tuple[OntologyGraph, list[dict], StageUsage]:
    """Merge all per-section extractions into a single OntologyGraph.

    Groups entities by type and uses an LLM to identify semantic duplicates.
    Updates relationship references to point to canonical entity IDs.

    Args:
        section_extractions: Results from per-section extraction.
        source_document: The full original document text.
        sections: The document sections from segmentation.
        client: Anthropic client for LLM dedup calls.
        cross_section_relationships: Relationships from Stage 3a (cross-section extraction).

    Returns:
        Tuple of (OntologyGraph, dedup_log, StageUsage).
    """
    model = model or _DEFAULT_MODEL

    # Collect all entities and relationships
    all_entities: list[BaseEntitySchema] = []
    all_relationships: list[Relationship] = []

    for se in section_extractions:
        all_entities.extend(se.entities)
        all_relationships.extend(se.relationships)

    if cross_section_relationships:
        all_relationships.extend(cross_section_relationships)

    cross_section_count = len(cross_section_relationships) if cross_section_relationships else 0
    print(
        f"    Collected {len(all_entities)} entities, "
        f"{len(all_relationships)} relationships "
        f"({cross_section_count} cross-section) "
        f"from {len(section_extractions)} sections"
    )

    # Pass 1: Exact ID dedup (deterministic — always runs)
    all_entities, exact_merges = _exact_id_dedup(all_entities)
    print(f"    Pass 1 (exact ID): {exact_merges} duplicates merged, {len(all_entities)} remaining")

    # Pass 2: LLM-based semantic deduplication (on reduced list)
    if client is not None:
        merged_entities, id_mapping, merge_count, api_calls, dedup_log = (
            _llm_semantic_dedup(all_entities, client, model=model)
        )
    else:
        # No client — pass through without dedup
        merged_entities = all_entities
        id_mapping = {}
        merge_count = 0
        api_calls = 0
        dedup_log = []

    # Build StageUsage from dedup log (tokens already captured there)
    dedup_input_tokens = 0
    dedup_output_tokens = 0
    for entry in dedup_log:
        dedup_input_tokens += entry.get("input_tokens", 0)
        dedup_output_tokens += entry.get("output_tokens", 0)
    usage = StageUsage(
        stage="stage3b_merge",
        model=model,
        input_tokens=dedup_input_tokens,
        output_tokens=dedup_output_tokens,
        api_calls=api_calls,
    )

    # Update relationship references using the ID mapping
    merged_relationships = _update_relationships(all_relationships, id_mapping)

    # Remove duplicate relationships
    merged_relationships = _deduplicate_relationships(merged_relationships)

    # Validate no orphaned relationships
    entity_ids = {e.id for e in merged_entities}
    orphaned = [
        r for r in merged_relationships
        if r.source_id not in entity_ids or r.target_id not in entity_ids
    ]
    if orphaned:
        # Collect missing IDs for diagnostics
        missing_ids: set[str] = set()
        for r in orphaned:
            if r.source_id not in entity_ids:
                missing_ids.add(r.source_id)
            if r.target_id not in entity_ids:
                missing_ids.add(r.target_id)
        print(
            f"    WARNING: {len(orphaned)} orphaned relationships "
            f"referencing {len(missing_ids)} non-existent entity IDs: "
            f"{sorted(missing_ids)[:10]}"
            + (f" ... and {len(missing_ids) - 10} more" if len(missing_ids) > 10 else "")
        )
        # Remove orphaned relationships
        merged_relationships = [
            r for r in merged_relationships
            if r.source_id in entity_ids and r.target_id in entity_ids
        ]

    # Compute source offsets for entities
    _compute_source_offsets(merged_entities, source_document)

    # Build metadata
    cross_section_count = len(cross_section_relationships) if cross_section_relationships else 0
    metadata = ExtractionMetadata(
        document_char_count=len(source_document),
        section_count=len(sections),
        extraction_passes=len(section_extractions),
        total_api_calls=api_calls,
        final_entity_count=len(merged_entities),
        final_relationship_count=len(merged_relationships),
        exact_id_dedup_merges=exact_merges,
        semantic_dedup_merges=merge_count,
        semantic_dedup_api_calls=api_calls,
        cross_section_relationship_count=cross_section_count,
        cross_section_api_calls=1 if cross_section_count > 0 else 0,
    )

    ontology = OntologyGraph(
        entities=merged_entities,
        relationships=merged_relationships,
        source_sections=sections,
        source_document=source_document,
        extraction_metadata=metadata,
    )

    return ontology, dedup_log, usage


# ---------------------------------------------------------------------------
# LLM-based deduplication
# ---------------------------------------------------------------------------


def _build_entities_block(entities: list[BaseEntitySchema]) -> str:
    """Format entities as a JSON array for the semantic dedup prompt."""
    items = []
    for e in entities:
        item: dict = {
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description[:200],
            "appears_in": e.appears_in,
        }
        typed = get_typed_attributes(e)
        if typed:
            item["attributes"] = {
                k: v for k, v in typed.items()
                if v is not None and v != "" and v != []
            }
        items.append(item)
    return json.dumps(items, indent=2, ensure_ascii=False)


def _apply_remappings(
    entities: list[BaseEntitySchema],
    remappings: list[dict],
) -> tuple[list[BaseEntitySchema], dict[str, str], int]:
    """Apply LLM remappings by merging old_id entities into new_id entities.

    Uses the same _merge_entity_group logic as Pass 1 (exact ID dedup).

    Handles synthetic canonical IDs: when the LLM invents a new_id that doesn't
    exist in the entity list (e.g., remapping both 'safe' and 'safe_response' to
    'safe_response_status'), we collect all old_id entities for that group and
    pick the one appearing in the most sections as the actual canonical.

    Returns:
        Tuple of (merged entity list, id_mapping old->new, merge count).
    """
    entities_by_id = {e.id: e for e in entities}
    id_mapping: dict[str, str] = {}

    # Group remappings by canonical (new_id)
    canonical_groups: dict[str, list[str]] = defaultdict(list)
    for remap in remappings:
        old_id = remap["old_id"]
        new_id = remap["new_id"]

        if old_id not in entities_by_id:
            print(f"      [WARN] Skipping remap: old_id '{old_id}' not found")
            continue

        canonical_groups[new_id].append(old_id)

    # Resolve synthetic canonical IDs (new_id doesn't exist as an entity)
    resolved_groups: dict[str, list[str]] = {}
    for new_id, old_ids in canonical_groups.items():
        if new_id in entities_by_id:
            # Normal case: canonical exists, old_ids merge into it
            resolved_groups[new_id] = old_ids
        else:
            # Synthetic canonical: LLM invented an ID. Pick the best old_id
            # as the actual canonical (most sections, then longest description).
            valid_old = [oid for oid in old_ids if oid in entities_by_id]
            if not valid_old:
                print(f"      [WARN] Skipping group: new_id '{new_id}' not found and no valid old_ids")
                continue
            # Sort: most appears_in first, then longest description
            valid_old.sort(
                key=lambda oid: (len(entities_by_id[oid].appears_in), len(entities_by_id[oid].description)),
                reverse=True,
            )
            actual_canonical = valid_old[0]
            others = valid_old[1:]
            if others:
                resolved_groups[actual_canonical] = others
                print(
                    f"      [INFO] Synthetic canonical '{new_id}' resolved to "
                    f"existing entity '{actual_canonical}' (merging {[actual_canonical] + others})"
                )
            else:
                # Only one entity in this group — nothing to merge
                print(
                    f"      [INFO] Synthetic canonical '{new_id}' resolved to "
                    f"'{actual_canonical}' (single entity, no merge needed)"
                )

    # Build id_mapping
    for canonical_id, old_ids in resolved_groups.items():
        for old_id in old_ids:
            id_mapping[old_id] = canonical_id

    # Merge each group
    merged_ids: set[str] = set()
    for canonical_id, old_ids in resolved_groups.items():
        group = [entities_by_id[canonical_id]]
        for old_id in old_ids:
            group.append(entities_by_id[old_id])
            merged_ids.add(old_id)
        merged = _merge_entity_group(group)
        # Force the merged entity to use the canonical ID (not whichever
        # entity had the longest description in _merge_entity_group)
        if merged.id != canonical_id:
            id_mapping[merged.id] = canonical_id
            merged.id = canonical_id
        entities_by_id[canonical_id] = merged

    # Build final list: all entities not retired by remapping
    result = [e for eid, e in entities_by_id.items() if eid not in merged_ids]

    return result, id_mapping, len(merged_ids)


def _llm_semantic_dedup(
    entities: list[BaseEntitySchema],
    client: Anthropic,
    model: str | None = None,
) -> tuple[list[BaseEntitySchema], dict[str, str], int, int, list[dict]]:
    """Pass 2: Single LLM call to identify semantic duplicates across all entities.

    Sends the full post-Pass-1 entity list to the LLM, which returns remapping
    instructions (old_id -> new_id). Remappings are then applied deterministically
    using _merge_entity_group.

    Returns:
        Tuple of:
            - deduplicated entities (list[BaseEntitySchema])
            - id_mapping old->new (dict[str, str])
            - merge count (int)
            - api call count (int)
            - dedup log for result storage (list[dict])
    """
    model = model or _DEFAULT_MODEL
    print(f"    Semantic dedup: sending {len(entities)} entities to LLM...")

    entities_block = _build_entities_block(entities)
    user_prompt = SEMANTIC_DEDUP_USER_PROMPT.format(ENTITY_LIST=entities_block)

    _dbg("SYSTEM PROMPT", SEMANTIC_DEDUP_SYSTEM_PROMPT)
    _dbg(f"USER PROMPT ({len(entities)} entities)", user_prompt)

    log_entry: dict = {
        "input_count": len(entities),
        "input_ids": [e.id for e in entities],
    }

    try:
        from src.models import SemanticDedupOutput

        thinking_budget = min(32768, max(4096, len(entities) * 400))
        max_tokens = thinking_budget + min(8192, max(2048, len(entities) * 100))

        # Use streaming to avoid timeout on large entity lists
        raw_text = ""
        thinking_text = ""
        input_tokens = 0
        output_tokens = 0

        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=SEMANTIC_DEDUP_SYSTEM_PROMPT,
            output_format=SemanticDedupOutput,
            thinking={
                "type": "enabled",
                "budget_tokens": thinking_budget,
            },
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "thinking":
                        print("\n      [Thinking]", flush=True)
                    elif event.content_block.type == "text":
                        print("\n      [Response]", flush=True)
                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "thinking"):
                        thinking_text += event.delta.thinking
                        print(event.delta.thinking, end="", flush=True)
                    elif hasattr(event.delta, "text"):
                        raw_text += event.delta.text
                        print(event.delta.text, end="", flush=True)
                elif event.type == "content_block_stop":
                    print(flush=True)
            response = stream.get_final_message()

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        print(f"      ({input_tokens} in, {output_tokens} out)")

        log_entry["input_tokens"] = input_tokens
        log_entry["output_tokens"] = output_tokens
        log_entry["raw_response"] = raw_text
        if thinking_text:
            log_entry["thinking"] = thinking_text

        _dbg("THINKING", thinking_text)
        _dbg(
            f"RESPONSE ({response.usage.input_tokens} in, {response.usage.output_tokens} out)",
            raw_text,
        )

        # Parse remappings from structured output
        parsed: SemanticDedupOutput = response.parsed_output
        remappings = [r.model_dump() for r in parsed.remappings]
        log_entry["remappings"] = remappings

        if not remappings:
            print("      -> No semantic duplicates found")
            log_entry["merges"] = 0
            return entities, {}, 0, 1, [log_entry]

        # Print each remapping
        for remap in remappings:
            print(f"      {remap['old_id']} -> {remap['new_id']}: {remap.get('reason', '')}")

        # Apply remappings deterministically
        merged_entities, id_mapping, merge_count = _apply_remappings(entities, remappings)

        log_entry["output_count"] = len(merged_entities)
        log_entry["merges"] = merge_count
        print(f"      -> {len(merged_entities)} unique ({merge_count} merged)")

        return merged_entities, id_mapping, merge_count, 1, [log_entry]

    except Exception as e:
        print(f"    WARNING: Semantic dedup failed: {e}")
        log_entry["error"] = str(e)
        return entities, {}, 0, 1, [log_entry]


# ---------------------------------------------------------------------------
# Relationship helpers (unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Source offset computation
# ---------------------------------------------------------------------------


def _normalize_text_for_search(text: str) -> str:
    """Normalize text for fuzzy source offset searching."""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return text


def _find_offset(source_text: str, source_document: str, normalized_doc: str) -> int:
    """Find the offset of source_text in the document. Returns -1 if not found."""
    if not source_text:
        return -1

    # Try exact match first
    idx = source_document.find(source_text)
    if idx >= 0:
        return idx

    # Try normalized match
    normalized_source = _normalize_text_for_search(source_text)
    idx = normalized_doc.find(normalized_source)
    if idx >= 0:
        return idx

    # Try fuzzy match with SequenceMatcher
    if len(source_text) > 20:
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
            return best_idx

    return -1


def _compute_source_offsets(entities: list[BaseEntitySchema], source_document: str) -> None:
    """Compute source_offset for each entity's source anchors in the document."""
    normalized_doc = _normalize_text_for_search(source_document)

    for entity in entities:
        # Compute offset for all source_anchors
        for anchor in entity.source_anchors:
            if anchor.source_text and anchor.source_offset < 0:
                anchor.source_offset = _find_offset(
                    anchor.source_text, source_document, normalized_doc
                )

        # Also compute for the primary source_anchor
        if entity.source_anchor.source_text and entity.source_anchor.source_offset < 0:
            entity.source_anchor.source_offset = _find_offset(
                entity.source_anchor.source_text, source_document, normalized_doc
            )


# ---------------------------------------------------------------------------
# JSON reconstruction helpers (for CLI)
# ---------------------------------------------------------------------------


def _sections_from_chunks(chunks: list[dict]) -> list[DocumentSection]:
    """Reconstruct DocumentSection objects from chunks.json dicts."""
    sections = []
    for c in chunks:
        sections.append(DocumentSection(
            section_id=c.get("section_id", c.get("chunk_id", "")),
            header=c.get("header", ""),
            section_number=c.get("section_number", ""),
            text=c["text"],
            source_offset=c.get("source_offset", 0),
        ))
    return sections


def _extractions_from_json(
    extractions_data: list[dict], sections: list[DocumentSection]
) -> list[SectionExtraction]:
    """Reconstruct SectionExtraction objects from extractions.json + sections."""
    section_by_id = {s.section_id: s for s in sections}

    results = []
    for ext in extractions_data:
        sid = ext.get("section_id", ext.get("chunk_id", ""))
        section = section_by_id.get(sid)
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
                    section_id=sid,
                    section_number=ext.get("section_number", ""),
                    text="",
                )

        entities = []
        for e_data in ext.get("entities", []):
            # Flatten legacy "attributes" dict to top-level for typed schema
            if "attributes" in e_data and isinstance(e_data["attributes"], dict):
                attrs = e_data.pop("attributes")
                for k, v in attrs.items():
                    if k not in e_data:
                        e_data[k] = v
            entity, warnings = validate_entity(e_data)
            if entity is not None:
                entities.append(entity)
            elif warnings:
                print(f"    [WARN] Loading entity: {'; '.join(warnings)}")
        relationships = [Relationship(**r) for r in ext.get("relationships", [])]

        results.append(SectionExtraction(
            section=section,
            entities=entities,
            relationships=relationships,
        ))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: merge extractions into a deduplicated ontology graph."""
    parser = argparse.ArgumentParser(
        prog="python -m src.merge",
        description="Stage 3: Merge per-section extractions with LLM deduplication.",
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
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip LLM deduplication (deterministic merge only, no API calls).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full prompts and responses for each type group.",
    )
    args = parser.parse_args(argv)

    global _DEBUG
    _DEBUG = args.debug

    with open(args.extractions, encoding="utf-8") as f:
        extractions_data = json.load(f)
    with open(args.chunks, encoding="utf-8") as f:
        chunks_data = json.load(f)
    source_text = open(args.source_text, encoding="utf-8").read()

    print(f"Loaded {len(extractions_data)} extraction results, {len(chunks_data)} chunks, {len(source_text)} chars source text")

    sections = _sections_from_chunks(chunks_data)
    section_extractions = _extractions_from_json(extractions_data, sections)

    client = None if args.no_dedup else Anthropic()
    ontology, dedup_log, usage = merge_extractions(
        section_extractions, source_text, sections, client=client
    )
    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out ({usage.api_calls} API calls)")

    # Write ontology
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(ontology.model_dump(), f, indent=2, ensure_ascii=False, default=str)

    # Write dedup log alongside ontology
    if dedup_log:
        dedup_log_path = args.output.replace(".json", "_dedup_log.json")
        with open(dedup_log_path, "w", encoding="utf-8") as f:
            json.dump(dedup_log, f, indent=2, ensure_ascii=False, default=str)
        print(f"Dedup log: {dedup_log_path}")

    meta = ontology.extraction_metadata
    print(
        f"Wrote ontology to {args.output}: "
        f"{meta.final_entity_count} entities, "
        f"{meta.final_relationship_count} relationships "
        f"({meta.exact_id_dedup_merges} exact-ID + {meta.semantic_dedup_merges} semantic duplicates merged, "
        f"{meta.semantic_dedup_api_calls} API calls)"
    )


if __name__ == "__main__":
    main()
