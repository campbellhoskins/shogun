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

from src.models import (
    DocumentSection,
    Entity,
    EnumeratedList,
    HierarchyEntry,
    Relationship,
    SectionExtraction,
    SourceAnchor,
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
You are an expert ontology engineer. Your task is to extract structured entities \
and relationships from a section of a corporate policy document and output them \
as JSON for knowledge graph construction.

# Input Data

## Section Text to Analyze

Here is the section text from which you will extract entities and relationships:

<section_text>
{section_text}
</section_text>

## Complete Document Structure

Here is an outline showing all sections in the complete document. This provides \
context about where the current section fits within the overall document structure:

<section_outline>
{section_outline}
</section_outline>

## Section Metadata

Here is metadata about the current section:

<section_metadata>
Section Number: {section_number}
Section Header: {section_header}
Parent Context: {parent_context}
Entity ID Prefix: {id_prefix}
</section_metadata>

## List Detection Information

<list_detection>
{list_instructions}
</list_detection>

# Task Overview

Your goal is to extract structured entities and relationships from the section \
text to build a knowledge graph. A knowledge graph represents information as \
nodes (entities) and edges (relationships) that can be traversed to answer \
questions.

# Critical Principles for Knowledge Graph Construction

Before you begin, understand these fundamental principles:

## Principle 1: Entities Are Things, Relationships Are Assertions

**Entities** represent discrete, identifiable things (nouns):
- Roles (e.g., "Executive Director", "Stakeholders")
- Documents (e.g., "Grant Agreement", "Policy")
- Organizational bodies (e.g., "General Meeting")
- Procedures, thresholds, definitions
- ANY named party type or category

**Relationships** express assertions (verbs) between entities:
- "Policy applies_to Personnel"
- "Manager requires Approval"
- "Procedure implements Rule"

**Critical Rule**: If you can express a statement as a simple \
(entity -> relationship -> entity) triple, you MUST do so. Do NOT create an \
entity to wrap the assertion. For example:

WRONG: Create a "PolicyRule" entity with description "The policy applies to \
Personnel"
CORRECT: Create a direct relationship: (Policy) --[applies_to]--> (Personnel)

**Exception for Complex Constraints**: Only create an entity to represent an \
assertion when the assertion is too complex to express as a single triple \
(e.g., it has multiple simultaneous targets, conditional logic, or references \
other rules). In such cases, use entity types like "Requirement" or \
"Constraint", not "PolicyRule".

## Principle 2: List Members Must Be Individual Entity Nodes

When you encounter a list of named parties, roles, or categories (e.g., \
"partners, suppliers, sub-grantees, beneficiaries, stakeholders, consultants"), \
you MUST create a separate entity node for each list member.

WRONG: Create one entity with `"applies_to": ["partners", "suppliers", \
"stakeholders"]` in attributes
CORRECT: Create separate entity nodes for "partners", "suppliers", and \
"stakeholders", each connected via relationships

**Why this matters**: Knowledge graphs derive value from traversal. If a user \
asks "what applies to stakeholders?", the system must traverse from a \
Stakeholders node through relationships. If "stakeholders" only exists as a \
string in an attribute array, that traversal path does not exist.

## Principle 3: Extract All Genuine Entities

Always extract these as entity nodes when they appear:
- Named organizational bodies (e.g., "General Meeting", "Board of Directors")
- Named roles (e.g., "Executive Director", "Travel Risk Manager", "Volunteers")
- Defined terms and the groups they refer to (e.g., "Personnel", \
"Representatives")
- Referenced documents or instruments (e.g., "Grant Agreement", "Policy", \
"Code of Conduct")
- ANY named party type mentioned in a list, even if it appears only once
- The Policy document itself (create an entity for "Policy" so relationships \
like "applies_to" have a valid source)

# Processing Steps

You will complete this task in multiple steps, conducting your analysis before \
producing the final JSON output.

## Step 1: Systematic Analysis Phase

Conduct a thorough analysis of the section text. Wrap your entire analysis \
inside `<extraction_analysis>` tags. It's OK for this analysis to be quite \
long, as exhaustive extraction requires careful attention to every detail.

Complete the following substeps in order:

### Substep 1.1: Quote All Extractable Claims

Go through the section text sequentially, sentence by sentence, and quote \
EVERY distinct complete claim. A **complete claim** is an assertion that:
- Contains a verb or action
- Makes a statement that can stand on its own
- Expresses a fact, rule, definition, threshold, procedure, or requirement

**IMPORTANT DISTINCTION - Named Entities vs. Claims:**

When you encounter enumerated lists, distinguish between:
- **Complete claims**: List items that are full assertions with verbs (e.g., \
"Managers must approve travel within 48 hours")
- **Pure named entities**: List items that are just names/labels without verbs \
or assertions (e.g., "General Meeting" or "Executive director")

**Critical Rule**: If a list item contains no verb and makes no assertion on \
its own, do NOT quote it as a standalone claim. Instead:
1. Quote the parent sentence as the claim (e.g., "Directly involved in the \
implementation of the Policy are: General Meeting; Executive director.")
2. Note the individual list items as named components of that claim

**Requirements:**
- Copy each quote character-for-character from the section text - do NOT \
paraphrase
- After copying each quote, explicitly note: "[COPIED VERBATIM]" to confirm \
you've copied it exactly
- Number each quote (1., 2., 3., etc.)
- Write out the full quote for each item
- Be exhaustive - extract every extractable claim
- For enumerated lists with complete claims, quote each list item separately
- For enumerated lists with pure named entities, quote only the parent \
sentence and note the entities as components

### Substep 1.2: Classify Each Quote

For each numbered quote from substep 1.1, determine what it represents. Ask \
yourself:

1. **Does this quote contain an assertion (verb)?**
   - If YES: Can it be expressed as a simple \
(entity -> relationship -> entity) triple?
     - If YES: This will become a direct relationship, not an entity. Note the \
subject, relationship type, and object.
     - If NO (too complex): This may need to be reified as a Requirement or \
Constraint entity. Note why it's complex.
   - If NO: This describes a thing (genuine entity). Proceed to step 2.

2. **If it's a genuine entity, what type is it?**
   - Role, Definition, Procedure, Threshold, ApprovalRequirement, Person, \
Vendor, Document, etc.

3. **Does this quote introduce a list of named entities?**
   - If YES: Note that you will create a separate entity node for EACH list \
member.

Write out the classification explicitly for each quote.

### Substep 1.3: Extract Attribute Values

For each entity you will create (both standalone entities and named entity \
components within lists), identify specific concrete values that should be \
captured in the attributes dictionary:
- Numbers, quantities, counts
- Dates, durations, timeframes
- Email addresses, phone numbers, contact details
- Thresholds, limits, minimums, maximums
- Lists of items (only when the items are values, not named entities that \
should be nodes)
- Risk levels, severity levels
- Names of specific people, vendors, destinations

Write out a preliminary attributes dictionary for each entity. Include specific \
values explicitly. Do not leave attributes empty if specific values are present \
in the text.

**For each attribute value, explicitly note which quote number it came from and \
the exact phrase in the source text that contains this value.** This ensures \
accuracy and traceability.

### Substep 1.4: Consider Hierarchical Context

Review the section metadata provided above, particularly the Parent Context \
field. Consider how the section's position in the document outline affects the \
interpretation of entities. For example, if this section falls under \
"RESPONSIBILITIES", all rules and entities relate to organizational \
responsibilities.

Note any contextual information that should inform entity descriptions or \
relationship interpretations.

### Substep 1.5: Verify List Coverage and Individual Entity Extraction

Review the list_detection information provided above. If enumerated lists were \
detected, verify that you have:

1. Identified each list item
2. For lists with complete claims: quoted each item separately in substep 1.1
3. For lists with pure named entities: quoted the parent sentence and noted \
each entity as a component
4. **CRITICAL VERIFICATION**: Confirmed that you will create a SEPARATE ENTITY \
NODE for each named entity in the list (not collapse them into an attribute \
array)

Write out explicitly: "I will create [number] separate entity nodes from this \
list: [list them]"

### Substep 1.6: Verify No PolicyRule Entities

Review all entities you plan to create. For each one that you initially \
classified as a potential "PolicyRule" or similar assertion-wrapping entity, \
verify:

1. Can this be expressed as a direct \
(entity -> relationship -> entity) triple?
2. If YES: Convert it to a direct relationship. Do NOT create a PolicyRule \
entity.
3. If NO: Is it genuinely complex (multiple targets, conditional logic)?
   - If YES: Reify as a Requirement or Constraint entity and explain why.
   - If NO: Convert it to a direct relationship.

Write out your verification explicitly for any potential assertion-based \
entities.

### Substep 1.7: Map Relationships

Identify which entities relate to which other entities and what type of \
relationship exists between them.

**CRITICAL RESTRICTION**: Only identify relationships between entities within \
this section. Do NOT create relationships to entities you imagine might exist \
in other sections.

For each pair, determine if a relationship exists and what type. Write it out \
explicitly as a triple in the format: \
(source entity) --[relationship_type]--> (target entity), followed by the \
justification.

### Substep 1.8: Final Verification Checklist

Before moving to entity creation, verify:

- [ ] I have extracted every distinct claim from the text
- [ ] For any lists of named entities, I will create separate entity nodes for \
each member (not attribute arrays)
- [ ] I have not created any "PolicyRule" entities for simple assertions that \
can be expressed as direct relationships
- [ ] I have extracted all genuine entities: roles, documents, organizational \
bodies, the Policy itself
- [ ] All my planned relationships are between entities within this section only
- [ ] I have identified concrete attribute values where they exist in the text
- [ ] I have linked each attribute value back to its source quote

## Step 2: Entity Extraction

After completing your analysis, create entity objects for the JSON output.

### Entity Types

Classify each entity using one of these types based on what the text describes:

- **Definition**: A formally defined term
- **RiskLevel**: A destination risk classification tier
- **ApprovalRequirement**: Who must approve and under what conditions
- **InsuranceRequirement**: Insurance coverage minimums
- **VaccinationRequirement**: Required vaccinations
- **Destination**: A country, region, or destination category
- **Role**: An organizational role or party type (Travel Risk Manager, CSO, \
Stakeholders, Partners, etc.)
- **Person**: A named individual
- **Vendor**: An approved vendor (airline, hotel, security firm)
- **Procedure**: A defined process or workflow
- **IncidentCategory**: A classification of incidents
- **CommunicationRequirement**: Check-in frequency or communication obligations
- **Equipment**: Required equipment or technology
- **Threshold**: Specific numeric thresholds or limits
- **ContactInformation**: Email addresses, phone numbers, contact details
- **BenefitOrPackage**: Social packages, work arrangements, programs
- **Document**: Referenced documents (Grant Agreement, Policy, Code of Conduct, \
etc.)
- **OrganizationalBody**: Named bodies (General Meeting, Board, Committee, etc.)
- **Requirement**: A complex constraint that cannot be expressed as a simple \
triple (use sparingly)
- **Constraint**: A complex condition with multiple parts (use sparingly)

**Note**: "PolicyRule" is NOT a valid entity type. If you find yourself wanting \
to create a PolicyRule, convert it to a direct relationship instead (see \
Principle 1).

### Entity Structure

Create each entity with the following fields:

**id** (required)
- Format: Start with the prefix `{id_prefix}_` followed by a descriptive \
identifier
- Use lowercase with underscores
- Make it descriptive of the entity content
- Example: `{id_prefix}_role_stakeholders` or `{id_prefix}_doc_policy`

**type** (required)
- Must be one of the entity types listed above

**name** (required)
- A clear, human-readable name for this entity
- Should be concise but descriptive

**description** (required)
- A brief description of what this entity represents
- Draw this from the policy text
- For named entities from lists, reference the parent sentence context

**attributes** (required)
- A dictionary of specific key-value pairs capturing concrete values
- Include numbers, dates, emails, thresholds, lists found in the text
- If no specific values are present, use an empty object: {{}}
- Examples: `{{"threshold_days": "30"}}`, `{{"minimum_coverage": "1000000"}}`, \
`{{"risk_level": "high"}}`

**source_anchor** (required)
- This is a mandatory object with two fields:
  - **source_text**: The EXACT verbatim quote from the section text that \
supports this entity. Copy character-for-character from the source. Do NOT \
paraphrase. For named entities from lists, use the complete parent sentence \
that introduces the list.
  - **source_section**: Must be set to `{section_number}`

### Special Handling for Definitions

When the section contains formal definitions (typically bold terms followed by \
explanations):
- Create one entity per definition
- Set type to "Definition"
- Include the COMPLETE definition text in the description
- Structure the attributes to capture breakdown of the definition
- Example: `{{"includes": ["item1", "item2"]}}` or \
`{{"applies_to": "scope"}}`

### Special Handling for List Items That Are Pure Named Entities

When you encounter list items that are pure named entities (no verbs, no \
standalone assertions):
- Create a separate entity for EACH named entity in the list
- Set the appropriate entity type (Role, Person, Vendor, OrganizationalBody, \
etc.)
- For the description: reference the context from the parent sentence
- For the source_anchor.source_text: use the complete parent sentence that \
introduces the list

### Extraction Density Guidelines

Be exhaustive in your extraction. Use these guidelines:
- A 200-300 word section typically contains 3-8 extractable facts
- A 500 word section should produce at least 5-15 entities
- A 2000 word section might produce 20-30 entities

Extract:
- Every rule or requirement (as direct relationships when possible, not \
PolicyRule entities)
- Every numeric threshold or limit
- Every role mentioned
- Every defined term
- Every procedure step
- Every contact detail
- Every approval requirement
- Every list item (whether complete claims or pure named entities)
- The Policy document itself
- Any referenced documents

## Step 3: Relationship Extraction

After creating entities, create relationship objects for the JSON output.

### Relationship Types

Use these relationship types to describe how entities connect:

- **requires**: Entity A requires Entity B
- **applies_to**: Rule applies to a destination, role, or risk level
- **triggers**: An event triggers a procedure or escalation
- **escalates_to**: One role escalates to another
- **prohibits**: A rule prohibits an action
- **permits**: A rule permits an action
- **provides**: An entity provides a service or coverage
- **classified_as**: A destination is classified as a risk level
- **managed_by**: A process is managed by a role
- **part_of**: Entity is part of a larger entity (use this for list members!)
- **references**: Entity references another entity
- **implements**: A procedure implements a rule
- **exceeds**: A value exceeds a threshold
- **reports_to**: Role reports to another role
- **responsible_for**: Role is responsible for a process or area

### Relationship Structure

Each relationship must have:

**source_id** (required)
- The ID of the source entity
- Must match an entity ID in your entities array

**target_id** (required)
- The ID of the target entity
- Must match an entity ID in your entities array

**type** (required)
- One of the relationship types listed above

**description** (required)
- A specific description of HOW these entities relate
- Draw this from the section text
- Avoid generic descriptions like "relates to" or "requires compliance"
- Be specific about the nature of the relationship

### Relationship Scope Restriction

**CRITICAL**: Create relationships ONLY between entities within this section.

Do NOT create relationships to entities you imagine might exist in other \
sections. Cross-section relationships will be handled in a later processing \
stage.

Only include a relationship if both the source_id and target_id refer to \
entities you have created from this section.

## Step 4: Output Format

After completing your analysis in `<extraction_analysis>` tags, provide your \
final output as a JSON object.

The JSON object must have this exact structure:

```json
{{
  "entities": [
    {{
      "id": "string (with required prefix)",
      "type": "string (from allowed types)",
      "name": "string",
      "description": "string",
      "attributes": {{
        "key": "value"
      }},
      "source_anchor": {{
        "source_text": "string (verbatim quote)",
        "source_section": "string (section number)"
      }}
    }}
  ],
  "relationships": [
    {{
      "source_id": "string (entity id)",
      "target_id": "string (entity id)",
      "type": "string (from allowed types)",
      "description": "string"
    }}
  ]
}}
```

### Example Output Structure

Here is a generic example showing the structure (this is purely illustrative - \
your actual output should be based on the section text):

```json
{{
  "entities": [
    {{
      "id": "sec_01_role_personnel",
      "type": "Role",
      "name": "Personnel",
      "description": "Staff members and employees covered by the policy",
      "attributes": {{}},
      "source_anchor": {{
        "source_text": "This policy applies to all Personnel of the organization.",
        "source_section": "1.0"
      }}
    }},
    {{
      "id": "sec_01_doc_policy",
      "type": "Document",
      "name": "Travel Safety Policy",
      "description": "The organizational travel safety policy document",
      "attributes": {{
        "document_type": "policy"
      }},
      "source_anchor": {{
        "source_text": "This policy applies to all Personnel of the organization.",
        "source_section": "1.0"
      }}
    }},
    {{
      "id": "sec_01_threshold_duration",
      "type": "Threshold",
      "name": "Extended Travel Duration",
      "description": "Threshold for travel duration that triggers additional requirements",
      "attributes": {{
        "threshold_days": "30",
        "unit": "days"
      }},
      "source_anchor": {{
        "source_text": "Travel exceeding 30 days requires additional approval.",
        "source_section": "1.0"
      }}
    }}
  ],
  "relationships": [
    {{
      "source_id": "sec_01_doc_policy",
      "target_id": "sec_01_role_personnel",
      "type": "applies_to",
      "description": "The policy applies to all personnel in the organization"
    }}
  ]
}}
```

## Final Instructions

- Return ONLY the JSON object after your `<extraction_analysis>` section
- Do not include any other text after the closing `</extraction_analysis>` tag \
and before the JSON
- Ensure the JSON is valid and properly formatted
- Include all entities you identified in your analysis
- Include all within-section relationships you identified in your analysis
- Remember: Create separate entity nodes for each list member, do not use \
PolicyRule entities, express simple assertions as direct relationships

Begin your analysis now.
"""


def _build_section_outline(all_sections: list[DocumentSection]) -> str:
    """Build a brief outline of all section headers for context."""
    lines = []
    for s in all_sections:
        indent = "  " * (s.level - 1)
        lines.append(f"{indent}- {s.section_number}: {s.header}")
    result = "\n".join(lines)
    _dbg("_build_section_outline", f"Generated outline for {len(all_sections)} sections:\n{result}", indent=1)
    return result


def _build_list_instructions(section: DocumentSection) -> str:
    """Build instructions about enumerated lists in this section."""
    if not section.enumerated_lists:
        _dbg(f"_build_list_instructions [{section.section_number}]", "(no enumerated lists)", indent=1)
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
    result = "\n".join(lines)
    _dbg(f"_build_list_instructions [{section.section_number}]", result, indent=1)
    return result


def _make_id_prefix(section_number: str) -> str:
    """Convert a section number to a valid ID prefix."""
    return "s" + re.sub(r"[^a-zA-Z0-9]", "_", section_number).strip("_")


def _build_parent_context(section: DocumentSection) -> str:
    """Build a human-readable parent context string for the extraction prompt."""
    if section.parent_header and section.parent_section:
        result = f"{section.parent_section} \u2014 {section.parent_header}"
    else:
        result = section.parent_section or "Top-level"
    _dbg(f"_build_parent_context [{section.section_number}]", f"Parent: {result}", indent=1)
    return result


def _build_prompt(section: DocumentSection, all_sections: list[DocumentSection]) -> str:
    """Build the complete extraction prompt for a section."""
    id_prefix = _make_id_prefix(section.section_number)

    _dbg(
        f"_build_prompt [{section.section_number}] {section.header}",
        f"id_prefix: {id_prefix}\n"
        f"section_text length: {len(section.text)} chars\n"
        f"Building sub-components...",
    )

    prompt = EXTRACTION_SYSTEM_PROMPT.format(
        section_outline=_build_section_outline(all_sections),
        section_header=section.header,
        section_number=section.section_number,
        parent_context=_build_parent_context(section),
        list_instructions=_build_list_instructions(section),
        section_text=section.text,
        id_prefix=id_prefix,
    )

    _dbg(
        f"FINAL PROMPT → LLM [{section.section_number}] ({len(prompt)} chars)",
        prompt,
    )

    return prompt


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

        _dbg(
            f"API CALL [{section.section_number}]",
            f"model: claude-sonnet-4-20250514\n"
            f"max_tokens: 8192\n"
            f"prompt length: {len(prompt)} chars",
        )

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
                f"Prepending retry prefix ({len(retry_prefix)} chars) to prompt",
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
    args = parser.parse_args(argv)

    _DEBUG = args.debug

    from dotenv import load_dotenv
    load_dotenv()

    with open(args.input, encoding="utf-8") as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks from {args.input}")

    sections = _sections_from_chunks(chunks)
    extractions = extract_all_sections(sections)

    data = serialize_extractions(extractions)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    total_entities = sum(d["entity_count"] for d in data)
    total_rels = sum(d["relationship_count"] for d in data)
    print(f"Wrote {len(data)} sections ({total_entities} entities, {total_rels} relationships) to {args.output}")


if __name__ == "__main__":
    main()
