"""Stage 2: Per-section entity and relationship extraction with source anchoring.

Extracts entities and relationships from each document section independently,
with mandatory source text anchoring for every entity.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

from src.models import (
    DocumentSection,
    Entity,
    EnumeratedList,
    Relationship,
    SectionExtraction,
    SourceAnchor,
)

EXTRACTION_SYSTEM_PROMPT = """\
You are an expert ontology engineer extracting entities and relationships from \
a single section of a corporate policy document.

## Section Context

This section is from a larger document with the following structure:
{section_outline}

You are extracting from:
**Section: {section_header} ({section_number})**
Parent: {parent_section}

{list_instructions}

## Section Text

<section_text>
{section_text}
</section_text>

## Extraction Requirements

For EVERY distinct factual claim, rule, definition, threshold, role, procedure, \
or requirement in this section, create an entity.

### Source Anchoring (MANDATORY)

For EVERY entity you create, you MUST include a "source_anchor" object with:
- **source_text**: The EXACT verbatim quote from the section text that this \
entity represents. Copy the text character-for-character. Do not paraphrase, \
summarize, or alter it in any way.
- **source_section**: "{section_number}"

If an entity cannot be tied to a specific quote (e.g., it represents an \
implicit concept), set source_text to the most relevant sentence from the section.

### Entity Types

- **PolicyRule**: A specific rule, requirement, or restriction
- **Definition**: Any formally defined term
- **RiskLevel**: A destination risk classification tier
- **ApprovalRequirement**: Who must approve and under what conditions
- **InsuranceRequirement**: Insurance coverage minimums
- **VaccinationRequirement**: Required vaccinations
- **Destination**: A country, region, or destination category
- **Role**: An organizational role (Travel Risk Manager, CSO, etc.)
- **Person**: A named individual
- **Vendor**: An approved vendor (airline, hotel, security firm)
- **Procedure**: A defined process or workflow
- **IncidentCategory**: A classification of incidents
- **CommunicationRequirement**: Check-in frequency or communication obligations
- **Equipment**: Required equipment or technology
- **Threshold**: Specific numeric thresholds or limits
- **ContactInformation**: Email addresses, phone numbers, contact details
- **BenefitOrPackage**: Social packages, work arrangements, programs

### Relationship Types

- **requires**: Entity A requires Entity B
- **applies_to**: Rule applies to a destination, role, or risk level
- **triggers**: An event triggers a procedure or escalation
- **escalates_to**: One role escalates to another
- **prohibits / permits**: A rule prohibits or permits an action
- **provides**: An entity provides a service or coverage
- **classified_as**: A destination is classified as a risk level
- **managed_by**: A process is managed by a role
- **part_of**: Entity is part of a larger entity
- **references**: Entity references another entity
- **implements**: A procedure implements a rule
- **exceeds**: A value exceeds a threshold

Create relationships ONLY between entities within this section. \
Cross-section relationships will be handled in a later stage.

### Entity ID Convention

Prefix ALL entity IDs with the section identifier: "{id_prefix}_"
Example: "{id_prefix}_risk_level_standard", "{id_prefix}_manager_approval"

### Output Format

Return a JSON object:
```json
{{
  "entities": [
    {{
      "id": "{id_prefix}_example_id",
      "type": "EntityType",
      "name": "Human Readable Name",
      "description": "Brief description from the policy",
      "attributes": {{"key": "value"}},
      "source_anchor": {{
        "source_text": "Exact verbatim quote from section",
        "source_section": "{section_number}"
      }}
    }}
  ],
  "relationships": [
    {{
      "source_id": "{id_prefix}_entity_1",
      "target_id": "{id_prefix}_entity_2",
      "type": "relationship_type",
      "description": "How they relate"
    }}
  ]
}}
```

### Density Requirements

Be exhaustive. Extract EVERY factual claim. A 500-word section should produce \
at least 5-15 entities. Every numeric value, every role mention, every rule, \
every definition, every procedure step is a separate entity.

Use attributes to capture specific values: amounts, dates, emails, thresholds, \
lists of items, risk levels, durations.

