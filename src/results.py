"""Result storage for pipeline runs.

Saves every pipeline run with full provenance so expensive API calls
are never lost. Organized by run ID with consistent structure.

Directory layout:
    results/
    ├── runs/
    │   ├── 2026-02-28T12-30-00_sample_policy/
    │   │   ├── run_meta.json          # Run metadata (timings, counts, config)
    │   │   ├── sections.json          # Stage 1 output: segmented sections
    │   │   ├── extractions.json       # Stage 2 output: per-section extractions
    │   │   ├── ontology.json          # Stage 3 output: merged ontology graph
    │   │   ├── entities.json          # Entities grouped by type (human-readable)
    │   │   ├── relationships.json     # Relationships grouped by type (human-readable)
    │   │   └── graph.html             # Visualization snapshot
    │   └── ...
    └── latest -> runs/<most_recent>/  # Symlink or file pointing to latest run
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from src.models import (
    DocumentSection,
    ExtractionMetadata,
    OntologyGraph,
    SectionExtraction,
)
from src.schemas import get_typed_attributes

RESULTS_DIR = Path(__file__).parent.parent / "results"
RUNS_DIR = RESULTS_DIR / "runs"


def _make_run_id(policy_name: str) -> str:
    """Generate a run ID from timestamp and policy name."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    # Sanitize policy name for filesystem
    clean_name = re.sub(r"[^\w\-.]", "_", Path(policy_name).stem)
    return f"{ts}_{clean_name}"


