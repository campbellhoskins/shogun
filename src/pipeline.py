"""Pipeline orchestrator: chains all extraction stages (0-4).

This is the top-level entry point for the Source-Anchored Extraction pipeline.
Stages: First Pass → Segmentation → Extraction → Cross-Section → Merge → Relationships.
"""

from __future__ import annotations

import os
import time

from anthropic import Anthropic
from dotenv import load_dotenv

from src.cross_section import extract_cross_section_relationships
from src.extraction import extract_all_sections
from src.first_pass import run_first_pass
from src.merge import merge_extractions
from src.models import OntologyGraph, StageUsage
from src.relationships import extract_relationships
from src.results import save_run
from src.schemas import validate_relationship
from src.segmenter import segment_document

load_dotenv()
_DEFAULT_MODEL = os.environ.get("TEST_MODEL", "claude-haiku-4-5-20251001")


def extract_ontology(
    document_text: str,
    client: Anthropic | None = None,
    policy_name: str = "unknown",
    model: str | None = None,
) -> OntologyGraph:
    """Full Source-Anchored Extraction pipeline.

    Phase 1 stages:
        Stage 1: LLM Segmentation
        Stage 2: Per-Section Extraction (parallel)
        Stage 3: Deterministic Merge & Deduplication

    All results are automatically saved to results/runs/.

    Args:
        document_text: The full document text.
        client: Anthropic client. Creates one if not provided.
        policy_name: Name of the source policy file (for result storage).

    Returns:
        OntologyGraph with source anchoring and extraction metadata.
    """
    if client is None:
        client = Anthropic()
    model = model or _DEFAULT_MODEL

    pipeline_start = time.time()
    stage_timings: dict[str, float] = {}

    all_usages: list[StageUsage] = []

    print(f"Using model: {model}")

    # --- Stage 0: First Pass ---
    print("Stage 0: First pass document analysis...")
    stage_start = time.time()
    first_pass_result, stage0_usage = run_first_pass(document_text, client=client, model=model)
    all_usages.append(stage0_usage)
    stage_timings["first_pass"] = round(time.time() - stage_start, 1)
    fp_map = first_pass_result.document_map
    print(
        f"  {len(fp_map.sections)} sections, "
        f"{len(first_pass_result.global_entity_pre_registration)} pre-registered entities, "
        f"{len(first_pass_result.cross_section_dependencies)} dependencies "
        f"({stage_timings['first_pass']}s)"
    )

    # --- Stage 1: Deterministic Chunking ---
    print("\nStage 1: Chunking document (deterministic)...")
    stage_start = time.time()
    sections = segment_document(
        document_text, first_pass_result=first_pass_result
    )
    stage_timings["segmentation"] = round(time.time() - stage_start, 1)
    print(f"  Found {len(sections)} chunks ({stage_timings['segmentation']}s)")
    for s in sections:
        print(
            f"    {s.section_id} "
            f"{s.section_number}: {s.header} "
            f"({len(s.text)} chars)"
        )

    # --- Stage 2: Per-Section Extraction ---
    print("\nStage 2: Extracting entities per section...")
    stage_start = time.time()
    section_extractions, stage2_usage = extract_all_sections(
        sections, client=client, first_pass_result=first_pass_result, model=model
    )
    all_usages.append(stage2_usage)
    stage_timings["extraction"] = round(time.time() - stage_start, 1)

    total_entities = sum(len(se.entities) for se in section_extractions)
    total_rels = sum(len(se.relationships) for se in section_extractions)
    print(
        f"  Extracted {total_entities} entities, "
        f"{total_rels} relationships ({stage_timings['extraction']}s)"
    )
    for se in section_extractions:
        print(
            f"    {se.section.section_number}: "
            f"{len(se.entities)} entities, {len(se.relationships)} rels"
        )

    # --- Stage 3a: Cross-Section Relationship Extraction ---
    print("\nStage 3a: Extracting cross-section relationships...")
    stage_start = time.time()
    cross_section_rels, cross_section_log, stage3a_usage = extract_cross_section_relationships(
        section_extractions, client=client, model=model
    )
    all_usages.append(stage3a_usage)
    stage_timings["cross_section"] = round(time.time() - stage_start, 1)
    print(
        f"  {len(cross_section_rels)} cross-section relationships "
        f"({stage_timings['cross_section']}s)"
    )

    # --- Stage 3b: Merge + LLM Deduplication ---
    print("\nStage 3b: Merging and deduplicating (LLM-based)...")
    stage_start = time.time()
    ontology, semantic_dedup_log, stage3b_usage = merge_extractions(
        section_extractions, document_text, sections, client=client,
        cross_section_relationships=cross_section_rels, model=model,
    )
    all_usages.append(stage3b_usage)
    stage_timings["merge"] = round(time.time() - stage_start, 1)

    meta = ontology.extraction_metadata
    print(
        f"  {meta.final_entity_count} entities, "
        f"{meta.final_relationship_count} relationships "
        f"({meta.exact_id_dedup_merges} exact-ID + {meta.semantic_dedup_merges} semantic duplicates merged, "
        f"{meta.semantic_dedup_api_calls} API calls) ({stage_timings['merge']}s)"
    )

    # --- Stage 4: Full-document relationship extraction ---
    print("\nStage 4: Extracting relationships (full document)...")
    stage_start = time.time()
    stage4_rels, stage4_invalid, stage4_log, stage4_usage = extract_relationships(
        entities=ontology.entities,
        sections=sections,
        cross_section_dependencies=first_pass_result.cross_section_dependencies,
        existing_relationships=ontology.relationships,
        client=client,
        model=model,
    )
    all_usages.append(stage4_usage)
    stage_timings["relationships"] = round(time.time() - stage_start, 1)

    # Combine Stage 4 relationships with existing ones
    if stage4_rels:
        combined_rels = list(ontology.relationships) + stage4_rels
        # Deduplicate by (source_id, target_id, type)
        seen_keys: set[tuple[str, str, str]] = set()
        deduped_rels = []
        for r in combined_rels:
            key = (r.source_id, r.target_id, r.type)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_rels.append(r)
        ontology.relationships = deduped_rels

    # Update metadata with Stage 4 stats
    stage4_dedup = stage4_log[0].get("dedup_count", 0) if stage4_log else 0
    ontology.extraction_metadata.stage4_relationship_count = len(stage4_rels)
    ontology.extraction_metadata.stage4_invalid_count = len(stage4_invalid)
    ontology.extraction_metadata.stage4_dedup_count = stage4_dedup
    ontology.extraction_metadata.stage4_api_calls = 1
    ontology.extraction_metadata.final_relationship_count = len(ontology.relationships)

    # Aggregate token usage from all stages
    ontology.extraction_metadata.stage_usages = all_usages
    ontology.extraction_metadata.total_input_tokens = sum(u.input_tokens for u in all_usages)
    ontology.extraction_metadata.total_output_tokens = sum(u.output_tokens for u in all_usages)
    ontology.extraction_metadata.total_api_calls = sum(u.api_calls for u in all_usages)

    print(
        f"  {len(stage4_rels)} new relationships "
        f"({len(stage4_invalid)} invalid, {stage4_dedup} deduplicated) "
        f"({stage_timings['relationships']}s)"
    )
    print(f"  Total relationships: {len(ontology.relationships)}")

    # --- Source anchoring stats ---
    anchored = sum(
        1 for e in ontology.entities if e.source_anchor.source_text
    )
    verified = sum(
        1 for e in ontology.entities
        if e.source_anchor.source_text
        and e.source_anchor.source_offset >= 0
    )
    print(
        f"\n  Source anchoring: {anchored}/{meta.final_entity_count} "
        f"({100 * anchored / max(meta.final_entity_count, 1):.0f}%) anchored, "
        f"{verified} verified in document"
    )

    # --- Relationship schema validation (advisory) ---
    entity_type_lookup = {e.id: e.type for e in ontology.entities}
    rel_warnings: list[str] = []
    for rel in ontology.relationships:
        warnings = validate_relationship(
            rel.type, rel.source_id, rel.target_id, entity_type_lookup
        )
        rel_warnings.extend(warnings)
    if rel_warnings:
        print(f"\n  Relationship validation: {len(rel_warnings)} warning(s)")
        for w in rel_warnings[:10]:  # Show first 10
            print(f"    [WARN] {w}")
        if len(rel_warnings) > 10:
            print(f"    ... and {len(rel_warnings) - 10} more")

    pipeline_elapsed = time.time() - pipeline_start
    total_in = ontology.extraction_metadata.total_input_tokens
    total_out = ontology.extraction_metadata.total_output_tokens
    total_calls = ontology.extraction_metadata.total_api_calls
    print(f"\nPipeline complete in {pipeline_elapsed:.1f}s")
    print(f"  Token usage: {total_in:,} in + {total_out:,} out = {total_in + total_out:,} total ({total_calls} API calls)")
    for u in all_usages:
        print(f"    {u.stage}: {u.input_tokens:,} in, {u.output_tokens:,} out ({u.api_calls} calls)")

    # --- Save results ---
    save_run(
        ontology=ontology,
        section_extractions=section_extractions,
        policy_name=policy_name,
        pipeline_elapsed=pipeline_elapsed,
        stage_timings=stage_timings,
        semantic_dedup_log=semantic_dedup_log,
        first_pass_result=first_pass_result,
        cross_section_log=cross_section_log,
        relationships_log=stage4_log,
    )

    return ontology
