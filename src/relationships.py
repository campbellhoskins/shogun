"""Stage 4: Full-document relationship extraction.

After entity deduplication (Pass 1 exact-ID + Pass 2 semantic), this stage
sends all deduplicated entities plus the full document to the LLM in a single
call. The LLM extracts every meaningful relationship grounded in the text.

Relationships are validated against the typed relationship schemas — invalid
relationships (wrong entity types for a given relationship type) are logged
but excluded from the final graph. Results are deduplicated against existing
per-section relationships from Stage 2.

CLI usage:
    python -m src.relationships <ontology.json> <chunks.json>
    python -m src.relationships <ontology.json> <chunks.json> --first-pass <first_pass.json>
    python -m src.relationships <ontology.json> <chunks.json> --debug
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

from anthropic import Anthropic
from dotenv import load_dotenv

from src.models import (
    DocumentSection,
    FirstPassDependency,
    FirstPassResult,
    Relationship,
    StageUsage,
)
from src.schemas import (
    BaseEntitySchema,
    generate_relationship_type_prompt_section,
    validate_relationship,
    validate_relationship_with_flip,
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
    safe = lambda s: s.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
        sys.stdout.encoding or "utf-8", errors="replace"
    )
    print(f"\n[DEBUG] {safe(header)}")
    if body:
        print("=" * 60)
        print(safe(body))
        print("=" * 60)


# ---------------------------------------------------------------------------
# Prompts (based on data/extract.txt)
# ---------------------------------------------------------------------------




RELATIONSHIP_SYSTEM_PROMPT = """\
You are an expert ontology knowledge graph extraction system. Your role is to \
extract relationships between entities that have already been identified in a \
section of a corporate travel policy document.

<pipeline_context>
Stage 2a (entity extraction) has already identified and validated all entities in this section. You receive those entities as input. Your task is to identify meaningful relationships between them, grounded in the section text.

Stage 3 receives entity and relationship sets from all sections simultaneously and resolves cross-section connections. Your relationship output must reference only entity IDs provided in the input. Any fabricated ID will create a dangling edge that breaks Stage 3 graph assembly.
</pipeline_context>

<graph_purpose>
This knowledge graph will be used by TMC agents during live incident
response to answer operational questions such as:
- "A Level 3 security incident just occurred — what are my timing
  obligations and who do I escalate to?"
- "The traveler replied NEED ASSISTANCE — what do I do next and
  how quickly?"
- "This booking was made off-channel — what services can I provide?"
- "It has been 90 minutes with no response — what is my next step?"

Prioritize extracting entities and relationships that support these
real-time decisions. Document-structural facts (which section defines
a term, which agreement incorporates another) are lower priority.
</graph_purpose>

<extraction_principles>
WHAT RELATIONSHIPS ARE
A relationship captures a specific, stated connection between two entities as evidenced by the section text. It represents how entities interact: governance, enablement, constraint, containment, classification, assignment, provision.

GROUNDING REQUIREMENT
Every relationship must be supported by specific text in the section. Do not infer relationships from general domain knowledge or from entity descriptions alone. If the section text does not state or clearly imply the connection, do not create the relationship.

DIRECTIONALITY
Relationships are directed (source → target). The source is the actor, subject, or governing entity; the target is the object, recipient, or governed entity. Do not create inverse duplicates.

ENTITY TYPE CONSTRAINTS
Each relationship type specifies permitted source and target entity types. Before producing a relationship, verify that the source entity's type and target entity's type match the permitted types. Relationships that violate type constraints are invalid and will be rejected by the pipeline validator.

NO ENTITY FABRICATION
Every source_id and target_id must exactly match an id from the provided entity list. If a valid relationship would require an entity that does not exist in the list, skip that relationship entirely. Do not create placeholder or implicit entities.
</extraction_principles>

<operational_priority>
EXTRACTION PRIORITY ORDER:
1. HIGHEST — Operational relationships: ACTIVATED_AT, ESCALATED_TO,
   TRIGGERS_ACTION, REQUIRES_AUTHORIZATION_FROM, SENT_TO, TRIGGERED_BY
2. HIGH — Service delivery: PROVIDES, ENABLED_BY, ENABLES_COVERAGE,
   REQUIRES_DATA, RESPONDS_WITH
