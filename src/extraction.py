"""Stage 2: Per-section entity and relationship extraction with source anchoring.

Extracts entities and relationships from each document section independently,
with mandatory source text anchoring for every entity.

CLI usage:
    python -m src.extraction <chunks.json> -o <extractions.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

# Thinking configuration for extraction calls
_THINKING_CONFIG = {"type": "enabled", "budget_tokens": 10000}

# Model used for extraction calls
_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

from src.models import (
    DocumentSection,
    EnumeratedList,
    FirstPassEntity,
    FirstPassResult,
    FirstPassSection,
    HierarchyEntry,
    Relationship,
    SectionExtraction,
    SourceAnchor,
)
from src.schemas import (
    generate_entity_structure_prompt_section,
    generate_entity_type_prompt_section,
    generate_example_entity,
    generate_example_relationship,
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


EXTRACTION_SYSTEM_PROMPT = """\
You are an expert ontology knowledge graph extraction system specializing in \
corporate travel policy documents. Your role is to perform exhaustive entity \
and relationship extraction on a single designated section of a travel policy \
document.

You are operating at STAGE 2 of a multi-stage pipeline. Your output will be \
consumed by downstream stages as follows:

Stage 3 receives all section-level entity sets simultaneously and identifies \
cross-section relationships. Consistent canonical entity naming in your output \
is required for Stage 3 to correctly resolve cross-section entity identity. If \
you rename a pre-registered entity, Stage 3 will treat it as a different \
entity and the cross-section relationship will be lost.

Stage 4 deduplicates and merges the complete entity registry across all \
sections. Inconsistent naming of the same entity across sections will generate \
merge conflicts that require manual resolution.

You have been provided with the following inputs:

Document-level context — establishes the governing document's identity and \
purpose.
Section metadata — identifies the section you are processing, its functional \
classification, and its role within the document.
Global entity pre-registration — a seed list of entities that span multiple \
sections, with canonical names you must use exactly. This list is intentionally \
incomplete. Independent entity discovery is required.
Section text — the raw text of the section you are extracting from. All \
entities and relationships must be grounded in this text.

You must be precise, exhaustive, and consistent. Every output field you produce \
will be consumed programmatically by downstream pipeline stages. Follow the \
output schema exactly as specified."""


EXTRACTION_USER_PROMPT = """\
## PIPELINE CONTEXT

You are processing section {section_id} of a travel policy document as part of \
a multi-stage ontology extraction pipeline. All context required for correct \
extraction is provided below. Read every section of this message before \
producing any output.

---

## DOCUMENT CONTEXT

Document Title:       {document_title}
Issuing Organization: {issuing_organization}
Effective Date:       {effective_date}
Document Purpose:     {document_purpose_summary}

---

## SECTION BEING PROCESSED

Section ID:                     {section_id}
Section Name:                   {section_name}
Section Purpose Classification: {section_purpose}
Section Summary:                {section_summary}

---

## GLOBAL ENTITY PRE-REGISTRATION

The following entities have been pre-registered by Stage 1 because they appear \
across multiple sections of this document. Each entry includes a canonical name, \
provisional type suggestions, and an identity disambiguation note.

BINDING INSTRUCTIONS:
- If any pre-registered entity is referenced in your section text, you MUST use \
  its entity_name value character-for-character as the entity name in your \
  output. Do not rename, abbreviate, shorten, or paraphrase pre-registered \
  entity names under any circumstances.
- You may classify a pre-registered entity under a different entity type than \
  the candidate_types suggest if the section text provides clear evidence for a \
  different classification.
- If a pre-registered entity is NOT referenced in this section's text, do not \
  include it in your output.
- If a pre-registered entity IS referenced in this section's text, you MUST \
  include it in your entities array even if the section adds no new attributes. \
  Its presence in this section is itself a graph fact.

SCOPE NOTE: This list is a known-incomplete seed whose sole purpose is \
cross-section entity naming coordination. It does not represent all entities in \
the document. You are required to discover and register additional entities not \
present in this list through independent analysis of section text.

