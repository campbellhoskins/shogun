# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Shogun is an AI pipeline that ingests unstructured travel duty-of-care policy documents and builds structured ontology graphs. The pipeline extracts typed entities, relationships, and source anchors, then saves the result as a reloadable ontology. Separate tools (agent REPL, frontend, eval) can consume the saved graphs. The quality bar is production-grade enterprise tooling, not prototype.

**Document scope:** Travel duty of care policies only (risk classifications, approval workflows, evacuation procedures, personnel tracking). Not education/school duty of care.

## Prerequisites

- **Python >=3.12** (required by pyproject.toml)
- **uv** package manager (not pip) — install via `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node.js** (for frontend) — React 18 + Vite 6 + Playwright 1.58
- **`.env` file** in project root with:
  ```
  ANTHROPIC_API_KEY=sk-ant-api03-...
  TEST_MODEL=claude-haiku-4-5-20251001
  BEST_MODEL=claude-sonnet-4-20250514
  ```

## Commands

```bash
# Setup
uv sync                     # Install Python dependencies
cd frontend && npm install   # Install frontend dependencies (first time)

# Full pipeline: document -> ontology graph -> save to runs/
uv run python -m src.main data/direct_travel_duty_of_care.md

# Individual pipeline stages
uv run python -m src.first_pass <input.md> -o <first_pass.json>                    # Stage 0
uv run python -m src.segmenter <input.md> --first-pass <first_pass.json> -o <out>  # Stage 1
uv run python -m src.extraction <chunks.json> --first-pass <fp.json> -o <out>      # Stage 2
uv run python -m src.extraction <chunks.json> --debug                              # Stage 2 with prompt tracing
uv run python -m src.merge <extractions.json> <chunks.json> <source.md> -o <out>   # Stage 3

