# Ontology Graph Improvement Plan: Document-Structure → Operational Knowledge Graph

## Context

The current pipeline produces graphs that function as contractual reference maps (~30-40% operational effectiveness). The graph for the Direct Travel duty of care document contains 108 entities and 116 relationships, but:
- ~75% of relationships are structural (DEFINED_IN, PARTY_TO, INCORPORATES) rather than operational
- All 4 severity levels are collapsed into a single entity, making level-specific traversal impossible
- Typed attribute fields in `src/schemas.py` exist but are **never populated** — the extraction prompt uses `generate_entity_type_prompt_section_slim()` which omits typed attributes
- Entity descriptions contain operational data (SLO timing, escalation conditions) in unstructured text instead of queryable attribute fields
- No procedural sequencing (welfare check outreach order, escalation chains)
- No conditional logic modeled (Corporate Security only for security incidents at Level 3+)

**Goal:** Transform the graph from "what does the policy say?" to "what do I do when X happens?" — enabling TMC agents to make real-time decisions during travel incidents via structured graph traversal.

---

## Phase 0: Merge Pipeline Hardening (BLOCKER — must land first)

> **Why first:** Deploying richer extraction (Phase 1) without fixing the merge pipeline produces WORSE results. Schema violations from attribute conflicts and entity re-collapse during dedup destroy the richer data before it reaches the graph.

### Step 0.1: Primary-source-wins attribute conflict resolution
**File:** `src/merge.py`, function `_merge_entity_group()` (~line 180-194)

**Problem:** When the same entity is extracted from multiple sections with different wording for the same typed attribute (e.g., "within 60 minutes" vs "60 minutes"), the merge stores all values as a list, violating Pydantic schema types (`str` field receives `list[str]`).

**Fix:** When multiple sections produce different string values for the same typed attribute, concatenate all unique values with semicolons (e.g., `"within 60 minutes; initiate Traveler outreach within 60 minutes"`). This preserves every extraction's contribution while keeping the field as a valid `str` — no list, no schema violation, no data loss.

### Step 0.2: Anti-merge rules in semantic dedup prompt
**File:** `src/merge.py`, constant `SEMANTIC_DEDUP_SYSTEM_PROMPT` (~line 66-108)

**Problem:** Four separate severity level entities get re-collapsed into one during semantic dedup because they share the same type and similar descriptions.

**Fix:** Add `<critical_anti_merge_rules>` to the dedup prompt:
- Numbered/leveled entities are NEVER duplicates (severity_level_1 through severity_level_4)
- Channel-specific entities are NEVER duplicates (alert_level_3_sms vs alert_level_3_email)
- Entities with different typed attribute values are NOT duplicates regardless of name similarity

### Step 0.3: Include typed attributes in dedup input + truncate descriptions
**File:** `src/merge.py`, function `_build_entities_block()` (~line 381-399)

**Fix:** Truncate descriptions to ~200 chars in dedup input. Cap concatenated descriptions in `_merge_entity_group()` to prevent bloat (keep primary description + "[Referenced in N additional section(s)]").

### Verification
- Create test entities with conflicting attribute values → verify merge outputs valid single-value attributes
- Run full pipeline → verify zero Pydantic validation errors on merged entities
- Feed four severity level entities into dedup → verify all four survive

---

## Phase 1: Schema Extensions + Extraction Prompt Upgrades

### Step 1.1: Add typed attributes to four entity schemas
**File:** `src/schemas.py`

| Entity Type | New Attributes |
|-------------|---------------|
| `TravelerResponseStatusEntity` | `tmc_action`, `action_time_target`, `closes_outreach`, `triggers_escalation` |
| `ContactRoleEntity` | `escalation_severity_levels`, `escalation_condition`, `roster_position` |
| `ServiceEntity` | `activation_severity_threshold`, `requires_client_authorization`, `authorization_details` |
| `AlertEntity` | `severity_level`, `channel_priority_order` |

