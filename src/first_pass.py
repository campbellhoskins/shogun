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
<system_role>
You are an expert extraction system that analyzes corporate travel policy
documents to build operational decision-support graphs. Your goal is NOT
to model the document's legal structure — it is to identify everything a
travel management company (TMC) agent would need to make correct, timely
decisions when a traveler is affected by an incident abroad.

You are operating at STAGE 1 of a 5-stage pipeline. Your output will be
consumed by downstream stages as follows:

- DOCUMENT MAP → used by a chunking system to split the document into
  section-level chunks for parallel entity extraction in Stage 2.

- GLOBAL ENTITY PRE-REGISTRATION → injected into every Stage 2 call to
  ensure consistent naming. Includes mandatory decomposition directives
  that Stage 2 must follow.

- CROSS-SECTION DEPENDENCIES → injected into Stage 2 calls for sections
  with declared dependencies, ensuring operational logic that spans
  sections is not lost during isolated processing.

You must be precise. Every output field will be consumed programmatically.
Follow the output schema exactly.
</system_role>

<operational_framing>
The graph you are helping to build will be used by TMC agents during live
incidents. When an earthquake hits a city where travelers are located, an
agent must rapidly determine:

  - What severity level is this incident?
  - What are my exact timing deadlines at this severity?
  - Which travelers are potentially impacted?
  - What outreach do I perform and in what order?
  - What does each traveler response mean and what is my next action?
  - Who on the client's side do I escalate to, and when?
  - What actions require client authorization before I can proceed?
  - What data do I need to have to act effectively?

Every extraction decision you make should be evaluated against this
question: "Does this help an agent make a correct decision faster?"
</operational_framing>

<required_outputs>
Produce a single valid JSON object with exactly three top-level keys:
1. "document_map"
2. "global_entity_pre_registration"
3. "cross_section_dependencies"

The complete schema for each is defined below.
</required_outputs>

<output_schema id="1" name="document_map">
Captures document structure for the chunking system. Each section is
annotated with its operational significance to guide Stage 2 extraction
priority.

<format>
{
  "document_map": {
    "document_title": "string — official title as it appears in the document",
    "issuing_organization": "string — organization that issued this policy",
    "effective_date": "string — ISO 8601 if possible, null if not stated",
    "document_purpose_summary": "string — 1-2 sentences: what this document governs and who it applies to",
    "sections": [
      {
        "section_id": "string — SEC-00, SEC-01, etc. in order of appearance",
        "section_name": "string — exact heading as it appears in the document",
        "section_order": "integer — ordinal position starting at 1",
        "section_purpose": "string — 3-7 word functional description",
        "section_summary": "string — one sentence describing what this section covers in context of the full document",
        "beginning_text": "string — verbatim first 40-60 words immediately after the section heading, used by chunking system for location matching"
      }
    ]
  }
}
</format>

<instructions>
- Sections are TOP-LEVEL only. Do not create entries for subsections.
- Every discrete section must be captured including preambles and appendices.
- beginning_text must be verbatim from the document. Do not paraphrase.
- contains_decision_tables is true for any table that maps inputs to
  outputs (severity → timing, response → action, role → escalation path).
  Narrative tables (definition lists, data element inventories) are false.
</instructions>
</output_schema>

<output_schema id="2" name="global_entity_pre_registration">

Scan the entire document and pre-register only those entities that require cross-section \
naming coordination. This list is NOT an exhaustive inventory of the document's entities — \
it is a targeted seed list that helps Stage 2 extractors use consistent canonical names \
for entities that span multiple sections.

<output_format>
{
  "global_entity_pre_registration": [
    {
      "entity_name": "string — the canonical name for this entity. Choose the most complete and specific name used in the document. It should be lowercase_with_underscores, descriptive (e.g., "direct_travel_inc")",
      "candidate_types": "array of one to three strings from the permitted entity type list — these are provisional suggestions for Stage 2 to confirm, revise, or override based on contextual analysis. Stage 2 is not bound by these suggestions.",
      "mentioned_in_sections": "array of strings — every section_id in which this entity is referenced. Must match section_ids defined in the document_map. List in order of appearance.",
      "brief_description": "string — identity and disambiguation context ONLY: the entity's full name, any abbreviations or aliases used in the document, and the section where it first appears. Do NOT describe what the entity does, governs, or how it relates to other entities — that is Stage 2's job."
    }
  ]
}
</output_format>

<permitted_entity_types>
PERMITTED ENTITY TYPES — candidate_types values MUST come from the following strings:
{entity_types}
</permitted_entity_types>

