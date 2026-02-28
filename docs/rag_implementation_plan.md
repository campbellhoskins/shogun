# RAG Confidence-Gated Fallback — Implementation Plan

## Overview

Add RAG as a confidence-gated fallback to the existing ontology graph agent. The agent first reasons over the graph, then emits a **confidence score from 0.0 to 1.0** (where 1.0 = absolute certainty, 0.0 = no relevant information found). If confidence is **below 0.85**, RAG retrieves the top 5 most semantically similar document chunks. Critically, the agent then synthesizes **both** the complex relationship paths it discovered during graph traversal **and** the raw document chunks from RAG — it does not discard the graph findings. This is toggleable via CLI flags — every entry point supports `--rag` / `--no-rag` (defaulting to RAG enabled).

## Architecture

```
Ingestion:
  PDF → load_document() → raw text
                            ├──→ parse_policy() → OntologyGraph → build_graph() → nx.DiGraph
                            └──→ chunk_document() → embed → FAISS index (saved alongside graph)

Query (--rag enabled):
  question + graph + rag_index
       │
       ▼
  [Phase 1: Graph Traversal]  ← existing tool-use loop, unchanged
       │
       ▼
  agent calls emit_confidence(score, reasoning)    score ∈ [0.0, 1.0]
       │
       ├── score >= 0.85 → agent produces final answer (graph-only, sufficiently confident)
       │
       └── score < 0.85 AND rag_index exists
              │
              ▼
           retrieve(question, rag_index, top_k=5) → 5 most relevant chunks
              │
              ▼
           Build combined context:
             1. Graph findings summary (all relationships/paths discovered so far)
             2. RAG chunks (raw document excerpts)
              │
              ▼
           Combined context injected as tool result
              │
              ▼
           Agent synthesizes BOTH graph relationships AND document chunks → final answer

Query (--no-rag):
  question + graph (no rag_index)
       │
       ▼
  [Existing behavior unchanged — no emit_confidence tool offered]
```

## CLI Toggle Design

Every entry point gets explicit RAG control:

| Command | RAG flag | Default | Behavior |
|---------|----------|---------|----------|
| `src.test_agent --graph 1-1` | `--rag` / `--no-rag` | `--rag` | Loads RAG index if available, warns if not |
| `src.eval --graph 1-1 --qa ...` | `--rag` / `--no-rag` | `--rag` | Tracks RAG usage per question in results |
| `src.main <policy>` | `--rag` / `--no-rag` | `--rag` | Builds RAG index at ingestion, uses in Q&A loop |
| `src.build_graph <policy> --prompt N` | `--rag` / `--no-rag` | `--rag` | Controls whether RAG index is built alongside graph |
| `src.build_rag --graph 1-1` | (always builds) | N/A | Standalone: build RAG index for an existing graph |

When `--no-rag` is passed:
- `ask()` receives `rag_index=None`
- The `emit_confidence` tool is NOT included in the tools list
- The SYSTEM_PROMPT reverts to the graph-only version
- Behavior is identical to current codebase — zero regression risk

---

## Phase 1: Models & RAG Module (no agent changes)

### 1.1 — Add dependencies to `pyproject.toml`

Add to the `dependencies` list:
```
"faiss-cpu>=1.7.4",
"voyageai>=0.3.0",
```

**Why these choices:**
- **`faiss-cpu`** — In-process vector store. No server, no network calls, no SQLite. For a corpus of 50-200 chunks, exact search (`IndexFlatIP`) is sub-millisecond. Production-quality (Meta scale). ChromaDB/Pinecone add unnecessary infrastructure.
- **`voyageai`** with `voyage-3-large` (1024-dim) — Anthropic's own embedding product (acquired Voyage AI). State-of-the-art retrieval accuracy. Keeps vendor surface to Anthropic ecosystem. Accuracy over cost per CLAUDE.md.

### 1.2 — Add `VOYAGE_API_KEY` to `.env.example`

```
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=vo-...
```

### 1.3 — Extend `src/models.py`

Add after `AgentResponse` (line 32):

