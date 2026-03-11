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
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
_DEFAULT_MODEL = os.environ.get("_DEFAULT_MODEL", "claude-haiku-4-5-20251001")

from src.models import FirstPassResult, StageUsage
from src.schemas import ENTITY_TYPE_MAP

# Module-level debug flag — set via CLI --debug or programmatically
_DEBUG = False

from src.llm import thinking_config


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
{{
  "document_map": {{
    "document_title": "string — official title as it appears in the document",
    "issuing_organization": "string — organization that issued this policy",
    "effective_date": "string — ISO 8601 if possible, null if not stated",
    "document_purpose_summary": "string — 1-2 sentences: what this document governs and who it applies to",
    "sections": [
      {{
        "section_id": "string — SEC-00, SEC-01, etc. in order of appearance",
        "section_name": "string — exact heading as it appears in the document",
        "section_order": "integer — ordinal position starting at 1",
        "section_purpose": "string — 3-7 word functional description",
        "section_summary": "string — one sentence describing what this section covers in context of the full document",
        "beginning_text": "string — verbatim first 40-60 words immediately after the section heading, used by chunking system for location matching"
      }}
    ]
  }}
}}
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
{{
  "cross_section_dependencies": [
    {{
      "primary_section_id": "string — the section_id of the section that contains the dependency or the section that is being modified",
      "dependent_section_id": "string — the section_id of the section that modifies, qualifies, or references the primary section",
      "dependency_type": "string — one of the following types: MODIFIES, REFERENCES, CONDITIONALLY_APPLIES, DEFINES_TERM_USED_BY, OVERRIDES, REQUIRES_CONTEXT_FROM",
      "dependency_description": "string — one sentence describing the nature of the dependency and why it is relevant for entity extraction. Explain what information from the dependent_section changes or contextualizes the primary_section."
    }}
  ]
}}
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

Once you have read the full document, produce the outputs in valid JSON format.

<document_text>
{document_text}
</document_text>

<final_instructions>
1. Read the entire document before writing a single character of output.
2. Ensure all section_ids referenced in global_entity_pre_registration \
(mentioned_in_sections) exactly match section_ids defined in the document_map.
3. Use null for any field where the value is genuinely not present in the document.
4. Preserve verbatim accuracy in beginning_text fields. These will be used for exact \
string matching against the source document.\
</final_instructions>
"""


def _build_entity_types_list() -> str:
    """Generate the permitted entity types list with descriptions from schemas.py."""
    lines = []
    for type_name, cls in sorted(ENTITY_TYPE_MAP.items()):
        doc = (cls.__doc__ or "").strip()
        lines.append(f'- "{type_name}": {doc}')
    return "\n".join(lines)


def run_first_pass(
    document_text: str,
    client: Anthropic | None = None,
    model: str | None = None,
) -> tuple[FirstPassResult, StageUsage]:
    """Run the first pass document analysis.

    Analyzes the full document in a single LLM call to produce a document map,
    global entity pre-registration, and cross-section dependencies.

    Args:
        document_text: The full document text (markdown).
        client: Anthropic client. Creates one if not provided.

    Returns:
        Tuple of (FirstPassResult, StageUsage with token counts).
    """
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    entity_types_list = _build_entity_types_list()
    system_prompt = FIRST_PASS_SYSTEM_PROMPT.format(
        entity_types=entity_types_list,
    )
    user_prompt = FIRST_PASS_USER_PROMPT.format(
        document_text=document_text,
    )

    _dbg(
        f"SYSTEM PROMPT ({len(system_prompt)} chars)",
        system_prompt,
    )
    _dbg(
        f"USER PROMPT ({len(user_prompt)} chars)",
        user_prompt,
    )
    thinking = thinking_config(model, budget_tokens=32768)
    _dbg(
        "API CALL",
        f"model: {model}\n"
        f"max_tokens: 49152 (thinking: {thinking})\n"
        f"user_prompt length: {len(user_prompt)} chars",
    )

    # Use streaming to avoid SDK timeout on large thinking requests
    collected_thinking = ""
    collected_text = ""
    with client.messages.stream(
        model=model,
        max_tokens=49152,
        thinking=thinking,
        output_format=FirstPassResult,
        system=system_prompt,
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
        response = stream.get_final_message()

    raw = collected_text
    _dbg(f"LLM RESPONSE ({len(raw)} chars)", raw)

    usage = StageUsage(
        stage="stage0_first_pass",
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        api_calls=1,
    )

    result: FirstPassResult = response.parsed_output
    _dbg(
        "PARSED RESULT",
        f"document_map sections: {len(result.document_map.sections)}\n"
        f"pre-registered entities: {len(result.global_entity_pre_registration)}\n"
        f"cross-section dependencies: {len(result.cross_section_dependencies)}",
    )

    return result, usage


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

    input_text = open(args.input, encoding="utf-8").read()
    print(f"Read {len(input_text)} chars from {args.input}")

    result, usage = run_first_pass(input_text)
    print(f"  Tokens: {usage.input_tokens} in, {usage.output_tokens} out ({usage.api_calls} API call)")

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
