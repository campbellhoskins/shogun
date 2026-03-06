# Deep Comparative Analysis: LangChain LLMGraphTransformer vs. Shogun Pipeline

## Context

This document compares two approaches to LLM-based knowledge graph extraction:

1. **LangChain's LLMGraphTransformer** — a general-purpose, single-pass extraction framework from `langchain-experimental`
2. **Shogun's Source-Anchored Extraction Pipeline** — a domain-specific, four-stage pipeline built for travel compliance documents

---

## 1. LangChain LLMGraphTransformer: How It Works

### Architecture: Single-Pass, Per-Chunk Extraction

```
Documents → Chunking (external) → LLM call per chunk → GraphDocument per chunk → Neo4j
```

Each text chunk gets one LLM call. The LLM extracts nodes and relationships. Output is a `GraphDocument` containing `Node[]` and `Relationship[]`. These get bulk-imported into Neo4j.

### Two Extraction Modes

| | Tool-Based (Default) | Prompt-Based (Fallback) |
|---|---|---|
| **Mechanism** | LLM function calling / `with_structured_output()` | JSON in prompt with few-shot examples |
| **Output format** | Pydantic models validated by LLM | Raw JSON parsed with `json_repair` |
| **Properties** | Supports node/relationship properties | No property extraction |
| **Isolated nodes** | Supported | Not supported |
| **Model requirement** | OpenAI, Mistral, etc. with function calling | Any LLM |

### Schema Handling

**Schema-free mode:** No `allowed_nodes` or `allowed_relationships` specified. The LLM decides entity and relationship types at runtime. The same concept may get different type labels in different chunks.

**Schema-guided mode:** User provides:
- `allowed_nodes: List[str]` — e.g., `["Person", "Organization", "Policy"]`
- `allowed_relationships: List[str]` or `List[Tuple[str,str,str]]` — e.g., `["WORKS_FOR"]` or `[("Person", "WORKS_FOR", "Organization")]`
- `node_properties: bool | List[str]` / `relationship_properties: bool | List[str]`

Schema constraints are enforced via:
1. Enum fields in the Pydantic model (for OpenAI models)
2. Prompt injection of allowed types (for non-OpenAI)
3. Strict-mode post-filtering that removes non-compliant nodes/relationships

### Prompt Design

The system prompt is generic and brief (~500 words):
- "You are a top-tier algorithm designed for extracting information in structured formats"
- Emphasizes **elementary entity types** ("Person" not "Mathematician")
- Emphasizes **general relationship types** ("PROFESSOR" not "BECAME_PROFESSOR")
- Coreference resolution: use most complete identifier
- Human-readable node IDs

### Normalization & Deduplication

Minimal:
- `_format_nodes()`: Title-cases IDs, capitalizes types
- `_format_relationships()`: Converts to `UPPER_CASE_WITH_UNDERSCORES`
- Node dedup: set-based `(id, type)` tracking **within a single chunk only**
- **No cross-chunk deduplication** — "Marie Curie" in chunk 1 and "Curie" in chunk 3 produce separate nodes
- Dedup is expected to happen downstream in Neo4j via entity resolution queries

### Source Provenance

Each `GraphDocument` retains a reference to its source `Document` object, but:
- No character-level offset tracking
- No verbatim source text anchoring per entity
- No verification that extracted entities actually appear in the source

### Async & Parallelism

`aconvert_to_graph_documents()` uses `asyncio.gather()` to process all chunks in parallel with **no concurrency limiting**.

---

## 2. Shogun Pipeline: How It Works

### Architecture: Four-Stage Sequential Pipeline

```
PDF → Parser → Markdown
                  ↓
            [Stage 0] First Pass    → Global document analysis (1 LLM call, extended thinking)
                  ↓
            [Stage 1] Segmenter    → Deterministic chunking (0 LLM calls)
                  ↓
            [Stage 2] Extraction   → Per-section extraction (N parallel LLM calls)
                  ↓
            [Stage 3] Merge        → LLM-based semantic dedup (M LLM calls) + deterministic offset verification
                  ↓
            OntologyGraph (saved to results/)
```

### Stage 0: First Pass (1 LLM call over full document)

Single streaming call with extended thinking (`budget_tokens: 32768`) analyzes the entire document to produce:

1. **Document map** — section inventory with `beginning_text` anchors for deterministic location, plus document-level metadata (title, org, date, purpose)
2. **Global entity pre-registration** — canonical names for entities appearing in 2+ sections, with `candidate_types` and `mentioned_in_sections`
3. **Cross-section dependencies** — `{primary_section_id, dependent_section_id, dependency_type, description}` tuples identifying which sections modify/reference/override others

This output flows downstream into both Stage 1 (section boundary detection) and Stage 2 (context injection per extraction call).

