"""Stage 2: Two-pass per-section extraction — entities first, then relationships.

Pass 1 extracts entities with base fields only (no typed attributes).
Pass 2 receives validated entities and extracts relationships, constrained
to reference only entity IDs that actually exist. 

CLI usage:
    python -m src.extraction <chunks.json> -o <extractions.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

from src.llm import thinking_config

# Default model for extraction calls — loaded from .env
import os
from dotenv import load_dotenv
load_dotenv()
_DEFAULT_MODEL = os.environ.get("_DEFAULT_MODEL", "claude-haiku-4-5-20251001")

from src.models import (
    DocumentSection,
    FirstPassEntity,
    FirstPassResult,
    Relationship,
    RelationshipExtractionOutput,
    SectionExtraction,
    SourceAnchor,
    StageUsage,
)
from src.schemas import (
    BaseEntitySchema,
    generate_entity_type_prompt_section,
    generate_relationship_type_prompt_section,
    validate_entity,
)

# Module-level debug flag — set via CLI --debug or programmatically
_DEBUG = False


def _dbg(header: str, body: str = "", indent: int = 0) -> None:
    """Print debug output when _DEBUG is enabled."""
    if not _DEBUG:
        return
    prefix = "  " * indent
    print(f"\n{prefix}[DEBUG] {header}")
    if body:
        print(f"{prefix}{'=' * 60}")
        print(body)
        print(f"{prefix}{'=' * 60}")


# ============================================================
# PASS 1: ENTITY-ONLY PROMPTS
# ============================================================

ENTITY_SYSTEM_PROMPT = """\
You are an expert ontology knowledge graph extraction system specializing in \
corporate travel policy documents. Your role is to perform entity \
extraction on a single designated section of a travel policy document.

<pipeline_integration>
You are operating at STAGE 2 of a multi-stage pipeline.
Your output feeds directly into:
- Stage 3: Cross-section relationship extraction. Entity names must be
  identical across sections for Stage 3 to resolve entity identity.
- Stage 4: Global deduplication and merge. Inconsistent naming generates
  merge conflicts.
</pipeline_integration>

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

<entity_model>
WHAT ENTITIES ARE
Entities are discrete, identifiable things (nouns): organizations, roles,
regulations, services, platforms, agreements, defined terms.

WHAT ENTITIES ARE NOT
Do not create an entity to wrap a simple assertion. If a statement is fully captured as a relationship between two existing entities, it is a relationship, not an entity.

Exception: Create an Obligation entity when a requirement has its own
constraints, exceptions, conditional logic, or must be independently
referenceable.

GRANULARITY CALIBRATION
A typical 2000-character section yields 5–15 entities. Significantly more suggests you are wrapping simple assertions as entities. Significantly fewer suggests you are collapsing list members or missing genuine entities.
</entity_model>

<decomposition_rules>
SEVERITY LEVELS: If the document defines multiple severity levels
(e.g., Level 1 through Level 4), create a SEPARATE entity for each
level. Each level carries distinct obligations and must be
independently addressable in the graph.

ALERT TEMPLATES: If the document provides message templates per
severity level and per channel, extract each template as a separate
Alert entity with severity_level, channel, and channel_priority_order
populated.

TRAVELER RESPONSE STATUSES: Extract each status as a separate entity
with tmc_action, action_time_target, closes_outreach, and
triggers_escalation populated from the document's response action
tables.

CONTACT ROLES: Extract each escalation roster role with
escalation_severity_levels and escalation_condition populated
from the escalation tables and procedures.
</decomposition_rules>

<procedural_sequences>
WORKFLOWS: When the document describes a named multi-step procedure
(e.g., welfare check outreach sequence, Crisis Bridge establishment
protocol, escalation procedure), extract a Workflow entity with
trigger_condition, step_count, and time_constraint populated.

The individual steps of the workflow should be extracted as their
own entities (Service, Alert, Obligation) and will be connected to
the Workflow via STEP_OF and FOLLOWED_BY relationships in the
relationship extraction pass.
</procedural_sequences>

<entity_types>
{entity_types}
</entity_types>

<attribute_quality>
ATTRIBUTE POPULATION IS MANDATORY for typed entity schemas.

When extracting a SeverityLevel entity, leaving alert_time_target
empty when the document specifies "within 60 minutes" is a critical
extraction failure — it forces downstream consumers to parse the
description string, defeating the purpose of typed attributes.

