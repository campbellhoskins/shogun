# Extraction Prompt Improvement — Context for Anthropic Console

Paste this entire document into the Anthropic Console BEFORE pasting the extraction prompt you want improved. This gives Claude full context about the pipeline architecture, what this prompt does, and what you want changed. Then paste the prompt and hit "Improve."

---

## What This Prompt Does — Pipeline Architecture

This prompt is **Stage 2** of a 3-stage ontology extraction pipeline that turns unstructured policy documents into structured knowledge graphs. The pipeline works like this:

### Stage 1: Semantic Chunking (already complete before this prompt runs)

An LLM breaks the full document into semantically complete chunks. Each chunk is a JSON object with:
- `chunk_id`, `header`, `section_number`, `level` — structural metadata
- `text` — the verbatim document text for this chunk
- `parent_section`, `parent_header` — what larger section this chunk belongs to
- `hierarchical_path` — full breadcrumb from document root (e.g., `[{section_number: "6", header: "RESPONSIBILITIES..."}]`)
- `enumerated_lists` — detected lists with item counts and types

A typical policy document produces 12-20 chunks. Each chunk is 200-3000 characters.

### Stage 2: Per-Section Extraction (THIS IS THE PROMPT BEING IMPROVED)

This prompt runs independently on EACH chunk from Stage 1. It receives:
1. A brief outline of ALL section headers in the document (so it knows where this chunk fits)
2. The current section's header, number, parent context, and hierarchical position
3. Any detected enumerated lists with item counts (so it can verify it extracted every item)
4. The full verbatim text of this one chunk

It must produce:
- **Entities** — every fact, rule, definition, threshold, role, procedure, or requirement as a structured object with a type, name, description, attributes dict, and a mandatory source anchor (exact verbatim quote from the section text)
- **Relationships** — typed connections between entities within this section only

Critical constraints:
- Entities are prefixed with a section identifier (e.g., `s6_1_` for section 6.1) to avoid ID collisions across sections
- Source anchoring is mandatory — every entity must have `source_text` containing an exact verbatim quote from the section. This is verified downstream.
- Relationships are ONLY between entities in this section. Cross-section relationships are handled in Stage 3.

### Stage 3: Merge and Deduplication (runs after this prompt)

A deterministic (no LLM) merge stage:
1. Collects all entities and relationships from every section extraction
2. Deduplicates entities that appear across sections (exact ID match after stripping section prefix, exact name+type match)
3. Merges attributes and picks the best source anchor for each duplicate group
4. Updates relationship references to point to canonical entity IDs
5. Computes source offsets by locating each entity's `source_text` in the original document
6. Builds the final `OntologyGraph` with metadata

### Downstream Usage

The final graph is used by an AI agent that traverses it programmatically to answer compliance questions. The agent does NOT read the original document — it only has the graph. This means:
- Every fact in the document must be captured as an entity or attribute
- Entities must be densely interconnected via relationships
- Specific values (numbers, names, dates, emails) must be in attributes, not just descriptions
- Source anchors must be exact verbatim quotes so they can be verified against the original document

## How the Prompt is Assembled at Runtime

The prompt is a template with these variables filled in by Python code:

- `{section_outline}` — A brief indented outline of ALL section headers, generated from all chunks. Example:
  ```
  - 0: [Document Header and Approval Block]
  - 1: INTRODUCTION
  - 2: SCOPE
  - 3: AIM
  - 4: DEFINITIONS
  - 5: DIRECTIONS OF ACTIVITY AND AREAS OF COMPETENCE
  - 6: RESPONSIBILITIES OF THE ORGANIZATION FOR SECURITY AND RIGHTS PROTECTION
    - 6.1: Physical security
    - 6.2: Non-Discrimination and equality
    - 6.3: Protection against sexual exploitation and abuse (SEA)
  ```

- `{section_header}` — The header of the current chunk (e.g., "Physical security")

- `{section_number}` — The section number (e.g., "6.1")

- `{parent_context}` — Human-readable parent context. For top-level sections: "Top-level". For subsections: "6 — RESPONSIBILITIES OF THE ORGANIZATION FOR SECURITY AND RIGHTS PROTECTION"

- `{list_instructions}` — If the chunk contains detected enumerated lists, this is populated with instructions like:
  ```
  ## Enumerated Lists in This Section

  The following enumerated lists have been detected in this section.
  You MUST produce a SEPARATE entity for EACH item in each list.

  1. A bulleted list with **7 items** (starts with: "situation assessment (based on official information...")
     -> You must produce exactly 7 entities for this list.
  ```
  This is empty string if no lists were detected.

- `{section_text}` — The full verbatim text of this chunk

- `{id_prefix}` — Section-specific prefix for entity IDs (e.g., "s6_1" for section 6.1)

## What I Want Improved

Here is my feedback on the current prompt's output quality, based on running it against real policy documents:

### 1. Entity extraction density is inconsistent

Some sections produce rich extractions (28 entities from a 2000-char section on Physical Security) while others produce very sparse results (1 entity from a section header, 4 entities from a 300-char notification section). The prompt should push harder for exhaustive extraction from every section, especially short ones that still contain policy-relevant facts.

### 2. Source anchoring quality varies

The `source_text` field sometimes contains paraphrased text instead of exact verbatim quotes. The downstream merge stage tries to locate each `source_text` in the original document using exact string matching and fuzzy matching. When the LLM paraphrases, the offset computation fails and the entity can't be verified. The prompt must be much more forceful about verbatim copying.

### 3. Attribute usage is too thin

Entities often have empty `attributes: {}` even when the section text contains specific values. Dates, email addresses, age thresholds, numerical limits, lists of required items — these should all be captured as structured key-value pairs in the attributes dict, not just mentioned in the description string. The agent downstream queries attributes directly.

### 4. Relationship descriptions are too generic

Many relationships have descriptions like "relates to" or "requires compliance." These should contain specific information about HOW the entities relate, drawn from the section text.

### 5. The prompt doesn't leverage the hierarchical context well enough

The prompt receives `{parent_context}` and `{section_outline}` but doesn't explicitly instruct the LLM to use the hierarchical position to understand scope. For example, when extracting from section 6.1 (Physical security), the LLM should understand that every rule here falls under the umbrella of "RESPONSIBILITIES OF THE ORGANIZATION FOR SECURITY AND RIGHTS PROTECTION" and tag entities accordingly.

### 6. Definition sections need special handling

When the section contains formal definitions (bold terms followed by explanations), the prompt should produce one entity per definition with the COMPLETE definition text as the description and structured attributes (e.g., `{"includes": ["injury or death", "damage to property", "economic loss"]}`).

### What NOT to change

- Keep the `source_anchor` requirement mandatory — this is critical and non-negotiable
- Keep the instruction to create relationships ONLY within this section — cross-section linking happens in Stage 3
- Keep the entity ID prefix convention (`{id_prefix}_`)
- Keep the JSON output format as-is — the downstream parser expects exactly this structure
- Do NOT add chain-of-thought / thinking tags — this prompt runs in parallel across 16 sections and needs to be fast

## The Extraction Prompt to Improve

Below is the current prompt template. The `{{` and `}}` are escaped braces for Python's `.format()` — they become literal `{` and `}` in the output. The `{variable_name}` placeholders are filled at runtime as described above.

```
You are an expert ontology engineer extracting entities and relationships from a single section of a corporate policy document.

## Section Context

This section is from a larger document with the following structure:
{{section_outline}}

You are extracting from:
**Section: {{section_header}} ({{section_number}})**
Parent: {{parent_context}}

{{list_instructions}}

## Section Text

<section_text>
{{section_text}}
</section_text>

## Extraction Requirements

For EVERY distinct factual claim, rule, definition, threshold, role, procedure, or requirement in this section, create an entity.

### Source Anchoring (MANDATORY)

For EVERY entity you create, you MUST include a "source_anchor" object with:
- **source_text**: The EXACT verbatim quote from the section text that this entity represents. Copy the text character-for-character. Do not paraphrase, summarize, or alter it in any way.
- **source_section**: "{{section_number}}"

If an entity cannot be tied to a specific quote (e.g., it represents an implicit concept), set source_text to the most relevant sentence from the section.

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

Create relationships ONLY between entities within this section. Cross-section relationships will be handled in a later stage.

### Entity ID Convention

Prefix ALL entity IDs with the section identifier: "{{id_prefix}}_"
Example: "{{id_prefix}}_risk_level_standard", "{{id_prefix}}_manager_approval"

### Output Format

Return a JSON object:
{
  "entities": [
    {
      "id": "{{id_prefix}}_example_id",
      "type": "EntityType",
      "name": "Human Readable Name",
      "description": "Brief description from the policy",
      "attributes": {"key": "value"},
      "source_anchor": {
        "source_text": "Exact verbatim quote from section",
        "source_section": "{{section_number}}"
      }
    }
  ],
  "relationships": [
    {
      "source_id": "{{id_prefix}}_entity_1",
      "target_id": "{{id_prefix}}_entity_2",
      "type": "relationship_type",
      "description": "How they relate"
    }
  ]
}

### Density Requirements

Be exhaustive. Extract EVERY factual claim. A 500-word section should produce at least 5-15 entities. Every numeric value, every role mention, every rule, every definition, every procedure step is a separate entity.

Use attributes to capture specific values: amounts, dates, emails, thresholds, lists of items, risk levels, durations.

Return ONLY the JSON object. No other text.
```

Please improve this prompt and return the improved version as a drop-in replacement. In the improved prompt, keep all template variables in double-brace format `{{variable_name}}` exactly as shown above. Literal JSON braces should remain as single `{` and `}`.