{global_entity_pre_registration}

---

## SECTION TEXT

Extract entities and relationships ONLY from the text below. Do not import \
rules, thresholds, or relationships from other sections unless they are \
explicitly referenced within this text.

--- BEGIN SECTION TEXT ---
{section_text}
--- END SECTION TEXT ---

---

## CRITICAL PRINCIPLES FOR KNOWLEDGE GRAPH CONSTRUCTION

### Principle 1: Entities Are Things, Relationships Are Assertions

**Entities** represent discrete, identifiable things (nouns): organizations, \
roles, policies, governance bodies, procedures, thresholds, definitions, \
service tiers, expense categories, named party types.

**Relationships** express assertions (verbs) between entities: \
"Policy APPLIES_TO_ROLE TravelerRole", "PolicyRule MANDATES_USE_OF ServiceProvider".

**Critical Rule**: If you can express a statement as a simple \
(entity → relationship → entity) triple, you MUST do so. Do NOT create an \
entity to wrap the assertion.

**Exception**: Only create an entity to represent an assertion when it is too \
complex for a single triple (multiple simultaneous targets, conditional logic, \
references other rules). Use the "Requirement" entity type in such cases.

### Principle 2: List Members Must Be Individual Entity Nodes

When you encounter a list of named parties, roles, or categories, you MUST \
create a separate entity node for each list member. Do NOT collapse them into \
an attribute array. Knowledge graphs derive value from traversal — if \
"stakeholders" only exists as a string in an attribute array, the traversal \
path to it does not exist.

### Principle 3: Extract All Genuine Entities

Always extract these when they appear: the owning organization, named \
governance bodies, named roles, defined terms, referenced policies or \
instruments, any named party type, the Policy document itself, training \
programs, service providers.

---

## PROCESSING STEPS

Complete your analysis inside `<extraction_analysis>` tags before producing the \
final JSON output.

### Step 1: Identify Key Entities

Read the section and identify the distinct **things** mentioned: roles, \
organizations, service providers, expense categories, transportation modes, \
constraints (thresholds, deadlines, conditions), classes of service, etc. \
Focus on entities that carry concrete information — names, numbers, conditions \
— not on restating every sentence as a separate entity.

**Avoid entity bloat:** Do NOT create a separate PolicyRule entity for every \
sentence. If a rule's content is fully captured by a relationship between two \
entities (e.g., PolicyRule COVERS ExpenseCategory), and the rule text is \
recorded in the relationship's description or the parent entity's attributes, \
a standalone PolicyRule entity adds no traversal value.

Create PolicyRule entities only when:
- The rule has its own constraints, exceptions, or requirements attached
- The rule governs a combination of entities that cannot be expressed as a \
  single relationship
- The rule needs to be independently referenceable by other parts of the graph

### Step 2: Extract Attribute Values

For each entity, populate its typed attributes from the text: numbers, dates, \
thresholds, contact details, rates, conditions. Use null for optional \
number/integer fields not present. Use "" for string fields not present. Use [] \
for array fields not present. Always provide true or false for boolean fields.

### Step 3: Map Relationships

Identify the meaningful relationships between entities in this section. \
Focus on relationships that capture how entities interact — what governs what, \
what constrains what, what covers what, who approves what.

CRITICAL: Only create relationships between entities within this section. \
Cross-section relationships are handled by Stage 3.

### Step 4: Verify

Before producing JSON, check:
- [ ] Pre-registered entity names used character-for-character
- [ ] Each list of named parties/roles has separate entity nodes (not arrays)
- [ ] Concrete attribute values populated where text provides them
- [ ] All relationship source_id/target_id reference entities in your output

---

## REQUIRED OUTPUT SCHEMA

After your `<extraction_analysis>`, produce a single valid JSON object with \
exactly two top-level keys: "entities" and "relationships".

### OUTPUT 1: entities

{entity_types_section}

{entity_structure_section}

Example entity:
```json
{entity_example}
```

### OUTPUT 2: relationships

{relationship_types_section}

