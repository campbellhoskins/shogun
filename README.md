# Shogun

Shogun is an AI pipeline that turns unstructured travel duty-of-care policy PDFs into structured ontology graphs, then lets you explore and query those graphs through an interactive web UI and a reasoning agent that traverses the graph with tool-use.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js (for the frontend)
- An [Anthropic API key](https://console.anthropic.com/)

### Setup

```bash
# Install Python dependencies
uv sync

# Create .env file with your API key
cat > .env << 'EOF'
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
TEST_MODEL=claude-haiku-4-5-20251001
BEST_MODEL=claude-sonnet-4-20250514
EOF

# Build the frontend (one time)
cd frontend && npm install && npm run build && cd ..
```

## Usage

### 1. Run the Pipeline on a Policy Document

The included source document is `data/Duty-of-Care-Policy.pdf` — an international development organization's duty of care policy covering destination risk classification, travel approval workflows, personnel tracking, emergency evacuation, and incident severity levels.

To extract an ontology graph from it:

```bash
uv run python -m src.main data/Duty-of-Care-Policy.pdf
```

This runs a six-stage pipeline:

| Stage | What happens | Output |
|-------|-------------|--------|
| **0 — First Pass** | Analyzes full document structure, pre-registers cross-section entities | Document map + entity registry |
| **1 — Segmentation** | Splits document into semantic sections using Stage 0 boundaries | Sections with source offsets |
| **2 — Extraction** | Extracts typed entities and relationships from each section (parallel) | Entities + relationships per section |
| **3a — Cross-Section** | Finds relationships that span multiple sections | Cross-section edges |
| **3b — Merge** | Deduplicates entities (deterministic + LLM semantic) and remaps edges | Unified ontology graph |
| **4 — Relationships** | Full-document relationship extraction over all deduplicated entities | Additional edges |

When it finishes, the pipeline saves all outputs to `results/runs/{timestamp}_Duty-of-Care-Policy/` and drops into an interactive Q&A session where you can ask the reasoning agent questions about the policy.

### 2. Visualize a Graph

#### Option A: Visualize the graph you just created

```bash
uv run python -m src.frontend --latest
```

This loads the most recent pipeline run and opens a browser automatically at `http://localhost:8000`.

#### Option B: Visualize a pre-built graph

The project includes pre-built graphs in `data/final_graphs/`:

```bash
# Load a specific graph file
uv run python -m src.frontend --graph data/final_graphs/shogun_pipeline_v1.json

# Or just launch — it auto-loads the first graph in data/final_graphs/
uv run python -m src.frontend
```

#### Option C: Visualize a specific pipeline run

```bash
uv run python -m src.frontend --graph results/runs/{run_id}/ontology.json
```

### The Explorer UI

The Ontology Explorer is a three-panel interface:

- **Center** — Force-directed graph visualization (vis-network). Click nodes to inspect, double-click to expand/collapse subtrees. Entity types are color-coded.
- **Right Panel** — Entity detail view showing type, description, attributes, source text from the original document, and all connected relationships.
- **Left Panel** — Four tabs:
  - **Path Finder** — Find paths between any two entities in the graph.
  - **Agent Chat** — Ask natural language questions. The agent answers by traversing the graph (it has no access to the raw document), and referenced entities appear as clickable chips.
  - **Cascade** — Select a travel event node to see a BFS cascade of all downstream effects.
  - **Scenarios** — Step through scripted or live agent walkthroughs with highlighted graph traversal and color-coded logs.

You can switch between graphs at runtime using the graph selector dropdown in the top bar.

## Running Individual Stages

Each pipeline stage is a standalone CLI if you want to run them separately:

```bash
# Stage 0: First pass analysis
uv run python -m src.first_pass data/parser_1/Duty-of-Care-Policy.md -o first_pass.json

# Stage 1: Segmentation (requires Stage 0 output)
uv run python -m src.segmenter data/parser_1/Duty-of-Care-Policy.md --first-pass first_pass.json -o sections.json

# Stage 2: Extraction (requires Stages 0-1 output)
uv run python -m src.extraction sections.json --first-pass first_pass.json -o extractions.json

# Stage 3: Merge
uv run python -m src.merge extractions.json sections.json data/parser_1/Duty-of-Care-Policy.md -o ontology.json
```

## Evaluation

Test the agent's ability to answer questions about the extracted graph:

```bash
# Generate a Q&A test set from the source document
uv run python -m src.generate_qa data/Duty-of-Care-Policy.pdf

# Run evaluation (scores: accuracy 0-3, completeness 0-2, no-hallucination 0-1, pass ≥ 4/6)
uv run python -m src.eval --graph <graph_id> --qa data/Duty-of-Care-Policy.qa.small.json
```

## Project Structure

```
src/
├── main.py            # Entry point: PDF → pipeline → interactive Q&A
├── pipeline.py        # Orchestrates all 6 stages, calls save_run()
├── first_pass.py      # Stage 0: document structure analysis
├── segmenter.py       # Stage 1: deterministic section boundary detection
├── extraction.py      # Stage 2: per-section entity + relationship extraction
├── cross_section.py   # Stage 3a: cross-section relationship extraction
├── merge.py           # Stage 3b: entity deduplication + relationship remapping
├── relationships.py   # Stage 4: full-document relationship extraction
├── agent.py           # Tool-use reasoning agent (9 graph traversal tools)
├── models.py          # Pydantic data models (OntologyGraph, Entity, Relationship, etc.)
├── schemas.py         # Entity type definitions + relationship type constraints
├── frontend.py        # FastAPI backend serving React SPA + REST API
├── pdf_parser.py      # PDF-to-markdown (font-metric heuristic parser)
├── eval.py            # LLM judge evaluation framework
├── results.py         # Pipeline run save/load/list
└── validate.py        # Graph structural + coverage validation

frontend/
├── src/
│   ├── App.tsx        # Three-panel layout root component
│   ├── api.ts         # REST client for backend
│   └── components/    # GraphCanvas, AgentChat, PathFinder, ScenarioPanel, etc.
└── tests/             # Playwright E2E tests

data/
├── Duty-of-Care-Policy.pdf          # Source policy document
├── final_graphs/                     # Pre-built ontology graphs for visualization
└── parser_1/                         # PDF-to-markdown conversions

results/runs/                         # Pipeline run outputs (auto-saved)
```