These fields already have natural homes in the existing schemas. No new entity types needed.

### Step 1.2: Switch entity extraction to full schema-aware prompt
**File:** `src/extraction.py`, function `_build_entity_prompt()` (~line 325)

**The single highest-impact change:** Replace `generate_entity_type_prompt_section_slim()` with `generate_entity_type_prompt_section()`. This exposes all typed attribute fields to the LLM during extraction, bridging the gap between schema definitions and LLM extraction behavior.

### Step 1.3: Add decomposition rules to entity extraction prompt
**File:** `src/extraction.py`, constant `ENTITY_SYSTEM_PROMPT` (after `</entity_model>`, before `<entity_types>`)
USE exact html tags from improvement-plan.md
Add `<decomposition_rules>` instructing:
- Create SEPARATE entity for EACH severity level (1-4)
- Extract EACH alert template as separate entity per severity level + channel
- Extract EACH traveler response status with action/timing attributes populated
- Extract EACH contact role with escalation levels and conditions populated

### Step 1.4: Add attribute quality + grounding instructions
**File:** `src/extraction.py`, constant `ENTITY_SYSTEM_PROMPT`

Add `<attribute_quality>` — mandate attribute population when section text provides values. Add `<attribute_grounding>` — only populate attributes from current section text (prevents hallucination from context).

### Step 1.5: Update output schema to include typed attributes
**File:** `src/extraction.py`, `<output_schema>` section in `ENTITY_SYSTEM_PROMPT`

Add: "All typed attributes defined for the entity's type. Populate every attribute for which the section text provides a value."

### Step 1.6: Add operational prioritization to relationship extraction
**File:** `src/extraction.py`, constant `RELATIONSHIP_SYSTEM_PROMPT`

Add `<operational_priority>` section ranking relationship types:
1. **HIGHEST** — ACTIVATED_AT, ESCALATED_TO, TRIGGERS_ACTION, REQUIRES_AUTHORIZATION_FROM
2. **HIGH** — PROVIDES, ENABLED_BY, ENABLES_COVERAGE, RESPONDS_WITH
3. **MEDIUM** — CLASSIFIED_AS, CATEGORIZED_AS, IMPACTS
4. **LOWER** — DEFINED_IN, PARTY_TO, INCORPORATES, COMPLIES_WITH

### Step 1.7: Add operational graph purpose to extraction prompts
**File:** `src/extraction.py`, both `ENTITY_SYSTEM_PROMPT` and `RELATIONSHIP_SYSTEM_PROMPT`

Add `<graph_purpose>` explaining this graph serves TMC agents during live incident response. Prioritize extracting entities/relationships that support real-time decisions over document-structural facts.

### Step 1.8: Update pre-registration for decomposed entities
**File:** `src/first_pass.py`, `FIRST_PASS_USER_PROMPT`

Add guidance to pre-register each severity level, each alert template per level+channel, each response status, and each contact role as separate entities with consistent naming patterns.

### Verification
- Run full pipeline on `data/231123_Duty_of_Care_Policy.pdf`
- Check `ontology.json` for:
  - 4 separate `SeverityLevel` entities (not 1 collapsed)
  - `alert_time_target` populated on severity entities
  - `escalation_severity_levels` populated on ContactRole entities
  - Operational relationships >= 40% of total (up from ~25%)
- Run `uv run python -m src.eval` to verify agent answer quality improves

---

## Phase 2: Agent Capability Upgrades

### Step 2.1: Add `get_typed_attributes` tool
**File:** `src/agent.py`

New tool that returns only typed attributes (excluding base fields) for a given entity. Enables the agent to quickly look up SLO targets, severity levels, escalation conditions without parsing descriptions.

### Step 2.2: Add `find_by_attribute` tool
**File:** `src/agent.py`

New tool to find entities by attribute value (e.g., "find all ContactRoles where escalation_severity_levels includes 3"). Enables direct operational lookups.

### Step 2.3: Update agent system prompt for operational queries
**File:** `src/agent.py`, constant `SYSTEM_PROMPT`