Each relationship must have:
- **source_id**: Must match an entity ID in your entities array
- **target_id**: Must match an entity ID in your entities array
- **type**: One of the relationship types listed above
- **description**: A specific description of HOW these entities relate, drawn \
  from the section text

CRITICAL: Create relationships ONLY between entities within this section. Do \
NOT create relationships to entities in other sections.

Example relationship:
```json
{relationship_example}
```

---

## FINAL INSTRUCTIONS

1. Read the section text in its entirety before writing any output.
2. Wrap your analysis in `<extraction_analysis>` tags.
3. After the closing `</extraction_analysis>` tag, produce ONLY the JSON object.
4. All entity IDs referenced in relationships must match entity IDs in the \
   entities array.
5. The output must be valid, parseable JSON.
6. Focus on the key entities, their attributes, and the relationships between \
   them. Prefer fewer, well-attributed entities over many thin ones.
7. Create separate entity nodes for each list member — do not collapse into \
   attribute arrays.

Begin your analysis now.
"""


def _build_entity_pre_registration(
    section: DocumentSection,
    first_pass_result: FirstPassResult,
) -> str:
    """Filter global_entity_pre_registration to entities relevant to this section.

    Returns a formatted text block for injection into the user prompt.
    """
    section_id = section.section_id
    if not section_id or not first_pass_result.global_entity_pre_registration:
        return "(No pre-registered entities for this section.)"

    relevant: list[FirstPassEntity] = []
    for e in first_pass_result.global_entity_pre_registration:
        if section_id in e.mentioned_in_sections:
            relevant.append(e)

    if not relevant:
        return "(No pre-registered entities for this section.)"

    lines = []
    for e in relevant:
        types_str = ", ".join(e.candidate_types) if e.candidate_types else "untyped"
        lines.append(
            f"- entity_name: {e.entity_name}\n"
            f"  candidate_types: [{types_str}]\n"
            f"  brief_description: {e.brief_description}"
        )

    result = "\n".join(lines)
    _dbg(
        f"_build_entity_pre_registration [{section_id}]",
        f"{len(relevant)} entities:\n{result}",
        indent=1,
    )
    return result


def _build_prompt(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    first_pass_result: FirstPassResult,
) -> tuple[str, str]:
    """Build the system + user extraction prompts for a section.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    fp = first_pass_result
    dm = fp.document_map

    _dbg(
        f"_build_prompt [{section.section_number}] {section.header}",
        f"section_id: {section.section_id}\n"
        f"section_text length: {len(section.text)} chars\n"
        f"Building sub-components...",
    )

    # Build the entity pre-registration block
    pre_reg_text = _build_entity_pre_registration(section, first_pass_result)

    user_prompt = EXTRACTION_USER_PROMPT.format(
        section_id=section.section_id or section.section_number,
        document_title=dm.document_title,
        issuing_organization=dm.issuing_organization,
        effective_date=dm.effective_date or "Not specified",
        document_purpose_summary=dm.document_purpose_summary,
        section_name=section.header,
        section_purpose=section.section_purpose or "Not classified",
        section_summary=section.section_summary or "Not summarized",
        global_entity_pre_registration=pre_reg_text,
        section_text=section.text,
        # Auto-generated schema sections
        entity_types_section=generate_entity_type_prompt_section(),
        entity_structure_section=generate_entity_structure_prompt_section(
            "", section.section_id or section.section_number
        ),
        relationship_types_section=generate_relationship_type_prompt_section(),
        entity_example=generate_example_entity(
            section_id=section.section_id or section.section_number
        ),
        relationship_example=generate_example_relationship(),
    )

    _dbg(
        f"SYSTEM PROMPT ({len(EXTRACTION_SYSTEM_PROMPT)} chars)",
        EXTRACTION_SYSTEM_PROMPT,
    )
    _dbg(
        f"USER PROMPT → LLM [{section.section_number}] ({len(user_prompt)} chars)",
        user_prompt,
    )

    return (EXTRACTION_SYSTEM_PROMPT, user_prompt)


