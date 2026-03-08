# Neo4j Migration Plan for Shogun

## Context

Shogun currently uses an in-memory NetworkX graph serialized to JSON. Migrating to Neo4j adds production credibility for the Arjun demo ("Neo4j-backed knowledge graph with Cypher traversal"), native graph query capabilities, full-text search indexing, and persistent storage. The migration is surgical — ~60% of the codebase is untouched because the extraction pipeline, schemas, models, and merge logic are storage-independent.

---

## What Stays the Same (No Changes)

| Component | Why |
|-----------|-----|
| `src/models.py` — Pydantic models | Data contracts, not storage logic |
| `src/schemas.py` — Entity/relationship type registries | Schema validation and prompt generation are storage-independent |
| `src/merge.py` — LLM deduplication | Operates on Pydantic models in-memory |
| `src/extraction.py` — Per-section extraction | Produces SectionExtraction objects, no graph dependency |
| `src/segmenter.py`, `src/first_pass.py` — Stages 0-1 | No graph involvement |
| `src/api_models.py` — API response models | Frontend contract unchanged |
| `src/results.py` — JSON persistence | Keep as audit/export alongside Neo4j |

---

## Implementation Steps

### Step 1: Add Neo4j dependency and configuration

**Files:** `pyproject.toml`, `.env`

- Add `neo4j = "^5.0"` to dependencies
- Add env vars: `GRAPH_BACKEND`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- Add `docker-compose.yml` with Neo4j container for local dev

### Step 2: Create `src/database.py` — Connection & Schema Management (~200 lines)

**New file.** Responsibilities:
- Neo4j driver initialization and connection pooling
- Schema setup: constraints (`UNIQUE` on entity ID), full-text index on `name`+`description`
- `load_ontology_to_neo4j(ontology: OntologyGraph)` — batch-writes entities and relationships using `UNWIND`
- `clear_graph()` — wipe database for fresh loads
- Session/transaction context managers

Key design decisions:
- Each entity type becomes a Neo4j label (`:Policy`, `:PolicyRule`, etc.) plus shared `:Entity` label
- Each relationship type becomes a Neo4j relationship type (`:CONTAINS`, `:APPLIES_TO`, etc.)
- Batch writes via `UNWIND` for performance

### Step 3: Create `GraphBackend` protocol in `src/graph.py` (~300 lines)

**Rewrite existing file.** Define abstract interface:

```python
class GraphBackend(Protocol):
    def list_entity_types(self) -> dict[str, int]: ...
    def find_entities(self, entity_type: str) -> list[dict]: ...
    def search_entities(self, keyword: str) -> list[dict]: ...
    def get_entity(self, entity_id: str) -> dict | None: ...
    def get_neighbors(self, entity_id: str, depth: int, direction: str) -> dict: ...
    def find_paths(self, source_id: str, target_id: str, max_hops: int) -> list[list[dict]]: ...
    def get_graph_summary(self) -> dict: ...
    def get_all_nodes_and_edges(self) -> tuple[list[dict], list[dict]]: ...
    def cascade(self, start_id: str, rel_types: list[str], depth: int) -> dict: ...
```

Implement two backends:
- `NetworkXBackend` — wraps current `build_graph()` logic (keep for local/testing)
- `Neo4jBackend` — Cypher queries against database

Backend selection via `GRAPH_BACKEND` env var (default: `networkx`).

### Step 4: Update `src/agent.py` — Swap NetworkX for GraphBackend (~100 lines changed)

Replace `_execute_tool(tool_name, tool_input, g: nx.DiGraph)` with `_execute_tool(tool_name, tool_input, backend: GraphBackend)`.

Cypher equivalents for each tool:

| Tool | Cypher |
|------|--------|
| `list_entity_types` | `MATCH (n:Entity) RETURN n.type, count(*) ORDER BY count(*) DESC` |
| `find_entities` | `MATCH (n:Entity {type: $type}) RETURN n.id, n.name, n.description` |
| `search_entities` | `CALL db.index.fulltext.queryNodes('entity_search', $q) YIELD node RETURN node` |
| `get_entity` | `MATCH (n:Entity {id: $id}) OPTIONAL MATCH (n)-[r]-(m) RETURN n, type(r), r, m` |
| `get_neighbors` | `MATCH (n:Entity {id: $id})-[*1..$depth]-(m) RETURN DISTINCT m` |
| `find_paths` | `MATCH path = allShortestPaths((a {id: $src})-[*..5]-(b {id: $tgt})) RETURN path` |
| `get_graph_summary` | `MATCH (n) RETURN count(n); MATCH ()-[r]->() RETURN count(r)` |

### Step 5: Update `src/frontend.py` — Swap NetworkX for GraphBackend (~150 lines changed)

Replace module-level `_graph: nx.DiGraph` with `_backend: GraphBackend`. Update all 7 endpoints:

| Endpoint | Change |
|----------|--------|
| `GET /api/graph` | `backend.get_all_nodes_and_edges()` |
| `GET /api/graph/stats` | `backend.list_entity_types()` |
| `GET /api/entity/{id}` | `backend.get_entity(id)` |
| `GET /api/search` | `backend.search_entities(q)` |
| `POST /api/paths` | `backend.find_paths(...)` |
| `POST /api/cascade` | `backend.cascade(...)` |
| `POST /api/agent/ask` | Pass `backend` to `ask()` instead of `g` |

### Step 6: Update `src/pipeline.py` — Add Neo4j write after merge (~10 lines)

After `save_run()`, add conditional Neo4j write:

```python
ontology = merge(...)
save_run(ontology, ...)              # Keep JSON export
if settings.graph_backend == "neo4j":
    load_ontology_to_neo4j(ontology) # Write to Neo4j
```

### Step 7: Update `src/eval.py` — Pass backend instead of graph (~10 lines)

Pass `GraphBackend` to `ask()` instead of `nx.DiGraph`.

---

## File Change Summary

| File | Change Type | Lines |
|------|-------------|-------|
| `src/database.py` | **New** | ~200 |
| `src/graph.py` | **Rewrite** | ~300 |
| `src/agent.py` | **Moderate** | ~100 changed |
| `src/frontend.py` | **Moderate** | ~150 changed |
| `src/pipeline.py` | **Minor** | ~10 added |
| `src/eval.py` | **Minor** | ~10 changed |
| `pyproject.toml` | **Minor** | 1 dep added |
| `.env` | **Minor** | 4 vars added |
| `docker-compose.yml` | **New** | ~20 |

**Total**: ~800 lines new/changed code.

---

## Verification

1. **NetworkX backend still works**: Run full pipeline with `GRAPH_BACKEND=networkx` (default) — zero behavior change
2. **Neo4j backend**: Start Neo4j via `docker compose up -d`, set `GRAPH_BACKEND=neo4j`, run pipeline against a policy doc
3. **Agent tools**: Run `uv run python -m src.test_agent` with both backends, compare outputs
4. **Frontend**: Launch `uv run python -m src.frontend --latest` with Neo4j backend, verify all panels work
5. **Eval**: Run `uv run python -m src.eval` with both backends, confirm identical scores
6. **Search**: Verify full-text search returns results for partial name matches (Neo4j indexed vs NetworkX linear scan)

---

## Benefits vs Cost

**Benefits:**
- Demo credibility — "Neo4j-backed knowledge graph" signals production-grade, not prototype
- Native Cypher queries — path traversal and pattern matching become first-class
- Full-text search — indexed search replaces linear scan
- Persistence — graph survives restarts; multiple clients query simultaneously
- Neo4j Browser — free interactive exploration for debugging/demos

**Costs:**
- ~800 lines of new/changed code
- Docker dependency for local dev
- Marginal performance gain at current scale (~100-500 nodes)

**Honest assessment:** The technical benefits are real but modest at current graph sizes. The main win is optics for the Arjun demo and positioning for production scale.