Rule: If the document text provides a value that maps to a typed
attribute field, that field MUST be populated. The description field
captures context and nuance; typed attributes capture queryable facts.

ANTI-PATTERN: Putting "SLO for outreach is within 30 minutes" in
description while leaving alert_time_target="" empty.

CORRECT: alert_time_target="within 30 minutes" AND description
captures additional context like exceptions or conditions.
</attribute_quality>

<attribute_grounding>
Only populate a typed attribute if the CURRENT SECTION TEXT provides
a specific value for it. Do not infer or extrapolate attribute values
from context, from knowledge of other sections, or from the entity's
description in a pre-registration block.

If this section references a severity level but does not state its
SLO timing, leave alert_time_target empty. The defining section will
provide the authoritative value and the merge step will fill it in.
</attribute_grounding>

<output_schema>
Produce a JSON object with one key: "entities" containing an array.

Each entity requires:
- id: lowercase_with_underscores, descriptive
- type: one of the types above
- name: concise human-readable name
- description: what this entity represents, grounded in section text
- source_anchor: object with source_text and source_section
- All typed attributes defined for the entity's type (see entity_types
  above). Populate every attribute for which the section text provides
  a value.
</output_schema>

<pre_registration_rules>
These rules apply ONLY when the user message includes a PRE-REGISTERED ENTITIES block:

1. If a pre-registered entity is referenced in the section text, you MUST include it in your output using the pre-registered name character-for-character. Do not rename, abbreviate, or paraphrase.
2. You MAY assign a different entity type than the candidate_types suggest if section text provides clear evidence for reclassification.
3. If a pre-registered entity is NOT referenced in the section text, do not include it.
4. If a pre-registered entity IS referenced, include it even if this section adds no new attributes. Presence in a section is itself a graph fact.
5. The pre-registered list is intentionally incomplete. You are required to discover additional entities through independent analysis of the section text.
</pre_registration_rules>
"""


ENTITY_USER_PROMPT = """\
<document_context>
{document_metadata}
</document_context>

<section_metadata>
{section_metadata}
</section_metadata>

{pre_registration_block}\
<section_text section_id="{section_id}">
{section_text}
</section_text>

<task>
Extract all entities from section {section_id}. \
Do not extract from content outside <section_text>.
</task>
"""


# ============================================================
# PASS 2: RELATIONSHIP-ONLY PROMPTS
# ============================================================

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
Use ONLY the types below. The Source Type and Target Type columns are hard constraints — the entity referenced by source_id must have the listed type, and likewise for target_id.

{relationship_types_section}

</relationship_types>

<output_schema>
Produce a JSON object with one key: "relationships" containing an array of relationships.
Each relationship must have:
- **source_id**: MUST exactly match an entity id from the EXTRACTED ENTITIES list above
- **target_id**: MUST exactly match an entity id from the EXTRACTED ENTITIES list above
- **type**: One of the relationship types listed above
- **description**: A specific description of HOW these entities relate, drawn \
  from the section text
Ensure that the output is in valid JSON format. Do not include any text outside the JSON object.
</output_schema>
"""


RELATIONSHIP_USER_PROMPT = """\
## SECTION TEXT

--- BEGIN ---
{section_text}
--- END ---

## ENTITIES IN SECTION {section_id}

Extract relationships ONLY between entities listed below. \
Every source_id and target_id must exactly match an id from this list.

```json
{entities_json}
```

Extract all relationships from section {section_id}. Return in valid JSON format.
"""


# ============================================================
# PROMPT BUILDERS
# ============================================================


def _get_relevant_pre_registered(
    section: DocumentSection,
    first_pass_result: FirstPassResult,
) -> list[FirstPassEntity]:
    """Filter global_entity_pre_registration to entities relevant to this section."""
    section_id = section.section_id
    if not section_id or not first_pass_result.global_entity_pre_registration:
        return []

    return [
        e for e in first_pass_result.global_entity_pre_registration
        if section_id in e.mentioned_in_sections
    ]


