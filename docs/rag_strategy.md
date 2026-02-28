# RAG Strategy for Shogun — Final Recommendation

## Context

This document synthesizes findings from four parallel research streams: best practices, implementation examples, framework comparison, and Anthropic's contextual retrieval technique. The goal: define the most accurate RAG implementation for an enterprise compliance system that processes markdown policy documents, where accuracy is the only priority that matters.

## The Core Insight That Changes Everything

**Anthropic's Contextual Retrieval** is the single most important finding. Traditional RAG embeds chunks in isolation — a chunk saying "The threshold is $500,000" loses the context of *which* threshold, *in which section*, *for which risk level*. Anthropic's technique prepends a short LLM-generated context to each chunk before embedding:

> **Before:** `"The threshold is $500,000"`
> **After:** `"This chunk is from Section 4.2 (Insurance Requirements for Level 3 destinations) of the Duty of Care Policy. The threshold is $500,000"`

Results from Anthropic's benchmarks:

| Technique | Retrieval Failure Rate | Improvement |
|-----------|----------------------|-------------|
| Embeddings only (baseline) | 5.7% | — |
| + Contextual Embeddings | 3.7% | **35% reduction** |
| + Contextual BM25 (hybrid) | 2.9% | **49% reduction** |
| + Reranking | 1.9% | **67% reduction** |

Cost: **$1.02 per million document tokens** with prompt caching. For a 50-page policy (~25K tokens, ~30 chunks), this is fractions of a cent. A no-brainer for enterprise accuracy.

---

## Recommended Architecture

### Why Not a Framework

Build from scratch using raw Python + FAISS + Voyage AI + Anthropic SDK. Rationale:

1. **We already have the stack.** The project uses Anthropic SDK, NetworkX, FAISS. Adding LlamaIndex or LangChain introduces a massive dependency surface for functionality we can implement in ~300 lines.
2. **Full control over chunking.** Our documents are structured markdown with known heading patterns. A custom markdown chunker that understands our specific document structure will outperform any generic framework chunker.
3. **No abstraction tax.** Frameworks add indirection that makes debugging retrieval failures harder. For enterprise compliance, we need to trace exactly why a chunk was or wasn't retrieved.
4. **Anthropic's own recommendation.** From "Building Effective Agents": "Start simple. Use direct API calls before frameworks."

What we take from frameworks (ideas, not dependencies):
- LangChain's `MarkdownHeaderTextSplitter` pattern (stack-based header tracking)
- LlamaIndex's parent-child retrieval concept (small chunks for retrieval, full sections for generation)
- The reciprocal rank fusion algorithm for hybrid search

### The Full Pipeline

```
INDEXING (at ingestion time):
  Markdown document
       │
       ▼
  [1] Markdown-aware chunking (section boundaries, header hierarchy)
       │
       ├──→ Parent chunks: full sections (## level), up to 2048 tokens
       └──→ Child chunks: subsections/paragraphs (### level), 256-512 tokens
              │
              ▼
  [2] Contextual annotation (Claude Haiku per child chunk, with prompt caching)
       │  Prepends ~50-100 token context: "This chunk is from Section X.Y..."
       │
       ├──→ [3a] Voyage AI voyage-3-large embedding (1024-dim, input_type="document")
       │         → FAISS IndexFlatIP (exact cosine search)
       │
       └──→ [3b] BM25 index on contextualized chunk text
                  → rank-bm25 Python library (no Elasticsearch needed)

RETRIEVAL (at query time):
  User question
       │
       ▼
  [4] Embed query with Voyage AI (input_type="query")
       │
       ├──→ [5a] FAISS vector search → top-150 candidates
       └──→ [5b] BM25 lexical search → top-150 candidates
              │
              ▼
  [6] Reciprocal Rank Fusion (semantic_weight=0.8, bm25_weight=0.2)
       │  → merged, deduplicated, ranked candidates
       │
       ▼
  [7] Reranking with Voyage rerank-2.5 → top-20 chunks
       │
       ▼
  [8] Parent expansion: if multiple children from same parent retrieved,
      serve the full parent section instead
       │
       ▼
  [9] Format in XML tags for Claude (most relevant first)
       │
       ▼
  Agent synthesizes graph findings + retrieved chunks → answer
```