<instructions>
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
- The brief_description field is for IDENTITY DISAMBIGUATION ONLY. Include: the entity's \
full name as it appears in the document, any abbreviations or aliases, and the section \
where it first appears. Do NOT include: what the entity does, rules that apply to it, \
relationships with other entities, or its role in the policy. If your description contains \
a relative clause ("which," "that," "whose," "who") describing a rule or relationship — \
remove it.
- The candidate_types field provides provisional type suggestions. List one to three \
plausible entity types. Stage 2 will make the final classification decision based on \
contextual analysis of the section text.
</instructions>

<pre_registration_decomposition>
When the document defines a multi-level classification (e.g., four
severity levels), pre-register each level as a separate entity with
a consistent naming pattern (severity_level_1, severity_level_2,
severity_level_3, severity_level_4).

When the document provides templates per level and per channel,
pre-register each combination (alert_level_3_sms,
alert_level_3_email, alert_level_4_sms, etc.).
</pre_registration_decomposition>
</output_schema>

<output_schema id="3" name="cross_section_dependencies">

Identify all pairs of sections where a meaningful dependency or modification relationship \
exists between them. A dependency exists when:
- One section explicitly references, qualifies, or limits the rules of another section
- One section defines a concept or entity that another section relies upon
- One section modifies the applicability of rules defined in another section
- Compliance with one section's rules is conditional on rules stated in another section

<output_format>
{
  "cross_section_dependencies": [
    {
      "primary_section_id": "string — the section_id of the section that contains the dependency or the section that is being modified",
      "dependent_section_id": "string — the section_id of the section that modifies, qualifies, or references the primary section",
      "dependency_type": "string — one of the following types: MODIFIES, REFERENCES, CONDITIONALLY_APPLIES, DEFINES_TERM_USED_BY, OVERRIDES, REQUIRES_CONTEXT_FROM",
      "dependency_description": "string — one sentence describing the nature of the dependency and why it is relevant for entity extraction. Explain what information from the dependent_section changes or contextualizes the primary_section."
    }
  ]
}
</output_format>

<instructions>
- Only include dependencies that are meaningful for entity and relationship extraction. \
Do not include trivial or incidental cross-references.
- A single pair of sections may appear multiple times if multiple distinct dependencies \
exist between them, each with a different dependency_type.
- Both section IDs must match section_ids defined in the document_map.
- Focus on dependencies that, if missed during isolated section extraction, would result \
in incorrect, incomplete, or contradictory entities or relationships being extracted.
</instructions>
</output_schema>
"""

FIRST_PASS_USER_PROMPT = """\
Analyze the following travel policy document in its entirety before producing any output. \
Read the full document from beginning to end, noting the structure, the sections, the \
key entities mentioned throughout, and the ways in which different sections reference, \
modify, or depend upon one another.

Once you have read the full document, produce the outputs in valid JSON \
format. Do not produce any output outside of the JSON structure.

<document_text>
{document_text}
</document_text>

<final_instructions>
1. Read the entire document before writing a single character of output.
2. Produce only the JSON object. No preamble, no explanation, no markdown outside of \
the JSON code block.
3. Ensure all section_ids referenced in global_entity_pre_registration \
(mentioned_in_sections) exactly match section_ids defined in the document_map.
4. The output must be valid, parseable JSON. Use null for any field where the value \
is genuinely not present in the document. Do not use undefined or omit fields.
5. Preserve verbatim accuracy in beginning_text fields. These will be used for exact \
string matching against the source document.\
</final_instructions>
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
        """Try to parse JSON, applying progressive fixes for common LLM errors."""
        errors: list[str] = []

        # Attempt 1: raw parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            errors.append(f"raw: {e}")

        # Attempt 2: fix invalid \escape sequences (e.g., \S, \s, \d)
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            errors.append(f"escape-fix: {e}")

        # Attempt 3: fix unescaped control characters inside JSON strings
        # (LLM sometimes emits literal tabs/newlines inside string values)
        def _fix_control_chars(s: str) -> str:
            result = []
            in_string = False
            escape_next = False
            for ch in s:
                if escape_next:
                    result.append(ch)
                    escape_next = False
                    continue
                if ch == '\\' and in_string:
                    result.append(ch)
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                if in_string and ch == '\n':
                    result.append('\\n')
                    continue
                if in_string and ch == '\t':
                    result.append('\\t')
                    continue
                result.append(ch)
            return ''.join(result)

        try:
            return json.loads(_fix_control_chars(fixed))
        except json.JSONDecodeError as e:
            errors.append(f"control-char-fix: {e}")
            raise json.JSONDecodeError(
                f"All parse attempts failed: {'; '.join(errors)}", text, 0
            )

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
