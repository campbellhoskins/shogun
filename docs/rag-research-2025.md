# RAG Best Practices Research (2025-2026)

## Enterprise Compliance System Context

This research is targeted at building a RAG system for processing structured markdown documents (corporate travel duty of care policies) where **maximum accuracy** is the priority and cost is not a concern. Every recommendation below is oriented toward that constraint.

---

## 1. Chunking Strategies

### 1.1 Optimal Chunk Sizes

Research converges on a nuanced picture depending on what you optimize for:

**Retrieval precision (finding exactly the right content):**
- Chroma's research found that **200-token chunks with no overlap** achieved the best IoU (Intersection over Union) scores of 6.9-8.0 with text-embedding-3-large, and the highest precision (7.0 +/- 5.6).
- 400-token chunks showed moderate IoU of 3.6 +/- 3.2 with ~89.5% recall.
- 800-token chunks with 400-token overlap performed worst across all metrics.
- Source: [Chroma Evaluating Chunking Research](https://research.trychroma.com/evaluating-chunking)

**End-to-end RAG quality (faithfulness + relevancy of final answers):**
- LlamaIndex's evaluation across 128, 256, 512, 1024, and 2048 tokens found that **1024 tokens** achieved the highest faithfulness and relevancy scores when evaluated by GPT-4.
- Source: [LlamaIndex Chunk Size Evaluation](https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5)

**Industry consensus starting point:**
- Unstructured.io recommends starting at **~250 tokens (~1000 characters)** for a balance of context retention and retrieval precision.
- Anthropic's contextual retrieval uses chunks of "usually no more than a few hundred tokens" with ~800 tokens in their cost calculations.
- Sources: [Unstructured Chunking Best Practices](https://unstructured.io/blog/chunking-for-rag-best-practices), [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)

**Recommendation for this project:** Use **256-512 token chunks** for retrieval (small enough for precise matching), but serve the **parent section (1024-2048 tokens)** to the LLM for generation context. This is the parent-child strategy (see 1.6).

### 1.2 Section-Aware / Structure-Aware Chunking vs Fixed-Size

**Structure-aware chunking is significantly better for structured documents.** The evidence:

- Pinecone documents that structure-based chunking "respects original document formatting and hierarchy" and is a specialized method for Markdown, HTML, PDF, and LaTeX.
- Unstructured.io's "Smart Chunking" operates on parsed document elements rather than raw text: "ensures chunk boundaries follow logical document structure." Their "By Title" strategy prevents content from different sections from mixing.
- LangChain's `MarkdownHeaderTextSplitter` tracks headers through a stack-based approach, maintaining hierarchical relationships. It sorts header markers by length (descending) to match longer patterns first, handles code blocks specially to avoid incorrect splits, and supports both aggregated and line-by-line output modes.
- Sources: [Pinecone Chunking Strategies](https://www.pinecone.io/learn/chunking-strategies/), [Unstructured](https://unstructured.io/blog/chunking-for-rag-best-practices), [LangChain Markdown Splitter](https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/markdown.py)

**Recommendation for this project:** Since the input is structured markdown with clear header hierarchy (# ## ###), use **markdown-aware chunking that preserves section boundaries**. Never split mid-section. Each chunk should carry its full header path as metadata (e.g., "Emergency Response > Medical Emergencies > Evacuation Procedures").

### 1.3 Markdown-Aware Chunking Implementation

Based on LangChain's `MarkdownHeaderTextSplitter` implementation:

1. **Header tracking:** Use a stack to maintain the current header hierarchy. When encountering a new header at the same or higher level, pop previous headers from the stack.
2. **Configurable headers:** Accept `headers_to_split_on` as tuples mapping header markers (`#`, `##`, `###`) to metadata keys.
3. **Code block handling:** Detect fence markers (``` and ~~~) to avoid splitting inside code blocks.
4. **Strip headers option:** Control whether header text appears in chunk content vs. only in metadata.
5. **Aggregation:** Combine consecutive lines sharing identical header metadata into single chunks.
6. **Tables:** Keep tables as atomic units. Never split a markdown table across chunks.
7. **Lists:** Keep related list items together. A definition list or enumerated set of requirements should remain in one chunk.

**Recommendation for this project:** Build a custom markdown chunker that:
- Splits on `##` and `###` headers (section and subsection level)
- Preserves the full header breadcrumb trail as metadata
- Keeps tables, definition blocks, and numbered lists as atomic units
- Targets 256-512 tokens per chunk (but allows overflow for atomic elements)
- Falls back to recursive splitting only for sections that exceed the target size

### 1.4 Recursive Chunking Strategies

LangChain's `RecursiveCharacterTextSplitter` attempts sequential splitting using separators in priority order: `["\n\n", "\n", " ", ""]`. This means:

1. First try to split on paragraph boundaries (`\n\n`)
2. If chunks are still too large, split on line boundaries (`\n`)
3. If still too large, split on spaces
4. Last resort: split on individual characters

**When it helps:** When you have sections that are too large for your target chunk size and need to sub-divide them while preserving as much structural integrity as possible.

**When it doesn't help:** When the document already has clear section boundaries (like well-structured markdown). In that case, section-aware splitting is superior.

**Recommendation for this project:** Use recursive splitting as a **fallback only** for sections that exceed the target chunk size after markdown-aware splitting. The primary splitting should be section-aware.

### 1.5 Overlap Between Chunks

**Research is surprisingly negative on overlap:**

- Chroma's research found that removing overlap **consistently improved results**. 800-token chunks with 400-token overlap had IoU of 1.5 +/- 1.3, but without overlap IoU improved to 3.6 +/- 3.2. The explanation: "reducing chunk overlap improves IoU scores, as this metric penalizes redundant information."
- Unstructured.io notes that "excessive overlap increases redundancy and wastes context capacity" and recommends treating overlap as a tunable parameter requiring empirical validation.
- Source: [Chroma Research](https://research.trychroma.com/evaluating-chunking), [Unstructured](https://unstructured.io/blog/chunking-for-rag-best-practices)

**However, overlap has a specific valid use case:** When you MUST use fixed-size chunking (no section awareness), overlap of 10-20% helps preserve continuity across arbitrary boundaries.

**Recommendation for this project:** **No overlap** for section-aware chunks. If recursive fallback splitting is needed within a section, use minimal overlap (50-100 tokens) at sub-section split points. The parent-child strategy (1.6) handles context continuity better than overlap.

### 1.6 Parent-Child Chunking (Small Chunks for Retrieval, Larger Context for Generation)

This is one of the most impactful strategies and is well-supported by research:

**How it works (LlamaIndex AutoMergingRetriever):**
- Create a multi-level hierarchy: Level 1 (2048 chars), Level 2 (512 chars), Level 3 (128 chars)
- Index leaf nodes (smallest chunks) in the vector store for precise retrieval
- Store all nodes (including parents) in a document store
- When multiple child chunks from the same parent are retrieved, **merge them into the parent** if they exceed a threshold
- In LlamaIndex's example: 6 initially retrieved nodes merged to 3 parent nodes, creating more cohesive context
- Source: [LlamaIndex Auto-Merging Retriever](https://developers.llamaindex.ai/python/examples/retrievers/auto_merging_retriever/)

**Why it matters:**
- LlamaIndex's research shows this "decouples retrieval and synthesis chunks." You "embed a sentence, which then links to a window around the sentence" -- enabling finer-grained retrieval while preserving synthesis context.
- Avoids the fundamental tension between small chunks (better retrieval precision) and large chunks (better generation context).
- Source: [LlamaIndex Production RAG](https://developers.llamaindex.ai/python/framework/optimizing/production_rag/)

**Recommendation for this project:** Implement a two-level parent-child system:
- **Child chunks (retrieval):** 256-512 tokens, section-aware, with header breadcrumb metadata
- **Parent chunks (generation):** The full section (up to 2048 tokens) that the child belongs to
- When multiple children from the same parent are retrieved, serve the full parent to the LLM
- This is the single most impactful architectural decision for accuracy

### 1.7 Semantic Chunking (Embedding-Based Topic Boundary Detection)

**How it works:** Embed individual sentences, compare consecutive sentence embeddings, and split where the semantic distance exceeds a threshold (indicating a topic shift).

**Assessment from Pinecone:** Described as "an experimental technique" that "groups sentences discussing the same topic by comparing semantic distance between embedded sentence groups."

**When it helps:** Unstructured markdown or natural language text without clear headers, where topic shifts are implicit rather than structural.

**When it doesn't help:** Well-structured markdown with explicit headers and sections. The headers already define the topic boundaries more reliably than embedding similarity.

**Recommendation for this project:** **Skip semantic chunking.** The duty of care documents are structured markdown with clear header hierarchy. Section-aware chunking is both simpler and more reliable for this use case. Semantic chunking adds complexity and latency for marginal benefit when structure is already explicit.

---

## 2. Embedding Models

### 2.1 Model Comparison (2025-2026 State of the Art)

#### Voyage AI (voyage-4-large / voyage-3-large)

**Current leader for retrieval tasks.**

- **voyage-3-large:** 2048 dimensions (supports 2048, 1024, 512, 256 via Matryoshka), 32K token context
  - Outperforms OpenAI text-embedding-3-large by **9.74% average** across 100 datasets and 8 domains
  - Outperforms Cohere v3 English by **20.71%**
  - Int8 at 1024 dimensions is only 0.31% below float at 2048 dimensions (8x less storage)
  - Binary 512-dim embeddings **outperform** OpenAI-v3-large (3072-dim float) by 1.16% with 200x less storage
  - Source: [Voyage 3 Large Blog](https://blog.voyageai.com/2025/01/07/voyage-3-large/)

- **voyage-4-large (latest):** 1024 default dimensions (supports 256-2048), 32K token context
  - Best general-purpose quality in Voyage's current lineup
  - Source: [Voyage AI Embeddings Docs](https://docs.voyageai.com/docs/embeddings)

- **voyage-3:** 1024 dimensions, 32K context, NDCG@10 of 76.72
  - Outperforms OpenAI v3 large "across all eight evaluated domains by 7.55% on average"
  - Source: [Voyage 3 Blog](https://blog.voyageai.com/2024/09/18/voyage-3/)

- Anthropic's own contextual retrieval research noted that "Gemini and Voyage embeddings showed superior performance."

#### OpenAI text-embedding-3-large

- 3072 default dimensions (supports Matryoshka shortening), 8K token context
- NDCG@10 of ~69.17 (per Voyage benchmarks)
- Supports Matryoshka representations for dimension reduction
- More expensive ($0.13/M tokens) with 3-4x larger embeddings than Voyage
- 8K context limit is a significant constraint compared to Voyage's 32K

#### Cohere Embed v3 / v4

- Supports `input_type` parameter: `search_document`, `search_query`, `classification`, `clustering`
- 1024 dimensions
- Strong multilingual performance
- int8 and binary quantization support
- However, Voyage outperforms Cohere v3 by 20.71% on retrieval benchmarks

#### BGE-M3 (BAAI)

- **1024 dimensions, 8192 token context, 100+ languages**
- Unique multi-functionality: supports dense, sparse (BM25-like), and multi-vector (ColBERT) retrieval simultaneously
- Self-hosted (no API costs), open-source
- Recommended weights for hybrid: `[0.4, 0.2, 0.4]` (dense, sparse, colbert)
- Competitive with proprietary models; surpasses OpenAI embeddings in some independent evaluations
- Source: [BGE-M3 on HuggingFace](https://huggingface.co/BAAI/bge-m3)

#### Jina Embeddings v3

- **570M parameters, 1024 default dimensions, 8192 token context, 89 languages**
- Task-specific LoRA adapters: `retrieval.query`, `retrieval.passage`, `separation`, `classification`, `text-matching`
- Matryoshka support down to 32 dimensions without significant performance loss
- Outperforms OpenAI and Cohere on MTEB English tasks
- Cost-efficient compared to LLM-based alternatives (570M vs 7B params)
- Source: [Jina v3 Announcement](https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/)

### 2.2 Optimal Embedding Dimensions

The key finding across all providers is that **Matryoshka representations allow dimension reduction with minimal quality loss:**

- Voyage-3-large: Int8 at 1024 dimensions loses only 0.31% vs float at 2048
- Voyage-3-large: Binary 512-dim still outperforms OpenAI-3-large at 3072-dim float
- Jina v3: Supports reduction from 1024 down to 32 dimensions
- All major models now support Matryoshka embeddings

**Recommendation for this project:** Use **1024 dimensions** as the sweet spot. This provides:
- Near-maximum quality (within <1% of higher dimensions)
- Reasonable storage and search performance
- Compatibility with all major providers
- Since cost is not a concern, there is no reason to go below 1024

### 2.3 Input Type (Query vs Document) -- Does It Actually Matter?

**Yes, it matters, but with nuance:**

- **Voyage AI:** The `input_type` parameter prepends different system prompts:
  - `query`: Prepends "Represent the query for retrieving supporting documents: "
  - `document`: Prepends "Represent the document for retrieval: "
  - `None` (default): Direct conversion without optimization
  - Voyage explicitly states that "embeddings generated with and without the input_type argument are compatible"
  - Source: [Voyage Embeddings Docs](https://docs.voyageai.com/docs/embeddings)

- **Jina v3:** Uses task-specific LoRA adapters (`retrieval.query` vs `retrieval.passage`) which are more architecturally significant than prompt prefixes.

- **Cohere:** Uses `search_document` vs `search_query` input types.

**Recommendation for this project:** Always use the appropriate input_type. Set `document` for indexing chunks and `query` for search queries. The overhead is zero and the models are trained to produce better asymmetric embeddings with these hints. Not using them leaves performance on the table.

### 2.4 Matryoshka Embeddings

**What they are:** Embedding models trained so that the first N dimensions of a larger embedding are themselves a valid, useful embedding. Named after Russian nesting dolls.

**Trade-offs:**
- Voyage-3-large at 512 binary dimensions with 200x less storage still outperforms OpenAI-3-large at 3072 float
- Jina v3 can reduce from 1024 to 32 dimensions
- Quality degrades gracefully rather than catastrophically

**When useful:** When you need to optimize storage or search speed. For a compliance system where cost is not a concern, **use the full dimensionality**.

**Recommendation for this project:** Use full 1024 (or 2048 for voyage-3-large) dimensions. Matryoshka capability is a nice fallback but not needed when accuracy is paramount.

### 2.5 Embedding Model Recommendation

**Primary: Voyage AI voyage-4-large (or voyage-3-large)**

Rationale:
1. Highest retrieval accuracy across benchmarks (9.74% above OpenAI, 20.71% above Cohere v3)
2. 32K token context window (4x OpenAI's 8K) -- critical for large chunks
3. 1024 default dimensions (efficient storage without quality sacrifice)
4. Endorsed by Anthropic's own research
5. Matryoshka + quantization flexibility if ever needed

**Fallback: BGE-M3 (self-hosted)**

Rationale:
1. Built-in hybrid retrieval (dense + sparse + ColBERT in one model)
2. Open source, no API dependency
3. Competitive quality
4. Native sparse vectors eliminate need for separate BM25 implementation

---

## 3. Similarity / Distance Functions

### 3.1 Cosine Similarity vs Dot Product vs L2 Distance

**Key insight from Weaviate:** "Use the distance metric that matches the model that you're using."

- **Cosine similarity:** Measures angle between vectors, normalizing for magnitude. Range: 0 (identical) to 2 (opposite). Best for NLP and document similarity where vector magnitude differences should not affect relevance.
- **Dot product:** Reports both angle AND magnitude. Produces identical results to cosine similarity **only if data is normalized**. When magnitude carries meaning (e.g., document importance/popularity), dot product preserves that signal.
- **L2 (Euclidean) distance:** Sum of squared differences. Range: 0 to infinity. More precise but computationally expensive.
- **Manhattan (L1) distance:** Sum of absolute differences. Faster to calculate, preferred for very high-dimensional data.
- Source: [Weaviate Distance Metrics](https://weaviate.io/blog/distance-metrics-in-vector-search)

### 3.2 Does the Choice Actually Matter with Normalized Embeddings?

**For normalized embeddings (which most modern models produce), cosine similarity and dot product yield identical rankings.** The models from Voyage, OpenAI, Cohere, and Jina all produce normalized embeddings by default.

The practical implication: **Cosine similarity is the safest default** because it works correctly regardless of whether embeddings are normalized. Dot product is slightly faster computationally but requires normalization.

**Recommendation for this project:** Use **cosine similarity**. It is the standard for all major embedding models, is normalization-agnostic, and has no accuracy disadvantage with normalized embeddings.

### 3.3 Hybrid Search: Dense + Sparse (BM25/TF-IDF)

**The evidence strongly supports hybrid search:**

- **Anthropic's contextual retrieval:** Combining contextual embeddings + BM25 reduced retrieval failure by **49%** (from 5.7% to 2.9%), compared to 35% for embeddings alone. Adding reranking on top brought the reduction to **67%** (to 1.9%).
- Source: [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)

- **Microsoft/Azure AI Search:** Hybrid retrieval achieved 48.4 NDCG@3 vs 43.8 for vector-only (~10.5% improvement). Hybrid + semantic reranking achieved 60.1 NDCG@3 -- a **37% improvement** over pure vector search.
- Source: [Azure AI Search Blog](https://techcommunity.microsoft.com/blog/azure-ai-services-blog/azure-ai-search-outperforming-vector-search-with-hybrid-retrieval-and-ranking-cap/3929167)

- **Weaviate:** Recommends alpha=0.75 (favoring semantic) as default, with domain-specific tuning. Reciprocal Rank Fusion (RRF) is the standard fusion algorithm.
- Source: [Weaviate Hybrid Search](https://weaviate.io/blog/hybrid-search-explained)

- **Qdrant:** Warns against linear score combinations ("relevant and non-relevant objects are not linearly separable"). Recommends Reciprocal Rank Fusion (RRF) as "the de facto standard."
- Source: [Qdrant Hybrid Search](https://qdrant.tech/articles/hybrid-search/)

**Why hybrid matters for compliance documents:** BM25 excels at exact term matching -- critical for policy-specific terminology like "IATA accreditation," "ARC compliance," "duty of care Level 3," specific dollar thresholds, or error codes. Semantic search alone might miss these exact matches.

**Recommendation for this project:** **Implement hybrid search (dense embeddings + BM25)**. Use Reciprocal Rank Fusion (RRF) to combine results. This is the single highest-ROI improvement after basic vector search.

---

## 4. Retrieval Strategies

### 4.1 Top-K Selection: Optimal K

**Anthropic's research is definitive here:**
- Tested top-5, top-10, and top-20 chunks
- **Top-20 was the most performant**
- Their pipeline: retrieve top-150 candidates via initial search, rerank to top-20, serve those 20 to the LLM
- Source: [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)

**Why more chunks is better (up to a point):**
- Higher K increases recall (probability of including the relevant chunk)
- Modern LLMs have large enough context windows to handle 20 chunks without "lost in the middle" problems when combined with reranking
- The cost is more input tokens to the LLM, but that is explicitly not a concern for this project

**The "lost in the middle" problem:** Weaviate's research notes that "relevant information placed in the middle of search results rather than beginning or end may be ignored by LLMs." The solution is reranking to place the most relevant chunks first.

**Recommendation for this project:** Retrieve **top-150 candidates** from the initial hybrid search, rerank to **top-20**, serve those to the LLM with the most relevant first.

### 4.2 Re-Ranking After Initial Retrieval

**Why reranking is essential:**

Cross-encoders (rerankers) process query-document pairs jointly through a full transformer, while bi-encoders (embedding models) encode them separately. This architectural difference means rerankers are "much more accurate" but computationally expensive (Pinecone notes that reranking 40M records would take 50+ hours on a V100 GPU, vs <100ms for vector search).

The solution: **two-stage retrieval**:
1. Fast initial retrieval (vector + BM25) to get ~150 candidates
2. Cross-encoder reranking to narrow to top-20
- Source: [Pinecone Rerankers](https://www.pinecone.io/learn/series/rag/rerankers/)

**Impact numbers:**
- Anthropic: Adding reranking to contextual embeddings + BM25 reduced failure from 2.9% to 1.9% (further 34% relative reduction)
- Azure AI Search: Semantic reranking improved NDCG@3 by 24% over hybrid alone
- LlamaIndex: CohereRerank and bge-reranker-large consistently improve all embeddings, with JinaAI-Base + bge-reranker-large achieving 0.938 hit rate and 0.869 MRR
- Source: [LlamaIndex Embedding+Reranker Comparison](https://www.llamaindex.ai/blog/boosting-rag-picking-the-best-embedding-reranker-models-42d079022e83)

**Available rerankers:**
- **Cohere Rerank 4.0:** Latest, supports 100+ languages, structured data via YAML formatting
- **Voyage AI rerank-2.5:** 32K token context, instruction-following, cross-encoder architecture
- **BGE-reranker-v2-m3:** Open source, strong performance per Pinecone evaluation
- **bge-reranker-large:** Frequently provides highest MRR values per LlamaIndex research

**Key insight from LlamaIndex:** "Rerankers have demonstrated their capability to transform any embedding into a competitive one. However, foundational embedding quality remains essential -- superior rerankers cannot fully compensate for weak initial retrieval results."

**Recommendation for this project:** Use **Cohere Rerank 4.0** or **Voyage rerank-2.5** as the production reranker. Retrieve 150 candidates, rerank to top-20. This is a non-negotiable component for maximum accuracy.

### 4.3 Contextual Retrieval (Anthropic's Approach)

**The technique:** Before embedding each chunk, use an LLM to generate a short contextual description (50-100 tokens) that situates the chunk within the full document. Prepend this context to the chunk before both embedding and BM25 indexing.

**The prompt (from Anthropic):**
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

**Results:**
- Contextual embeddings alone: **35% reduction** in retrieval failures
- Combined with BM25: **49% reduction**
- With reranking: **67% reduction** (5.7% -> 1.9%)

**Cost:** $1.02 per million document tokens using prompt caching with Claude.

**Implementation consideration:** Use prompt caching so the full document is only sent once, with each chunk processed as a follow-up. This reduces cost by ~90%.

**Recommendation for this project:** **Implement contextual retrieval.** At preprocessing time, generate contextual descriptions for every chunk using Claude. This is the highest-impact preprocessing step identified in the research. For a compliance document system, the context helps disambiguate chunks like "The threshold is $500" by prepending "This chunk describes the medical evacuation expense threshold in the Emergency Response section of the International Travel Policy."

### 4.4 HyDE (Hypothetical Document Embedding)

**How it works:** Instead of embedding the user's query directly, first have an LLM generate a hypothetical document that would answer the query, then embed that hypothetical document for retrieval.

**Results from the original paper (Gao et al., 2022):**
- "Significantly outperforms the state-of-the-art unsupervised dense retriever Contriever"
- Shows "strong performance comparable to fine-tuned retrievers" across web search, QA, and fact verification
- Source: [HyDE Paper](https://arxiv.org/abs/2212.10496)

**Limitations:**
- Generated documents are "unreal and may contain false details"
- Depends on the encoder to filter out hallucinations via "dense bottleneck"
- Performance degrades on highly specialized or niche retrieval tasks
- Adds latency (LLM call before every search)

**Recommendation for this project:** **Consider but do not prioritize.** HyDE adds latency and complexity. The combination of contextual retrieval + hybrid search + reranking already achieves 67% failure reduction. HyDE may provide marginal additional benefit for ambiguous queries but is not justified as a primary strategy. Test it as an optional enhancement.

### 4.5 Multi-Query Retrieval

**How it works:** Reformulate the original query into multiple variants, run each through the retrieval pipeline, and take the union of results.

**When it helps:** Ambiguous or multi-faceted queries that might match different terminology in the document. Example: "What happens if an employee gets sick abroad?" could also be phrased as "medical emergency during international travel," "overseas illness policy," or "duty of care health incident."

**Recommendation for this project:** **Implement as a secondary enhancement.** Use the LLM to generate 2-3 query variants before retrieval. This is relatively cheap (one LLM call) and can catch terminology mismatches between queries and policy language.

### 4.6 Metadata Filtering Combined with Vector Search

**The approach:** Attach structured metadata to chunks (section name, policy area, geographic scope, effective date, policy tier) and filter on metadata before or alongside vector search.

**LlamaIndex recommends:** "Metadata filters with auto-retrieval for keyword-based precision" as documents scale.

**Recommendation for this project:** **Essential for compliance documents.** Every chunk should carry:
- `section_path`: Full header breadcrumb (e.g., "International Travel > Medical Emergencies > Evacuation")
- `policy_area`: Top-level category (e.g., "medical", "security", "natural_disaster", "travel_advisory")
- `document_title`: Source document name
- `effective_date`: When the policy applies from
- These metadata fields enable precise filtering when the agent knows which policy area is relevant.

---

## 5. Accuracy Optimization

### 5.1 Biggest Sources of Retrieval Failure

Based on the research:

1. **Semantic dilution in large chunks:** Embedding models compress meaning via pooling (CLS, mean, or max). Larger chunks lose fine-grained detail. Unstructured.io: "This compression is inherently lossy -- larger chunks risk obscuring important details."

2. **Vocabulary mismatch:** User queries use different terms than the document. Example: querying "sick abroad" when the policy says "medical evacuation during international assignment." BM25 hybrid search and multi-query help here.

3. **Exact term/number matching:** Semantic embeddings fail on specific identifiers, thresholds, and codes. Anthropic's example: "Error code TS-999" requires exact matching, not semantic similarity. BM25 solves this.

4. **Lost in the middle:** LLMs pay less attention to information in the middle of the context window. Weaviate identifies this as a common failure mode. Reranking (placing most relevant content first) mitigates this.

5. **Cross-section references:** A chunk saying "as described in Section 4.2" loses meaning without that section. Contextual retrieval (prepending document context) addresses this.

6. **Distribution shift:** Over time, as new documents are added, vector index quality can degrade. Weaviate notes that "vector quantization centroids can degrade with data distribution changes."

7. **Irrelevant context as distractors:** Weaviate: "LLMs struggle with irrelevant context mixed with relevant information." Higher-precision retrieval and reranking reduce the noise-to-signal ratio.

### 5.2 Evaluation Metrics

**Retrieval quality (measure before generation):**
- **Recall@K:** Fraction of all relevant documents that appear in the top K results. Most important metric for RAG because missing a relevant chunk means the LLM cannot use it.
- **Precision@K:** Fraction of top K results that are relevant. Important for minimizing distracting context.
- **MRR (Mean Reciprocal Rank):** Average position of the first relevant result. "Ranges from 0 to 1, where a higher value indicates better performance." Focuses on whether the MOST relevant result appears early.
- **NDCG (Normalized Discounted Cumulative Gain):** Handles graded relevance (not just binary relevant/irrelevant). Normalizes against ideal ranking for fair cross-query comparison.
- Source: [Pinecone RAG Evaluation](https://www.pinecone.io/learn/series/rag/rag-evaluation/)

**Generation quality (measure the final answer):**
- **Faithfulness:** Are all claims in the answer supported by the retrieved context? (Detects hallucinations)
- **Answer Relevance:** Does the answer actually address the question?
- **Context Precision/Recall:** LLM-based evaluation of whether the right context was retrieved
- **RAGAS framework:** Uses four automated evaluators for faithfulness, answer relevancy, context precision, and context recall
- Source: [Weaviate RAG Evaluation](https://weaviate.io/blog/rag-evaluation)

**Recommendation for this project:** Evaluate at both levels:
1. **Retrieval:** Recall@20 (primary), MRR, NDCG@20
2. **Generation:** Faithfulness (primary -- no hallucinations), Answer Relevance
3. Build a ground-truth test set of question-answer pairs with expected source chunks

### 5.3 Late Chunking vs Early Chunking

**Late chunking (Jina Research, 2024):**
- Instead of chunking before embedding, process the **entire document through the transformer first**, then chunk the token representations and pool each chunk separately
- Preserves contextual information from surrounding text that early chunking loses
- Requires a long-context embedding model
- "Works generically across various long-context embedding models"
- "Requires no additional training for basic implementation"
- Source: [Late Chunking Paper](https://arxiv.org/abs/2409.04701)

**Early chunking (standard approach):**
- Chunk first, embed each chunk independently
- Each chunk's embedding has no information about surrounding chunks
- Simpler to implement, works with any embedding model

**Recommendation for this project:** Late chunking is theoretically superior but requires specific model support and adds implementation complexity. **Contextual retrieval achieves a similar benefit** (providing surrounding context for each chunk) through a more portable mechanism. Use contextual retrieval rather than late chunking for now, but revisit if embedding model support improves.

### 5.4 Document-Level Context Windows vs Chunk-Level

**The spectrum:**
1. **Full document in context:** Works for small documents that fit in the LLM context window. No retrieval errors possible, but does not scale.
2. **Chunk-level only:** Standard RAG. Risk of missing relevant chunks.
3. **Hybrid approaches:**
   - **Parent-child:** Retrieve on small chunks, serve parent sections (see 1.6)
   - **Contextual retrieval:** Prepend document context to each chunk (see 4.3)
   - **Document summaries + chunk retrieval:** LlamaIndex recommends "document summaries mapping to underlying chunks for semantic document-level lookups"

**Recommendation for this project:** Given that duty of care policies are typically 10-50 pages (fitting within Claude's context window):
- For **single-document queries**, consider passing the entire document as context alongside the retrieved chunks
- For **multi-document queries** or when documents grow larger, use the full retrieval pipeline
- Always include document summaries as metadata for high-level routing

---

## 6. Recommended Architecture for This Project

Based on all the research above, here is the recommended full pipeline:

### Preprocessing (Indexing Pipeline)

1. **Parse markdown** with structure-aware splitter (respect headers, tables, lists)
2. **Create parent-child hierarchy:**
   - Parent: Full sections (## level), up to 2048 tokens
   - Child: Subsections or paragraphs (### level), 256-512 tokens
3. **Generate contextual descriptions** for each child chunk using Claude (Anthropic's contextual retrieval approach)
4. **Embed** each contextualized child chunk using Voyage AI voyage-4-large (1024 dimensions, input_type="document")
5. **Index** for both dense (vector) and sparse (BM25) retrieval
6. **Store metadata:** section_path, policy_area, parent_chunk_id, document_title

### Query Pipeline

1. **Generate query variants** (2-3 reformulations using the LLM)
2. **Embed queries** using Voyage AI (input_type="query")
3. **Hybrid retrieval:** Dense vector search + BM25 on each query variant
4. **Fuse results** using Reciprocal Rank Fusion (RRF), deduplicate
5. **Retrieve top-150 candidates** from the fused results
6. **Rerank** using Cohere Rerank 4.0 or Voyage rerank-2.5, narrow to top-20
7. **Expand to parent chunks** where multiple children from the same parent are retrieved
8. **Serve to LLM** with most relevant chunks first
9. **Generate answer** with faithfulness constraints

### Evaluation

1. Build ground-truth test set (50-100 question-answer pairs with expected source chunks)
2. Measure Recall@20, MRR, NDCG@20 on retrieval
3. Measure Faithfulness and Answer Relevance on generation
4. Use RAGAS framework for automated evaluation
5. Iterate on chunk sizes, reranker thresholds, and retrieval parameters

---

## Sources

- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) -- The definitive reference for contextual retrieval technique, with specific performance numbers (35%, 49%, 67% failure reduction)
- [Anthropic Engineering: Contextual Retrieval Implementation](https://www.anthropic.com/engineering/contextual-retrieval) -- Implementation details including the exact prompt template
- [Voyage AI: Voyage 3 Large](https://blog.voyageai.com/2025/01/07/voyage-3-large/) -- Benchmark data showing 9.74% improvement over OpenAI
- [Voyage AI: Voyage 3](https://blog.voyageai.com/2024/09/18/voyage-3/) -- Model specifications and domain-level performance
- [Voyage AI: Embeddings Documentation](https://docs.voyageai.com/docs/embeddings) -- input_type parameter details, model specs for Voyage 4 series
- [Voyage AI: Reranker Documentation](https://docs.voyageai.com/docs/reranker) -- Reranker model specifications
- [Chroma: Evaluating Chunking](https://research.trychroma.com/evaluating-chunking) -- Chunk size and overlap research showing 200-token chunks optimal for precision
- [LlamaIndex: Chunk Size Evaluation](https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5) -- 1024 tokens optimal for end-to-end RAG quality
- [LlamaIndex: Auto-Merging Retriever](https://developers.llamaindex.ai/python/examples/retrievers/auto_merging_retriever/) -- Parent-child merging implementation
- [LlamaIndex: Production RAG Optimization](https://developers.llamaindex.ai/python/framework/optimizing/production_rag/) -- Decoupled retrieval/synthesis chunks
- [LlamaIndex: Embedding+Reranker Comparison](https://www.llamaindex.ai/blog/boosting-rag-picking-the-best-embedding-reranker-models-42d079022e83) -- Hit rate and MRR benchmarks
- [Pinecone: Chunking Strategies](https://www.pinecone.io/learn/chunking-strategies/) -- Overview of all chunking approaches
- [Pinecone: Rerankers](https://www.pinecone.io/learn/series/rag/rerankers/) -- Cross-encoder vs bi-encoder comparison
- [Pinecone: RAG Evaluation](https://www.pinecone.io/learn/series/rag/rag-evaluation/) -- Metrics definitions (Recall@K, MRR, NDCG, Precision@K)
- [Weaviate: Hybrid Search Explained](https://weaviate.io/blog/hybrid-search-explained) -- Alpha parameter, fusion algorithms
- [Weaviate: Distance Metrics](https://weaviate.io/blog/distance-metrics-in-vector-search) -- Cosine vs dot product vs L2 comparison
- [Weaviate: RAG Evaluation](https://weaviate.io/blog/rag-evaluation) -- Faithfulness, relevance, context precision metrics, failure modes
- [Qdrant: Hybrid Search](https://qdrant.tech/articles/hybrid-search/) -- RRF as de facto standard, warning against linear combinations
- [Unstructured.io: Chunking Best Practices](https://unstructured.io/blog/chunking-for-rag-best-practices) -- Smart chunking, structure-aware approaches
- [Azure AI Search: Hybrid vs Vector Performance](https://techcommunity.microsoft.com/blog/azure-ai-services-blog/azure-ai-search-outperforming-vector-search-with-hybrid-retrieval-and-ranking-cap/3929167) -- 37% improvement with hybrid + semantic ranking
- [BGE-M3 on HuggingFace](https://huggingface.co/BAAI/bge-m3) -- Multi-functional embedding model specs
- [Jina Embeddings v3](https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/) -- Task-specific adapters, Matryoshka support
- [LangChain Markdown Splitter](https://github.com/langchain-ai/langchain/blob/master/libs/text-splitters/langchain_text_splitters/markdown.py) -- Implementation details for markdown-aware chunking
- [HyDE Paper (Gao et al., 2022)](https://arxiv.org/abs/2212.10496) -- Hypothetical document embedding technique
- [Late Chunking Paper (2024)](https://arxiv.org/abs/2409.04701) -- Late chunking technique for better chunk embeddings
- [Cohere Rerank Documentation](https://docs.cohere.com/v2/docs/rerank-overview) -- Rerank 4.0 specifications