---

## Decision-by-Decision Breakdown

### 1. Chunking: Markdown-Aware, Parent-Child Hierarchy

**Strategy:** Section-aware chunking that respects the document's heading structure. Two levels:

- **Parent chunks** = full `##` sections (up to 2048 tokens). These are stored but NOT embedded — they exist only to provide expanded context when child chunks are retrieved.
- **Child chunks** = `###` subsections, paragraphs, or table/list blocks within a section (256-512 tokens). These ARE embedded and indexed for retrieval.

**Why this specific approach:**
- Chroma research: 200-token chunks achieve best retrieval precision (IoU 6.9-8.0)
- LlamaIndex research: 1024-token chunks achieve best generation quality
- Parent-child resolves this tension: small children for precise retrieval, full parent sections for accurate generation
- Duty of care documents have explicit heading hierarchy — we should use it, not ignore it

**Atomic units (never split):**
- Markdown tables
- Numbered/bulleted lists that form a logical unit (e.g., list of risk levels, vaccination requirements)
- Definition blocks (bold term + definition)

**No overlap.** Chroma research found overlap consistently hurts precision. The parent-child strategy handles context continuity instead.

**Fallback:** If a section exceeds 512 tokens and has no `###` subsections, use recursive splitting: split on `\n\n` (paragraphs), then `\n` (lines), then by sentence. This is LangChain's `RecursiveCharacterTextSplitter` pattern, implemented directly.

**Metadata on every chunk:**
- `section_path`: Full header breadcrumb, e.g., `"Emergency Response > Medical Emergencies > Evacuation"`
- `parent_chunk_id`: Links child to its parent for expansion
- `page_number`: Estimated from source document
- `chunk_index`: Sequential position in document
- `char_start` / `char_end`: Character offsets in source text

### 2. Contextual Annotation: Claude Haiku Per Chunk

**What:** Before embedding, call Claude Haiku with the full document + individual chunk and ask for a short context sentence. Prepend this to the chunk text.

**Prompt (from Anthropic):**
```
<document>
{{WHOLE_DOCUMENT}}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{{CHUNK_CONTENT}}
</chunk>
Please give a short succinct context to situate this chunk within the
overall document for the purposes of improving search retrieval of the
chunk. Answer only with the succinct context and nothing else.
```

**Implementation detail:** Use prompt caching. The full document goes in a cached content block. For a policy with 50 chunks, the document is sent once and cached; each subsequent chunk call reads it from cache at 90% discount.

**Why this matters for our use case:** A compliance policy chunk saying "Coverage must be at least $1,000,000" is useless without knowing it's about medical evacuation insurance for Level 3 destinations. The context annotation makes this explicit in the embedding.

### 3. Embeddings: Voyage AI voyage-3-large, 1024 Dimensions

**Model:** `voyage-3-large` at 1024 dimensions.

