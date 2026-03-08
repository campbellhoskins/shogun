"""Stage 0: First pass document analysis for the extraction pipeline.

Performs a single LLM call over the full document to produce:
1. A document map (section inventory with beginning_text for chunking)
2. Global entity pre-registration (canonical names for cross-section consistency)
3. Cross-section dependencies (section pairs with dependency types)

This output is consumed by Stage 1 (segmenter) and Stage 2 (extraction) to
provide structural guidance and global context that would otherwise be lost
when processing sections in isolation.

CLI usage:
    python -m src.first_pass <input_markdown> -o <first_pass.json>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
TEST_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")

from src.models import FirstPassResult
from src.schemas import VALID_ENTITY_TYPES

# Module-level debug flag — set via CLI --debug or programmatically
_DEBUG = False

# Thinking configuration for the first pass call
_THINKING_CONFIG = {"type": "enabled", "budget_tokens": 32768}


def _dbg(header: str, body: str = "") -> None:
    """Print debug output when _DEBUG is enabled."""
    if not _DEBUG:
        return
    print(f"\n[DEBUG] {header}")
    if body:
        print(f"{'=' * 60}")
        print(body)
        print(f"{'=' * 60}")

FIRST_PASS_SYSTEM_PROMPT = """\
You are an expert ontology knowledge graph extraction system specializing in corporate \
travel policy documents. Your role is to perform a high-level structural analysis of a \
travel policy document in preparation for a multi-stage ontology graph extraction pipeline.

You are operating at STAGE 1 of a 5-stage pipeline. Your output will be consumed by \
downstream stages in the following ways:

- The DOCUMENT MAP will be used by a chunking system to split the document into \
section-level chunks for parallel entity extraction in Stage 2.

- The GLOBAL ENTITY PRE-REGISTRATION will be injected as context into every Stage 2 \
section-level extraction call, ensuring that entities referenced across multiple \
sections are consistently identified and named throughout the pipeline.

- The CROSS-SECTION DEPENDENCIES will be injected as additional context during Stage 2 \
extraction calls for any section that has a declared dependency, ensuring that \
relationship context is not lost when processing sections in isolation.

You must be precise and consistent. Do not summarize loosely. Every output \
field you produce will be consumed programmatically by downstream systems. Follow the \
output schema exactly as specified.\
"""

FIRST_PASS_USER_PROMPT = """\
Analyze the following travel policy document in its entirety before producing any output. \
Read the full document from beginning to end, noting the structure, the sections, the \
key entities mentioned throughout, and the ways in which different sections reference, \
modify, or depend upon one another.

Once you have read the full document, produce the following outputs in valid JSON \
format. Do not produce any output outside of the JSON structure.

---

## DOCUMENT

{document_text}

---

## REQUIRED OUTPUT SCHEMA

Produce a single valid JSON object with exactly three top-level keys:
1. "document_map"
2. "global_entity_pre_registration"
3. "cross_section_dependencies"

The complete schema for each is defined below.

---

### OUTPUT 1: document_map

The document map captures the identity of the document and a structured inventory of \
every section it contains. This will be used by a downstream chunking system to split \
the document into section-level chunks.

```json
{{
  "document_map": {{
    "document_title": "string — the official title of the document as it appears in the document",
    "issuing_organization": "string — the name of the organization that issued this policy",
    "effective_date": "string — the effective or proposed date of the document. Use ISO 8601 format if possible. Use null if not stated.",
    "document_purpose_summary": "string — one to two sentences describing the overall purpose of this document and who it applies to",
    "sections": [
      {{
        "section_id": "string — a unique identifier you assign to this section using the format SEC-01, SEC-02, etc. in order of appearance",
        "section_name": "string — the exact heading or title of the section as it appears in the document",
        "section_order": "integer — the ordinal position of this section in the document, starting at 1",
        "section_purpose": "string — a short descriptive name (3-7 words) describing what functional purpose this section serves within the document. This is NOT the section title — it is your functional classification of what the section achieves. Examples: 'Defines air travel booking rules', 'Establishes reimbursement submission process'",
        "section_summary": "string — exactly one sentence describing what this section covers and how it relates to the document as a whole. This sentence must be written in the context of the full document, not in isolation.",
        "beginning_text": "string — copy the first 40-60 words of this section IMMEDIATELY after the section's main heading line (the line starting with ## or ###). If the first line after the heading is a subheading (e.g., ### 1.1 Purpose), include that subheading text as the start of beginning_text. Do NOT skip past subheadings or numbered items to reach body paragraphs. The text must start at the very first content line after the section heading. This will be used by the downstream chunking system to locate this section."
      }}
    ]
  }}
}}
```