def _build_entity_prompt(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    first_pass_result: FirstPassResult,
) -> tuple[str, str]:
    """Build the system + user prompts for Pass 1 (entity extraction).

    Uses the slim entity type list (type names + descriptions only, no
    typed attribute fields) to minimize prompt size.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    fp = first_pass_result
    dm = fp.document_map

    _dbg(
        f"_build_entity_prompt [{section.section_number}] {section.header}",
        f"section_id: {section.section_id}\n"
        f"section_text length: {len(section.text)} chars\n"
        f"Building entity prompt...",
    )

    # Build document metadata block — only include populated fields
    doc_lines = []
    if dm.document_title:
        doc_lines.append(f"  Title: {dm.document_title}")
    if dm.issuing_organization:
        doc_lines.append(f"  Issuing Organization: {dm.issuing_organization}")
    if dm.effective_date:
        doc_lines.append(f"  Effective Date: {dm.effective_date}")
    if dm.document_purpose_summary:
        doc_lines.append(f"  Purpose: {dm.document_purpose_summary}")
    document_metadata = "\n".join(doc_lines) if doc_lines else "Document-level metadata was not extractable from this document."

    # Build section metadata block — only include populated fields
    sec_lines = []
    sid = section.section_id or section.section_number
    if sid:
        sec_lines.append(f"  ID: {sid}")
    if section.header:
        sec_lines.append(f"  Name: {section.header}")
    if section.section_purpose:
        sec_lines.append(f"  Purpose: {section.section_purpose}")
    if section.section_summary:
        sec_lines.append(f"  Summary: {section.section_summary}")
    section_metadata = "\n".join(sec_lines)

    # Build pre-registration block — only include if there are relevant entities
    pre_registered = _get_relevant_pre_registered(section, first_pass_result)
    if pre_registered:
        entity_lines = []
        for e in pre_registered:
            types_str = ", ".join(e.candidate_types) if e.candidate_types else "untyped"
            line = f'  - name: "{e.entity_name}"\n'
            line += f"    candidate_types: [{types_str}]\n"
            line += f"    note: {e.brief_description}"
            entity_lines.append(line)
        entities_block = "\n".join(entity_lines)
        pre_registration_block = (
            f"<pre_registered_entities>\n"
            f"Use each name character-for-character if it appears in section text.\n"
            f"See system instructions for full binding rules.\n\n"
            f"{entities_block}\n"
            f"</pre_registered_entities>\n\n"
        )
        _dbg(
            f"pre_registered_entities [{sid}]",
            f"{len(pre_registered)} entities:\n{entities_block}",
            indent=1,
        )
    else:
        pre_registration_block = ""

    user_prompt = ENTITY_USER_PROMPT.format(
        section_id=sid,
        document_metadata=document_metadata,
        section_metadata=section_metadata,
        pre_registration_block=pre_registration_block,
        section_text=section.text,
    )

    system_prompt = ENTITY_SYSTEM_PROMPT.format(
        entity_types=generate_entity_type_prompt_section(),
    )

    _dbg(
        f"ENTITY SYSTEM PROMPT ({len(system_prompt)} chars)",
        system_prompt,
    )
    _dbg(
        f"ENTITY USER PROMPT → LLM [{section.section_number}] ({len(user_prompt)} chars)",
        user_prompt,
    )

    return (system_prompt, user_prompt)


def _build_relationship_prompt(
    section: DocumentSection,
    validated_entities: list[BaseEntitySchema],
) -> tuple[str, str]:
    """Build the system + user prompts for Pass 2 (relationship extraction).

    Serializes validated entities to compact JSON and includes the full
    relationship type list with source/target constraints.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    # Compact entity representation for the relationship prompt
    entities_compact = [
        {
            "id": e.id,
            "type": e.type,
            "name": e.name,
            "description": e.description,
        }
        for e in validated_entities
    ]
    entities_json = json.dumps(entities_compact, indent=2)

    _dbg(
        f"_build_relationship_prompt [{section.section_number}]",
        f"entities: {len(validated_entities)}\n"
        f"entities_json length: {len(entities_json)} chars",
    )

    sid = section.section_id or section.section_number

    system_prompt = RELATIONSHIP_SYSTEM_PROMPT.format(
        relationship_types_section=generate_relationship_type_prompt_section(),
    )

    user_prompt = RELATIONSHIP_USER_PROMPT.format(
        section_id=sid,
        section_text=section.text.strip(),
        entities_json=entities_json,
    )

    _dbg(
        f"REL SYSTEM PROMPT ({len(system_prompt)} chars)",
        system_prompt,
    )
    _dbg(
        f"REL USER PROMPT → LLM [{section.section_number}] ({len(user_prompt)} chars)",
        user_prompt,
    )

    return (system_prompt, user_prompt)


