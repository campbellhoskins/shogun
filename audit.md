# Shogun Codebase Audit

**Date:** 2026-03-07
**Scope:** Full codebase — data models, pipeline flow, frontend/API layer, dependencies, project structure

---

## Executive Summary

The codebase has accumulated significant bloat from experimentation: **6 unused Python dependencies** (including the entire LangChain stack), **17 stale data files**, **3 files that can be deleted entirely**, and **substantial dead code** within otherwise-needed files. The core pipeline architecture (Stages 0-4) is well-designed, but the supporting infrastructure has legacy artifacts, duplicated utility functions, and inconsistencies that make the codebase harder to follow than it needs to be.

The data model layer (`models.py`, `schemas.py`, `api_models.py`) is clean with a proper separation between domain models and API presentation models. The main issues are dead fields on `ExtractionMetadata`, 5 unused fields on `RelationshipSchema`, and duplicated helper functions across 3+ files.

---

## 1. Dead Dependencies (High Priority)

**6 of 13 Python dependencies are completely unused:**

| Dependency | Status | Impact |
|---|---|---|
| `llama-parse>=0.6.94` | Zero imports anywhere | Requires separate API key, heavyweight |
| `langchain-experimental>=0.3.0` | Zero imports anywhere | Pulls dozens of transitive deps |
| `langchain-anthropic>=0.3.0` | Zero imports anywhere | LangChain experiment abandoned |
| `langchain-community>=0.3.0` | Zero imports anywhere | LangChain experiment abandoned |
| `langchain-core>=0.3.0` | Zero imports anywhere | LangChain experiment abandoned |
| `scipy>=1.17.1` | Zero imports anywhere | Speculatively added, never used |

**Additionally marginal:**
| Dependency | Status |
|---|---|
| `pyvis>=0.3.2` | Only used by legacy `src/visualizer.py` (Pyvis HTML), not the React frontend |
| `pymupdf4llm>=0.3.4` | Only used by inactive `src/pdf_parser_2.py` |
| `pypdf>=6.7.4` | Only used by `src/generate_qa.py` (not main pipeline) |

**Frontend:** All npm dependencies are actively used. `vis-data` is technically redundant (bundled inside `vis-network/standalone`) but causes no harm.

---

## 2. Files That Can Be Deleted

### Delete entirely:
| File | Reason |
|---|---|
| `src/pdf_parser_1.py` | Byte-for-byte identical copy of `src/pdf_parser.py`. Never imported. |
| `src/pdf_parser_2.py` | Never imported by any module. Inactive reference parser. |
| `src/visualizer.py` | Legacy Pyvis HTML generator. Superseded by React frontend. Only called by `main.py`. |

### Legacy files to evaluate for removal:
| File | Reason |
|---|---|
| `src/parser.py` | `parse_policy()` is a one-line wrapper around `extract_ontology()`. `parse_policy_legacy()` is dead. Only exists as indirection for `build_graph.py` and `validate.py`. |
| `src/build_graph.py` | Legacy CLI. Now delegates to the full pipeline anyway. Its only unique value is `load_graph_file()`/`list_graphs()` used by `test_agent.py` and `eval.py`. |

---

## 3. Dead Code Within Needed Files

### Dead imports:
| File | Dead Import |
|---|---|
| `src/main.py` | `from src.parser import parse_policy` — never called |
| `src/main.py` | `serialize_graph` from `src.graph` — never called |
| `src/validate.py` | `serialize_graph` from `src.graph` — never called |

### Dead functions:
| File | Function | Reason |
|---|---|---|
| `src/graph.py` | `serialize_graph()` | Imported in 2 files but never called in either |
| `src/graph.py` | `get_source_text()` | Never called from anywhere |
| `src/graph.py` | `get_section_text()` | Never called from anywhere |
| `src/graph.py` | `query_neighbors()` | Never called from anywhere |
| `src/graph.py` | `query_by_type()` | Never called from anywhere |
| `src/extraction.py` | `extract_section()` | Sync single-section function; pipeline uses async `_extract_section_async` via `extract_all_sections` |
| `src/parser.py` | `parse_policy_legacy()` | Never called |
| `src/parser.py` | `LEGACY_EXTRACTION_SYSTEM_PROMPT` | Only used by dead `parse_policy_legacy()` |
| `src/pdf_parser.py` | `parse_all_pdfs()` | Only called from its own `__main__` CLI block |

