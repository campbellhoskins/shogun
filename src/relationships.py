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
import re
import sys
from collections import defaultdict

from anthropic import Anthropic
from dotenv import load_dotenv

from src.models import (
    DocumentSection,
    FirstPassDependency,
    FirstPassResult,
    Relationship,
)
from src.schemas import (
    BaseEntitySchema,
    RELATIONSHIP_SCHEMAS,
    validate_relationship,
)

load_dotenv()
TEST_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")

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


def _generate_relationship_types_section() -> str:
    """Generate relationship type list with type + description only.

    Intentionally omits source/target entity type constraints so the LLM
    extracts freely. Validation happens post-extraction.
    """
    lines = []
    seen: set[str] = set()
    for rs in RELATIONSHIP_SCHEMAS:
        if rs.type not in seen:
            seen.add(rs.type)
            lines.append(f"{rs.type:<28}{rs.description}")
    return "\n".join(lines)


RELATIONSHIP_SYSTEM_PROMPT = """\
You are a relationship extraction system for corporate travel policy documents.
You receive a set of entities and the full document. Extract every meaningful
relationship between entities that is grounded in the document text.

<rules>
Every relationship must be supported by specific document text — not domain
knowledge or entity type compatibility alone.

Relationships are directed: source is the actor or governing entity, target
is the object or governed entity.

source_id and target_id must match IDs from the provided entity list exactly.

Extract as many valid, grounded relationships as you can find. Prioritize
thoroughness and completeness.
</rules>

<cross_section_dependencies>
You are provided with a set of cross-section dependencies identified during an
earlier document analysis pass. These describe structural connections between
sections — where one section defines terms used by another, where one section
modifies or constrains another, or where one section requires context from another
to be fully understood.

Use these dependencies as a starting point for relationship discovery. Each
dependency suggests that entities from those two sections are likely connected.
Read the referenced sections closely and extract the specific entity-to-entity
relationships that underlie each dependency.

These dependencies are NOT exhaustive. They capture the most prominent structural
connections but many valid relationships exist that are not represented in this
list. Extract all grounded relationships you find, whether or not they correspond
to a listed dependency.

Do not treat the dependencies as relationships themselves. They describe
section-to-section connections. Your job is to find the entity-to-entity
relationships within and beyond them.
</cross_section_dependencies>

<relationship_types>
{relationship_types_section}
</relationship_types>

<output_schema>
Return a JSON object with key "relationships" containing an array. Each object:

  source_id        (string) Entity ID from provided list.
  target_id        (string) Entity ID from provided list.
  type             (string) From relationship_types above.
  description      (string) 1-2 sentences explaining the connection.

Return ONLY the JSON object.
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
        f"Produce only the JSON object."
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_relationships_response(raw: str) -> list[dict]:
    """Parse the LLM response into a list of relationship dicts."""
    cleaned = raw.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            data = json.loads(match.group())
        else:
            raise

    if isinstance(data, dict) and "relationships" in data:
        return data["relationships"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected response format: {type(data)}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_relationships(
    entities: list[BaseEntitySchema],
    sections: list[DocumentSection],
    cross_section_dependencies: list[FirstPassDependency],
    existing_relationships: list[Relationship],
    client: Anthropic,
) -> tuple[list[Relationship], list[dict], list[dict]]:
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
    """
    # Build relationship types section (type + description only, no constraints)
    rel_types_section = _generate_relationship_types_section()
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
        thinking_budget = min(32768, max(8192, len(entities) * 500))
        max_tokens = thinking_budget + min(32768, max(8192, len(entities) * 300))

        raw_text = ""
        thinking_text = ""

        with client.messages.stream(
            model=TEST_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
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

        # Parse response
        raw_rels = _parse_relationships_response(raw_text)
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
            warnings = validate_relationship(
                rel_type, source_id, target_id, entity_type_lookup
            )
            if warnings:
                invalid_relationships.append({
                    **rel_dict,
                    "warnings": warnings,
                })
                continue

            valid_relationships.append(Relationship(
                source_id=source_id,
                target_id=target_id,
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

        return valid_relationships, invalid_relationships, [log_entry]

    except Exception as e:
        print(f"    WARNING: Relationship extraction failed: {e}")
        log_entry["error"] = str(e)
        return [], [], [log_entry]


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
        help="Path to write output JSON (default: print to stdout).",
    )
    parser.add_argument(
        "--output-ontology",
        default=None,
        help="Path to write updated ontology JSON with new relationships merged in.",
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
    valid_rels, invalid_rels, log = extract_relationships(
        entities=ontology.entities,
        sections=sections,
        cross_section_dependencies=cross_deps,
        existing_relationships=ontology.relationships,
        client=client,
    )

    # Output
    result = {
        "valid_relationships": [r.model_dump() for r in valid_rels],
        "invalid_relationships": invalid_rels,
        "stats": {
            "valid": len(valid_rels),
            "invalid": len(invalid_rels),
        },
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nWrote {len(valid_rels)} relationships to {args.output}")
    else:
        print(f"\n{len(valid_rels)} valid relationships extracted")
        for r in valid_rels:
            print(f"  {r.source_id} --[{r.type}]--> {r.target_id}: {r.description}")

    # Write updated ontology with new relationships merged in
    if args.output_ontology:
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
        with open(args.output_ontology, "w", encoding="utf-8") as f:
            json.dump(ontology.model_dump(), f, indent=2, ensure_ascii=False, default=str)
        print(f"Wrote updated ontology to {args.output_ontology}: {len(deduped)} total relationships")


if __name__ == "__main__":
    main()