Return ONLY the JSON object. No other text.
"""


def _build_section_outline(all_sections: list[DocumentSection]) -> str:
    """Build a brief outline of all section headers for context."""
    lines = []
    for s in all_sections:
        indent = "  " * (s.level - 1)
        lines.append(f"{indent}- {s.section_number}: {s.header}")
    return "\n".join(lines)


def _build_list_instructions(section: DocumentSection) -> str:
    """Build instructions about enumerated lists in this section."""
    if not section.enumerated_lists:
        return ""

    lines = ["## Enumerated Lists in This Section\n"]
    lines.append(
        "The following enumerated lists have been detected in this section. "
        "You MUST produce a SEPARATE entity for EACH item in each list.\n"
    )
    for i, el in enumerate(section.enumerated_lists, 1):
        lines.append(
            f"{i}. A {el.list_type} list with **{el.item_count} items** "
            f'(starts with: "{el.preview}")'
        )
        lines.append(
            f"   → You must produce exactly {el.item_count} entities for this list.\n"
        )
    return "\n".join(lines)


def _make_id_prefix(section_number: str) -> str:
    """Convert a section number to a valid ID prefix."""
    return "s" + re.sub(r"[^a-zA-Z0-9]", "_", section_number).strip("_")


def _build_prompt(section: DocumentSection, all_sections: list[DocumentSection]) -> str:
    """Build the complete extraction prompt for a section."""
    id_prefix = _make_id_prefix(section.section_number)
    return EXTRACTION_SYSTEM_PROMPT.format(
        section_outline=_build_section_outline(all_sections),
        section_header=section.header,
        section_number=section.section_number,
        parent_section=section.parent_section or "Top-level",
        list_instructions=_build_list_instructions(section),
        section_text=section.text,
        id_prefix=id_prefix,
    )


def _parse_extraction_response(raw: str) -> dict:
    """Parse JSON from extraction response."""
    cleaned = raw.strip()
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
    """Build a SectionExtraction from parsed JSON data."""
    entities = []
    for e in data.get("entities", []):
        anchor_data = e.get("source_anchor", {})
        entities.append(
            Entity(
                id=str(e["id"]),
                type=str(e["type"]),
                name=str(e["name"]),
                description=str(e.get("description", "")),
                attributes={
                    k: v
                    for k, v in e.get("attributes", {}).items()
                    if k not in ("type", "name", "description")
                },
                source_anchor=SourceAnchor(
                    source_text=str(anchor_data.get("source_text", "")),
                    source_section=str(
                        anchor_data.get("source_section", section.section_number)
                    ),
                ),
            )
        )

    relationships = []
    for r in data.get("relationships", []):
        relationships.append(
            Relationship(
                source_id=str(r["source_id"]),
                target_id=str(r["target_id"]),
                type=str(r["type"]),
                description=str(r.get("description", "")),
                source_sections=[section.section_number],
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
) -> SectionExtraction:
    """Extract entities and relationships from a single section.

    Args:
        section: The section to extract from.
        all_sections: All sections for context outline.
        client: Anthropic client.

    Returns:
        SectionExtraction with entities, relationships, and source anchoring.
    """
    if client is None:
        client = Anthropic()

    prompt = _build_prompt(section, all_sections)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    data = _parse_extraction_response(raw)
    result = _build_section_extraction(data, section)

    # If zero entities, retry with aggressive prompt
    if not result.entities and len(section.text.strip()) > 100:
        result = _retry_extraction(section, all_sections, client)

    return result


def _retry_extraction(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: Anthropic,
) -> SectionExtraction:
    """Retry extraction with a more aggressive prompt."""
    prompt = _build_prompt(section, all_sections)
    retry_prefix = (
        "IMPORTANT: Your previous extraction of this section produced ZERO entities. "
        "This section MUST contain at least one extractable fact. Look for: "
        "implicit rules, scope statements, organizational information, dates, "
        "roles mentioned, or any other factual claims.\n\n"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        messages=[{"role": "user", "content": retry_prefix + prompt}],
    )

    raw = response.content[0].text
    data = _parse_extraction_response(raw)
    return _build_section_extraction(data, section)


async def _extract_section_async(
    section: DocumentSection,
    all_sections: list[DocumentSection],
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
) -> SectionExtraction:
    """Extract a single section asynchronously with retry on rate limits."""
    async with semaphore:
        prompt = _build_prompt(section, all_sections)

        # Retry loop for rate limit errors
        for attempt in range(max_retries):
            try:
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}],
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

        raw = response.content[0].text
        data = _parse_extraction_response(raw)
        result = _build_section_extraction(data, section)

        # If zero entities, retry with aggressive prompt
        if not result.entities and len(section.text.strip()) > 100:
            retry_prefix = (
                "IMPORTANT: Your previous extraction produced ZERO entities. "
                "This section MUST contain at least one extractable fact.\n\n"
            )
            for attempt in range(max_retries):
                try:
                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=8192,
                        messages=[
                            {"role": "user", "content": retry_prefix + prompt}
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
            raw = response.content[0].text
            data = _parse_extraction_response(raw)
            result = _build_section_extraction(data, section)

        return result


def extract_all_sections(
    sections: list[DocumentSection],
    client: Anthropic | None = None,
    max_concurrent: int = 2,
) -> list[SectionExtraction]:
    """Extract entities from all sections in parallel.

    Args:
        sections: List of document sections to extract from.
        client: Synchronous Anthropic client (used to get API key config).
        max_concurrent: Maximum concurrent API calls.

    Returns:
        List of SectionExtraction results in the same order as input sections.
    """
    if client is None:
        client = Anthropic()

    async def _run() -> list[SectionExtraction]:
        async_client = AsyncAnthropic()
        semaphore = asyncio.Semaphore(max_concurrent)

        tasks = [
            _extract_section_async(section, sections, async_client, semaphore)
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
