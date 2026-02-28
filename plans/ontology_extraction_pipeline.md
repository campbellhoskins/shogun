# Ontology Extraction Pipeline — Full Implementation Plan

## Problem Statement

A single-pass LLM extraction of a corporate duty of care policy produces fatally sparse ontology graphs. On a 7-page policy document, the legacy approach extracted only 39 entities and 36 edges across 11 disconnected components, yielding a **43.6% pass rate** on a 101-question evaluation set. The agent frequently reports "graph does not contain information" for questions with known answers because the extraction permanently lost the data.

## Root Cause Analysis

Four failure modes account for all evaluation failures:

| Failure Mode | Share | Description |
|---|---|---|
| **Wholesale section omission** | ~35% | Entire document sections never extracted (definitions, welfare provisions, legal details) |
| **Granular sub-claim loss** | ~25% | Entities extracted but enumerated lists compressed (e.g., 7 measures → 5 captured). LLMs naturally summarize rather than preserve every list item |
| **Agent confabulation** | ~20% | Agent synthesizes plausible-sounding answers from adjacent graph nodes rather than admitting ignorance |
| **Cross-section reasoning failures** | ~20% | Disconnected components make multi-hop queries across sections impossible |

## Solution Architecture

Replace the single-pass extraction with a multi-stage pipeline, delivered in 6 phases. Each phase introduces one capability, is evaluated against the previous baseline, and is tuned before the next phase begins.

### Full Pipeline

```
Document Text
    │
    ▼
[Stage 1: LLM Segment]          → list[DocumentSection]         (1 LLM call)           ◄ Phase 1
    │
    ▼
[Stage 2: Per-Section Extract]   → list[SectionExtraction]       (parallel, 1 LLM/sec)  ◄ Phase 1
    │
    ▼
[Stage 3: Deterministic Merge]   → OntologyGraph                 (no LLM)               ◄ Phase 1
    │
    ▼
[Stage 4: Cross-Section Infer]   → list[Relationship]            (3 targeted LLM passes) ◄ Phase 2
    │
    ▼
[Stage 5: Semantic Dedup]        → OntologyGraph                 (1-2 LLM calls)        ◄ Phase 4
    │
    ▼
[Stage 6: Exhaustive Verify]     → OntologyGraph (enriched)      (per-paragraph, 3 iter) ◄ Phase 5
    │
    ▼
[Stage 7: Consistency Validate]  → OntologyGraph (final)         (2-5 LLM calls)        ◄ Phase 6
```

### Phase Overview

| Phase | What | New Prompts | Primary Failure Mode Addressed | Eval Gate |
|-------|------|-------------|-------------------------------|-----------|
| **1** | LLM Segmenter + Per-Section Extraction + Deterministic Merge | 2 | Section omission, sub-claim loss | 100+ entities, 100+ rels, 90%+ anchored |
| **2** | Cross-Section Inference | 3 | Cross-section reasoning failures | Components ≤3, multi-hop Q pass rate up |
| **3** | Agent Enhancements (source text tools + system prompt) | 0 | Agent confabulation | Exact-wording Q pass rate up |
| **4** | LLM Semantic Deduplication | 1 | (Quality refinement) | Duplicate entities reduced |
| **5** | Exhaustive Verification | 2 | Remaining section omission + sub-claim loss | Previously-failing Qs now pass |
| **6** | Consistency Validation | 2-3 | (Structural polish) | 0 orphans, ≤2 components |

---

## Phase 1: Per-Section Extraction with Source Anchoring

**Status: IMPLEMENTED**

### What It Does

Replaces the single-pass LLM extraction with a three-stage pipeline: LLM segmentation, per-section extraction with source anchoring, and deterministic merge.

### Results

| Metric | Legacy (single-pass) | Phase 1 | Target |
|--------|---------------------|---------|--------|
| Entities | 39 | **249** | 100+ |
| Relationships | 36 | **227** | 100+ |
| Source anchored | 0% | **100%** | 90%+ |
| Verified in document | 0% | **86%** (214/249) | — |
| Sections identified | 1 pass | **34** | — |
| Dedup merges | — | 73 | — |
| Pipeline time | ~60s | ~440s | — |
| API calls | 1 | ~10-35 | — |