# ============================================================
# RESPONSE PARSING
# ============================================================


import re


def _extract_text_block(response) -> str:
    """Extract the text content block from an API response (skip thinking blocks)."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM text with progressive fallback.

    1. Raw json.loads
    2. Strip markdown fences (```json ... ```)
    3. Strip control characters
    4. Raise ValueError with context
    """
    # Attempt 1: raw parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: strip markdown fences
    stripped = re.sub(r"```(?:json)?\s*\n?", "", text).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Attempt 3: strip control characters (except newline/tab)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", stripped)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        preview = text[:200] if len(text) > 200 else text
        raise ValueError(
            f"Failed to parse JSON after all fallbacks. Preview: {preview!r}"
        ) from exc


# ============================================================
# VALIDATION HELPERS
# ============================================================


def _build_validated_entities_from_parsed(
    parsed_entities: list, section: DocumentSection
) -> list[BaseEntitySchema]:
    """Post-process parsed AnyEntity objects from structured output.

    Stamps source_anchor section and appears_in. Re-validates through
    validate_entity() to ensure typed schema compliance.
    """
    entities = []
    for e in parsed_entities:
        # Convert parsed Pydantic model to dict for re-validation.
        # exclude_defaults strips empty typed-attribute fields from the flat
        # union model so validate_entity() doesn't warn about irrelevant fields.
        entity_dict = e.model_dump(exclude_defaults=True) if hasattr(e, "model_dump") else dict(e)

        # Ensure source_anchor has section info
        anchor = entity_dict.get("source_anchor", {})
        if not anchor.get("source_section"):
            anchor["source_section"] = section.section_id or section.section_number
            entity_dict["source_anchor"] = anchor

        # Flatten legacy "attributes" dict if present
        if "attributes" in entity_dict and isinstance(entity_dict["attributes"], dict):
            attrs = entity_dict.pop("attributes")
            for k, v in attrs.items():
                if k not in entity_dict:
                    entity_dict[k] = v

        entity, warnings = validate_entity(entity_dict)
        if warnings:
            for w in warnings:
                print(f"    [WARN] Section {section.section_number}: {w}")
        if entity is not None:
            if section.section_id:
                entity.appears_in = [section.section_id]
            entities.append(entity)

    return entities


def _build_validated_relationships(
    data: dict,
    entities: list[BaseEntitySchema],
    section: DocumentSection,
) -> list[Relationship]:
    """Validate raw relationship dicts with referential integrity checking.

    Relationships with source_id or target_id not matching any validated
    entity are skipped with a warning.
    """
    entity_ids = {e.id for e in entities}
    relationships = []
    dangling_count = 0

    for r in data.get("relationships", []):
        source_id = str(r.get("source_id", ""))
        target_id = str(r.get("target_id", ""))

        # Referential integrity check
        if source_id not in entity_ids or target_id not in entity_ids:
            dangling_count += 1
            missing = []
            if source_id not in entity_ids:
                missing.append(f"source_id={source_id}")
            if target_id not in entity_ids:
                missing.append(f"target_id={target_id}")
            _dbg(
                f"DANGLING REL [{section.section_number}]",
                f"Skipping relationship {r.get('type', '?')}: {', '.join(missing)}",
                indent=2,
            )
            continue

        relationships.append(
            Relationship(
                source_id=source_id,
                target_id=target_id,
                type=str(r.get("type", "")),
                description=str(r.get("description", "")),
                source_sections=[section.section_id or section.section_number],
            )
        )

    total = dangling_count + len(relationships)
    if dangling_count and total > 0:
        pct = dangling_count / total * 100
        print(
            f"    [WARN] Section {section.section_number}: "
            f"{dangling_count}/{total} relationships dangling ({pct:.0f}%)"
        )

    return relationships


# ============================================================
# RATE-LIMITED API CALL HELPER
# ============================================================


