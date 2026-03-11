"""Stage 3a: Cross-section relationship extraction.

Identifies relationships that SPAN sections — connections between an entity
extracted in one section and an entity extracted in a different section.
Runs after Stage 2 (per-section extraction) and before Stage 3b (merge/dedup).

CLI usage:
    python -m src.cross_section <extractions.json> <chunks.json> -o <cross_section.json>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

from src.models import Relationship, SectionExtraction, StageUsage
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
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """\
You are a cross-section relationship extraction system for corporate travel \
policy documents, operating at Stage 3a of a multi-stage ontology extraction \
pipeline.

<pipeline_context>
Stages 0–2 have completed:
- Stage 0: Full-document structural analysis and entity pre-registration.
- Stage 1: Document segmentation and section classification.
- Stage 2a: Per-section entity extraction. All entities have been validated.
- Stage 2b: Per-section intra-section relationship extraction. All relationships
  WITHIN each section have been captured.

You receive ALL section texts and ALL validated entities, grouped by section.
Your task is to identify relationships that SPAN sections — connections between
an entity in one section and an entity in a different section.

Stage 3b merges your output with Stage 2b intra-section relationships to produce
the complete knowledge graph. Your output is purely additive.
</pipeline_context>

<extraction_principles>
CROSS-SECTION CONSTRAINT
Every relationship you produce MUST connect entities from DIFFERENT sections.
If source_section equals target_section, the relationship is invalid and will
be rejected. Intra-section relationships were exhaustively extracted in Stage 2b.

TEXT GROUNDING
Every cross-section relationship must be grounded in actual document text. You
have the full text of every section. Find the passage that states or directly
implies the cross-section connection and quote it verbatim in source_anchor.

Cross-section connections appear in the text as:
- Explicit references: "as defined in Section 5", "services described in
  Section 3", "Severity Levels classified under Section 5"