### Files Implemented

**New files:**
- `src/segmenter.py` — LLM-based segmentation. Single API call identifies sections, hierarchy, enumerated lists with exact item counts. Character offsets used to slice text from original document. Sections exceeding 2000 chars auto-split at paragraph boundaries.
- `src/extraction.py` — Per-section extraction. Each section gets its own API call with: section text, document outline for context, list-aware density requirements, mandatory source anchoring. Async parallel execution (max 2 concurrent) with exponential backoff retry on rate limits (15s/30s/60s). Zero-entity sections trigger re-extraction with aggressive prompt.
- `src/merge.py` — Deterministic merge. Two-tier deduplication: exact ID match (after stripping section prefix) and exact Name+Type match (normalized). Union-find algorithm clusters duplicates. Source offset computation via normalized text search with `SequenceMatcher` fallback at 0.85 threshold.
- `src/pipeline.py` — Orchestrator. Chains stages 1-3 with progress logging, stage timing, and auto-save to `results/runs/`.
- `src/results.py` — Result storage. Every pipeline run saved with full provenance: `run_meta.json`, `sections.json`, `extractions.json`, `ontology.json`, `entities.json`, `relationships.json`.

**Modified files:**
- `src/models.py` — Added `SourceAnchor`, `DocumentSection`, `EnumeratedList`, `SectionExtraction`, `ExtractionMetadata`. Extended `Entity` with `source_anchor`, `Relationship` with `source_sections`, `OntologyGraph` with `source_sections`, `source_document`, `extraction_metadata`. All backward compatible via defaults.
- `src/parser.py` — `parse_policy()` delegates to `extract_ontology()`. Legacy preserved as `parse_policy_legacy()`.
- `src/graph.py` — `build_graph()` stores `source_text`, `source_section`, `source_offset` as explicit node attributes. Added `get_source_text()` and `get_section_text()` utilities. Source document and sections stored on `g.graph`.
- `src/main.py` — Pipeline metadata logging. `load_document()` unchanged.
- `src/validate.py` — Added `source_anchoring_report()`.
- `src/visualizer.py` — Source text shown in node tooltips.

### Key Design Decisions

1. **LLM segmentation over regex** — Corporate policy documents vary too much in format. The LLM handles markdown, numbered sections, no-header documents, and everything in between.
2. **Source anchoring is mandatory** — Every entity carries the exact verbatim quote it was extracted from. This enables later phases (agent source text tools, verification) and makes the extraction auditable.
3. **Entity IDs prefixed with section number** — `s2_1_risk_level_standard` prevents collisions across sections and makes dedup traceable.
4. **Parallel extraction with rate limit handling** — Async with semaphore (max 2 concurrent) plus exponential backoff. Handles 429 errors gracefully.
5. **Deterministic merge only in Phase 1** — No LLM-based semantic dedup yet. Keeps this phase to exactly 2 prompts so each can be evaluated and tuned independently.

---

## Phase 2: Cross-Section Inference

**Status: NOT STARTED**

### What It Does

After all sections are extracted independently, this phase identifies relationships BETWEEN entities from different sections. The current Phase 1 output has only intra-section relationships, leaving the graph as multiple disconnected components.

### Design

Three targeted LLM passes instead of one monolithic call:

1. **Role-centric pass** — For each `Role` entity, find all `PolicyRule`, `Procedure`, `ApprovalRequirement` entities across other sections that mention or apply to that role. Produces `managed_by`, `applies_to`, `escalates_to` relationships.

2. **Definition-to-application pass** — For each `Definition` entity, find all `PolicyRule`, `Procedure` entities across other sections that reference that defined term. Produces `references`, `implements` relationships.

3. **Risk-level cohesion pass** — For each `RiskLevel` or `Threshold` entity, collect all `InsuranceRequirement`, `ApprovalRequirement`, `CommunicationRequirement`, `Procedure` entities that reference it. Produces `requires`, `applies_to`, `classified_as` relationships.

Each pass receives a focused subset of entities (one category + all potential targets from other sections), not the full entity list. This produces more reliable results than a single unfocused call.

