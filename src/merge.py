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

from anthropic import Anthropic

from src.models import (
    DocumentSection,
    ExtractionMetadata,
    OntologyGraph,
    Relationship,
    SectionExtraction,
    SourceAnchor,
)
from src.schemas import (
    BaseEntitySchema,
    get_typed_attributes,
    reconstruct_merged_entity,
    validate_entity,
)


# ---------------------------------------------------------------------------
# Debug mode
# ---------------------------------------------------------------------------

_DEBUG = False


def _dbg(header: str, body: str = "") -> None:
    if not _DEBUG:
        return
    safe = lambda s: s.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
    print(f"\n[DEBUG] {safe(header)}")
    if body:
        print("=" * 60)
        print(safe(body))
        print("=" * 60)


# ---------------------------------------------------------------------------
# LLM deduplication prompt
# ---------------------------------------------------------------------------

DEDUP_PROMPT = """\
You are deduplicating entities that were extracted from a travel policy document. \
The extraction process pulled entities of the same type from different sections \
of the document. Some of these entities may refer to the same real-world thing \
despite having different names, IDs, or descriptions.

Here are all the entities of this type that need deduplication:

<entities>
{ENTITIES}
</entities>

<entity_type>
{ENTITY_TYPE}
</entity_type>

---

## CORE PRINCIPLE: PRESERVE QUERYABILITY

Every distinctly-named entity that a user might search for must exist as its own \
node in the graph. When two entities are related but use different names, keep both \
and connect them with a relationship. Only merge when two extractions are truly the \
same entity appearing in different sections — same name, same real-world referent — \
where keeping both would create a meaningless exact duplicate.

A redundant node with a relationship is always preferable to a lost query path. \
When in doubt, do NOT merge.

---

## MERGE LOGIC

Produce a deduplicated list of entities. For every group of entities that are true \
duplicates, merge them into ONE entity. All other entities pass through with \
relationships added where appropriate.

### When to Merge

Merge two entities ONLY when ALL of the following are true:
- Their names are the same or unambiguous abbreviations of each other \
(e.g., "ED" and "Executive Director")
- Their descriptions refer to the same real-world role, object, or concept — \
not merely a related or overlapping one
- Keeping both as separate nodes would create a meaningless exact duplicate \
with no distinct query value

### When NOT to Merge

Do NOT merge when:
- Two entities use different terminology for the same or similar group \
(e.g., "Employees" and "Personnel") — instead, keep both and link with \
an `equivalent_to` relationship
- One entity is an umbrella or collective term that contains the other \
(e.g., "Representatives" contains "Consultants") — instead, keep both \
and link with a `part_of` relationship
- Two entities share a generic name (e.g., both called "Policy") but describe \
clearly different real-world things
- You are unsure — false negatives (keeping duplicates) are always preferable \
to false positives (incorrectly merging distinct entities)

### Relationships Between Non-Merged Entities

When two entities are related but must remain separate, add a `relationships` \
entry to connect them:

| Situation | Action | Relationship |
|---|---|---|
| Same name, same role, different sections | **Merge** | — |
| Different name, same or similar group of people | **Keep both** | \
`equivalent_to` (on both entities, bidirectional) |
| One entity is a named subcategory or member of another | **Keep both** | \
`part_of` (on the child, pointing to the parent) |
| Unclear whether same or different | **Keep both** | \
Add relationship only if confident |

### Conflicting Attributes

If merged entities have conflicting values for the same attribute key, keep both \
values as a list:
```json
"effective_date": ["2023-01-01", "2023-04-03"]
```
And note the conflict in the description.

---

## OUTPUT SCHEMA

Output ONLY a JSON array. No preamble, no explanation, no commentary outside the JSON.

Every entity in the array must follow this exact structure:
```json
{{
  "id": "clean_lowercase_snake_case_id",
  "type": "{ENTITY_TYPE}",
  "name": "Best most complete name",
  "description": "Combined or original description",
  "attributes": {{"key": "value"}},
  "relationships": [
    {{"target_id": "other_entity_id", "type": "equivalent_to | part_of"}}
  ],
  "source_anchors": [
    {{"source_text": "EXACT verbatim quote from input", "source_section": "0"}}
  ],
  "merged_from": ["original_id_1", "original_id_2"]
}}
```

### Field Rules

- **id**: Lowercase snake_case. Remove section prefixes (e.g., `s3_role_expense_limit` \
→ `expense_limit`). If two non-merged entities would produce the same clean ID, \
append a disambiguating suffix (e.g., `policy_travel`, `policy_expense`).
- **name**: For merged entities, pick the most specific and complete name. \
For pass-through entities, keep as-is.
- **description**: For merged entities, combine descriptions using the pattern: \
"[Most complete description]. [Unique facts from other sources not already covered]." \
For pass-through entities, keep the original description verbatim — do not rewrite it.
- **attributes**: For merged entities, take the union of all attribute keys. \
For pass-through entities, keep as-is.
- **relationships**: Array of relationship objects. Use `equivalent_to` for entities \
that use different names for the same or similar group (add to both entities \
bidirectionally). Use `part_of` for entities that are a named member or subcategory \
of an umbrella entity (add only to the child, pointing at the parent). \
Empty array `[]` if no relationships apply.
- **source_anchors**: Include ALL source references from all original entities. \
The `source_text` value must be copied character-for-character from the input. \
Do not paraphrase, truncate, or edit.
- **merged_from**: Array of all original entity IDs that were merged. \
For pass-through entities, a single-element array.

---

## SELF-VERIFICATION

Before finalizing your output, verify:

1. Every `source_text` value matches the input exactly — character for character
2. Every original entity ID appears in exactly one `merged_from` array across \
the entire output
3. The total count of original IDs across all `merged_from` arrays equals the \
total number of input entities
4. No information from any original entity's description or attributes was lost
5. No two output entities should themselves be merged (check your own output \
for remaining duplicates)
6. Every `target_id` in a relationship points to an `id` that exists in your output
7. All `equivalent_to` relationships are bidirectional (if A → B, then B → A)
8. The JSON is syntactically valid
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def merge_extractions(
    section_extractions: list[SectionExtraction],
    source_document: str,
    sections: list[DocumentSection],
    client: Anthropic | None = None,
) -> tuple[OntologyGraph, list[dict]]:
    """Merge all per-section extractions into a single OntologyGraph.

    Groups entities by type and uses an LLM to identify semantic duplicates.
    Updates relationship references to point to canonical entity IDs.

    Args:
        section_extractions: Results from per-section extraction.
        source_document: The full original document text.
        sections: The document sections from segmentation.
        client: Anthropic client for LLM dedup calls.

    Returns:
        Tuple of (OntologyGraph, dedup_log for result storage).
    """
    # Collect all entities and relationships
    all_entities: list[BaseEntitySchema] = []
    all_relationships: list[Relationship] = []

    for se in section_extractions:
        all_entities.extend(se.entities)
        all_relationships.extend(se.relationships)

    print(f"    Collected {len(all_entities)} entities, {len(all_relationships)} relationships from {len(section_extractions)} sections")

    # Run LLM-based deduplication
    if client is not None:
        merged_entities, dedup_relationships, id_mapping, merge_count, api_calls, dedup_log = (
            _llm_deduplicate_entities(all_entities, client)
        )
    else:
        # No client — pass through without dedup
        merged_entities = all_entities
        dedup_relationships = []
        id_mapping = {}
        merge_count = 0
        api_calls = 0
        dedup_log = []

    # Update relationship references using the ID mapping
    merged_relationships = _update_relationships(all_relationships, id_mapping)

    # Add relationships discovered during dedup (equivalent_to, part_of)
    merged_relationships.extend(dedup_relationships)

    # Remove duplicate relationships
    merged_relationships = _deduplicate_relationships(merged_relationships)

    # Validate no orphaned relationships
    entity_ids = {e.id for e in merged_entities}
    orphaned = [
        r for r in merged_relationships
        if r.source_id not in entity_ids or r.target_id not in entity_ids
    ]
    if orphaned:
        print(f"    WARNING: {len(orphaned)} orphaned relationships (referencing non-existent entities)")
        # Remove orphaned relationships
        merged_relationships = [
            r for r in merged_relationships
            if r.source_id in entity_ids and r.target_id in entity_ids
        ]

    # Compute source offsets for entities
    _compute_source_offsets(merged_entities, source_document)

    # Build metadata
    metadata = ExtractionMetadata(
        document_char_count=len(source_document),
        section_count=len(sections),
        extraction_passes=len(section_extractions),
        total_api_calls=api_calls,
        final_entity_count=len(merged_entities),
        final_relationship_count=len(merged_relationships),
        semantic_dedup_merges=merge_count,
        semantic_dedup_api_calls=api_calls,
    )

    ontology = OntologyGraph(
        entities=merged_entities,
        relationships=merged_relationships,
        source_sections=sections,
        source_document=source_document,
        extraction_metadata=metadata,
    )

    return ontology, dedup_log


# ---------------------------------------------------------------------------
# LLM-based deduplication
# ---------------------------------------------------------------------------


def _build_entities_block(entities: list[BaseEntitySchema]) -> str:
    """Format entities as a JSON array for the dedup prompt."""
    items = []
    for e in entities:
        item: dict = {
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description,
            "source_text": e.source_anchor.source_text,
            "source_section": e.source_anchor.source_section,
        }
        # Include typed attributes (type-specific fields + extras)
        typed_attrs = get_typed_attributes(e)
        if typed_attrs:
            item["typed_attributes"] = typed_attrs
        items.append(item)
    return json.dumps(items, indent=2, ensure_ascii=False)


def _parse_dedup_response(raw: str) -> list[dict]:
    """Parse JSON array from LLM dedup response."""
    cleaned = raw.strip()
    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group())
        raise


def _llm_deduplicate_entities(
    entities: list[BaseEntitySchema],
    client: Anthropic,
) -> tuple[list[BaseEntitySchema], list[Relationship], dict[str, str], int, int, list[dict]]:
    """Use LLM to deduplicate entities by type group.

    Groups entities by type, sends each group to the LLM, and gets back
    a deduplicated entity list with merged descriptions, attributes, source
    anchors, and inter-entity relationships (equivalent_to, part_of).

    Returns:
        Tuple of:
            - deduplicated entities (list[BaseEntitySchema])
            - new relationships discovered during dedup (list[Relationship])
            - id_mapping old->new (dict[str, str])
            - merge count (int)
            - api call count (int)
            - dedup log for result storage (list[dict])
    """
    # Group entities by type
    by_type: dict[str, list[BaseEntitySchema]] = defaultdict(list)
    for entity in entities:
        by_type[entity.type].append(entity)

    id_mapping: dict[str, str] = {}
    merge_count = 0
    api_calls = 0
    dedup_log: list[dict] = []
    all_deduped: list[BaseEntitySchema] = []
    new_relationships: list[Relationship] = []

    for entity_type, type_entities in sorted(by_type.items()):
        if len(type_entities) == 1:
            # Single entity — pass through, populate source_anchors
            entity = type_entities[0]
            entity.source_anchors = [SourceAnchor(
                source_text=entity.source_anchor.source_text,
                source_section=entity.source_anchor.source_section,
                source_offset=entity.source_anchor.source_offset,
            )]
            all_deduped.append(entity)
            continue

        print(f"    Deduplicating {len(type_entities)} entities of type '{entity_type}'...")

        # Build prompt
        entities_block = _build_entities_block(type_entities)
        prompt = DEDUP_PROMPT.format(
            ENTITY_TYPE=entity_type,
            ENTITIES=entities_block,
        )

        _dbg(f"PROMPT for type '{entity_type}' ({len(type_entities)} entities)", prompt)

        # Call LLM
        log_entry: dict = {
            "entity_type": entity_type,
            "input_count": len(type_entities),
            "input_ids": [e.id for e in type_entities],
            "prompt": prompt,
        }

        try:
            # Scale token budgets based on group size
            thinking_budget = min(32768, max(4096, len(type_entities) * 800))
            max_tokens = thinking_budget + min(16384, max(4096, len(type_entities) * 300))
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                thinking={
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                },
                messages=[{"role": "user", "content": prompt}],
            )
            api_calls += 1

            # Extract text and thinking blocks from response
            raw_text = ""
            thinking_text = ""
            for block in response.content:
                if block.type == "thinking":
                    thinking_text = block.thinking
                elif block.type == "text":
                    raw_text = block.text

            log_entry["input_tokens"] = response.usage.input_tokens
            log_entry["output_tokens"] = response.usage.output_tokens
            log_entry["raw_response"] = raw_text
            if thinking_text:
                log_entry["thinking"] = thinking_text

            _dbg(
                f"THINKING for type '{entity_type}'",
                thinking_text,
            )
            _dbg(
                f"RESPONSE for type '{entity_type}' "
                f"({response.usage.input_tokens} in, {response.usage.output_tokens} out)",
                raw_text,
            )

            # Parse response
            deduped_list = _parse_dedup_response(raw_text)

            # Build lookup of original entities for source anchor collection
            originals_by_id = {e.id: e for e in type_entities}

            # Process each returned entity
            type_deduped: list[BaseEntitySchema] = []

            for item in deduped_list:
                merged_from = item.get("merged_from", [])

                # Build source_anchors from the LLM response
                raw_anchors = item.get("source_anchors", [])
                source_anchors = [
                    SourceAnchor(
                        source_text=a.get("source_text", ""),
                        source_section=a.get("source_section", ""),
                    )
                    for a in raw_anchors
                ]

                # If no source_anchors in response, collect from originals
                if not source_anchors and merged_from:
                    for orig_id in merged_from:
                        if orig_id in originals_by_id:
                            orig = originals_by_id[orig_id]
                            source_anchors.append(SourceAnchor(
                                source_text=orig.source_anchor.source_text,
                                source_section=orig.source_anchor.source_section,
                                source_offset=orig.source_anchor.source_offset,
                            ))

                # Primary source anchor = first (or best)
                primary_anchor = source_anchors[0] if source_anchors else SourceAnchor()

                # Build entity dict for typed schema validation.
                # Flatten "attributes" dict if LLM returned old-format.
                entity_dict: dict = {
                    "id": item["id"],
                    "type": item["type"],
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "source_anchor": primary_anchor.model_dump(),
                    "source_anchors": [a.model_dump() for a in source_anchors],
                }
                # Flatten legacy attributes dict to top-level
                if "attributes" in item and isinstance(item["attributes"], dict):
                    for k, v in item["attributes"].items():
                        if k not in entity_dict:
                            entity_dict[k] = v
                # Also carry any top-level typed attribute fields
                skip_keys = {"id", "type", "name", "description", "source_anchor",
                             "source_anchors", "attributes", "merged_from",
                             "relationships", "source_text", "source_section"}
                for k, v in item.items():
                    if k not in skip_keys and k not in entity_dict:
                        entity_dict[k] = v

                # Reconstruct as typed entity with merge-specific checks
                source_entities = [
                    originals_by_id[oid]
                    for oid in merged_from
                    if oid in originals_by_id
                ]
                entity, warnings = reconstruct_merged_entity(
                    entity_dict, source_entities
                )
                if warnings:
                    for w in warnings:
                        print(f"      [WARN] {w}")
                if entity is None:
                    print(f"      [WARN] Skipping entity '{item.get('id', '?')}' — failed validation")
                    continue
                type_deduped.append(entity)

                # Build id_mapping for relationship remapping
                for orig_id in merged_from:
                    if orig_id != entity.id:
                        id_mapping[orig_id] = entity.id

                # Extract relationships discovered during dedup
                for rel in item.get("relationships", []):
                    target_id = rel.get("target_id", "")
                    rel_type = rel.get("type", "")
                    if target_id and rel_type:
                        new_relationships.append(Relationship(
                            source_id=entity.id,
                            target_id=target_id,
                            type=rel_type,
                            description=f"{entity.name} {rel_type} {target_id}",
                            source_sections=[],
                        ))

            # Merge count = actual entity reduction (not ID renames)
            type_merges = len(type_entities) - len(type_deduped)
            type_new_rels = sum(
                len(item.get("relationships", []))
                for item in deduped_list
            )
            merge_count += type_merges
            log_entry["output_count"] = len(type_deduped)
            log_entry["merges"] = type_merges
            log_entry["new_relationships"] = type_new_rels
            log_entry["llm_response"] = deduped_list

            all_deduped.extend(type_deduped)
            rels_msg = f", {type_new_rels} relationships" if type_new_rels else ""
            print(f"      -> {len(type_deduped)} unique ({type_merges} merged{rels_msg})")

        except Exception as e:
            print(f"    WARNING: Dedup failed for type '{entity_type}': {e}")
            log_entry["error"] = str(e)
            # Fall back — keep all entities unchanged, populate source_anchors
            for entity in type_entities:
                entity.source_anchors = [SourceAnchor(
                    source_text=entity.source_anchor.source_text,
                    source_section=entity.source_anchor.source_section,
                    source_offset=entity.source_anchor.source_offset,
                )]
            all_deduped.extend(type_entities)

        dedup_log.append(log_entry)

    return all_deduped, new_relationships, id_mapping, merge_count, api_calls, dedup_log


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

    from dotenv import load_dotenv
    load_dotenv()
    client = None if args.no_dedup else Anthropic()
    ontology, dedup_log = merge_extractions(
        section_extractions, source_text, sections, client=client
    )

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
        f"({meta.semantic_dedup_merges} duplicates merged, "
        f"{meta.semantic_dedup_api_calls} API calls)"
    )


if __name__ == "__main__":
    main()