### Stage 1: Segmenter (0 LLM calls — fully deterministic)

No LLM involved. Uses `beginning_text` from Stage 0 to locate section boundaries via a cascading text-match strategy:

1. Exact substring match
2. Normalized match (whitespace/case collapsed)
3. Token-prefix match
4. Heading fallback search

Derives hierarchy from section IDs (`SEC-01`, `SEC-02a`, `SEC-02a1` → parent-child). Detects enumerated lists via regex. Computes character offsets for each section boundary.

### Stage 2: Extraction (N parallel LLM calls)

Per-section extraction with `asyncio.gather()` + semaphore-based concurrency control (default: 2 concurrent). Each call receives rich context injection:

- **Document metadata** from Stage 0 (title, org, date, purpose)
- **Section metadata** (ID, purpose, summary, hierarchy)
- **Filtered global entity pre-registration** — only entities whose `mentioned_in_sections` includes the current section
- The section text itself

The extraction prompt is ~3000+ words with domain-specific instructions:
- "Entities are things, relationships are assertions"
- "List members must be individual nodes" (no collapsing into arrays)
- Entity bloat avoidance rules (when NOT to create PolicyRule entities)
- Mandatory source anchoring (`source_text` must be exact verbatim quote)
- Chain-of-thought via `<extraction_analysis>` tags (stripped before JSON parse)

**Typed schema:** 21 entity classes with domain-specific attributes (e.g., `TravelerRoleEntity` has `receipt_requirement_threshold`, `expense_report_deadline_days`). 34 valid relationship types with source/target type constraints. All defined in `src/schemas.py` with Pydantic models using `Literal` type discriminators.

**Retry logic:** Zero-entity results on sections >100 chars trigger automatic retry with aggressive prompt.

### Stage 3: Merge (M LLM calls for dedup + deterministic post-processing)

Groups entities by type. For each group with 2+ entities, makes an LLM call (with extended thinking) for semantic deduplication:

- "Redundant node with relationship ALWAYS preferable to lost query path"
- "When in doubt: DO NOT MERGE"
- Can discover new relationships during dedup (`equivalent_to`, `part_of`)
- Self-verification checklist in prompt

Post-dedup deterministic operations:
- All relationship source/target IDs remapped via accumulated `id_mapping` dict
- Relationship deduplication (same source + target + type)
- Orphaned relationship removal
- Source offset computation against original document via 3-tier matching: exact → normalized → fuzzy (SequenceMatcher, threshold 0.85)

---

## 3. Comparative Analysis

### A. Design Philosophy

| Dimension | LangChain | Shogun |
|-----------|-----------|--------|
| **Goal** | General-purpose graph extraction for any domain | Domain-specific extraction for compliance documents |
| **Optimization target** | Simplicity, broad applicability | Accuracy, completeness, traceability |
| **Schema approach** | Optional constraint (user-provided string lists) | Mandatory typed schema (21 Pydantic entity classes with domain attributes) |
| **Error tolerance** | Errors expected, cleaned up downstream | Errors caught at extraction time via retries, validation, verification |
| **Token efficiency** | Minimal (1 call per chunk) | Expensive (4+ stages, 1 + N + M LLM calls) |

### B. Chunking Strategy