### Files to Create/Modify

- **New:** `src/cross_section.py` — `infer_cross_section_relationships(section_extractions, client) -> list[Relationship]`
- **Modify:** `src/pipeline.py` — Add Stage 4 after merge
- **Modify:** `src/results.py` — Add `cross_section.json` to run output

### Eval Gate

- Connected components: ≤3 (down from 10+)
- Multi-hop questions in eval set show improved pass rate
- No regression on single-section questions

### Token Budget

3 API calls, ~$0.08 estimated.

---

## Phase 3: Agent Enhancements

**Status: NOT STARTED**

### What It Does

Gives the agent access to original source text and strengthens its behavioral directives. No new extraction prompts — this phase is purely about improving how the agent uses the graph that already exists.

### Design

**Three new agent tools:**

1. **`get_source_text(entity_id)`** — Returns the exact verbatim quote from the original policy that an entity was extracted from. Already implemented in `src/graph.py` but not yet exposed as an agent tool.

2. **`get_section_text(section_number)`** — Returns the full text of a document section. Already implemented in `src/graph.py` but not yet exposed as an agent tool.

3. **`search_source_text(keyword)`** — Substring search over all entities' `source_text` node attributes. Directly fixes the "not in graph" false negative pattern where `search_entities` misses because entity names don't match the query keywords but the source text does. Pure graph traversal, no LLM call.

**Updated agent system prompt with stronger behavioral directives:**
- For questions asking "what does X mean", "what specific items are listed", or containing "exact"/"specific" — ALWAYS call `get_source_text` before answering.
- Before providing a final answer, verify completeness by checking 2-3 related entities via `get_neighbors`.
- If initial search returns no results, try at least 2 alternative keyword searches AND `search_source_text` before concluding information is not in the graph.
- Do not synthesize answers from adjacent entities when the specific information is not present.

### Files to Modify

- `src/agent.py` — Add 3 tool definitions to `TOOLS`, add handlers in `_execute_tool()`, update `SYSTEM_PROMPT`

### Eval Gate

- Exact-wording questions show improved pass rate
- "Not in graph" false negatives reduced
- No increase in hallucination rate

### Token Budget

Zero additional API calls for extraction. Agent tool calls are the same per-query cost as before.

---

## Phase 4: LLM Semantic Deduplication

**Status: NOT STARTED**

### What It Does

Replaces the Phase 1 deterministic dedup with an LLM-assisted semantic dedup pass. Handles cross-section synonyms that string matching cannot catch (e.g., "duty holder" vs "responsible person", or `s2_personnel_def` vs `s6_personnel_scope`).

### Design

After the deterministic dedup tiers (exact ID match, exact Name+Type match), send all remaining entities grouped by type to the LLM:

> "Which of these entities refer to the same real-world concept? Group duplicates and identify the canonical entity for each group."

1-2 API calls. Only needed when multiple entities of the same type remain after deterministic dedup.

### Files to Modify

- `src/merge.py` — Add `_semantic_deduplicate()` function, integrate after deterministic tiers
- `src/results.py` — Add `dedup_decisions.json` to run output (which entities were merged and why)

### Eval Gate

- Duplicate entity count reduced
- No information loss (merged entities retain all attributes and source anchors)
- Pass rate does not decrease

### Token Budget

1-2 API calls, ~$0.04 estimated.

---

## Phase 5: Exhaustive Verification

**Status: NOT STARTED**

### What It Does

Goes paragraph-by-paragraph through the entire source document, checking whether every factual claim is represented in the graph. Any gaps trigger additional extraction. This is the safety net that catches everything the per-section extraction missed.

### Design

**Verification loop (max 3 iterations):**

1. **Gap-finding:** Process paragraphs individually or in groups of 2-3. For each paragraph, send the paragraph text + full entity details including attributes (not just name/description summaries). Ask the LLM to:
   - First extract all factual claims in the paragraph as a numbered list
   - Then check each claim individually against the graph entities
   - Report any claims not covered, with a unique `gap_id`

2. **Gap-filling:** For each paragraph with gaps, send a targeted extraction prompt with:
   - The paragraph text and specific missing claims
   - Full existing entity list (for relationship creation)
   - Instruction: extract only what's missing
   - Post-fill lightweight dedup against existing graph

