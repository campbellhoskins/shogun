# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Why This Project Exists

Shogun is a demonstration project being built to prove technical capability to Arjun Chopra, a Silicon Valley VC (Floodgate partner) who is assembling a team to build an AI-powered travel industry roll-up. The venture has three interlocking entities:

- **O1** — A hybrid PE/VC investment firm (similar to General Catalyst's model) that acquires travel management companies already entrenched in the industry.
- **Spotnana** — A modern cloud-native travel infrastructure platform ($100M+ raised) that replaces legacy GDS systems with APIs. Acquired companies get migrated onto Spotnana.
- **Shogun (the AI task force)** — A "Palantir for Travel" that deploys Forward Deployed Engineers into acquired companies to automate their workflows using AI. This is the entity I'm building toward joining.

The business thesis: Travel management companies run on **30% manual workflows**. A $600M revenue TMC at 10% margin earns $60M profit — but if you automate even half the manual work, margin jumps to 15%+ ($90M). The play is to acquire these companies (which have regulatory moats like IATA/ARC accreditation), migrate them onto Spotnana, and deploy AI agents to automate operations.

## What I'm Demonstrating

An engineer they hired from Amazon impressed Arjun by spending a weekend building an agent that ingests travel compliance data and constructs an ontology graph from it. I need to demonstrate the same kind of initiative — but go further. Instead of just parsing a document into a graph, this project shows the full pipeline:

1. **Ingest** a real corporate travel duty of care policy document (PDF)
2. **Extract** a complete ontology graph — entities, relationships, attributes — that captures every rule, threshold, role, definition, and procedure
3. **Reason** over the graph using an AI agent with tool-use that traverses the graph programmatically (not just dumping text into a prompt)
4. **Evaluate** the quality of both the graph and the agent's answers against a ground-truth test set

The sophistication matters because this mirrors what Shogun would actually deploy: take messy, unstructured policy documents from acquired TMCs and turn them into structured knowledge that agents can act on. If I can demonstrate this on duty of care policies, the same pattern extends to booking rules, fare rules, expense policies, and the PNR disruption workflows that are the core business opportunity.

## Document Scope

This project is exclusively focused on **travel duty of care** policies — documents from organizations (NGOs, international development orgs, corporations) that govern the safety, security, and wellbeing of personnel traveling or working in field locations, high-risk zones, and foreign countries. These documents contain travel-specific concepts like destination risk classifications, travel approval workflows, pre-travel security briefings, personnel tracking/check-in requirements, emergency evacuation procedures, and SEA (Sexual Exploitation and Abuse) compliance.

**Not in scope:** Education/school duty of care policies (yard supervision, child safe standards, campus premises). These are a different document class with different entity types and have been removed from the data directory.

## The Bar

Arjun specifically praised the Amazon engineer's initiative. The bar is not "interesting prototype" — it's "this person clearly understands the domain, the technical challenges, and can build production-quality tooling." Every piece of this project should reflect that standard.

## Commands

```bash
# Setup
uv sync                     # Install dependencies (uses uv, not pip)

# Full pipeline: PDF -> ontology graph -> interactive Q&A
uv run python -m src.main data/231123_Duty_of_Care_Policy.pdf

# Individual pipeline stages (standalone CLIs)
uv run python -m src.segmenter <input.md> -o <chunks.json>         # Stage 1: Semantic chunking
uv run python -m src.extraction <chunks.json> -o <extractions.json> # Stage 2: Entity extraction
uv run python -m src.extraction <chunks.json> --debug               # Stage 2 with full prompt/response tracing
uv run python -m src.merge <extractions.json> <chunks.json> <source.md> -o <ontology.json>  # Stage 3: Merge

# Legacy single-pass extraction (for A/B comparison)
uv run python -m src.build_graph data/231123_Duty_of_Care_Policy.pdf --prompt 1
uv run python -m src.build_graph --list

# Graph validation (structural + coverage + source anchoring)
uv run python -m src.validate data/231123_Duty_of_Care_Policy.pdf

# Agent testing (verbose mode showing every tool call)
uv run python -m src.test_agent --graph <graph_id>

# Evaluation against Q&A test set
uv run python -m src.eval --graph <graph_id> --qa data/231123_Duty_of_Care_Policy.qa.small.json

# Generate Q&A test set from a policy document
uv run python -m src.generate_qa data/231123_Duty_of_Care_Policy.pdf

# Frontend: Interactive Ontology Explorer
cd frontend && npm install && npm run build  # First time setup
uv run python -m src.frontend --graph <path/to/ontology.json>  # Launch with specific graph
uv run python -m src.frontend --latest                          # Launch with latest pipeline run
uv run python -m src.frontend --graph data/extractions.json --port 8080  # Custom port

# Frontend tests (Playwright — must have server running on :8789 first)
cd frontend && npx playwright test                    # Run all tests
cd frontend && npx playwright test --headed           # Run with visible browser
cd frontend && npx playwright test zoom-controls      # Run specific test file
cd frontend && npx playwright test --reporter=list    # Verbose output
```

## Architecture

### Pipeline (Source-Anchored Extraction)

The core pipeline is a three-stage process orchestrated by `src/pipeline.py`:

```
PDF → pdf_parser.py → markdown
                         ↓
                   [Stage 1] segmenter.py    → LLM semantic chunking → DocumentSection[]
                         ↓
                   [Stage 2] extraction.py   → Per-section entity extraction (async parallel) → SectionExtraction[]
                         ↓
                   [Stage 3] merge.py        → Deterministic dedup (union-find) → OntologyGraph
                         ↓
                   results.py saves to results/runs/{timestamp}_{policy}/
```

**Stage 1 (Segmenter):** Single LLM call breaks the document into semantic chunks with hierarchical metadata (parent sections, enumerated list detection). Post-hoc offset computation locates each chunk in the source document.

**Stage 2 (Extraction):** Each chunk gets its own LLM call (async with semaphore-based concurrency control, default 2 concurrent). The extraction prompt enforces graph-first principles: entities are things, relationships are assertions, list members become individual nodes. Uses `<extraction_analysis>` chain-of-thought tags that get stripped before JSON parsing. Zero-entity results trigger an automatic retry with an aggressive prompt.

**Stage 3 (Merge):** Deterministic deduplication using union-find over two tiers: exact base-ID match (after stripping section prefixes) and exact Name+Type match. Source offsets are verified against the original document using exact, normalized, and fuzzy (SequenceMatcher) matching.

### Reasoning Agent

`src/agent.py` implements a tool-use agent loop. The agent has NO access to the raw policy document — it can only query the ontology graph through six tools (`list_entity_types`, `find_entities`, `search_entities`, `get_entity`, `get_neighbors`, `find_paths`, `get_graph_summary`). This forces graph traversal rather than text retrieval, proving the graph's completeness.

### Frontend (Ontology Explorer)

`src/frontend.py` serves a React SPA (`frontend/`) via FastAPI. Three-panel layout: left (Path Finder + Agent Chat), center (vis-network force-directed graph), right (entity detail panel). The frontend talks to the graph exclusively through REST API endpoints (`/api/graph`, `/api/entity/{id}`, `/api/search`, `/api/paths`, `/api/agent/ask`). The agent chat calls the existing `ask()` function from `src/agent.py` via `run_in_threadpool`. Neo4j-ready architecture: swapping NetworkX for Neo4j later only changes backend endpoint implementations. API models live in `src/api_models.py`.

### Evaluation

`src/eval.py` runs the agent against a Q&A test set and uses a separate LLM judge call to score each answer on accuracy (0-3), completeness (0-2), and hallucination (0-1). Pass threshold is 4/6.

### Data Models

All Pydantic models live in `src/models.py`: `Entity`, `Relationship`, `OntologyGraph`, `DocumentSection`, `SectionExtraction`, `SourceAnchor`, `ExtractionMetadata`, `AgentResponse`. The `OntologyGraph` is the central model — it serializes to/from JSON and can be reconstructed via `OntologyGraph(**data)`.

### Two Extraction Paths

- **Current (pipeline):** `src/main.py` → `src/pipeline.py` → segmenter → extraction → merge. Multi-stage with source anchoring.
- **Legacy (single-pass):** `src/build_graph.py` → `src/parser.py` (calls `parse_policy_legacy()`). Single LLM call, no source anchoring. Kept for A/B comparison. Saves to `output/graphs/`.

### LLM Configuration

All LLM calls use `claude-sonnet-4-20250514` via the Anthropic Python SDK except Q&A generation (`src/generate_qa.py`) which uses `claude-opus-4-20250514`. API key is loaded from `.env` via `python-dotenv`.

## Project Structure Conventions

### PDF Parsers

We maintain two PDF-to-markdown parsers. **Parser 1 is the active parser** used by the pipeline (`src/pdf_parser.py`).

- `src/pdf_parser.py` — Parser 1 (custom heuristic, font-metric analysis via raw PyMuPDF). Handles bold ALL-CAPS heading detection, page number stripping, repeated header/footer removal, TOC dot-filler removal, cover page logic, definition formatting, and paragraph joining. **This is imported by `src/main.py`.**
- `src/pdf_parser_1.py` — Named copy of Parser 1 for reference.
- `src/pdf_parser_2.py` — Parser 2 (pymupdf4llm wrapper). Better at tables, links, and italic preservation, but misses body-size bold headings and does not strip noise.

### Parsed Output Organization

Each parser writes its markdown output to its own subfolder under `data/`:

- `data/parser_1/` — Markdowns generated by Parser 1
- `data/parser_2/` — Markdowns generated by Parser 2

Source PDFs live in `data/` root. Do not mix parser outputs into the same folder.

### Result Storage Conventions

Every pipeline run that makes API calls **must** save its outputs to `results/`. No LLM-generated data should exist only in console output or in-memory. If an API was called and tokens were spent, the result has a file.

#### Directory Layout

```
results/
├── runs/                              # One subdirectory per pipeline run
│   ├── {timestamp}_{policy_name}/     # Run ID = UTC timestamp + sanitized policy name
│   │   ├── run_meta.json              # Run metadata, timings, counts, anchoring stats
│   │   ├── sections.json              # Stage 1: LLM segmentation output
│   │   ├── extractions.json           # Stage 2: per-section extraction (pre-merge)
│   │   ├── ontology.json              # Stage 3: final merged OntologyGraph (reloadable)
│   │   ├── entities.json              # Entities grouped by type (human-readable)
│   │   └── relationships.json         # Relationships grouped by type (human-readable)
│   └── ...
└── latest.txt                         # Contains the run_id of the most recent run
```

#### File Contracts

Each file in a run directory has a fixed schema. Do not add ad-hoc files or change these schemas without updating both `src/results.py` and this section.

| File | Purpose | Schema Owner |
|------|---------|--------------|
| `run_meta.json` | Pipeline config, timings, entity/relationship counts, source anchoring quality stats | `save_run()` in `src/results.py` |
| `sections.json` | Array of sections: header, section_number, level, char_count, enumerated_lists | `save_run()` — sourced from `DocumentSection` model |
| `extractions.json` | Array of per-section results: section info + raw entities/relationships before merge | `save_run()` — sourced from `SectionExtraction` model |
| `ontology.json` | Full `OntologyGraph.model_dump()` — reloadable via `OntologyGraph(**data)` | `save_run()` — sourced from `OntologyGraph` model |
| `entities.json` | Entities grouped by type with id, name, description, attributes, source_section, source_text | `save_run()` — derived view for human reading |
| `relationships.json` | Relationships grouped by type with resolved entity names | `save_run()` — derived view for human reading |

#### Rules

1. **Every pipeline run auto-saves.** The `extract_ontology()` function in `src/pipeline.py` calls `save_run()` at the end of every execution. No manual save step.
2. **Never lose API results.** If a new pipeline stage is added (e.g., cross-section inference, verification), its LLM output must be added as a new file in the run directory and registered in `save_run()`.
3. **Run IDs are immutable.** Format: `YYYY-MM-DDTHH-MM-SS_{policy_name}`. Once a run is saved, its directory is never overwritten — each run gets a unique timestamp.
4. **`ontology.json` is the source of truth.** It contains the complete serialized graph and can reconstruct the full `OntologyGraph` object. All other files are derived views for convenience.
5. **Reload without re-running.** Use `load_latest_ontology()` or `load_run(run_id)` from `src/results.py` to reload any previous run's graph without making API calls.
6. **When adding a new pipeline stage**, add a corresponding JSON file to the run directory (e.g., `cross_section.json`, `verification.json`), update `save_run()` to write it, and update `load_run()` to read it. Document the new file in this table.

#### What Goes Where

| Data Type | Where It Lives |
|-----------|---------------|
| Source policy PDFs | `data/` |
| PDF-to-markdown conversions | `data/parser_1/`, `data/parser_2/` |
| Q&A test sets | `data/*.qa.json` |
| Pipeline run outputs (entities, relationships, ontology) | `results/runs/{run_id}/` |
| Evaluation results (agent Q&A scoring) | `output/eval_results.json` |
| Graph visualizations (interactive HTML) | `output/graph.html` |
| Saved graphs (legacy format from `build_graph.py`) | `output/graphs/` |
| Planning/design docs | `docs/` |

## Core Principles

- **Accuracy over cost.** Never accept a worse outcome to save tokens or reduce API calls. If the agent needs more iterations, let it iterate.
- **Enterprise-grade quality.** Every decision should be evaluated as: "Would this hold up at scale with high-stakes compliance documents where errors have real consequences?"
- **No shortcuts.** If a more robust solution exists — even if harder to implement — that is the correct choice.
- **Correctness first, then performance.** A fast wrong answer is worthless. A slower correct answer is the standard.

## Frontend Testing Standard (Mandatory)

**Every frontend change MUST follow test-driven development with Playwright.**

### Workflow (Red → Green)

1. **Write the Playwright test first.** The test describes the desired behavior — what the UI should do after the change. Be specific: assert element visibility, click interactions, state transitions, visual regressions.
2. **Run the test — it MUST FAIL.** This confirms the test is actually testing the new behavior, not something that already works. If it passes before you've made any code changes, the test is wrong.
3. **Implement the frontend change.** Write the React/CSS code to make the feature work.
4. **Run the test again — it MUST PASS.** If it doesn't, fix the implementation (not the test) until it does.
5. **Run the full test suite** to confirm nothing else broke.

### Test Infrastructure

- Tests live in `frontend/tests/` as `*.spec.ts` files
- Config: `frontend/playwright.config.ts`
- Tests run against the frontend served at `http://localhost:8789` (start the server first)
- Use `npx playwright test` from the `frontend/` directory

### What to Test

| Change Type | What to Assert |
|-------------|---------------|
| New UI component | Element exists, correct content, proper styling classes |
| Interactive feature | Click/type triggers expected state change, correct elements appear/disappear |
| Zoom/navigation | Scale changes, viewport shows expected nodes after action |
| Panel open/close | Panel visibility, animation completion, content population |
| API integration | Loading states, data rendering, error handling |

### Rules

1. **No frontend PR without tests.** Every frontend change must have a corresponding Playwright test.
2. **Tests describe behavior, not implementation.** Test what the user sees and does, not internal React state.
3. **Tests must be deterministic.** Use `waitFor` for async operations. Never rely on timing alone.
4. **Test file naming:** `frontend/tests/{feature}.spec.ts` — one file per feature area.