async def _api_call_with_retry(
    client: AsyncAnthropic,
    system_prompt: str,
    user_prompt: str,
    section_number: str,
    model: str,
    output_format: type | None = None,
    max_retries: int = 3,
    pass_name: str = "extraction",
) -> Any:
    """Make an async API call with rate-limit retry logic.

    Returns the raw API response object (ParsedMessage if output_format given).
    """
    for attempt in range(max_retries):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": 16384,
                "system": system_prompt,
                "thinking": thinking_config(model, budget_tokens=10000),
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if output_format is not None:
                kwargs["output_format"] = output_format
                response = await client.messages.parse(**kwargs)
            else:
                response = await client.messages.create(**kwargs)
            return response
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 2 ** attempt * 15  # 15s, 30s, 60s
                print(
                    f"    Rate limited on {pass_name} for section {section_number}, "
                    f"retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                if attempt == max_retries - 1:
                    raise
            else:
                raise
    # Should not reach here, but satisfy type checker
    raise RuntimeError(f"All {max_retries} retries exhausted for {pass_name}")


# ============================================================
# SYNC EXTRACTION (single section)
# ============================================================


def extract_section(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: Anthropic | None = None,
    first_pass_result: FirstPassResult | None = None,
    model: str | None = None,
) -> SectionExtraction:
    """Extract entities and relationships from a single section (two-pass).

    Pass 1: Extract entities only.
    Pass 2: Extract relationships constrained to validated entity IDs.

    Args:
        section: The section to extract from.
        all_sections: All sections for context outline.
        client: Anthropic client.
        first_pass_result: First pass output for global context.
        model: LLM model ID. Defaults to env TEST_MODEL.

    Returns:
        SectionExtraction with entities, relationships, and source anchoring.
    """
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    if first_pass_result is None:
        first_pass_result = FirstPassResult()

    # Pass 1: Entity extraction
    entity_sys, entity_user = _build_entity_prompt(section, all_sections, first_pass_result)

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=entity_sys,
        thinking=thinking_config(model, budget_tokens=10000),
        messages=[{"role": "user", "content": entity_user}],
    )

    try:
        raw_entities = _parse_json_response(_extract_text_block(response)).get("entities", [])
    except ValueError as exc:
        print(f"    [WARN] Section {section.section_number}: entity JSON parse failed: {exc}")
        raw_entities = []
    entities = _build_validated_entities_from_parsed(raw_entities, section)

    # Retry if zero entities
    if not entities and len(section.text.strip()) > 100:
        entities = _retry_entity_extraction(
            section, all_sections, client,
            first_pass_result=first_pass_result,
            model=model,
        )

    # Pass 2: Relationship extraction (skip if no entities)
    relationships: list[Relationship] = []
    if entities:
        rel_sys, rel_user = _build_relationship_prompt(section, entities)

        rel_response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=rel_sys,
            thinking=thinking_config(model, budget_tokens=10000),
            output_format=RelationshipExtractionOutput,
            messages=[{"role": "user", "content": rel_user}],
        )

        rel_parsed: RelationshipExtractionOutput = rel_response.parsed_output
        rel_data = {"relationships": [r.model_dump() for r in rel_parsed.relationships]}
        relationships = _build_validated_relationships(rel_data, entities, section)

    return SectionExtraction(
        section=section,
        entities=entities,
        relationships=relationships,
    )


def _retry_entity_extraction(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: Anthropic,
    first_pass_result: FirstPassResult | None = None,
    model: str | None = None,
) -> list[BaseEntitySchema]:
    """Retry entity extraction with a more aggressive prompt."""
    if first_pass_result is None:
        first_pass_result = FirstPassResult()
    model = model or _DEFAULT_MODEL

    entity_sys, entity_user = _build_entity_prompt(section, all_sections, first_pass_result)
    retry_prefix = (
        "IMPORTANT: Your previous extraction of this section produced ZERO entities. "
        "This section MUST contain at least one extractable fact. Look for: "
        "implicit rules, scope statements, organizational information, dates, "
        "roles mentioned, or any other factual claims.\n\n"
    )

    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=entity_sys,
        thinking=thinking_config(model, budget_tokens=10000),
        messages=[{"role": "user", "content": retry_prefix + entity_user}],
    )

    try:
        raw_entities = _parse_json_response(_extract_text_block(response)).get("entities", [])
    except ValueError as exc:
        print(f"    [WARN] Section {section.section_number}: entity retry JSON parse failed: {exc}")
        raw_entities = []
    return _build_validated_entities_from_parsed(raw_entities, section)


# ============================================================
# ASYNC EXTRACTION (single section, two-pass)
# ============================================================


