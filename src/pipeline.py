"""Pipeline orchestrator: chains segmentation, extraction, and merge stages.

This is the top-level entry point for the Source-Anchored Extraction pipeline.
Phase 1 implements Stages 1-3. Later phases will add stages 4-7.
"""

from __future__ import annotations

import time

from anthropic import Anthropic

from src.cross_section import extract_cross_section_relationships
from src.extraction import extract_all_sections
from src.first_pass import run_first_pass
from src.merge import merge_extractions
from src.models import OntologyGraph
from src.results import save_run
from src.schemas import validate_relationship
from src.segmenter import segment_document


def extract_ontology(
    document_text: str,
    client: Anthropic | None = None,
    policy_name: str = "unknown",
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

    pipeline_start = time.time()
    stage_timings: dict[str, float] = {}

    # --- Stage 0: First Pass ---
    print("Stage 0: First pass document analysis...")
    stage_start = time.time()
    first_pass_result = run_first_pass(document_text, client=client)
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
        document_text, client=client, first_pass_result=first_pass_result
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
    section_extractions = extract_all_sections(
        sections, client=client, first_pass_result=first_pass_result
    )
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
    cross_section_rels, cross_section_log = extract_cross_section_relationships(
        section_extractions, client=client
    )
    stage_timings["cross_section"] = round(time.time() - stage_start, 1)
    print(
        f"  {len(cross_section_rels)} cross-section relationships "
        f"({stage_timings['cross_section']}s)"
    )

    # --- Stage 3b: Merge + LLM Deduplication ---
    print("\nStage 3b: Merging and deduplicating (LLM-based)...")
    stage_start = time.time()
    ontology, semantic_dedup_log = merge_extractions(
        section_extractions, document_text, sections, client=client,
        cross_section_relationships=cross_section_rels,
    )
    stage_timings["merge"] = round(time.time() - stage_start, 1)

    meta = ontology.extraction_metadata
    print(
        f"  {meta.final_entity_count} entities, "
        f"{meta.final_relationship_count} relationships "
        f"({meta.semantic_dedup_merges} semantic duplicates merged, "
        f"{meta.semantic_dedup_api_calls} API calls) ({stage_timings['merge']}s)"
    )

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
    print(f"\nPipeline complete in {pipeline_elapsed:.1f}s")

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
    )

    return ontology