3. MEDIUM — Classification: CLASSIFIED_AS, CATEGORIZED_AS, IMPACTS,
   BOOKED_THROUGH, HAS_BOOKING, ENGAGES
4. LOWER — Structural: DEFINED_IN, PARTY_TO, INCORPORATES,
   COMPLIES_WITH, ASSIGNED_TO, DESIGNATED_BY, RELATES_TO, OPERATES

Extract ALL valid relationships, but if you find yourself generating
many DEFINED_IN or PARTY_TO relationships without corresponding
operational relationships from the same text, re-read for operational
content you may have missed.
</operational_priority>

<attribute_awareness>
Entity schemas carry typed attributes that encode many operational
facts (SLO timing, activation thresholds, channel priority, TMC
actions, conditional triggers). Do NOT create relationships solely
to duplicate information already captured in entity attributes.

Focus relationships on connections BETWEEN entities that attributes
cannot capture: which services activate at which severity levels,
which contact roles receive escalations at which levels, which
incidents impact which travelers, which response statuses trigger
which services, which booking channels enable which services.
</attribute_awareness>

<procedural_sequences>
When the document describes ordered steps (e.g., "first SMS, then
Email, then Push Notification, then Voice Call"), extract FOLLOWED_BY
relationships between the sequential steps.

When an action is conditional (e.g., "Corporate Security is contacted
only for security-related incidents at Level 3+"), extract a
CONDITIONAL_ON relationship from the action/role to the condition entity.

When a Workflow entity exists and the section describes its component
steps, extract STEP_OF relationships from each step to the Workflow.
</procedural_sequences>

<relationship_types>
{relationship_types_section}
</relationship_types>

<output_schema>
Return a JSON object with key "relationships" containing an array. Each object:

  source_id        (string) Entity ID from provided list.
  target_id        (string) Entity ID from provided list.
  type             (string) From relationship_types above.
  description      (string) 1-2 sentences explaining the connection.

Produce the JSON object matching the schema described above.
</output_schema>"""


def _build_user_prompt(
    entities: list[BaseEntitySchema],
    sections: list[DocumentSection],
    cross_section_dependencies: list[FirstPassDependency],
) -> str:
    """Build the user prompt with entities, document sections, and dependencies."""
    parts: list[str] = []

    # --- Entities ---
    entity_list = [
        {
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description,
            "appears_in": e.appears_in,
        }
        for e in entities
    ]
    parts.append(
        "## ENTITIES\n\n"
        f"```json\n{json.dumps(entity_list, indent=2, ensure_ascii=False)}\n```"
    )

    # --- Build dependency index by section ---
    deps_by_section: dict[str, list[str]] = defaultdict(list)
    for dep in cross_section_dependencies:
        desc = (
            f"{dep.primary_section_id} {dep.dependency_type} "
            f"{dep.dependent_section_id}: {dep.dependency_description}"
        )
        deps_by_section[dep.primary_section_id].append(desc)
        deps_by_section[dep.dependent_section_id].append(desc)

    # --- Document sections with inline dependencies ---
    parts.append("## DOCUMENT\n")
    for s in sections:
        header_line = f"--- {s.section_id}: {s.header} ---"
        meta_lines = []
        if s.section_purpose:
            meta_lines.append(f"Purpose: {s.section_purpose}")
        if s.section_summary:
            meta_lines.append(f"Summary: {s.section_summary}")

        section_block = header_line + "\n"
        if meta_lines:
            section_block += "\n".join(meta_lines) + "\n\n"
        section_block += s.text.strip() + "\n"

        # Append cross-section dependencies relevant to this section
        if s.section_id in deps_by_section:
            section_block += "\nCross-section dependencies:\n"
            for dep_desc in deps_by_section[s.section_id]:
                section_block += f"- {dep_desc}\n"

        parts.append(section_block)

    # --- Closing instruction ---
    parts.append(
        f"\nExtract all meaningful relationships between the "
        f"{len(entity_list)} entities above grounded in the document text. "
        f"Produce the JSON object."
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_relationships(
    entities: list[BaseEntitySchema],
    sections: list[DocumentSection],
    cross_section_dependencies: list[FirstPassDependency],
    existing_relationships: list[Relationship],
    client: Anthropic,
    model: str | None = None,
) -> tuple[list[Relationship], list[dict], list[dict], StageUsage]:
    """Stage 4: Extract relationships across the full document.

    Args:
        entities: Deduplicated entity list from merge.
        sections: Document sections with text.
        cross_section_dependencies: From first pass analysis.
        existing_relationships: Per-section relationships from Stage 2 (for dedup).
        client: Anthropic client.

    Returns:
        Tuple of:
            - valid_relationships: Relationships that pass schema validation
            - invalid_relationships: Dicts with relationship + validation warnings
            - log: Pipeline log entries for result storage
            - usage: StageUsage with token counts
    """
    model = model or _DEFAULT_MODEL

    # Build relationship types section with source/target type constraints
    rel_types_section = generate_relationship_type_prompt_section()
    system_prompt = RELATIONSHIP_SYSTEM_PROMPT.format(
        relationship_types_section=rel_types_section,
    )
    user_prompt = _build_user_prompt(entities, sections, cross_section_dependencies)

    _dbg("SYSTEM PROMPT", system_prompt)
    _dbg(f"USER PROMPT ({len(entities)} entities, {len(sections)} sections)", user_prompt)

    print(f"    Sending {len(entities)} entities, {len(sections)} sections to LLM...")

    entity_ids = {e.id for e in entities}
    entity_type_lookup = {e.id: e.type for e in entities}

    # Build set of existing relationship keys for dedup
    existing_keys: set[tuple[str, str, str]] = {
        (r.source_id, r.target_id, r.type) for r in existing_relationships
    }

    log_entry: dict = {
        "entity_count": len(entities),
        "section_count": len(sections),
        "dependency_count": len(cross_section_dependencies),
        "existing_relationship_count": len(existing_relationships),
    }

    try:
        from src.models import RelationshipExtractionOutput

        thinking_budget = min(32768, max(8192, len(entities) * 500))
        max_tokens = thinking_budget + min(32768, max(8192, len(entities) * 300))

        raw_text = ""
        thinking_text = ""

        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            output_format=RelationshipExtractionOutput,
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

        # Parse from structured output
        parsed: RelationshipExtractionOutput = response.parsed_output
        raw_rels = [r.model_dump() for r in parsed.relationships]
        log_entry["total_extracted"] = len(raw_rels)
        print(f"    Extracted {len(raw_rels)} relationships from LLM")

        # Validate and categorize
        valid_relationships: list[Relationship] = []
        invalid_relationships: list[dict] = []
        dedup_count = 0
        orphan_count = 0

        for rel_dict in raw_rels:
            source_id = rel_dict.get("source_id", "")
            target_id = rel_dict.get("target_id", "")
            rel_type = rel_dict.get("type", "")
            description = rel_dict.get("description", "")

            # Check entity IDs exist
            if source_id not in entity_ids or target_id not in entity_ids:
                missing = []
                if source_id not in entity_ids:
                    missing.append(f"source_id '{source_id}'")
                if target_id not in entity_ids:
                    missing.append(f"target_id '{target_id}'")
                invalid_relationships.append({
                    **rel_dict,
                    "warnings": [f"Unknown entity: {', '.join(missing)}"],
                })
                orphan_count += 1
                continue

            # Check for duplicate against existing relationships
            key = (source_id, target_id, rel_type)
            if key in existing_keys:
                dedup_count += 1
                continue
            existing_keys.add(key)

            # Validate relationship type and entity type constraints
            # Try direction flip if original direction fails
            warnings, flipped = validate_relationship_with_flip(
                rel_type, source_id, target_id, entity_type_lookup
            )
            if warnings:
                invalid_relationships.append({
                    **rel_dict,
                    "warnings": warnings,
                })
                continue

            final_source = target_id if flipped else source_id
            final_target = source_id if flipped else target_id

            valid_relationships.append(Relationship(
                source_id=final_source,
                target_id=final_target,
                type=rel_type,
                description=description,
                source_sections=[],
            ))

        log_entry["valid_count"] = len(valid_relationships)
        log_entry["invalid_count"] = len(invalid_relationships)
        log_entry["dedup_count"] = dedup_count
        log_entry["orphan_count"] = orphan_count
        log_entry["invalid_relationships"] = invalid_relationships

        print(
            f"    Results: {len(valid_relationships)} valid, "
            f"{len(invalid_relationships)} invalid, "
            f"{dedup_count} deduplicated"
        )
        if invalid_relationships:
            for inv in invalid_relationships[:5]:
                warns = "; ".join(inv.get("warnings", []))
                print(f"      [INVALID] {inv.get('source_id')}->{inv.get('target_id')} ({inv.get('type')}): {warns}")
            if len(invalid_relationships) > 5:
                print(f"      ... and {len(invalid_relationships) - 5} more")

        usage = StageUsage(
            stage="stage4_relationships",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_calls=1,
        )
        return valid_relationships, invalid_relationships, [log_entry], usage

    except Exception as e:
        print(f"    WARNING: Relationship extraction failed: {e}")
        log_entry["error"] = str(e)
        return [], [], [log_entry], StageUsage(stage="stage4_relationships", model=model)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for standalone relationship extraction."""
    parser = argparse.ArgumentParser(
        prog="python -m src.relationships",
        description="Stage 4: Full-document relationship extraction.",
    )
    parser.add_argument(
        "ontology",
        help="Path to ontology.json (Stage 3b output with deduplicated entities).",
    )
    parser.add_argument(
        "chunks",
        help="Path to chunks.json (Stage 1 output with section text).",
    )
    parser.add_argument(
        "--first-pass",
        default=None,
        help="Path to first_pass.json (Stage 0 output, for cross-section dependencies).",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Path to write updated ontology with all relationships merged (default: print to stdout).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full prompts and responses.",
    )
    args = parser.parse_args(argv)

    global _DEBUG
    _DEBUG = args.debug

    # Load ontology for entities and existing relationships
    from src.models import OntologyGraph
    with open(args.ontology, encoding="utf-8") as f:
        ontology_data = json.load(f)
    ontology = OntologyGraph(**ontology_data)

    # Load chunks for section text
    with open(args.chunks, encoding="utf-8") as f:
        chunks_data = json.load(f)
    sections = []
    for c in chunks_data:
        sections.append(DocumentSection(
            section_id=c.get("section_id", c.get("chunk_id", "")),
            header=c.get("header", ""),
            section_number=c.get("section_number", ""),
            text=c["text"],
            source_offset=c.get("source_offset", 0),
            section_purpose=c.get("section_purpose", ""),
            section_summary=c.get("section_summary", ""),
        ))

    # Load cross-section dependencies
    cross_deps: list[FirstPassDependency] = []
    if args.first_pass:
        with open(args.first_pass, encoding="utf-8") as f:
            fp_data = json.load(f)
        fp = FirstPassResult(**fp_data)
        cross_deps = fp.cross_section_dependencies

    print(
        f"Loaded {len(ontology.entities)} entities, "
        f"{len(sections)} sections, "
        f"{len(cross_deps)} cross-section dependencies, "
        f"{len(ontology.relationships)} existing relationships"
    )

    client = Anthropic()
    valid_rels, invalid_rels, log, usage = extract_relationships(
        entities=ontology.entities,
        sections=sections,
        cross_section_dependencies=cross_deps,
        existing_relationships=ontology.relationships,
        client=client,
    )
    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out ({usage.api_calls} API call)")

    # Merge Stage 4 relationships with existing ones
    combined = list(ontology.relationships) + valid_rels
    seen_keys: set[tuple[str, str, str]] = set()
    deduped = []
    for r in combined:
        key = (r.source_id, r.target_id, r.type)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(r)
    ontology.relationships = deduped
    ontology.extraction_metadata.stage4_relationship_count = len(valid_rels)
    ontology.extraction_metadata.stage4_invalid_count = len(invalid_rels)
    ontology.extraction_metadata.final_relationship_count = len(deduped)

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(ontology.model_dump(), f, indent=2, ensure_ascii=False, default=str)
        print(
            f"\nWrote ontology to {args.output}: "
            f"{len(deduped)} total relationships "
            f"({len(ontology.relationships) - len(valid_rels)} existing + {len(valid_rels)} new)"
        )
    else:
        print(f"\n{len(valid_rels)} new relationships extracted, {len(deduped)} total")
        for r in valid_rels:
            print(f"  {r.source_id} --[{r.type}]--> {r.target_id}: {r.description}")


if __name__ == "__main__":
    main()