| | LangChain | Shogun |
|---|---|---|
| **Who chunks** | External (user's responsibility) | Pipeline Stage 1 (deterministic, guided by Stage 0) |
| **Chunk boundaries** | Token-count based (e.g., 512 tokens, 24 overlap) | Semantic/structural (section boundaries from document analysis) |
| **Context awareness** | None — chunks are arbitrary windows | Full — each chunk is a coherent document section with hierarchy |
| **Cross-chunk context** | None | Stage 0 provides global entity names + cross-section dependencies |

**Key insight:** LangChain's arbitrary chunking means an entity definition might be split across two chunks, or a chunk boundary might fall mid-sentence. Shogun's document-aware chunking ensures each chunk is a complete semantic unit.

### C. Entity/Relationship Modeling

| | LangChain | Shogun |
|---|---|---|
| **Entity types** | Generic strings ("Person", "Organization") | 21 domain-specific typed classes with attributes |
| **Type system** | Flat list of allowed strings | Hierarchical Pydantic models (`BaseEntitySchema` → `PolicyEntity`, `TravelerRoleEntity`, etc.) with discriminated unions |
| **Attributes** | Generic key-value properties | Typed fields per entity class (e.g., `nightly_rate_limit: str`, `is_restricted: bool`) |
| **Relationship types** | Generic strings or source-rel-target tuples | 34 domain-specific types with source/target type constraints |
| **Validation** | Post-hoc strict-mode filtering | Schema validation + relationship constraint checking at extraction time |

### D. Cross-Chunk Consistency

| | LangChain | Shogun |
|---|---|---|
| **Entity naming** | No coordination — same entity may get different names/types across chunks | Stage 0 pre-registers canonical names; Stage 2 MUST use them |
| **Cross-chunk relationships** | Not supported (each chunk is independent) | Stage 0 identifies cross-section dependencies; Stage 3 discovers relationships during dedup |
| **Deduplication** | Within-chunk only (set-based ID+type) | LLM-based semantic dedup across all sections per entity type |

**This is the biggest architectural difference.** LangChain treats each chunk as an isolated extraction unit. The same entity appearing in chunks 3, 7, and 12 produces three separate nodes with potentially different names, types, and IDs. Resolution happens externally (e.g., Neo4j entity resolution queries). Shogun's three-layer approach (pre-registration → per-section extraction → semantic dedup) directly addresses this.

### E. Source Provenance & Traceability

| | LangChain | Shogun |
|---|---|---|
| **Source linking** | `GraphDocument` → source `Document` reference | Per-entity `SourceAnchor` with exact verbatim quote |
| **Character offsets** | None | Computed via 3-tier fuzzy matching (exact → normalized → SequenceMatcher) |
| **Hallucination detection** | None | `source_offset = -1` flags potentially hallucinated entities |
| **Auditability** | "This came from document X" | "This came from characters 1234-1298 of the source, exact quote: '...'" |

### F. Quality Assurance

| | LangChain | Shogun |
|---|---|---|
| **Extraction retries** | None | Zero-entity sections retry with aggressive prompt |
| **Output validation** | Strict-mode type filtering | Schema validation + relationship constraint checking + source offset verification |
| **Dedup quality** | None (deferred to storage layer) | LLM dedup with self-verification checklist |
| **Pipeline resilience** | Fails on malformed JSON (with `json_repair` fallback) | Graceful degradation per section (failed sections don't block pipeline) |

### G. Cost & Performance

| | LangChain | Shogun |
|---|---|---|
| **LLM calls** | N (one per chunk) | 1 (first pass) + N (extraction) + M (dedup groups) |
| **Token cost per call** | Low (short generic prompt) | High (long domain-specific prompts with context injection + extended thinking) |
| **Total cost** | Low | 3-5x higher |
| **Latency** | Fast (fully parallel, no concurrency limit) | Slower (sequential stages; Stage 2 parallel but semaphore-limited to 2 concurrent) |
| **Suitable for** | Exploratory analysis, prototyping, high-volume low-stakes | High-stakes compliance documents where errors have consequences |

---

## 4. When Each Approach Wins

**LangChain LLMGraphTransformer is better when:**
- You need a quick graph from arbitrary documents across many domains
- Schema is unknown or evolving (exploratory/prototyping)
- You have a downstream graph database (Neo4j) with entity resolution capabilities
- Token cost matters more than extraction quality
- Documents are short or don't have complex cross-reference structures

**Shogun Pipeline is better when:**
- Documents are long, structured compliance/policy documents with cross-references
- Accuracy and completeness are non-negotiable (enterprise compliance use case)
- You need audit trails — every extracted fact must be traceable to source text
- Domain schema is known and entity types have meaningful typed attributes
- Cross-section consistency matters (same entity must have same name everywhere)
- You need to detect hallucinated extractions

---

## 5. The Fundamental Difference

LangChain is a **generic extraction tool** — it does one thing (chunk → LLM → graph) and does it broadly. Shogun is a **domain-specific extraction pipeline** — it uses document understanding (Stage 0), structural chunking (Stage 1), context-enriched extraction (Stage 2), and intelligent deduplication (Stage 3) to produce a higher-fidelity graph at higher cost.

The trade-off is clear: LangChain optimizes for **breadth and speed** (any document, any domain, minimal setup), while Shogun optimizes for **depth and correctness** (specific document types, rich schema, source-anchored provenance). For the travel compliance use case — where a missed policy rule or a hallucinated constraint could have real operational consequences — the Shogun approach is the appropriate engineering choice.

---

## 6. Shogun's Single-Pass Problem and Lessons from LangChain

### The Problem: Cognitive Overload in Stage 2

Shogun's Stage 2 extraction asks the model to do three cognitively expensive things **in a single LLM call**:

1. **Find entities** — scan the section text, identify every extractable concept
2. **Type and schema-validate each entity** — choose from 21 typed Pydantic schemas, each with different domain-specific attributes
3. **Find relationships between those entities** — choose from 34 relationship types with source/target type constraints, referencing entities **by the exact IDs it just generated**

The rendered prompt (without section text) is **21,218 characters**, of which **64% is schema definition** (entity types, relationship types, structural instructions, examples). The actual section text — the content being extracted — is a minority of what the model reads.

### The Evidence: 29% Dangling Relationship Rate

From `data/test_extraction.json` (a recent schema-compliant run):

- 168 total relationships across 16 sections
- **49 dangling relationships** (29%) — source_id or target_id references an entity that doesn't exist
- 44 of those are genuine hallucinations (the model invented IDs for entities it never extracted)
- 5 are cross-section references (entity exists in a different section)

The dominant pattern: the model creates `APPLIES_TO_ROLE` relationships pointing to `board_of_directors`, `site_visitor`, `contractors` — roles it *understands* from the text but *didn't extract as entity nodes*. It's referencing its comprehension of the document, not its own output.

The merge stage's orphan filter catches all of these — the final ontology has 0 dangling relationships. But every pruned relationship is a **lost query path** that should have existed in the graph.

### Why LangChain Doesn't Have This Problem (As Badly)

LangChain also extracts entities and relationships in a single pass. But:

- **~500 word prompt** vs Shogun's ~21,000 character prompt
- **Flat string labels** ("Person", "Organization") vs 21 typed Pydantic schemas with domain attributes
- **No typed attribute extraction** per entity (just `id`, `type`, optional generic properties)
- **No source/target type constraints** on relationships

The cognitive load per extraction call is dramatically lower. The model isn't simultaneously discriminating 21 entity schemas, filling typed attribute fields, AND constructing a referentially consistent relationship graph.

### Design Decisions Worth Adopting

#### 1. Split Entity Extraction from Relationship Extraction (Two-Pass)

The single highest-impact change. Instead of one call that does entities+relationships:

- **Pass 1 (Entity-only):** Extract all entity nodes with their typed schemas and attributes. The model focuses entirely on "what things exist in this text?"
- **Pass 2 (Relationship-only):** Receive the **already-extracted entities** as input. Extract relationships that connect them. The model can only reference entities that exist — hallucinated IDs become structurally impossible.

This doubles the LLM calls per section but eliminates the 29% dangling relationship class entirely. It mirrors Shogun's own multi-stage philosophy (Stage 0 informs Stage 1 informs Stage 2) — the extraction stage just hasn't applied that principle *within itself* yet.

#### 2. Flatten the Entity Type System

LangChain uses elementary, generic types ("Person" not "Mathematician"). Shogun has 21 highly specialized types where the boundary between, say, `Requirement` and `Constraint` is blurry and domain-expert-level.

Options:
- **Reduce to 8-12 core types** by merging semantically adjacent types (e.g., `Constraint` + `Requirement` → `PolicyConstraint`; `ExpenseCategory` + `ReimbursementLimit` → `FinancialRule`)
- **Move attribute specificity to post-processing** — extract with simpler types first, then a targeted enrichment pass adds the domain-specific attributes. This separates "what is this entity?" from "what are its detailed properties?"

#### 3. Reduce Relationship Type Count or Use Hierarchical Selection

34 relationship types with source/target constraints is a large decision space. LangChain just uses generic strings.

Options:
- **Tier the relationship types** — present a core set of ~10-12 most common types in the prompt, with the full 34 available only if the model signals it needs a specialized type
- **Derive relationships from entity proximity and co-occurrence** — instead of asking the model to name relationships, let it assert "these two entities are connected" and infer the relationship type from their entity types and the source text

#### 4. Post-Hoc Referential Validation (Not Just Orphan Pruning)

Currently, dangling relationships are silently discarded at merge time. Instead:
- **Validate at extraction time** — after parsing the JSON response, check that every `source_id` and `target_id` exists in the extracted entity set
- **Auto-repair** — if the target ID looks like a plausible entity that should have been extracted (e.g., `board_of_directors` clearly refers to a role), automatically create the missing entity node rather than discarding the relationship
- **Feedback loop** — if dangling rate exceeds a threshold, re-run extraction with the dangling IDs flagged ("you referenced these entities but didn't extract them — either extract them or remove the relationships")

#### 5. Schema-Free First, Schema-Guided Second (LangChain's Exploration Pattern)

LangChain's schema-free mode is useful for discovery. Shogun could adopt this as a pre-step:
- Run a schema-free extraction first to discover what the model *naturally* identifies
- Then run a schema-guided pass that maps the free-form results to the typed schema
- This avoids the problem of the model trying to force-fit text into 21 predetermined types while simultaneously doing relationship extraction

### Summary: The Core Lesson

LangChain succeeds at single-pass extraction because it keeps each call **cognitively simple**. Shogun's domain-specific schema is more valuable for downstream reasoning, but the current architecture pays for that value by cramming too much into a single extraction call. The fix isn't to abandon the rich schema — it's to **decompose the extraction** the same way Shogun already decomposes the pipeline. Extract entities first, relationships second. Type simply first, enrich second. The multi-stage philosophy that makes Stages 0→1→2→3 work should extend into Stage 2 itself.