INSTRUCTIONS FOR document_map:
- Sections should be TOP-LEVEL sections only (e.g., "1. PURPOSE AND LEGAL CONTEXT", \
"2. DEFINITIONS", "3. SERVICE OVERVIEW"). Do NOT create separate entries for \
subsections (e.g., 3.1, 3.2, 6.1, 6.2). Subsections are part of their parent section \
and will be handled by the downstream chunking system. A typical policy document should \
produce 10-25 sections, not 50+.
- Every discrete top-level section of the document must be captured, including any \
introductory sections, preambles, or quick reference sections.
- Section order must be strictly sequential based on physical order in the document.
- The beginning_text must be verbatim from the document. Do not paraphrase.
- If the document contains a table of contents, do not treat it as a content section \
unless it contains substantive policy information.

---

### OUTPUT 2: global_entity_pre_registration

Scan the entire document and pre-register only those entities that require cross-section \
naming coordination. This list is NOT an exhaustive inventory of the document's entities — \
it is a targeted seed list that helps Stage 2 extractors use consistent canonical names \
for entities that span multiple sections.

```json
{{
  "global_entity_pre_registration": [
    {{
      "entity_name": "string — the canonical name for this entity. Choose the most complete and specific name used in the document. It should be lowercase_with_underscores, descriptive (e.g., "direct_travel_inc")",
      "candidate_types": "array of one to three strings from the permitted entity type list — these are provisional suggestions for Stage 2 to confirm, revise, or override based on contextual analysis. Stage 2 is not bound by these suggestions.",
      "mentioned_in_sections": "array of strings — every section_id in which this entity is referenced. Must match section_ids defined in the document_map. List in order of appearance.",
      "brief_description": "string — identity and disambiguation context ONLY: the entity's full name, any abbreviations or aliases used in the document, and the section where it first appears. Do NOT describe what the entity does, governs, or how it relates to other entities — that is Stage 2's job."
    }}
  ]
}}
```

PERMITTED ENTITY TYPES — candidate_types values must come from the following strings:
{entity_types}

INSTRUCTIONS FOR global_entity_pre_registration:
- Pre-register an entity ONLY if it satisfies at least one of these conditions:
  (a) It is referenced by name or role in TWO OR MORE sections of the document, \
creating a cross-section naming coordination risk if left unregistered.
  (b) It is a foundational actor, authority, role, or category that every Stage 2 \
extraction call needs to recognize consistently regardless of which section it is processing.
- Do NOT pre-register: numeric thresholds, individual rule criteria, single-section \
policy details, or any entity whose naming in the document is unambiguous and consistent. \
These entities appear in exactly one section, carry no cross-section coordination risk, \
and will be discovered correctly by Stage 2 working on that section's text.
- If the same entity is referred to by multiple names or abbreviations in the document, \
choose the most complete name and note the alias in the brief_description.
- Do NOT pre-register PolicySection entities. Section structure is already captured \
by the document_map. PolicySection nodes will be generated from the document map by \
pipeline infrastructure.
- The brief_description field is for IDENTITY DISAMBIGUATION ONLY. Include: the entity's \
full name as it appears in the document, any abbreviations or aliases, and the section \
where it first appears. Do NOT include: what the entity does, rules that apply to it, \
relationships with other entities, or its role in the policy. If your description contains \
a relative clause ("which," "that," "whose," "who") describing a rule or relationship — \
remove it.
- The candidate_types field provides provisional type suggestions. List one to three \
plausible entity types. Stage 2 will make the final classification decision based on \
contextual analysis of the section text.