### Dead model fields:
| Model | Field | Issue |
|---|---|---|
| `ExtractionMetadata` | `deduplication_merges` | Always 0. Superseded by `exact_id_dedup_merges` + `semantic_dedup_merges` |
| `ExtractionMetadata` | `total_input_tokens` | Always 0. Never populated by any stage |
| `ExtractionMetadata` | `total_output_tokens` | Always 0. Never populated by any stage |
| `RelationshipSchema` | `cardinality` | Set on every instance but never read by any code |
| `RelationshipSchema` | `is_directed` | Set on every instance but never read by any code |
| `RelationshipSchema` | `mandatory` | Set on every instance but never read by any code |
| `RelationshipSchema` | `inverse_type` | Set on every instance but never read by any code |
| `RelationshipSchema` | `agent_traversal_hint` | Substantial text on every instance, never surfaced anywhere |

---

## 4. Duplicated Code (DRY Violations)

### `_sections_from_chunks()` — triplicated
Identical function in 3 files reconstructing `DocumentSection` from JSON dicts:
- `src/extraction.py:887`
- `src/merge.py:683`
- `src/cross_section.py:483`

### `_extractions_from_json()` — duplicated
Near-identical in 2 files:
- `src/merge.py:697`
- `src/cross_section.py:501`

### JSON response parsing — quintuplicated
Five copies of "strip markdown fences, parse JSON, fallback to regex":
- `src/first_pass.py:_parse_json_response()`
- `src/extraction.py:_parse_extraction_response()`
- `src/merge.py:_parse_dedup_response()`
- `src/relationships.py:_parse_relationships_response()`
- `src/cross_section.py:_parse_response()`

### `_dbg()` debug helper — quintuplicated
Five identical debug print functions across pipeline stages.

### `ask_verbose()` in `test_agent.py`
Duplicates most of `agent.ask()` with added print statements. Could be a wrapper.

### Edge styling in `GraphCanvas.tsx`
Edge style object duplicated between initial creation (lines 147-172) and collapse re-creation (lines 324-348).

**Recommendation:** Create `src/utils.py` with shared `parse_json_response()`, `sections_from_chunks()`, `extractions_from_json()`, and `dbg()` functions.

---

## 5. Hardcoded Model Names (Violating CLAUDE.md)

CLAUDE.md mandates using `TEST_MODEL` from `.env` for all LLM calls. These files ignore it:

| File | Line | Hardcoded Model |
|---|---|---|
| `src/first_pass.py` | 317 | `claude-sonnet-4-20250514` |
| `src/agent.py` | 319 | `claude-sonnet-4-20250514` |
| `src/test_agent.py` | 43 | `claude-sonnet-4-20250514` |
| `src/eval.py` | 66 | `claude-sonnet-4-20250514` |
| `src/generate_qa.py` | 83 | `claude-opus-4-20250514` |
| `src/validate.py` | 91 | `claude-sonnet-4-20250514` |

**Files that correctly use TEST_MODEL:** `src/extraction.py`, `src/merge.py`, `src/relationships.py`, `src/cross_section.py`.

---

## 6. Data Model Assessment

### Architecture (Good)
The model layer has clean separation:
- **`src/base_models.py`** → `SourceAnchor` (exists to break circular import — valid pattern)
- **`src/schemas.py`** → `BaseEntitySchema` + 16 entity subclasses + `RelationshipSchema` + `AnyEntity` discriminated union
- **`src/models.py`** → Domain models: `DocumentSection`, `FirstPass*`, `Relationship`, `OntologyGraph`, etc.
- **`src/api_models.py`** → 15 presentation-layer models for the React frontend API
- **`frontend/src/types.ts`** → TypeScript mirrors of API models (well synchronized)