3. **Convergence conditions:**
   - No gaps found → complete coverage achieved
   - Max iterations reached (default 3)
   - Gap ID tracking: if same gap persists across 2 consecutive iterations, mark as "acknowledged" and exclude from future iterations. Stop if gap reduction rate < 20% from previous iteration.

### Files to Create/Modify

- **New:** `src/verifier.py` — `verify_coverage(ontology, client, max_iterations=3) -> OntologyGraph`
- **New model:** `VerificationGap(BaseModel)` — `paragraph_text`, `paragraph_offset`, `gap_id`, `missing_claims`, `iteration_first_seen`
- **Modify:** `src/pipeline.py` — Add Stage 6 after semantic dedup
- **Modify:** `src/results.py` — Add `verification.json` to run output (gaps found, filled, acknowledged per iteration)

### Eval Gate

- Previously-failing questions now pass
- Gap count decreases across iterations
- No increase in hallucination

### Token Budget

12-27 API calls (3 iterations x per-paragraph gap finding + gap filling), ~$0.45 estimated.

---

## Phase 6: Consistency Validation

**Status: NOT STARTED**

### What It Does

Structural cleanup and quality enforcement. Fixes orphan nodes, bridges disconnected components, removes dangling references, and validates source anchoring integrity.

### Design

**Checks (with auto-fix):**

1. **Orphan nodes** — Entities with zero relationships. LLM call: "What relationship should this entity have to existing entities?"

2. **Disconnected components** — If > 2 components remain, LLM generates bridge relationships: "These two groups of entities are disconnected. Identify at least one relationship that should connect them."

3. **Dangling references** — Relationships pointing to nonexistent entity IDs. Deterministic removal.

4. **Source anchor validation** — Verify each entity's `source_text` appears in the source document using normalized search + `SequenceMatcher` with 0.85 threshold. Flag unverified entities.

5. **Minimum density thresholds** — ≥10 entities per page, ≥1.5 relationships per entity, ≤5% orphan nodes, ≤2 connected components.

**Contradiction detection** — LLM reviews all relationships for logical contradictions (e.g., Entity A "permits" something that Entity B "prohibits" in the same context without a conditional).

### Files to Create/Modify

- **New:** `src/consistency.py` — `validate_consistency(ontology, client, auto_fix=True) -> tuple[OntologyGraph, list[str]]`
- **Modify:** `src/pipeline.py` — Add Stage 7 as final stage
- **Modify:** `src/results.py` — Add `consistency.json` to run output (issues found, fixes applied)

### Eval Gate

- 0 orphan nodes
- ≤2 connected components
- All source anchors verified or flagged
- Density thresholds met

### Token Budget

2-5 API calls, ~$0.07 estimated.

---

## Cumulative Token Budget (all phases, 7-page policy)

| Phase | API Calls | Est. Cost |
|-------|-----------|-----------|
| 1: Segmentation + Extraction + Merge | 10-35 | ~$0.33 |
| 2: Cross-Section Inference | 3 | ~$0.08 |
| 3: Agent Enhancements | 0 | $0.00 |
| 4: Semantic Dedup | 1-2 | ~$0.04 |
| 5: Exhaustive Verification | 12-27 | ~$0.45 |
| 6: Consistency Validation | 2-5 | ~$0.07 |
| **Total** | **~30-72** | **~$0.97** |

~8x the legacy single-pass cost ($0.12). Per project principles: accuracy over cost.

---

## Target Outcomes

| Metric | Legacy | Phase 1 (achieved) | All Phases (target) |
|--------|--------|--------------------|--------------------|
| Entities | 39 | 249 | 150-300 (post-dedup) |
| Relationships | 36 | 227 | 300+ (with cross-section) |
| Connected components | 11 | TBD | 1-2 |
| Orphan nodes | 5+ | TBD | 0 |
| Source anchored | 0% | 100% | 95%+ |
| Eval pass rate | 43.6% | TBD | 75%+ |
| Avg eval score | 3.08/6 | TBD | 4.5+/6 |