Add guidance for operational query patterns:
1. Search for SeverityLevel entity first → read typed attributes
2. Follow ACTIVATED_AT edges → find activated services
3. Follow ESCALATED_TO edges → find escalation contacts
4. Use `get_typed_attributes` for SLO targets

### Verification
- Run `uv run python -m src.test_agent` with operational questions:
  - "Level 3 security incident — what are my timing obligations?"
  - "Traveler replied NEED ASSISTANCE — what do I do?"
  - "Who gets escalated at Level 4?"
- Verify agent uses typed attributes directly instead of parsing descriptions

---

## Phase 3: Procedural & Conditional Logic Extraction

### Step 3.1: Add new relationship types
**File:** `src/schemas.py`

- `FOLLOWED_BY` — procedural sequencing (SMS → Email → Push → Voice in outreach)
- `CONDITIONAL_ON` — conditional activation (Corporate Security ← security incidents at Level 3+)

### Step 3.2: Add `WorkflowEntity` type
**File:** `src/schemas.py`

New entity type for named multi-step procedures (welfare check outreach sequence, Crisis Bridge establishment protocol, escalation procedure). Attributes: `trigger_condition`, `step_count`, `time_constraint`. Connected via `STEP_OF` relationship.

### Step 3.3: Update extraction prompts for procedural/conditional discovery
**File:** `src/extraction.py`, `src/relationships.py`, `src/cross_section.py`

Add `<procedural_sequences>` guidance: when document describes ordered steps, extract FOLLOWED_BY relationships. When action is conditional, extract CONDITIONAL_ON relationships.

### Step 3.4: Add `traverse_workflow` tool to agent
**File:** `src/agent.py`

New tool that follows FOLLOWED_BY chains from a starting entity to enumerate complete procedures in order.

### Verification
- Check for FOLLOWED_BY relationships between alert channels (SMS → Email → Push → Voice)
- Check for CONDITIONAL_ON relationships (Corporate Security → security-related incidents)
- Agent test: "Walk me through the welfare check outreach procedure step by step"
- Agent test: "Under what conditions is Corporate Security contacted?"

---

## Dependency Graph

```
Phase 0 (Merge Hardening)
    ↓ BLOCKS
Phase 1 (Schema + Extraction)
    ↓ BLOCKS
Phase 2 (Agent Upgrades)     Phase 3 (Workflow Extraction)
    [can run in parallel with Phase 3]
```

## Key Files Summary

| File | Phase(s) | Changes |
|------|----------|---------|
| `src/merge.py` | 0 | Primary-source-wins conflict resolution, anti-merge rules, description truncation |
| `src/schemas.py` | 1, 3 | New typed attributes on 4 entity types, new relationship types, WorkflowEntity |
| `src/extraction.py` | 1, 3 | Switch slim→full prompt, decomposition rules, attribute quality, operational priority |
| `src/first_pass.py` | 1 | Pre-registration decomposition guidance |
| `src/agent.py` | 2, 3 | New tools (get_typed_attributes, find_by_attribute, traverse_workflow), system prompt |

## Expected Outcome

After all phases, the target agent query becomes fully answerable via graph traversal:

> "Level 3 security incident in Tokyo — what do I do?"

1. Retrieve `severity_level_3` → read `alert_time_target="within 60 minutes"`, `crisis_bridge_required=False` from typed attributes
2. Follow ACTIVATED_AT edges → get `welfare_checks_service` (threshold=3), `incident_response` (threshold=2)
3. Follow ESCALATED_TO edges → get `primary_travel_program_owner` (Primary), `corporate_security` (condition="security-related", levels=[3,4])
4. Find Alert entities where severity_level=3 → get ordered outreach templates (SMS→Email→Push→Voice)
5. When traveler responds → retrieve response status → read `tmc_action` and `action_time_target` directly

Every step is a structured attribute lookup or edge traversal. No description parsing required.