**Why Voyage:**
- Outperforms OpenAI text-embedding-3-large by 9.74% across 100 datasets
- Outperforms Cohere v3 by 20.71%
- 32K token context window (4x OpenAI's 8K) — critical for our contextualized chunks
- Endorsed by Anthropic's own contextual retrieval research
- Already in our dependency stack (Anthropic ecosystem)

**Why 1024 dimensions:** Within <1% of maximum quality at 2048 dims. No reason to go lower when accuracy is the priority.

**Input types:**
- `input_type="document"` for indexing chunks (prepends "Represent the document for retrieval:")
- `input_type="query"` for search queries (prepends "Represent the query for retrieving supporting documents:")
- This asymmetric embedding is trained into the model and improves retrieval. Free accuracy — always use it.

**Note:** Voyage embeddings are pre-normalized, so FAISS `IndexFlatIP` (inner product) gives cosine similarity directly without manual L2 normalization.

### 4. Vector Store: FAISS IndexFlatIP (Exact Search)

**Why FAISS IndexFlatIP:**
- Exact inner product search — zero approximation error
- With pre-normalized Voyage embeddings, inner product = cosine similarity
- For 50-200 chunks, search is sub-millisecond. Approximate indices (IVF, HNSW) add complexity for zero benefit at this scale
- Persistence via `faiss.write_index()` / `faiss.read_index()`
- No server, no SQLite, no network calls — pure in-process

**Storage:** `output/rag_indexes/{graph_id}.faiss` + `{graph_id}.chunks.json` (co-located with graph files)

### 5. Hybrid Search: Dense + BM25 with Reciprocal Rank Fusion

**Why hybrid:**
- Anthropic's research: hybrid reduces retrieval failures by 49% (vs 35% for embeddings alone)
- Azure AI Search: hybrid achieves 10.5% improvement over vector-only
- BM25 catches exact term matches that embeddings miss: specific dollar amounts, policy codes, section numbers, role titles

**BM25 implementation:** Use `rank-bm25` Python library (pure Python, no Elasticsearch needed). Index the contextualized chunk text (same text that gets embedded). This is lightweight — no server infrastructure.

**Fusion algorithm:** Reciprocal Rank Fusion (RRF), the industry standard per Qdrant and Weaviate:
```
score(chunk) = semantic_weight * (1 / (semantic_rank + k)) + bm25_weight * (1 / (bm25_rank + k))
```
Where `semantic_weight=0.8`, `bm25_weight=0.2`, `k=60` (standard RRF constant).

**Why not linear score combination:** Qdrant explicitly warns that "relevant and non-relevant objects are not linearly separable" with raw scores from different systems.

### 6. Reranking: Voyage rerank-2.5

**Why rerank:**
- Anthropic's data: reranking adds a further 34% failure reduction on top of hybrid search (2.9% → 1.9%)
- Cross-encoders process query-document pairs jointly through a full transformer — fundamentally more accurate than bi-encoder similarity
- LlamaIndex research: reranking "transforms any embedding into a competitive one"

**Why Voyage rerank-2.5 (over Cohere):**
- 32K token context — matches our embedding model's context window
- Same vendor as embeddings (single API key, coherent stack)
- Instruction-following capability for domain-specific relevance tuning

**Pipeline:** Retrieve top-150 from hybrid search → rerank → take top-20.

**Why top-20 (not top-5):**
- Anthropic explicitly tested and recommends top-20
- Higher recall — more likely to include the relevant chunk
- Claude's context window easily handles 20 chunks (~10-20K tokens)

### 7. Parent Expansion

After reranking selects the top-20 child chunks, check if multiple children from the same parent section were retrieved. If so, replace them with the full parent section. This:
- Reduces redundancy (overlapping children from the same section)
- Provides the LLM with full section context for better reasoning
- Typically reduces the final chunk count from 20 to 8-15 (more cohesive)

### 8. Formatting for Claude

Use XML tags (Claude is specifically trained to parse them):
```xml
<retrieved_documents>
  <document index="1" section="Section 4.2: Insurance Requirements" relevance="0.94">
    <content>
      {{CHUNK_TEXT}}
    </content>
  </document>
  <document index="2" section="Section 3.1: Risk Level Definitions" relevance="0.91">
    <content>
      {{CHUNK_TEXT}}
    </content>
  </document>
</retrieved_documents>
```

Place retrieved chunks **before** the query in the message (Anthropic testing showed up to 30% improvement placing data above instructions).

---

## What NOT to Implement

Based on the research, these are deliberately excluded:

| Technique | Why Excluded |
|-----------|-------------|
| **Semantic chunking** | Our documents have explicit heading structure. Embedding-based boundary detection adds complexity for no gain over structure-aware splitting. |
| **HyDE** | Adds an LLM call per query for marginal benefit when contextual retrieval + hybrid + reranking already achieves 67% failure reduction. Consider as future enhancement only. |
| **Late chunking** | Requires specific embedding model support (Jina). Contextual retrieval achieves similar benefits with Voyage embeddings. Doesn't improve BM25. |
| **ChromaDB / Pinecone / Weaviate** | Unnecessary infrastructure for 50-200 chunks. FAISS IndexFlatIP is sub-millisecond, persists to a flat file, and has zero operational overhead. |
| **LlamaIndex / LangChain** | We take their ideas (parent-child, markdown splitting, RRF) but implement directly. Avoids massive dependency surface. Full control over every decision. |
| **Overlap between chunks** | Research shows it hurts precision. Parent-child strategy handles context continuity better. |
| **Multi-query retrieval** | Worth considering later, but adds query-time latency. Start without it, measure, then add if retrieval recall is insufficient. |

---

## New Dependencies

```toml
# Add to pyproject.toml
"faiss-cpu>=1.7.4",     # Vector store (in-process, exact search)
"voyageai>=0.3.0",      # Embeddings + reranking (Anthropic ecosystem)
"rank-bm25>=0.2.2",     # BM25 lexical search (pure Python, no server)
"numpy>=1.26.0",        # Required by FAISS
```

New environment variable:
```
VOYAGE_API_KEY=vo-...
```

---

## New Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `src/rag.py` | Core RAG module: chunking, contextual annotation, embedding, indexing, hybrid retrieval, reranking, parent expansion | ~400 |
| `src/build_rag.py` | CLI to build RAG index for an existing graph: `uv run python -m src.build_rag --graph 1-1` | ~80 |

---

## Expected Impact

Based on the research numbers and our current 43.6% pass rate:

- **Pure graph (current):** 43.6% pass rate — information loss at extraction is the bottleneck
- **Graph + basic RAG (embed+retrieve):** Estimated 65-70% — fills factual gaps but may miss exact terms
- **Graph + full pipeline (contextual + hybrid + rerank):** Estimated 80-90% — the 67% failure reduction in retrieval cascades to dramatically better generation

The questions that currently fail ("What is the order number?", "What values are activities based on?") are exactly the type that BM25 excels at — specific terms and values that semantic search alone misses.

---

## Sources

- [Anthropic: Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) — 35-67% failure reduction, contextual embedding technique, hybrid search, reranking pipeline
- [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) — "Start simple, use direct API calls before frameworks"
- [Voyage AI: voyage-3-large benchmarks](https://blog.voyageai.com/2025/01/07/voyage-3-large/) — 9.74% over OpenAI, 20.71% over Cohere
- [Chroma: Evaluating Chunking](https://research.trychroma.com/evaluating-chunking) — 200-token chunks optimal for precision, overlap hurts
- [LlamaIndex: Chunk Size Evaluation](https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5) — 1024 tokens optimal for generation quality
- [LlamaIndex: Auto-Merging Retriever](https://developers.llamaindex.ai/python/examples/retrievers/auto_merging_retriever/) — Parent-child retrieval pattern
- [Azure AI Search](https://techcommunity.microsoft.com/blog/azure-ai-services-blog/) — Hybrid + reranking: 37% improvement over vector-only
- [Qdrant: Hybrid Search](https://qdrant.tech/articles/hybrid-search/) — RRF as de facto standard
- [Pinecone: Rerankers](https://www.pinecone.io/learn/series/rag/rerankers/) — Cross-encoder vs bi-encoder analysis
- [LangChain: MarkdownHeaderTextSplitter](https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/markdown.py) — Stack-based header tracking pattern