# Agent & evaluation (consume saved graphs)
uv run python -m src.agent_repl --graph <path/to/ontology.json>                     # Interactive agent REPL
uv run python -m src.agent_repl --latest                                            # Agent REPL with latest run
uv run python -m src.eval --graph <path/to/ontology.json> --qa data/*.qa.small.json # Eval against Q&A set
uv run python -m src.eval --latest --qa data/*.qa.small.json                       # Eval latest run
uv run python -m src.generate_qa data/direct_travel_duty_of_care.md                 # Generate Q&A test set
uv run python -m src.validate data/direct_travel_duty_of_care.md                    # Graph validation

# Frontend
cd frontend && npm run build                                        # Build React SPA
uv run python -m src.frontend --graph <path/to/ontology.json>      # Launch with specific graph
uv run python -m src.frontend --latest                              # Launch with latest pipeline run

# Frontend tests (Playwright — server must be running on :8789)
cd frontend && npx playwright test                         # Run all tests
cd frontend && npx playwright test zoom-controls           # Run specific test file
cd frontend && npx playwright test --grep "zoom in"        # Run specific test by name
cd frontend && npx playwright test --headed                # Run with visible browser
cd frontend && npx playwright test --reporter=list         # Verbose output
```

## Architecture

### Pipeline Overview (5 stages, orchestrated by `src/pipeline.py`)

```
Document (PDF/markdown) → pdf_parser.py (if PDF) → markdown
    ↓
[Stage 0] first_pass.py      1 LLM call (streaming + thinking)  → FirstPassResult
    ↓
[Stage 1] segmenter.py       0 LLM calls (deterministic)        → DocumentSection[]
    ↓
[Stage 2] extraction.py      2N LLM calls (async, 2 concurrent) → SectionExtraction[]
    ↓
[Stage 3] merge.py            1 LLM call (semantic dedup)         → OntologyGraph
    ↓
[Stage 4] relationships.py   1 LLM call (full-doc relationships) → Relationship[]
    ↓
results.py → saves to results/runs/{timestamp}_{policy}/
```

### Stage Details

**Stage 0 — First Pass** (`src/first_pass.py`): Single streaming LLM call with extended thinking (budget: 32768 tokens, max output: 49152). Produces three outputs that guide all downstream stages:
- **document_map**: Section inventory with `beginning_text` (first 40-60 words) used by Stage 1 for deterministic boundary detection
- **global_entity_pre_registration**: Canonical entity names for cross-section consistency
- **cross_section_dependencies**: Section pairs with typed dependency relationships (MODIFIES, REFERENCES, OVERRIDES, etc.)

**Stage 1 — Segmenter** (`src/segmenter.py`): **No LLM call** — purely deterministic. Matches `beginning_text` from Stage 0 against the source document using a multi-tier cascade: exact match → normalized match → token-prefix regex → heading fallback. Walks backward from body start to find heading boundaries. Emits a preamble section (SEC-00) if >50 chars exist before the first detected section. Warns if coverage <85%.

**Stage 2 — Extraction** (`src/extraction.py`): Two-pass per section, run async with `asyncio.Semaphore(2)`:
- **Pass 1 (Entities)**: Extracts typed entities using schemas from `src/schemas.py`. Uses thinking (budget: 10000). Zero-entity results trigger auto-retry with aggressive fallback prompt.
- **Pass 2 (Relationships)**: Extracts relationships constrained by entity type pairs from schemas. Validates source/target IDs exist (dangling edges rejected).

**Stage 3 — Merge** (`src/merge.py`): Two-pass deduplication:
- Pass 1 (deterministic): Groups by `(id, type)` tuple after stripping section prefixes (e.g., `SEC-01:client` → `client`). Merges attributes, source anchors.
- Pass 2 (LLM): Semantic dedup with thinking budget scaled to entity count. Anti-merge rules: numbered/leveled entities and channel-specific entities never merge.
- Post-merge: Remaps all relationship IDs, removes orphaned edges, deduplicates by `(source_id, target_id, type)`.

**Stage 4 — Relationships** (`src/relationships.py`): Full-document relationship extraction using all deduplicated entities. No cross-section restriction (intra-section allowed). Deduplicates against existing Stage 2-3 relationships.

### Key Modules

| Module | Role |
|--------|------|
| `src/models.py` | Core Pydantic models: `OntologyGraph`, `Entity`, `Relationship`, `DocumentSection`, `SectionExtraction`, `FirstPassResult`, `ExtractionMetadata` |
| `src/base_models.py` | Shared base models (`SourceAnchor`) to avoid circular imports between models.py and schemas.py |
| `src/schemas.py` | **Single source of truth** for all entity type definitions (typed attributes, field descriptions) and relationship type constraints (source/target type pairs). Generates prompt sections for LLM calls. |
| `src/graph.py` | Builds NetworkX `DiGraph` from `OntologyGraph` |
| `src/api_models.py` | Presentation-layer Pydantic models for REST API responses (`GraphNode`, `GraphEdge`, `EntityDetail`, `PathResponse`, etc.) |
| `src/results.py` | Save/load pipeline runs. Key functions: `save_run()`, `load_run()`, `load_latest_ontology()`, `list_runs()` |
| `src/__init__.py` | Windows UTF-8 console encoding fix for LLM unicode output |

### Reasoning Agent (`src/agent.py`)

Tool-use loop with **no access to raw document** — only graph traversal tools:

| Tool | Purpose |
|------|---------|
| `list_entity_types` | Count of each entity type |
| `find_entities` | All entities of a specific type |
| `search_entities` | Keyword search across all entity fields |
| `get_entity` | Full entity detail with attributes and relationships |
| `get_neighbors` | BFS expansion within N hops (default 1) |
| `find_paths` | Up to 5 undirected paths between two entities (cutoff 5 hops) |
| `get_graph_summary` | High-level node/edge/type counts |
| `traverse_workflow` | Follow FOLLOWED_BY chains for ordered procedures |
| `find_by_attribute` | Find entities by attribute value (substring match) |

Hard limit: 15 turns per question. `run_walkthrough()` is an enhanced version that traces every tool call for frontend scenario visualization.

### Frontend (`src/frontend.py` + `frontend/`)

FastAPI serves a React SPA. Three-panel layout: left (PathFinder / Agent Chat / Cascade / Scenarios), center (vis-network force-directed graph), right (entity detail).

**Key API endpoints:** `/api/graphs` (list), `/api/graphs/load` (switch), `/api/graph` (full data + centrality metrics), `/api/entity/{id}`, `/api/search`, `/api/paths`, `/api/cascade`, `/api/scenarios`, `/api/agent/ask`, `/api/agent/walkthrough`.

**Centrality metrics** computed at graph load: `importance = 0.40 * betweenness + 0.35 * pagerank + 0.25 * degree` (all normalized 0-1). Used for node sizing.

**Graph files** served from `data/final_graphs/`. Scenario sidecars: `{graph_name}.scenarios.json` in same directory.

### Evaluation (`src/eval.py`)

LLM judge scores agent answers on 3 dimensions: accuracy (0-3), completeness (0-2), no-hallucination (0-1). **Pass threshold: 4/6.** Results saved to `output/eval_results.json`.

## LLM Configuration

**When Claude Code runs any pipeline stage, service, or LLM call, always use `TEST_MODEL`.** Only switch to `BEST_MODEL` when the user explicitly requests it. This applies to all modules.

API key loaded from `.env` via `python-dotenv`. Model env vars: `TEST_MODEL`, `BEST_MODEL`, `LLM_CLI_MODEL`.

## Cleanup Rules

1. **Always delete screenshots after use.** When taking Playwright screenshots for debugging or verification, delete them (and the `screenshots/` directory) before finishing the task. Never commit screenshots to the repo.

## Critical Gotchas

1. **Stage 1 is deterministic, not LLM-based.** If Stage 0's `beginning_text` is inaccurate, segmentation silently fails with wrong boundaries. No LLM fallback.
2. **Async concurrency hardcoded to 2.** `asyncio.Semaphore(2)` in extraction.py — bottleneck for documents with many small sections.
3. **Entity ID prefix stripping in merge.** `SEC-01:client` → `client` for dedup matching. New code consuming merge output must handle both forms.
4. **Synthetic canonical IDs.** LLM semantic dedup sometimes invents new IDs not in the entity list. `merge.py` handles this by picking the best existing ID as canonical.
5. **No API retry/backoff.** If an LLM call fails (rate limit, token overflow), the pipeline fails hard.
6. **Source anchoring is optional.** Entities may have empty `source_anchor.source_text`. Merge uses SequenceMatcher fuzzy matching as fallback for offset computation.
7. **Orphaned relationships silently removed.** After merge remapping, edges referencing deleted entity IDs are dropped with a warning log, not an error.
8. **Anti-merge rules are strict.** Numbered/leveled entities (severity_level_1 through severity_level_4) and channel-specific entities never merge, even if names are similar.
9. **JSON parsing has progressive fallback.** First pass and extraction both handle: raw parse → strip markdown fences → fix escape sequences → strip control characters.

## PDF Parser

`src/pdf_parser.py` — custom heuristic parser using raw PyMuPDF font metrics. Four-phase: extraction (font size, bold, position per span) → noise removal (headers/footers/page numbers/TOC dots) → font analysis (body size detection, heading level mapping) → markdown rendering (heading hierarchy, lists, definitions, paragraph joining). Parsed markdown goes to `data/parser_1/`.

## Result Storage

Every pipeline run auto-saves to `results/runs/{YYYY-MM-DDTHH-MM-SS}_{policy_name}/`. Run IDs are immutable. `ontology.json` is the source of truth (reloadable via `OntologyGraph(**data)`). Latest run ID stored in `results/latest.txt`.

**Files per run:** `run_meta.json`, `first_pass.json`, `sections.json`, `extractions.json`, `ontology.json`, `entities.json`, `relationships.json`, plus optional `semantic_dedup.json`, `relationships_log.json`.

**Rules:**
1. Never lose API results — every LLM output gets a file.
2. When adding a pipeline stage, add a JSON file to the run directory and update `save_run()` / `load_run()` in `src/results.py`.
3. Reload previous runs without API calls via `load_latest_ontology()` or `load_run(run_id)`.

**Data locations:** Source PDFs in `data/`, Q&A test sets as `data/*.qa.json`, pipeline runs in `results/runs/`, eval results in `output/eval_results.json`, legacy graphs in `output/graphs/`, planning docs in `docs/`.

## Core Principles

- **Accuracy over cost.** Never accept a worse outcome to save tokens. If the agent needs more iterations, let it iterate.
- **Enterprise-grade quality.** Every decision evaluated as: "Would this hold up at scale with high-stakes compliance documents?"
- **Correctness first, then performance.** A fast wrong answer is worthless.

## Frontend Testing Standard (Mandatory)

**Every frontend change MUST follow test-driven development with Playwright.**

### Workflow (Red → Green)

1. **Write the Playwright test first** — assert element visibility, interactions, state transitions.
2. **Run the test — it MUST FAIL** before any code changes.
3. **Implement the frontend change.**
4. **Run the test — it MUST PASS.** Fix the implementation, not the test.
5. **Run the full suite** to confirm no regressions.

### Test Infrastructure

- Tests: `frontend/tests/*.spec.ts` (one file per feature area)
- Config: `frontend/playwright.config.ts` (chromium only, 30s timeout, 0 retries)
- Base URL: `http://localhost:8789` (server must be running)
- Tests must be deterministic — use `waitFor` for async, never rely on timing alone.