def _extract_text_from_response(response) -> str:
    """Extract the text content from a thinking-enabled API response."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _parse_extraction_response(raw: str) -> dict:
    """Parse JSON from extraction response, stripping analysis tags and fences."""
    # Strip <extraction_analysis>...</extraction_analysis> thinking block
    cleaned = re.sub(
        r"<extraction_analysis>[\s\S]*?</extraction_analysis>", "", raw
    ).strip()

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
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group())
        raise


def _build_section_extraction(
    data: dict, section: DocumentSection
) -> SectionExtraction:
    """Build a SectionExtraction from parsed JSON data.

    Uses validate_entity() from schemas.py to construct typed entity subclasses.
    Entities with unknown types or validation failures are skipped with warnings.
    """
    entities = []
    for e in data.get("entities", []):
        # Ensure required base fields are present as strings
        entity_dict: dict = {
            "id": str(e.get("id", "")),
            "type": str(e.get("type", "")),
            "name": str(e.get("name", "")),
            "description": str(e.get("description", "")),
        }

        # Source anchor
        anchor_data = e.get("source_anchor", {})
        entity_dict["source_anchor"] = {
            "source_text": str(anchor_data.get("source_text", "")),
            "source_section": str(
                anchor_data.get("source_section", section.section_id or section.section_number)
            ),
        }

        # Carry over all other fields from LLM output (typed attributes,
        # or legacy "attributes" dict flattened to top-level).
        # If LLM returns old-style {"attributes": {...}}, flatten them.
        if "attributes" in e and isinstance(e["attributes"], dict):
            for k, v in e["attributes"].items():
                if k not in entity_dict:
                    entity_dict[k] = v
        # Also carry any top-level typed attribute fields
        skip_keys = {"id", "type", "name", "description", "source_anchor", "attributes"}
        for k, v in e.items():
            if k not in skip_keys and k not in entity_dict:
                entity_dict[k] = v

        entity, warnings = validate_entity(entity_dict)
        if warnings:
            for w in warnings:
                print(f"    [WARN] Section {section.section_number}: {w}")
        if entity is not None:
            # Stamp appears_in with the section's SEC-XX id
            if section.section_id:
                entity.appears_in = [section.section_id]
            entities.append(entity)

    relationships = []
    for r in data.get("relationships", []):
        relationships.append(
            Relationship(
                source_id=str(r["source_id"]),
                target_id=str(r["target_id"]),
                type=str(r["type"]),
                description=str(r.get("description", "")),
                source_sections=[section.section_id or section.section_number],
            )
        )

    return SectionExtraction(
        section=section,
        entities=entities,
        relationships=relationships,
    )


def extract_section(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: Anthropic | None = None,
    first_pass_result: FirstPassResult | None = None,
) -> SectionExtraction:
    """Extract entities and relationships from a single section.

    Args:
        section: The section to extract from.
        all_sections: All sections for context outline.
        client: Anthropic client.
        first_pass_result: First pass output for global context.

    Returns:
        SectionExtraction with entities, relationships, and source anchoring.
    """
    if client is None:
        client = Anthropic()

    if first_pass_result is None:
        first_pass_result = FirstPassResult()

    system_prompt, user_prompt = _build_prompt(section, all_sections, first_pass_result)

    response = client.messages.create(
        model=_EXTRACTION_MODEL,
        max_tokens=16000,
        system=system_prompt,
        thinking=_THINKING_CONFIG,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = _extract_text_from_response(response)
    data = _parse_extraction_response(raw)
    result = _build_section_extraction(data, section)

    # If zero entities, retry with aggressive prompt
    if not result.entities and len(section.text.strip()) > 100:
        result = _retry_extraction(
            section, all_sections, client,
            first_pass_result=first_pass_result,
        )

    return result


def _retry_extraction(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: Anthropic,
    first_pass_result: FirstPassResult | None = None,
) -> SectionExtraction:
    """Retry extraction with a more aggressive prompt."""
    if first_pass_result is None:
        first_pass_result = FirstPassResult()

    system_prompt, user_prompt = _build_prompt(section, all_sections, first_pass_result)
    retry_prefix = (
        "IMPORTANT: Your previous extraction of this section produced ZERO entities. "
        "This section MUST contain at least one extractable fact. Look for: "
        "implicit rules, scope statements, organizational information, dates, "
        "roles mentioned, or any other factual claims.\n\n"
    )

    response = client.messages.create(
        model=_EXTRACTION_MODEL,
        max_tokens=16000,
        system=system_prompt,
        thinking=_THINKING_CONFIG,
        messages=[{"role": "user", "content": retry_prefix + user_prompt}],
    )

    raw = _extract_text_from_response(response)
    data = _parse_extraction_response(raw)
    return _build_section_extraction(data, section)


async def _extract_section_async(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
    first_pass_result: FirstPassResult | None = None,
) -> SectionExtraction:
    """Extract a single section asynchronously with retry on rate limits."""
    if first_pass_result is None:
        first_pass_result = FirstPassResult()

    async with semaphore:
        system_prompt, user_prompt = _build_prompt(
            section, all_sections, first_pass_result
        )

        _dbg(
            f"API CALL [{section.section_number}]",
            f"model: {_EXTRACTION_MODEL}\n"
            f"max_tokens: 16000 (thinking: {_THINKING_CONFIG['budget_tokens']})\n"
            f"system prompt length: {len(system_prompt)} chars\n"
            f"user prompt length: {len(user_prompt)} chars",
        )

        # Retry loop for rate limit errors
        for attempt in range(max_retries):
            try:
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=16384,
                    system=system_prompt,
                    thinking=_THINKING_CONFIG,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                break
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    wait = 2 ** attempt * 15  # 15s, 30s, 60s
                    print(
                        f"    Rate limited on section {section.section_number}, "
                        f"retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                    if attempt == max_retries - 1:
                        raise
                else:
                    raise

        raw = _extract_text_from_response(response)
        _dbg(
            f"LLM RESPONSE [{section.section_number}] ({len(raw)} chars)",
            raw,
        )

        data = _parse_extraction_response(raw)
        result = _build_section_extraction(data, section)

        _dbg(
            f"PARSED RESULT [{section.section_number}]",
            f"entities: {len(result.entities)}\n"
            f"relationships: {len(result.relationships)}",
        )

        # If zero entities, retry with aggressive prompt
        if not result.entities and len(section.text.strip()) > 100:
            retry_prefix = (
                "IMPORTANT: Your previous extraction produced ZERO entities. "
                "This section MUST contain at least one extractable fact.\n\n"
            )

            _dbg(
                f"RETRY API CALL [{section.section_number}] (zero entities)",
                f"Prepending retry prefix ({len(retry_prefix)} chars) to user prompt",
            )

            for attempt in range(max_retries):
                try:
                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=16384,
                        system=system_prompt,
                        thinking=_THINKING_CONFIG,
                        messages=[
                            {"role": "user", "content": retry_prefix + user_prompt}
                        ],
                    )
                    break
                except Exception as e:
                    if "rate_limit" in str(e).lower() or "429" in str(e):
                        wait = 2 ** attempt * 15
                        await asyncio.sleep(wait)
                        if attempt == max_retries - 1:
                            raise
                    else:
                        raise
            raw = _extract_text_from_response(response)
            _dbg(
                f"RETRY LLM RESPONSE [{section.section_number}] ({len(raw)} chars)",
                raw,
            )
            data = _parse_extraction_response(raw)
            result = _build_section_extraction(data, section)

            _dbg(
                f"RETRY PARSED RESULT [{section.section_number}]",
                f"entities: {len(result.entities)}\n"
                f"relationships: {len(result.relationships)}",
            )

        return result


def extract_all_sections(
    sections: list[DocumentSection],
    client: Anthropic | None = None,
    max_concurrent: int = 2,
    first_pass_result: FirstPassResult | None = None,
) -> list[SectionExtraction]:
    """Extract entities from all sections in parallel.

    Args:
        sections: List of document sections to extract from.
        client: Synchronous Anthropic client (used to get API key config).
        max_concurrent: Maximum concurrent API calls.
        first_pass_result: Optional first pass output for global context.

    Returns:
        List of SectionExtraction results in the same order as input sections.
    """
    if client is None:
        client = Anthropic()

    # Backfill section_id from first pass if chunks are missing it
    if first_pass_result:
        _backfill_section_metadata(sections, first_pass_result)

    # Force sequential execution in debug mode so output is readable
    if _DEBUG:
        max_concurrent = 1
        _dbg(
            "extract_all_sections",
            f"Processing {len(sections)} sections SEQUENTIALLY (debug mode)\n"
            f"Sections: {', '.join(s.section_number for s in sections)}",
        )

    async def _run() -> list[SectionExtraction]:
        async_client = AsyncAnthropic()
        semaphore = asyncio.Semaphore(max_concurrent)

        tasks = [
            _extract_section_async(
                section, sections, async_client, semaphore,
                first_pass_result=first_pass_result,
            )
            for section in sections
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        extractions = []
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
                extractions.append(result)

        return extractions

    return asyncio.run(_run())


def _sections_from_chunks(chunks: list[dict]) -> list[DocumentSection]:
    """Reconstruct DocumentSection objects from chunks.json dicts."""
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
            section_id=c.get("section_id", ""),
            section_purpose=c.get("section_purpose", ""),
            section_summary=c.get("section_summary", ""),
        ))
    return sections


def _backfill_section_metadata(
    sections: list[DocumentSection],
    first_pass_result: FirstPassResult,
) -> None:
    """Backfill section_id/purpose/summary from first_pass onto sections missing them.

    Matches by normalized header name against FirstPassSection.section_name.
    Mutates sections in place.
    """
    if not first_pass_result or not first_pass_result.document_map.sections:
        return

    # Build lookup: lowercase section_name -> FirstPassSection
    fp_lookup: dict[str, FirstPassSection] = {}
    for fps in first_pass_result.document_map.sections:
        fp_lookup[fps.section_name.lower().strip()] = fps

    backfilled = 0
    for section in sections:
        if section.section_id:
            continue  # Already has section_id
        key = section.header.lower().strip()
        fps = fp_lookup.get(key)
        if fps:
            section.section_id = fps.section_id
            section.section_purpose = fps.section_purpose
            section.section_summary = fps.section_summary
            backfilled += 1

    if backfilled:
        print(f"  Backfilled section metadata for {backfilled}/{len(sections)} sections from first pass")


def serialize_extractions(extractions: list[SectionExtraction]) -> list[dict]:
    """Serialize SectionExtraction objects to the Stage 2 JSON contract.

    Output contains only chunk identifiers plus entities/relationships —
    no full section text or Pydantic reconstruction needed by the caller.
    """
    out = []
    for se in extractions:
        out.append({
            "chunk_id": se.section.chunk_id,
            "section_number": se.section.section_number,
            "entity_count": len(se.entities),
            "relationship_count": len(se.relationships),
            "entities": [e.model_dump() for e in se.entities],
            "relationships": [r.model_dump() for r in se.relationships],
        })
    return out


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

    from dotenv import load_dotenv
    load_dotenv()

    with open(args.input, encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks from {args.input}")

    fp_result = None
    if args.first_pass:
        with open(args.first_pass, encoding="utf-8") as f:
            fp_result = FirstPassResult(**json.load(f))
        print(f"Loaded first pass from {args.first_pass}")

    sections = _sections_from_chunks(chunks)
    if fp_result:
        _backfill_section_metadata(sections, fp_result)
    extractions = extract_all_sections(sections, first_pass_result=fp_result)

    data = serialize_extractions(extractions)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total_entities = sum(d["entity_count"] for d in data)
    total_rels = sum(d["relationship_count"] for d in data)
    print(f"Wrote {len(data)} sections ({total_entities} entities, {total_rels} relationships) to {args.output}")


if __name__ == "__main__":
    main()