<pre_registration_decomposition>
When the document defines a multi-level classification (e.g., four
severity levels), pre-register each level as a separate entity with
a consistent naming pattern (severity_level_1, severity_level_2,
severity_level_3, severity_level_4).

When the document provides templates per level and per channel,
pre-register each combination (alert_level_3_sms,
alert_level_3_email, alert_level_4_sms, etc.).
</pre_registration_decomposition>
---

### OUTPUT 3: cross_section_dependencies

Identify all pairs of sections where a meaningful dependency or modification relationship \
exists between them. A dependency exists when:
- One section explicitly references, qualifies, or limits the rules of another section
- One section defines a concept or entity that another section relies upon
- One section modifies the applicability of rules defined in another section
- Compliance with one section's rules is conditional on rules stated in another section

```json
{{
  "cross_section_dependencies": [
    {{
      "primary_section_id": "string — the section_id of the section that contains the dependency or the section that is being modified",
      "dependent_section_id": "string — the section_id of the section that modifies, qualifies, or references the primary section",
      "dependency_type": "string — must be exactly one of: MODIFIES | REFERENCES | CONDITIONALLY_APPLIES | DEFINES_TERM_USED_BY | OVERRIDES | REQUIRES_CONTEXT_FROM",
      "dependency_description": "string — one sentence describing the nature of the dependency and why it is relevant for entity extraction. Explain what information from the dependent_section changes or contextualizes the primary_section."
    }}
  ]
}}
```

DEPENDENCY TYPE DEFINITIONS:
- MODIFIES: The dependent section directly changes, limits, or expands rules in the primary section
- REFERENCES: The dependent section explicitly mentions or points to the primary section
- CONDITIONALLY_APPLIES: Rules in the primary section only apply under conditions defined in the dependent section
- DEFINES_TERM_USED_BY: The dependent section defines a term, role, or concept that the primary section uses without defining
- OVERRIDES: Rules in the dependent section take precedence over rules in the primary section under specific circumstances
- REQUIRES_CONTEXT_FROM: Correct interpretation of the primary section's rules requires reading the dependent section first

INSTRUCTIONS FOR cross_section_dependencies:
- Only include dependencies that are meaningful for entity and relationship extraction. \
Do not include trivial or incidental cross-references.
- A single pair of sections may appear multiple times if multiple distinct dependencies \
exist between them, each with a different dependency_type.
- Both section IDs must match section_ids defined in the document_map.
- Focus on dependencies that, if missed during isolated section extraction, would result \
in incorrect, incomplete, or contradictory entities or relationships being extracted.

---

## FINAL INSTRUCTIONS