**No true duplicates between api_models.py and models.py.** The `AgentResponse` → `AgentAnswer` conversion is intentional (domain IDs → resolved summaries for frontend).

### Issues (Minor)
| Issue | Location | Impact |
|---|---|---|
| `source_offset` default inconsistency: `0` for sections, `-1` for anchors | `models.py:20` vs `base_models.py:17` | Semantic confusion, potential bugs |
| `section_name` vs `header` naming inconsistency | `FirstPassSection` vs `DocumentSection` | Cognitive friction |
| `entity_name` vs `name` naming inconsistency | `FirstPassEntity` vs all other entities | Minor |
| 12 of 16 entity subclasses have zero typed attributes | `schemas.py:65-215` | Forward-looking design, not a problem per se |
| `OntologyGraph.source_document` stores full markdown text | `models.py` | Makes `ontology.json` files very large |
| Typed attributes stringified in `graph.py:22` | `str(v)` conversion | Loses type info (int/bool → string) for frontend |

---

## 7. Stale Data Files

### LangChain experiment artifacts (5 files):
- `data/langchain_kg_chunked_schema_free.json`
- `data/langchain_kg_chunked_schema_guided.json`
- `data/langchain_kg_comparison.json`
- `data/langchain_kg_whole_doc_schema_free.json`
- `data/langchain_kg_whole_doc_schema_guided.json`

### Pipeline intermediates in wrong location (5 files):
Per CLAUDE.md conventions, these belong in `results/runs/`, not `data/`:
- `data/DT_first_pass.json`
- `data/DT_chunks.json`
- `data/extractions.json`
- `data/cross_section.json`
- `data/ontology_dedup_log.json`

### Debug dumps (2 files):
- `data/extract.txt`
- `data/merge.txt`

### Test/mock fixtures (5 files):
- `data/sample_policy.md`
- `data/example_segment_output.txt`
- `data/test_ontology.json`
- `data/test_extraction.json` / `test_extraction2.json`
- `data/ontology_mock.json`
- `data/test_chunks.json`

### Documentation mismatch:
- CLAUDE.md references `data/231123_Duty_of_Care_Policy.pdf` — file does not exist (actual: `data/Duty-of-Care-Policy.pdf`)
- CLAUDE.md references `data/231123_Duty_of_Care_Policy.qa.small.json` — no `.qa.json` files exist
- `data/parser_1/` documented as Parser 1 output directory — directory is empty; outputs are in `output/parsed/` instead

---

## 8. Frontend Issues

### Dead CSS:
| Rule | File | Reason |
|---|---|---|
| `.pathfinder-loading` | `styles/PathFinder.css:185` | No component uses this class |
| `@keyframes travel-event-glow` | `styles/GraphCanvas.css:115` | Animation defined but never applied |
| `.legend-toggle.collapsed` rotation | `styles/Legend.css:40` | Rotation on text characters has no visible effect |
| `.top-bar` | `styles/App.css:15` | TopBar uses className `topbar`, not `top-bar` |

### Test issues:
| Test File | Issue |
|---|---|
| `force-layout.spec.ts` | Hardcoded `http://localhost:8789` instead of relative path |
| `collapsible-subtrees.spec.ts` | Named "collapsible subtrees" but never tests collapsing |
| `cascade-highlighting.spec.ts` | Conditional logic allows silent pass if no TravelEvent exists |
| `hierarchical-layout.spec.ts` | Misleading name — tests generic layout, not hierarchical |
| `click-highlight.spec.ts:50` | `firstName` variable declared but never used |
| Multiple files | Heavy overlap: zoom, search, legend tested 3-4x across files |

### Redundant endpoint:
`/api/graph/stats` returns entity counts and type distribution — all derivable client-side from `/api/graph` which already contains all nodes. This is an extra HTTP request for redundant data.

---

## 9. Configuration Issues