- Scope statements: "This section applies to all Duty of Care Services"
  (linking this section's obligations to a Service defined elsewhere)
- Role assignments: "Direct Travel will provide..." in one section, with
  specific services enumerated in another
- Structural composition: an overview section listing service components,
  with detail sections defining each component

The grounding text will typically appear in ONE section — the section that
makes the cross-reference. The source_anchor should cite that section.

WHAT IS NOT GROUNDED
Do not create relationships based on:
- General domain knowledge ("TMCs typically operate platforms")
- Entity description similarity alone
- Type compatibility alone (two entity types CAN connect doesn't mean they DO)

If you cannot find specific text in any section that states or directly implies
the connection, do not create the relationship.

DIRECTIONALITY
Relationships are directed (source → target). Source is the actor, subject, or
governing entity; target is the object, recipient, or governed entity. Do not
create inverse duplicates.

ENTITY TYPE CONSTRAINTS
Each relationship type specifies permitted source and target entity types. Before
producing a relationship, verify that the source entity's type and target entity's
type match the permitted types.

NO ENTITY FABRICATION
Every source_id and target_id must exactly match an id from the provided entity
list. Do not create, rename, or infer entities.

DISCOVERY PATTERNS
Common cross-section relationship patterns:

  Composition    Overview section defines umbrella Service; detail sections
                 define specific sub-services. Look for "services described in
                 Section X" or enumerated service lists.
  Governance     One section states obligations; another defines the services
                 or roles those obligations govern.
  Enablement     Platform defined in one section enables services in another.
  Provision      Organization in one section provides services detailed elsewhere.
  Activation     SeverityLevel defined in one section triggers responses in another.
  Data flow      Service in one section requires data elements defined in another.
  Escalation     SeverityLevel in one section escalates to contacts in another.
  Compliance     Agreement references regulations defined or listed elsewhere.

These are prompts for where to look, not an exhaustive list.
</extraction_principles>

<relationship_types>
{relationship_types_section}
</relationship_types>

<output_schema>
Return a JSON object with key "relationships" containing an array. Each object:

  source_id        (string) Entity ID from provided list.
  target_id        (string) Entity ID from provided list.
  type             (string) From relationship_types above.
  description      (string) 1-2 sentences explaining the connection.

HARD CONSTRAINT: source_section (in the relationship) MUST differ from target_section.

Produce the JSON object matching the schema above.
</output_schema>

<validation_checklist>
Before including each relationship:
1. source_id exists in the provided entity list
2. target_id exists in the provided entity list
3. source entity's section ≠ target entity's section
4. Source entity's type matches permitted source type for the relationship type
5. Target entity's type matches permitted target type for the relationship type

If any check fails, do not include that relationship.
</validation_checklist>"""


def build_cross_section_system_prompt() -> str:
    """Build system prompt with auto-generated relationship types from schema registry."""
    return _SYSTEM_PREAMBLE.format(
        relationship_types_section=generate_relationship_type_prompt_section(),
    )


# ---------------------------------------------------------------------------
# User prompt
# ---------------------------------------------------------------------------


def build_cross_section_user_prompt(
    section_extractions: list[SectionExtraction],
) -> str:
    """Build the cross-section relationship extraction prompt from SectionExtractions.

    Lists all sections first (with metadata and text), then all entities
    with their section membership. This gives the LLM a complete picture
    of document structure before seeing entities.
    """
    from src.models import DocumentSection
    sections = [se.section for se in section_extractions]

    # Collect all entities with section membership
    entities: list[tuple[BaseEntitySchema, str]] = []
    for se in section_extractions:
        sid = se.section.section_id or se.section.section_number
        for e in se.entities:
            entities.append((e, sid))

    # Build entity slim list with appears_in
    entity_dicts = []
    for e, sid in entities:
        appears_in = getattr(e, "appears_in", None) or [sid]
        entity_dicts.append({
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description,
            "appears_in": appears_in,
        })

    return _build_user_prompt_core(sections, entity_dicts)


def build_cross_section_user_prompt_from_ontology(
    ontology: "OntologyGraph",
) -> str:
    """Build the cross-section relationship extraction prompt from a merged OntologyGraph.

    Same structure as the SectionExtraction version but uses deduplicated entities.
    """
    entities_slim = []
    for e in ontology.entities:
        appears_in = getattr(e, "appears_in", None) or []
        if not appears_in and e.source_anchor and e.source_anchor.source_section:
            appears_in = [e.source_anchor.source_section]
        entities_slim.append({
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description,
            "appears_in": appears_in,
        })

    return _build_user_prompt_core(ontology.source_sections, entities_slim)


def _build_user_prompt_core(
    sections: list,
    entities: list[dict],
) -> str:
    """Shared prompt builder: sections first, then all entities."""
    parts = []

    parts.append(
        "## DOCUMENT SECTIONS\n\n"
        "Below are all sections of the document. Read all sections before "
        "producing output. Create relationships ONLY between entities from "
        "DIFFERENT sections."
    )

    for section in sections:
        sid = section.section_id or section.section_number
        section_block = (
            f"### {sid}: {section.header}\n"
            f"Summary: {section.section_summary}\n\n"
            f"Text:\n"
            f"--- BEGIN ---\n"
            f"{section.text.strip()}\n"
            f"--- END ---"
        )
        parts.append(section_block)

    # All entities with section membership
    entity_block = json.dumps(entities, indent=2)
    parts.append(
        f"## ENTITIES ({len(entities)} total)\n\n"
        f"Each entity lists the sections it appears in via `appears_in`.\n\n"
        f"```json\n{entity_block}\n```"
    )

    parts.append(
        f"Extract all cross-section relationships across {len(sections)} "
        f"sections ({len(entities)} total entities). Every relationship must "
        f"connect entities from different sections and be grounded in the "
        f"document text above."
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM call + validation
# ---------------------------------------------------------------------------


def extract_cross_section_relationships(
    section_extractions: list[SectionExtraction],
    client: Anthropic | None = None,
    model: str | None = None,
) -> tuple[list[Relationship], dict, StageUsage]:
    """Extract cross-section relationships from per-section extractions."""
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    # Build entity lookup: id -> (type, section_id)
    entity_lookup: dict[str, tuple[str, str]] = {}
    for se in section_extractions:
        sid = se.section.section_id or se.section.section_number
        for e in se.entities:
            entity_lookup[e.id] = (e.type, sid)

    entity_type_lookup = {eid: etype for eid, (etype, _) in entity_lookup.items()}

    system_prompt = build_cross_section_system_prompt()
    user_prompt = build_cross_section_user_prompt(section_extractions)

    total_entities = sum(len(se.entities) for se in section_extractions)
    print(
        f"    Cross-section extraction: {len(section_extractions)} sections, "
        f"{total_entities} entities (model: {model})"
    )

    return _run_cross_section_llm(
        system_prompt, user_prompt,
        entity_lookup, entity_type_lookup,
        client, model,
    )


def extract_cross_section_from_ontology(
    ontology: "OntologyGraph",
    client: Anthropic | None = None,
    model: str | None = None,
) -> tuple[list[Relationship], dict, StageUsage]:
    """Extract cross-section relationships from a merged OntologyGraph.

    Uses deduplicated entities and their appears_in metadata.
    """
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    # Build entity lookup from ontology entities
    entity_lookup: dict[str, tuple[str, str]] = {}
    for e in ontology.entities:
        section = ""
        if e.appears_in:
            section = e.appears_in[0]
        elif e.source_anchor and e.source_anchor.source_section:
            section = e.source_anchor.source_section
        entity_lookup[e.id] = (e.type, section)

    entity_type_lookup = {eid: etype for eid, (etype, _) in entity_lookup.items()}

    system_prompt = build_cross_section_system_prompt()
    user_prompt = build_cross_section_user_prompt_from_ontology(ontology)

    print(
        f"    Cross-section extraction: {len(ontology.source_sections)} sections, "
        f"{len(ontology.entities)} entities (model: {model})"
    )

    return _run_cross_section_llm(
        system_prompt, user_prompt,
        entity_lookup, entity_type_lookup,
        client, model,
    )


def _run_cross_section_llm(
    system_prompt: str,
    user_prompt: str,
    entity_lookup: dict[str, tuple[str, str]],
    entity_type_lookup: dict[str, str],
    client: Anthropic,
    model: str,
) -> tuple[list[Relationship], dict, StageUsage]:
    """Shared LLM call + validation for cross-section extraction."""
    _dbg(f"SYSTEM PROMPT ({len(system_prompt)} chars)", system_prompt)
    _dbg(f"USER PROMPT ({len(user_prompt)} chars)", user_prompt)

    log: dict = {
        "total_entities": len(entity_lookup),
        "system_prompt_length": len(system_prompt),
        "user_prompt_length": len(user_prompt),
    }

    try:
        from src.models import CrossSectionRelOutput

        raw_text = ""
        thinking_text = ""
        input_tokens = 0
        output_tokens = 0

        from src.llm import thinking_config
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            system=system_prompt,
            output_format=CrossSectionRelOutput,
            thinking=thinking_config(model, budget_tokens=10000),
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            if _DEBUG:
                print("\n[DEBUG] STREAMING RESPONSE")
                print("=" * 60)
                for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "thinking":
                            print("\n--- THINKING ---")
                        elif block.type == "text":
                            print("\n--- TEXT ---")
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "thinking"):
                            print(delta.thinking, end="", flush=True)
                        elif hasattr(delta, "text"):
                            print(delta.text, end="", flush=True)
                print("\n" + "=" * 60)
            response = stream.get_final_message()

        for block in response.content:
            if block.type == "thinking":
                thinking_text = block.thinking
            elif block.type == "text":
                raw_text = block.text

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        log["input_tokens"] = input_tokens
        log["output_tokens"] = output_tokens
        log["raw_response"] = raw_text
        if thinking_text:
            log["thinking"] = thinking_text

        _dbg(f"THINKING ({len(thinking_text)} chars)", thinking_text)
        _dbg(
            f"RESPONSE ({input_tokens} in, {output_tokens} out, {len(raw_text)} chars)",
            raw_text,
        )

        # Parse from structured output
        parsed: CrossSectionRelOutput = response.parsed_output
        raw_rels = [r.model_dump() for r in parsed.relationships]
        log["raw_relationship_count"] = len(raw_rels)

        # Validate each relationship
        validated: list[Relationship] = []
        rejected: list[dict] = []

        for r in raw_rels:
            source_id = str(r.get("source_id", ""))
            target_id = str(r.get("target_id", ""))
            rel_type = str(r.get("type", ""))
            description = str(r.get("description", ""))

            if source_id not in entity_lookup:
                rejected.append({"reason": f"source_id '{source_id}' not found", **r})
                continue
            if target_id not in entity_lookup:
                rejected.append({"reason": f"target_id '{target_id}' not found", **r})
                continue

            actual_source_section = entity_lookup[source_id][1]
            actual_target_section = entity_lookup[target_id][1]

            if actual_source_section == actual_target_section:
                rejected.append({
                    "reason": f"same section ({actual_source_section})", **r,
                })
                continue

            warnings, flipped = validate_relationship_with_flip(
                rel_type, source_id, target_id, entity_type_lookup
            )
            if warnings:
                rejected.append({"reason": "; ".join(warnings), **r})
                continue

            final_source = target_id if flipped else source_id
            final_target = source_id if flipped else target_id

            final_source_section = entity_lookup[final_source][1]
            final_target_section = entity_lookup[final_target][1]
            if final_source_section == final_target_section:
                rejected.append({
                    "reason": f"same section after direction flip ({final_source_section})",
                    **r,
                })
                continue

            anchor = r.get("source_anchor", {})
            anchor_section = str(anchor.get("source_section", final_source_section))

            validated.append(Relationship(
                source_id=final_source,
                target_id=final_target,
                type=rel_type,
                description=description,
                source_sections=[anchor_section],
            ))

        log["validated_count"] = len(validated)
        log["rejected_count"] = len(rejected)
        if rejected:
            log["rejected"] = rejected

        print(
            f"    -> {len(validated)} cross-section relationships "
            f"({len(rejected)} rejected)"
        )

        usage = StageUsage(
            stage="stage3a_cross_section",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_calls=1,
        )
        return validated, log, usage

    except Exception as e:
        print(f"    WARNING: Cross-section extraction failed: {e}")
        log["error"] = str(e)
        return [], log, StageUsage(stage="stage3a_cross_section", model=model)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _sections_from_chunks(chunks: list[dict]) -> list:
    """Reconstruct DocumentSection objects from chunks.json dicts."""
    from src.models import DocumentSection

    sections = []
    for c in chunks:
        sections.append(DocumentSection(
            section_id=c.get("section_id", c.get("chunk_id", "")),
            header=c.get("header", ""),
            section_number=c.get("section_number", ""),
            text=c["text"],
            source_offset=c.get("source_offset", 0),
            section_purpose=c.get("section_purpose", ""),
            section_summary=c.get("section_summary", ""),
        ))
    return sections


def _extractions_from_json(
    extractions_data: list[dict], sections: list,
) -> list[SectionExtraction]:
    """Reconstruct SectionExtraction objects from extractions.json + sections."""
    from src.models import DocumentSection
    from src.schemas import validate_entity

    section_by_id = {s.section_id: s for s in sections}

    results = []
    for ext in extractions_data:
        sid = ext.get("section_id", ext.get("chunk_id", ""))
        section = section_by_id.get(sid)
        if section is None:
            sec_num = ext.get("section_number", "")
            for s in sections:
                if s.section_number == sec_num:
                    section = s
                    break
            if section is None:
                section = DocumentSection(
                    section_id=sid,
                    section_number=ext.get("section_number", ""),
                    text="",
                )

        entities = []
        for e_data in ext.get("entities", []):
            if "attributes" in e_data and isinstance(e_data["attributes"], dict):
                attrs = e_data.pop("attributes")
                for k, v in attrs.items():
                    if k not in e_data:
                        e_data[k] = v
            entity, warnings = validate_entity(e_data)
            if entity is not None:
                entities.append(entity)

        relationships = [Relationship(**r) for r in ext.get("relationships", [])]

        results.append(SectionExtraction(
            section=section,
            entities=entities,
            relationships=relationships,
        ))
    return results


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: extract cross-section relationships."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cross_section",
        description="Extract cross-section relationships.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--ontology",
        help="Path to merged ontology.json (uses deduplicated entities).",
    )
    source.add_argument(
        "--extractions",
        help="Path to extractions.json (Stage 2 output, requires --chunks).",
    )
    parser.add_argument(
        "--chunks",
        help="Path to chunks.json (required with --extractions).",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/cross_section.json",
        help="Path to write cross-section relationships JSON.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full system prompt, user prompt, thinking, and LLM response.",
    )
    args = parser.parse_args(argv)

    global _DEBUG
    _DEBUG = args.debug

    client = Anthropic()

    if args.ontology:
        from src.models import OntologyGraph
        data = json.loads(open(args.ontology, encoding="utf-8").read())
        if "ontology" in data and isinstance(data["ontology"], dict):
            data = data["ontology"]
        ontology = OntologyGraph(**data)
        print(f"Loaded ontology: {len(ontology.entities)} entities, {len(ontology.source_sections)} sections")
        rels, log, usage = extract_cross_section_from_ontology(ontology, client=client)
    else:
        if not args.chunks:
            parser.error("--chunks is required when using --extractions")
        with open(args.extractions, encoding="utf-8") as f:
            extractions_data = json.load(f)
        with open(args.chunks, encoding="utf-8") as f:
            chunks_data = json.load(f)
        print(f"Loaded {len(extractions_data)} extractions, {len(chunks_data)} chunks")
        sections = _sections_from_chunks(chunks_data)
        section_extractions = _extractions_from_json(extractions_data, sections)
        rels, log, usage = extract_cross_section_relationships(section_extractions, client=client)

    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out ({usage.api_calls} API call)")

    # Write relationships
    output_data = {
        "relationships": [r.model_dump() for r in rels],
        "log": log,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)

    print(f"Wrote {len(rels)} cross-section relationships to {args.output}")


if __name__ == "__main__":
    main()