1. Read the entire document before writing a single character of output.
2. Produce only the JSON object. No preamble, no explanation, no markdown outside of \
the JSON code block.
3. Ensure all section_ids referenced in global_entity_pre_registration \
(mentioned_in_sections) and cross_section_dependencies exactly match section_ids \
defined in the document_map.
4. The output must be valid, parseable JSON. Use null for any field where the value \
is genuinely not present in the document. Do not use undefined or omit fields.
5. Preserve verbatim accuracy in beginning_text fields. These will be used for exact \
string matching against the source document.\
"""


def _build_entity_types_list() -> str:
    """Generate the permitted entity types list from schemas.py."""
    return "\n".join(f'- "{t}"' for t in sorted(VALID_ENTITY_TYPES))


def _extract_text_from_response(response) -> str:
    """Extract the text content from a thinking-enabled API response."""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _parse_json_response(raw: str) -> dict:
    """Parse JSON from the LLM response, handling markdown fences."""
    cleaned = raw.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening fence line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # remove closing fence line
        cleaned = "\n".join(lines)

    def _try_parse(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fix invalid \escape sequences from LLM (e.g., \S, \s, \d)
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
            return json.loads(fixed)

    try:
        return _try_parse(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return _try_parse(match.group())
        raise


def run_first_pass(
    document_text: str, client: Anthropic | None = None
) -> FirstPassResult:
    """Run the first pass document analysis.

    Analyzes the full document in a single LLM call to produce a document map,
    global entity pre-registration, and cross-section dependencies.

    Args:
        document_text: The full document text (markdown).
        client: Anthropic client. Creates one if not provided.

    Returns:
        FirstPassResult with document_map, global_entity_pre_registration,
        and cross_section_dependencies.
    """
    if client is None:
        client = Anthropic()

    entity_types_list = _build_entity_types_list()
    user_prompt = FIRST_PASS_USER_PROMPT.format(
        document_text=document_text,
        entity_types=entity_types_list,
    )

    _dbg(
        f"SYSTEM PROMPT ({len(FIRST_PASS_SYSTEM_PROMPT)} chars)",
        FIRST_PASS_SYSTEM_PROMPT,
    )
    _dbg(
        f"USER PROMPT ({len(user_prompt)} chars)",
        user_prompt,
    )
    _dbg(
        "API CALL",
        f"model: {TEST_MODEL}\n"
        f"max_tokens: 49152 (thinking: {_THINKING_CONFIG['budget_tokens']})\n"
        f"user_prompt length: {len(user_prompt)} chars",
    )

    # Use streaming to avoid SDK timeout on large thinking requests
    collected_thinking = ""
    collected_text = ""
    with client.messages.stream(
        model=TEST_MODEL,
        max_tokens=49152,
        thinking=_THINKING_CONFIG,
        system=FIRST_PASS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for event in stream:
            if event.type == "content_block_start":
                if event.content_block.type == "thinking":
                    collected_thinking = ""
                elif event.content_block.type == "text":
                    collected_text = ""
            elif event.type == "content_block_delta":
                if event.delta.type == "thinking_delta":
                    collected_thinking += event.delta.thinking
                elif event.delta.type == "text_delta":
                    collected_text += event.delta.text
            elif event.type == "content_block_stop":
                if collected_thinking:
                    _dbg(f"THINKING ({len(collected_thinking)} chars)", collected_thinking)

    raw = collected_text
    _dbg(f"LLM RESPONSE ({len(raw)} chars)", raw)

    data = _parse_json_response(raw)
    _dbg(
        "PARSED RESULT",
        f"document_map sections: {len(data.get('document_map', {}).get('sections', []))}\n"
        f"pre-registered entities: {len(data.get('global_entity_pre_registration', []))}\n"
        f"cross-section dependencies: {len(data.get('cross_section_dependencies', []))}",
    )

    return FirstPassResult(**data)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: run first pass analysis on a document."""
    global _DEBUG

    parser = argparse.ArgumentParser(
        prog="python -m src.first_pass",
        description="Stage 0: First pass document analysis for the extraction pipeline.",
    )
    parser.add_argument(
        "input",
        help="Path to the input markdown/text file.",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/first_pass.json",
        help="Path to write the first pass JSON (default: data/first_pass.json).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full prompts, thinking, and LLM response for tracing.",
    )
    args = parser.parse_args(argv)

    _DEBUG = args.debug

    from dotenv import load_dotenv
    load_dotenv()

    input_text = open(args.input, encoding="utf-8").read()
    print(f"Read {len(input_text)} chars from {args.input}")

    result = run_first_pass(input_text)

    data = result.model_dump()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    fp_map = result.document_map
    print(
        f"Wrote first pass to {args.output}: "
        f"{len(fp_map.sections)} sections, "
        f"{len(result.global_entity_pre_registration)} pre-registered entities, "
        f"{len(result.cross_section_dependencies)} dependencies"
    )


if __name__ == "__main__":
    main()