| Issue | Detail |
|---|---|
| Port confusion | Vite dev proxies to `:8787`, Playwright tests hit `:8789`, CLAUDE.md only mentions `:8789` |
| TypeScript strictness disabled | `noUnusedLocals: false`, `noUnusedParameters: false` in `tsconfig.json` |
| `output/parsed/` vs `data/parser_1/` | Parsed markdowns in `output/parsed/` but convention says `data/parser_1/` |
| `.gitignore` gaps | Missing entries for `data/*.txt`, `data/ontology_dedup_log.json`, `data/cross_section.json` |
| Orphan `.pyc` | `src/__pycache__/old_pdf_parser.cpython-312.pyc` from deleted source file |

---

## 10. Pipeline Flow (Reference)

```
src/main.py
  → src/pdf_parser.py (parse_pdf)
  → src/pipeline.py (extract_ontology)
       → Stage 0: src/first_pass.py      → FirstPassResult
       → Stage 1: src/segmenter.py       → DocumentSection[]
       → Stage 2: src/extraction.py      → SectionExtraction[]  (async parallel)
       → Stage 3a: src/cross_section.py  → Relationship[]       (cross-section)
       → Stage 3b: src/merge.py          → OntologyGraph         (dedup + merge)
       → Stage 4: src/relationships.py   → Relationship[]       (full-document)
       → src/results.py (save_run)
  → src/graph.py (build_graph → NetworkX)
  → src/visualizer.py (generate_visualization)  ← LEGACY
  → src/agent.py (ask → interactive Q&A)

src/frontend.py (FastAPI)
  → src/graph.py, src/agent.py, src/results.py, src/api_models.py
```

### Essential files (12):
`pipeline.py`, `first_pass.py`, `segmenter.py`, `extraction.py`, `cross_section.py`, `merge.py`, `relationships.py`, `models.py`, `schemas.py`, `results.py`, `agent.py`, `frontend.py`

### Supporting files (4):
`main.py`, `graph.py`, `api_models.py`, `base_models.py`, `pdf_parser.py`

### Legacy/deletable files (5):
`pdf_parser_1.py`, `pdf_parser_2.py`, `visualizer.py`, `parser.py`, `build_graph.py`

---

## 11. Recommended Action Plan

### Phase 1: Dependency & File Cleanup
1. Remove 6 unused Python deps from `pyproject.toml`, run `uv sync`
2. Delete `src/pdf_parser_1.py` (exact duplicate)
3. Delete 5 `data/langchain_kg_*.json` files
4. Delete or move misplaced pipeline intermediates from `data/`
5. Update `.gitignore` for debug files

### Phase 2: Dead Code Removal
6. Remove 5 dead functions from `src/graph.py`
7. Remove dead imports from `main.py` and `validate.py`
8. Remove `parse_policy_legacy()` and `LEGACY_EXTRACTION_SYSTEM_PROMPT` from `parser.py`
9. Remove dead fields from `ExtractionMetadata` and `RelationshipSchema`
10. Remove dead CSS rules

### Phase 3: DRY Consolidation
11. Create `src/utils.py` with shared `parse_json_response()`, `sections_from_chunks()`, `extractions_from_json()`, `dbg()`
12. Fix all hardcoded model names to use `TEST_MODEL`
13. Consolidate `parser.py` into direct calls to `pipeline.extract_ontology()`

### Phase 4: Convention Alignment
14. Fix CLAUDE.md references to nonexistent files
15. Reconcile `output/parsed/` vs `data/parser_1/` convention
16. Fix test file names to match what they actually test
17. Remove test overlap / strengthen weak tests
18. Enable TypeScript strict unused checks

---

## 12. What's Working Well

- **Pipeline architecture (Stages 0-4):** Well-structured, clear separation of concerns, proper async parallelism
- **Model layer separation:** Domain models, entity schemas, and API models are properly layered
- **TypeScript/Python API sync:** Frontend types closely mirror backend models
- **Result storage conventions:** `results/runs/` with immutable run IDs and reloadable ontology
- **Entity schema system:** The `BaseEntitySchema` + discriminated union + auto-discovery pattern is solid
- **Source anchoring:** The `SourceAnchor` system with offset verification is enterprise-grade
- **Frontend API layer:** All endpoints are consumed, no dead endpoints, clean `api.ts` client