async def _extract_section_async(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
    first_pass_result: FirstPassResult | None = None,
    model: str | None = None,
) -> tuple[SectionExtraction, StageUsage]:
    """Extract a single section asynchronously with two-pass approach.

    Both passes are sequential within the semaphore (pass 2 depends on pass 1).
    Different sections still run in parallel via asyncio.gather.

    Returns:
        Tuple of (SectionExtraction, StageUsage with accumulated token counts).
    """
    if first_pass_result is None:
        first_pass_result = FirstPassResult()
    model = model or _DEFAULT_MODEL

    section_input_tokens = 0
    section_output_tokens = 0
    section_api_calls = 0

    async with semaphore:
        # ---- Pass 1: Entity extraction ----
        entity_sys, entity_user = _build_entity_prompt(
            section, all_sections, first_pass_result
        )

        _dbg(
            f"ENTITY API CALL [{section.section_number}]",
            f"model: {model}\n"
            f"max_tokens: 16384 (thinking: adaptive/enabled)\n"
            f"system prompt length: {len(entity_sys)} chars\n"
            f"user prompt length: {len(entity_user)} chars",
        )

        response = await _api_call_with_retry(
            client, entity_sys, entity_user,
            section.section_number,
            model=model,
            max_retries=max_retries,
            pass_name="entity pass",
        )

        section_input_tokens += response.usage.input_tokens
        section_output_tokens += response.usage.output_tokens
        section_api_calls += 1

        try:
            raw_entities = _parse_json_response(_extract_text_block(response)).get("entities", [])
        except ValueError as exc:
            print(f"    [WARN] Section {section.section_number}: entity JSON parse failed: {exc}")
            raw_entities = []
        entities = _build_validated_entities_from_parsed(raw_entities, section)

        _dbg(
            f"ENTITY RESULT [{section.section_number}]",
            f"entities: {len(entities)}",
        )

        # Retry if zero entities
        if not entities and len(section.text.strip()) > 100:
            retry_prefix = (
                "IMPORTANT: Your previous extraction produced ZERO entities. "
                "This section MUST contain at least one extractable fact.\n\n"
            )

            _dbg(
                f"ENTITY RETRY [{section.section_number}] (zero entities)",
                f"Prepending retry prefix ({len(retry_prefix)} chars)",
            )

            response = await _api_call_with_retry(
                client, entity_sys, retry_prefix + entity_user,
                section.section_number,
                model=model,
                max_retries=max_retries,
                pass_name="entity retry",
            )

            section_input_tokens += response.usage.input_tokens
            section_output_tokens += response.usage.output_tokens
            section_api_calls += 1

            try:
                retry_raw = _parse_json_response(_extract_text_block(response)).get("entities", [])
            except ValueError as exc:
                print(f"    [WARN] Section {section.section_number}: entity retry JSON parse failed: {exc}")
                retry_raw = []
            entities = _build_validated_entities_from_parsed(retry_raw, section)

            _dbg(
                f"ENTITY RETRY RESULT [{section.section_number}]",
                f"entities: {len(entities)}",
            )

        # ---- Pass 2: Relationship extraction (skip if no entities) ----
        relationships: list[Relationship] = []
        if entities:
            rel_sys, rel_user = _build_relationship_prompt(section, entities)

            _dbg(
                f"REL API CALL [{section.section_number}]",
                f"entities provided: {len(entities)}\n"
                f"system prompt length: {len(rel_sys)} chars\n"
                f"user prompt length: {len(rel_user)} chars",
            )

            rel_response = await _api_call_with_retry(
                client, rel_sys, rel_user,
                section.section_number,
                model=model,
                output_format=RelationshipExtractionOutput,
                max_retries=max_retries,
                pass_name="relationship pass",
            )

            section_input_tokens += rel_response.usage.input_tokens
            section_output_tokens += rel_response.usage.output_tokens
            section_api_calls += 1

            rel_parsed: RelationshipExtractionOutput = rel_response.parsed_output
            rel_data = {"relationships": [r.model_dump() for r in rel_parsed.relationships]}
            relationships = _build_validated_relationships(rel_data, entities, section)

            _dbg(
                f"REL RESULT [{section.section_number}]",
                f"relationships: {len(relationships)}",
            )

        usage = StageUsage(
            stage="stage2_extraction",
            model=model,
            input_tokens=section_input_tokens,
            output_tokens=section_output_tokens,
            api_calls=section_api_calls,
        )

        return (
            SectionExtraction(
                section=section,
                entities=entities,
                relationships=relationships,
            ),
            usage,
        )


# ============================================================
# BATCH EXTRACTION
# ============================================================


