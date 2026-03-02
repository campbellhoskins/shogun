"""Pipeline orchestrator: chains segmentation, extraction, and merge stages.

This is the top-level entry point for the Source-Anchored Extraction pipeline.
Phase 1 implements Stages 1-3. Later phases will add stages 4-7.
"""

from __future__ import annotations

import time

from anthropic import Anthropic

from src.extraction import extract_all_sections
from src.merge import merge_extractions
from src.models import OntologyGraph
from src.results import save_run
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

    # --- Stage 1: Semantic Chunking ---
    print("Stage 1: Chunking document...")
    stage_start = time.time()
    sections = segment_document(document_text, client=client)
    stage_timings["segmentation"] = round(time.time() - stage_start, 1)
    print(f"  Found {len(sections)} chunks ({stage_timings['segmentation']}s)")
    for s in sections:
        list_info = ""
        if s.enumerated_lists:
            list_counts = [
                f"{el.item_count} {el.list_type}" for el in s.enumerated_lists
            ]
            list_info = f" [lists: {', '.join(list_counts)}]"
        print(
            f"    {'  ' * (s.level - 1)}{s.chunk_id} "
            f"{s.section_number}: {s.header} "
            f"({len(s.text)} chars){list_info}"
        )

    # --- Stage 2: Per-Section Extraction ---
    print("\nStage 2: Extracting entities per section...")
    stage_start = time.time()
    section_extractions = extract_all_sections(sections, client=client)
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

    # --- Stage 3: Merge + LLM Deduplication ---
    print("\nStage 3: Merging and deduplicating (LLM-based)...")
    stage_start = time.time()
    ontology, semantic_dedup_log = merge_extractions(
        section_extractions, document_text, sections, client=client
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
    )

    return ontology