def save_run(
    ontology: OntologyGraph,
    section_extractions: list[SectionExtraction],
    policy_name: str,
    pipeline_elapsed: float,
    stage_timings: dict[str, float] | None = None,
    semantic_dedup_log: list[dict] | None = None,
) -> Path:
    """Save a complete pipeline run.

    Args:
        ontology: The final merged OntologyGraph.
        section_extractions: Per-section extraction results from Stage 2.
        policy_name: Name/path of the source policy file.
        pipeline_elapsed: Total pipeline time in seconds.
        stage_timings: Optional dict of stage name -> elapsed seconds.
        semantic_dedup_log: LLM dedup decisions per entity type.

    Returns:
        Path to the run directory.
    """
    run_id = _make_run_id(policy_name)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- run_meta.json ---
    meta = ontology.extraction_metadata
    run_meta = {
        "run_id": run_id,
        "policy_file": policy_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_elapsed_seconds": round(pipeline_elapsed, 1),
        "stage_timings": stage_timings or {},
        "document_char_count": meta.document_char_count,
        "section_count": meta.section_count,
        "extraction_passes": meta.extraction_passes,
        "total_api_calls": meta.total_api_calls,
        "total_input_tokens": meta.total_input_tokens,
        "total_output_tokens": meta.total_output_tokens,
        "final_entity_count": meta.final_entity_count,
        "final_relationship_count": meta.final_relationship_count,
        "deduplication_merges": meta.deduplication_merges,
        "semantic_dedup_merges": meta.semantic_dedup_merges,
        "semantic_dedup_api_calls": meta.semantic_dedup_api_calls,
        "source_anchoring": {
            "total_entities": len(ontology.entities),
            "anchored": sum(
                1 for e in ontology.entities if e.source_anchor.source_text
            ),
            "verified_in_document": sum(
                1
                for e in ontology.entities
                if e.source_anchor.source_text
                and e.source_anchor.source_offset >= 0
            ),
        },
    }
    _write_json(run_dir / "run_meta.json", run_meta)

    # --- sections.json ---
    sections_data = []
    for s in ontology.source_sections:
        sections_data.append({
            "chunk_id": s.chunk_id,
            "section_number": s.section_number,
            "header": s.header,
            "level": s.level,
            "source_offset": s.source_offset,
            "parent_section": s.parent_section,
            "parent_header": s.parent_header,
            "hierarchical_path": [
                entry.model_dump() for entry in s.hierarchical_path
            ],
            "char_count": len(s.text),
            "enumerated_lists": [el.model_dump() for el in s.enumerated_lists],
        })
    _write_json(run_dir / "sections.json", sections_data)

    # --- extractions.json ---
    extractions_data = []
    for se in section_extractions:
        extractions_data.append({
            "section_number": se.section.section_number,
            "section_header": se.section.header,
            "entity_count": len(se.entities),
            "relationship_count": len(se.relationships),
            "entities": [e.model_dump() for e in se.entities],
            "relationships": [r.model_dump() for r in se.relationships],
        })
    _write_json(run_dir / "extractions.json", extractions_data)

    # --- ontology.json (full serialized graph) ---
    _write_json(run_dir / "ontology.json", ontology.model_dump())

    # --- entities.json (grouped by type, human-readable) ---
    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in ontology.entities:
        entity_data: dict = {
            "id": e.id,
            "name": e.name,
            "description": e.description,
            "typed_attributes": get_typed_attributes(e),
            "source_section": e.source_anchor.source_section,
            "source_text": e.source_anchor.source_text,
        }
        if e.source_anchors:
            entity_data["source_anchors"] = [
                {"source_text": a.source_text, "source_section": a.source_section}
                for a in e.source_anchors
            ]
        by_type[e.type].append(entity_data)
    entities_grouped = {
        "total": len(ontology.entities),
        "by_type": {
            t: {"count": len(entities), "entities": entities}
            for t, entities in sorted(by_type.items())
        },
    }
    _write_json(run_dir / "entities.json", entities_grouped)

    # --- relationships.json (grouped by type, human-readable) ---
    rel_by_type: dict[str, list[dict]] = defaultdict(list)
    for r in ontology.relationships:
        # Resolve names for readability
        source_name = r.source_id
        target_name = r.target_id
        for e in ontology.entities:
            if e.id == r.source_id:
                source_name = e.name
            if e.id == r.target_id:
                target_name = e.name

        rel_by_type[r.type].append({
            "source_id": r.source_id,
            "source_name": source_name,
            "target_id": r.target_id,
            "target_name": target_name,
            "description": r.description,
            "source_sections": r.source_sections,
        })
    rels_grouped = {
        "total": len(ontology.relationships),
        "by_type": {
            t: {"count": len(rels), "relationships": rels}
            for t, rels in sorted(rel_by_type.items())
        },
    }
    _write_json(run_dir / "relationships.json", rels_grouped)

    # --- semantic_dedup.json ---
    if semantic_dedup_log:
        _write_json(run_dir / "semantic_dedup.json", {
            "total_type_groups_analyzed": len(semantic_dedup_log),
            "total_merges": meta.semantic_dedup_merges,
            "total_api_calls": meta.semantic_dedup_api_calls,
            "type_groups": semantic_dedup_log,
        })

    # --- Update latest pointer ---
    latest_file = RESULTS_DIR / "latest.txt"
    latest_file.write_text(run_id, encoding="utf-8")

    print(f"\n  Results saved to: results/runs/{run_id}/")

    return run_dir


def load_run(run_id: str) -> dict:
    """Load a saved run by its ID. Returns dict with all components."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_dir}")

    result = {}
    for name in ["run_meta", "sections", "extractions", "ontology", "entities", "relationships", "semantic_dedup"]:
        filepath = run_dir / f"{name}.json"
        if filepath.exists():
            result[name] = json.loads(filepath.read_text(encoding="utf-8"))
    return result


def load_latest_run() -> dict:
    """Load the most recent run."""
    latest_file = RESULTS_DIR / "latest.txt"
    if not latest_file.exists():
        raise FileNotFoundError("No runs saved yet.")
    run_id = latest_file.read_text(encoding="utf-8").strip()
    return load_run(run_id)


def load_latest_ontology() -> OntologyGraph:
    """Load the OntologyGraph from the most recent run."""
    run = load_latest_run()
    return OntologyGraph(**run["ontology"])


def list_runs() -> list[dict]:
    """List all saved runs with summary metadata."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        meta_path = run_dir / "run_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                runs.append(meta)
            except (json.JSONDecodeError, KeyError):
                continue
    return runs


def _write_json(path: Path, data) -> None:
    """Write JSON with consistent formatting."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