def extract_all_sections(
    sections: list[DocumentSection],
    client: Anthropic | None = None,
    max_concurrent: int = 2,
    first_pass_result: FirstPassResult | None = None,
    model: str | None = None,
) -> tuple[list[SectionExtraction], StageUsage]:
    """Extract entities from all sections in parallel.

    Args:
        sections: List of document sections to extract from.
        client: Synchronous Anthropic client (used to get API key config).
        max_concurrent: Maximum concurrent API calls.
        first_pass_result: Optional first pass output for global context.
        model: LLM model ID. Defaults to env TEST_MODEL.

    Returns:
        Tuple of (list of SectionExtraction results, aggregated StageUsage).
    """
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    # Force sequential execution in debug mode so output is readable
    if _DEBUG:
        max_concurrent = 1
        _dbg(
            "extract_all_sections",
            f"Processing {len(sections)} sections SEQUENTIALLY (debug mode)\n"
            f"Sections: {', '.join(s.section_number for s in sections)}",
        )

    async def _run() -> tuple[list[SectionExtraction], StageUsage]:
        async_client = AsyncAnthropic()
        semaphore = asyncio.Semaphore(max_concurrent)

        tasks = [
            _extract_section_async(
                section, sections, async_client, semaphore,
                first_pass_result=first_pass_result,
                model=model,
            )
            for section in sections
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions and aggregate usage
        extractions = []
        total_input = 0
        total_output = 0
        total_calls = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(
                    f"  WARNING: Extraction failed for section "
                    f"'{sections[i].section_number}': {result}"
                )
                extractions.append(
                    SectionExtraction(section=sections[i])
                )
            else:
                extraction, section_usage = result
                extractions.append(extraction)
                total_input += section_usage.input_tokens
                total_output += section_usage.output_tokens
                total_calls += section_usage.api_calls

        usage = StageUsage(
            stage="stage2_extraction",
            model=model,
            input_tokens=total_input,
            output_tokens=total_output,
            api_calls=total_calls,
        )
        return extractions, usage

    return asyncio.run(_run())


# ============================================================
# UTILITIES
# ============================================================


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
            section_purpose=c.get("section_purpose", ""),
            section_summary=c.get("section_summary", ""),
        ))
    return sections




def serialize_extractions(extractions: list[SectionExtraction]) -> list[dict]:
    """Serialize SectionExtraction objects to the Stage 2 JSON contract.

    Output contains only chunk identifiers plus entities/relationships —
    no full section text or Pydantic reconstruction needed by the caller.
    """
    out = []
    for se in extractions:
        out.append({
            "section_id": se.section.section_id,
            "section_number": se.section.section_number,
            "entity_count": len(se.entities),
            "relationship_count": len(se.relationships),
            "entities": [e.model_dump() for e in se.entities],
            "relationships": [r.model_dump() for r in se.relationships],
        })
    return out


# ============================================================
# CLI ENTRY POINT
# ============================================================


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: extract entities/relationships from chunks."""
    global _DEBUG

    parser = argparse.ArgumentParser(
        prog="python -m src.extraction",
        description="Stage 2: Extract entities and relationships from chunked sections.",
    )
    parser.add_argument(
        "input",
        help="Path to chunks.json (Stage 1 output).",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/extractions.json",
        help="Path to write extractions JSON (default: data/extractions.json).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print every prompt, API call, and LLM response for tracing. "
             "Forces sequential execution so output is readable.",
    )
    parser.add_argument(
        "--first-pass",
        default=None,
        help="Path to first_pass.json (Stage 0 output) for global context.",
    )
    args = parser.parse_args(argv)

    _DEBUG = args.debug

    with open(args.input, encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks from {args.input}")

    fp_result = None
    if args.first_pass:
        with open(args.first_pass, encoding="utf-8") as f:
            fp_result = FirstPassResult(**json.load(f))
        print(f"Loaded first pass from {args.first_pass}")

    sections = _sections_from_chunks(chunks)
    extractions, usage = extract_all_sections(sections, first_pass_result=fp_result)
    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out ({usage.api_calls} API calls)")

    data = serialize_extractions(extractions)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total_entities = sum(d["entity_count"] for d in data)
    total_rels = sum(d["relationship_count"] for d in data)
    print(f"Wrote {len(data)} sections ({total_entities} entities, {total_rels} relationships) to {args.output}")


if __name__ == "__main__":
    main()