```python
# Confidence threshold — RAG triggers when score falls below this
RAG_CONFIDENCE_THRESHOLD = 0.85

class DocumentChunk(BaseModel):
    chunk_id: str              # "{source_stem}_chunk_{index:04d}"
    text: str                  # The chunk content
    section_title: str = ""    # Detected section heading
    page_number: int = 0       # 1-indexed page (estimated from pypdf page breaks)
    chunk_index: int = 0       # Sequential index within document
    char_start: int = 0        # Character offset in full text
    char_end: int = 0          # Character offset end

class RetrievalResult(BaseModel):
    chunk: DocumentChunk
    score: float               # Cosine similarity (0-1)
    rank: int                  # 1-indexed rank
```

Extend `AgentResponse` with three new fields (all with defaults so existing code doesn't break):

```python
class AgentResponse(BaseModel):
    answer: str
    referenced_entities: list[str] = []
    reasoning_path: str = ""
    confidence: float = -1.0       # NEW: 0.0-1.0 score, -1.0 if not emitted
    used_rag: bool = False         # NEW: whether RAG retrieval was triggered
    rag_chunks_used: list[str] = [] # NEW: chunk_ids that influenced the answer
```

### 1.4 — Create `src/rag.py`

New module, ~250 lines. Fully standalone — no imports from `agent.py` or `graph.py`.

**`RAGIndex` dataclass** (not Pydantic — holds live FAISS index):
```python
@dataclass
class RAGIndex:
    chunks: list[DocumentChunk]
    faiss_index: Any           # faiss.IndexFlatIP
    embedding_dim: int         # 1024 for voyage-3-large
    graph_id: str              # e.g., "graph-2-1"
```

**Functions:**

| Function | Purpose |
|----------|---------|
| `_detect_sections(text) -> list[tuple[int, str]]` | Regex scan for heading patterns (ALL CAPS, numbered `1.`, `2.1`, short bold lines). Returns `(char_offset, title)` pairs. |
| `chunk_document(text, source_path) -> list[DocumentChunk]` | Section-aware chunking. Splits at section boundaries, then applies sliding window (2400 chars / ~600 tokens, overlap 600 chars / ~150 tokens). Page numbers estimated by counting `\n\n` separators from pypdf output. |
| `_embed_texts(texts, vo_client) -> np.ndarray` | Calls `vo_client.embed(texts, model="voyage-3-large", input_type="document")` in batches of 128. Returns float32 numpy array. |
| `_embed_query(text, vo_client) -> np.ndarray` | Calls `vo_client.embed([text], model="voyage-3-large", input_type="query")`. Separate function because Voyage uses different input_type for queries vs documents. |
| `build_rag_index(chunks, vo_client, graph_id) -> RAGIndex` | Embeds all chunks, L2-normalizes, builds `faiss.IndexFlatIP`. |
| `save_rag_index(index) -> Path` | Saves to `output/rag_indexes/{graph_id}.faiss` + `{graph_id}.chunks.json` |
| `load_rag_index(graph_id) -> RAGIndex \| None` | Loads both files. Returns `None` if missing (graceful degradation). |
| `retrieve(query, index, vo_client, top_k=5) -> list[RetrievalResult]` | Embeds query, searches FAISS, maps indices back to chunks. |

**FAISS choice:** `IndexFlatIP` (exact inner product). Vectors are L2-normalized before indexing, so inner product = cosine similarity. No approximation — accuracy over speed. For 200 chunks this is sub-millisecond.

**Error handling:**
- If `voyageai` not installed → `import` wrapped in try/except, functions raise clear error
- If FAISS file corrupted → `load_rag_index()` catches exception, logs warning, returns `None`
- If Voyage API call fails → `retrieve()` catches, returns empty list with warning printed
- If `emit_confidence` called multiple times → only the first call with score < 0.85 triggers RAG; subsequent calls are no-ops

---

## Phase 2: Build RAG Indexes

### 2.1 — Create `src/build_rag.py`

Standalone CLI module (~80 lines):

```
Usage:
    uv run python -m src.build_rag --graph <graph_id>
    uv run python -m src.build_rag --graph 1-1

Loads the graph metadata to find the policy file path, loads the document,
chunks it, embeds it, saves the FAISS index.
```

Implementation:
1. Parse `--graph` from argv
2. `load_graph_file(graph_id)` → get `metadata["policy_file"]`
3. Resolve policy path against `data/` directory
4. `load_document(policy_path)` → raw text
5. `chunk_document(text, policy_path)` → chunks
6. `build_rag_index(chunks, vo_client, graph_id)` → index
7. `save_rag_index(index)` → saved files
8. Print: chunk count, embedding dimensions, index file size

### 2.2 — Create `output/rag_indexes/` directory

Created automatically by `save_rag_index()` via `mkdir(parents=True, exist_ok=True)`.

---

## Phase 3: Agent Modifications

This is the most critical phase. The key constraint: **when `rag_index=None`, behavior must be identical to the current codebase.**

### 3.1 — Modify `src/agent.py` imports

Add:
```python
from __future__ import annotations  # already present
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag import RAGIndex
```

Runtime import of `retrieve` happens inside `ask()` only when RAG is triggered, to avoid import errors if `voyageai`/`faiss` aren't installed.

### 3.2 — Add `SYSTEM_PROMPT_RAG` (new constant, keep `SYSTEM_PROMPT` unchanged)

Two system prompts coexist:

- `SYSTEM_PROMPT` — The existing graph-only prompt (lines 11-34). **Unchanged.**
- `SYSTEM_PROMPT_RAG` — New prompt that explains the two-phase workflow and `emit_confidence`.

```python
SYSTEM_PROMPT_RAG = """\
You are a Duty of Care Compliance Agent. You answer questions about a corporate \
policy by querying a structured ontology graph. When the graph does not fully answer \
the question, you will receive relevant excerpts from the original policy document \
to supplement your graph findings.

## Phase 1: Graph Traversal

Your primary source of information is the ontology graph, which you query using tools.

Typical workflow:
1. Use `get_graph_summary` or `list_entity_types` to understand what the graph contains.
2. Use `find_entities` or `search_entities` to find relevant entities.
3. Use `get_entity` to read full details of specific entities.
4. Use `get_neighbors` and `find_paths` to trace relationships and policy logic.
5. Exhaust all relevant graph traversal paths before concluding.

The graph contains complex entity relationships (requires, applies_to, triggers, \
escalates_to, etc.) that represent the policy's logical structure. These relationship \
chains are valuable even when the graph is incomplete — they capture the structural \
reasoning that flat text cannot.

## Phase 2: Confidence Assessment

After thorough graph traversal, you MUST call `emit_confidence` with:
- score: A decimal from 0.0 to 1.0 representing your confidence that the graph \
  contains sufficient information to fully and accurately answer the question.
  - 1.0 = absolute certainty — the graph contains every detail needed.
  - 0.85+ = high confidence — the graph answers the question with specific details.
  - 0.5-0.84 = partial confidence — found some information but missing key details, \
    thresholds, or specifics.
  - 0.0-0.49 = low confidence — the graph lacks sufficient information to answer \
    meaningfully.
- reasoning: Summarize what you found in the graph (entities, relationships, paths) \
  and what is missing or uncertain.

If your score is below 0.85, the system will automatically retrieve the most relevant \
excerpts from the original policy document. You will receive BOTH:
1. A summary of the graph relationships and entities you already discovered
2. The top 5 most semantically relevant document chunks

You MUST then synthesize BOTH sources — use the structural relationships from the graph \
AND the specific details from the document chunks to produce a comprehensive answer. \
Do not discard your graph findings; they provide relationship context that the raw \
document excerpts alone may not make explicit.

## Answer Guidelines

- Always incorporate graph-derived relationship chains when they add structural context.
- When citing retrieved document excerpts, quote the relevant passage.
- Be precise about thresholds, values, and requirements.
- If graph relationships reveal connections between entities that the document chunks \
  describe in detail, combine both for the most complete answer.
- If graph data and document excerpts conflict, trust the document excerpt and note \
  the discrepancy.
- Do not invent information not found in either the graph or retrieved excerpts.
"""
```

### 3.3 — Add `EMIT_CONFIDENCE_TOOL` definition

New constant (not added to `TOOLS` — appended dynamically):

```python
EMIT_CONFIDENCE_TOOL = {
    "name": "emit_confidence",
    "description": (
        "Call this AFTER you have finished exploring the graph and are ready to answer. "
        "Emit a confidence score from 0.0 to 1.0 indicating how completely the graph "
        "answers the question. "
        "1.0 = absolute certainty, graph has every detail needed. "
        "0.85+ = high confidence, graph fully answers with specifics. "
        "0.5-0.84 = partial, found some info but missing key details or values. "
        "Below 0.5 = low, graph lacks sufficient information. "
        "If your score is below 0.85, the system will retrieve relevant document "
        "excerpts and present them alongside your graph findings for you to synthesize."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence score from 0.0 (no information found) to 1.0 (complete certainty)",
            },
            "reasoning": {
                "type": "string",
                "description": "What was found in the graph and what is missing or uncertain",
            },
        },
        "required": ["score", "reasoning"],
    },
}
```

### 3.4 — Modify `ask()` function signature and logic

Current signature (line 303):
```python
def ask(question: str, g: nx.DiGraph, client: Anthropic | None = None, max_turns: int = 15) -> AgentResponse:
```

New signature:
```python
def ask(
    question: str,
    g: nx.DiGraph,
    client: Anthropic | None = None,
    max_turns: int = 15,
    rag_index: RAGIndex | None = None,
) -> AgentResponse:
```

**Logic changes inside `ask()`:**

1. **Tool list selection** — At the top of the function:
   ```python
   if rag_index is not None:
       tools = TOOLS + [EMIT_CONFIDENCE_TOOL]
       system = SYSTEM_PROMPT_RAG
   else:
       tools = TOOLS
       system = SYSTEM_PROMPT
   ```
   This is the toggle: when `rag_index=None`, the agent never sees `emit_confidence` and uses the original prompt. Zero behavioral change.

2. **State tracking** — Add variables:
   ```python
   confidence_score: float = -1.0
   used_rag: bool = False
   rag_chunks_used: list[str] = []
   rag_already_triggered: bool = False
   ```

3. **Confidence gate** — Inside the `tool_use` processing loop, when `tool_name == "emit_confidence"`:

   The gate triggers when **score < 0.85**. Anything at or above 0.85 is considered
   sufficiently confident to answer from the graph alone. When triggered, the tool
   result includes both a summary of all graph findings accumulated during traversal
   AND the top 5 RAG chunks, so the agent synthesizes both sources.

   ```python
   if tool_name == "emit_confidence":
       score = float(tool_input.get("score", 0.0))
       reasoning = tool_input.get("reasoning", "")
       confidence_score = score

       ack = f"Confidence: {score:.2f}. {reasoning}"

       triggers_rag = score < RAG_CONFIDENCE_THRESHOLD  # 0.85

       if triggers_rag and rag_index is not None and not rag_already_triggered:
           rag_already_triggered = True
           # Lazy import to avoid errors when voyageai/faiss not installed
           from src.rag import retrieve
           import voyageai
           vo_client = voyageai.Client()

           rag_results = retrieve(question, rag_index, vo_client, top_k=5)
           used_rag = True
           rag_chunks_used = [r.chunk.chunk_id for r in rag_results]

           # --- Build graph findings summary ---
           # Reconstruct what the agent found during graph traversal by
           # summarizing all entities it queried and their relationships.
           graph_findings_lines = ["GRAPH FINDINGS (from your traversal):"]
           for eid in sorted(referenced_entities):
               if eid in g:
                   ndata = g.nodes[eid]
                   line = f"  - [{ndata.get('type', '?')}] {ndata.get('name', eid)}: {ndata.get('description', '')}"
                   # Include attributes
                   attrs = {k: v for k, v in ndata.items() if k not in ('type', 'name', 'description')}
                   if attrs:
                       line += f" | Attributes: {attrs}"
                   graph_findings_lines.append(line)
                   # Include relationships for this entity
                   for _, tgt, edata in g.out_edges(eid, data=True):
                       tgt_name = g.nodes[tgt].get('name', tgt) if tgt in g else tgt
                       graph_findings_lines.append(
                           f"    --[{edata.get('type', '?')}]--> {tgt_name}: {edata.get('description', '')}"
                       )
                   for src, _, edata in g.in_edges(eid, data=True):
                       src_name = g.nodes[src].get('name', src) if src in g else src
                       graph_findings_lines.append(
                           f"    <--[{edata.get('type', '?')}]-- {src_name}: {edata.get('description', '')}"
                       )
           graph_summary = "\n".join(graph_findings_lines) if len(graph_findings_lines) > 1 else "No graph entities were found during traversal."

           # --- Build RAG chunks ---
           chunks_text = []
           for r in rag_results:
               header = f"[Chunk {r.rank} | Section: {r.chunk.section_title or 'General'} | Relevance: {r.score:.3f}]"
               chunks_text.append(f"{header}\n{r.chunk.text}")

           ack = (
               f"Confidence noted: {score:.2f} (below 0.85 threshold).\n\n"
               f"The system is providing both your graph findings and relevant document "
               f"excerpts. You MUST synthesize BOTH sources for your final answer.\n\n"
               f"{'=' * 40}\n"
               f"{graph_summary}\n\n"
               f"{'=' * 40}\n"
               f"DOCUMENT EXCERPTS ({len(rag_results)} most relevant chunks):\n\n"
               + "\n\n---\n\n".join(chunks_text)
               + "\n\n" + "=" * 40
               + "\n\nNow synthesize BOTH the graph relationships above AND the document "
               + "excerpts to produce a complete, accurate answer. The graph provides "
               + "structural relationship context; the document excerpts provide specific "
               + "details, values, and language from the policy."
           )
       elif triggers_rag and rag_index is None:
           ack += " No document retrieval available. Provide your best answer from the graph."
       else:
           # score >= 0.85 — graph alone is sufficient
           ack += f" Score {score:.2f} >= 0.85 threshold. Provide your final answer."

       tool_results.append({
           "type": "tool_result",
           "tool_use_id": block.id,
           "content": ack,
       })
   ```

4. **Return value** — Update the `AgentResponse` construction:
   ```python
   return AgentResponse(
       answer=answer_text,
       referenced_entities=sorted(referenced_entities),
       reasoning_path=f"Completed in {turn_count} turns",
       confidence=confidence_score,
       used_rag=used_rag,
       rag_chunks_used=rag_chunks_used,
   )
   ```

### 3.5 — `_execute_tool` is NOT modified

The `emit_confidence` handling happens inline in `ask()` before calling `_execute_tool`, because it needs access to `rag_index` and the query. `_execute_tool` remains a pure graph-querying function.

---

## Phase 4: CLI Integration

### 4.1 — Modify `src/test_agent.py`

**Changes:**
1. Parse `--rag` / `--no-rag` flags (default: `--rag`)
2. If RAG enabled, load RAG index via `load_rag_index(graph_id)`
3. Print RAG status at startup: `"RAG: enabled (42 chunks indexed)"` or `"RAG: disabled"`
4. Pass `rag_index` to `ask_verbose()`
5. In `ask_verbose()`: add `rag_index` parameter, pass to `client.messages.create()` via the same tool-selection logic as `ask()`
6. When printing tool calls, detect `emit_confidence` and print prominently:
   ```
   CONFIDENCE: 0.35 — "Graph lacks insurance details for Level 3"
   RAG TRIGGERED (0.35 < 0.85) — retrieving 5 document chunks...
   ```
   Or when RAG is not needed:
   ```
   CONFIDENCE: 0.92 — "Graph contains complete approval chain for Level 3"
   GRAPH SUFFICIENT (0.92 >= 0.85) — answering from graph only
   ```

**Updated usage:**
```
uv run python -m src.test_agent --graph 1-1              # RAG enabled (default)
uv run python -m src.test_agent --graph 1-1 --no-rag     # graph-only mode
```

### 4.2 — Modify `src/eval.py`

**Changes:**
1. Parse `--rag` / `--no-rag` flags (default: `--rag`)
2. If RAG enabled, `load_rag_index(graph_id)` after `load_graph_file()` (line 126)
3. Print RAG status: `"RAG: enabled (42 chunks)"` or `"RAG: disabled"`
4. Pass `rag_index=rag_index` to `ask()` call (line 153)
5. Add to each result entry (line 178-184):
   ```python
   "confidence": agent_response.confidence,
   "used_rag": agent_response.used_rag,
   "rag_chunks_used": agent_response.rag_chunks_used,
   ```
6. Add to per-question output line: `[RAG]` marker when RAG was used
7. Add RAG summary to final report:
   ```
   RAG Usage: 42/101 questions (41.6%)
     RAG questions pass rate:  71.4%
     Graph-only pass rate:     20.3%
   ```
8. Add to saved JSON:
   ```json
   "rag_enabled": true,
   "rag_summary": {
       "questions_using_rag": 42,
       "rag_trigger_rate": 41.6,
       "pass_rate_with_rag": 71.4,
       "pass_rate_graph_only": 20.3
   }
   ```

### 4.3 — Modify `src/build_graph.py`

**Changes:**
1. Parse `--rag` / `--no-rag` flags (default: `--rag`)
2. After `save_graph()` (line 182), if RAG enabled:
   ```python
   if rag_enabled:
       from src.rag import chunk_document, build_rag_index, save_rag_index
       import voyageai

       print("\nBuilding RAG index...")
       chunks = chunk_document(policy_text, policy_path.name)
       print(f"  {len(chunks)} chunks created")

       vo_client = voyageai.Client()
       graph_id = filepath.stem  # e.g., "graph-2-1"
       index = build_rag_index(chunks, vo_client, graph_id)
       save_rag_index(index)
       print(f"  RAG index saved ({len(chunks)} chunks, {index.embedding_dim}d embeddings)")
   ```

### 4.4 — Modify `src/main.py`

**Changes:**
1. Parse `--rag` / `--no-rag` flags (default: `--rag`)
2. After building graph, if RAG enabled, build RAG index from `policy_text`
3. Pass `rag_index` to `ask()` in the Q&A loop (line 94)
4. Print RAG status in the interactive header

---

## Phase 5: Evaluation & Measurement

### 5.1 — Run comparative eval

After implementation, run both modes on the same graph and Q&A set:

```bash
# Baseline: graph-only
uv run python -m src.eval --graph 2-1 --qa data/231123_Duty_of_Care_Policy.qa.small.json --no-rag --out output/eval_graph_only.json

# Hybrid: graph + RAG fallback
uv run python -m src.eval --graph 2-1 --qa data/231123_Duty_of_Care_Policy.qa.small.json --rag --out output/eval_hybrid.json
```

This directly measures the RAG fallback's impact without any other variables changing.

### 5.2 — Expected metrics to track

- Overall pass rate (graph-only vs hybrid)
- Per-difficulty pass rate
- RAG trigger rate (what % of questions needed RAG)
- Pass rate of RAG-triggered questions vs graph-only questions
- Average confidence score across all questions
- Confidence score distribution (histogram buckets: 0-0.25, 0.25-0.50, 0.50-0.85, 0.85-1.0)
- Correlation between confidence score and pass/fail (are low scores actually harder questions?)

---

## Build Sequence (Dependency Order)

```
Step 1: pyproject.toml + .env.example          ← no code depends on this yet
Step 2: src/models.py extensions                ← new types needed by rag.py
Step 3: src/rag.py (new file)                   ← depends on models.py
Step 4: src/build_rag.py (new file)             ← depends on rag.py
Step 5: Test — build RAG index for existing graph, verify retrieval works
Step 6: src/agent.py modifications              ← depends on rag.py
Step 7: Test — manual Q&A with RAG fallback working
Step 8: src/test_agent.py CLI flags             ← depends on agent.py changes
Step 9: src/eval.py CLI flags + tracking        ← depends on agent.py changes
Step 10: src/build_graph.py CLI flags           ← depends on rag.py
Step 11: src/main.py CLI flags                  ← depends on rag.py + agent.py
Step 12: Run comparative eval
```

Steps 8-11 are independent of each other and can be done in any order.

---

## File Change Summary

| File | Action | What Changes |
|------|--------|--------------|
| `pyproject.toml` | Modify | Add `faiss-cpu`, `voyageai` deps |
| `.env.example` | Modify | Add `VOYAGE_API_KEY` |
| `src/models.py` | Modify | Add `RAG_CONFIDENCE_THRESHOLD`, `DocumentChunk`, `RetrievalResult`; extend `AgentResponse` with `confidence: float` |
| `src/rag.py` | **Create** | Full RAG module: chunking, embedding, FAISS, retrieval (~250 lines) |
| `src/build_rag.py` | **Create** | Standalone CLI to build RAG index for existing graphs (~80 lines) |
| `src/agent.py` | Modify | Add `SYSTEM_PROMPT_RAG`, `EMIT_CONFIDENCE_TOOL`, modify `ask()` signature + loop |
| `src/test_agent.py` | Modify | Add `--rag`/`--no-rag` flags, pass rag_index, display confidence/RAG events |
| `src/eval.py` | Modify | Add `--rag`/`--no-rag` flags, track RAG usage, report RAG metrics |
| `src/build_graph.py` | Modify | Add `--rag`/`--no-rag` flags, build RAG index alongside graph |
| `src/main.py` | Modify | Add `--rag`/`--no-rag` flags, build/load RAG index for Q&A |

**Unchanged:** `src/parser.py`, `src/graph.py`, `src/visualizer.py`, `src/validate.py`, `src/generate_qa.py`, `src/pdf_parser.py`
