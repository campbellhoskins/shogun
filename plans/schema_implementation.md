# Typed Entity Schemas for Ontology Extraction Pipeline

## Status Summary

| Step | Description | Status |
|------|-------------|--------|
| Step 1 | Create `src/schemas.py` — The Schema Framework | **DONE** |
| Step 2 | Modify `src/models.py` — Replace Entity with Discriminated Union | **DONE** |
| Step 3 | Modify `src/extraction.py` — Auto-Generated Prompt + Typed Parsing | **DONE** |
| Step 4 | Modify `src/merge.py` — Typed Entity Handling in Dedup | **DONE** |
| Step 5 | Modify `src/graph.py` — Typed Attribute Unpacking | **DONE** |
| Step 6 | Modify `src/results.py` — Serialize Typed Attributes | **DONE** |
| Step 7 | Modify `src/pipeline.py` — Validation Logging | **DONE** |
| Step 8 | User Provides Schema Content | **DONE** |
| Verification | End-to-end pipeline run, agent test, frontend test | **NOT DONE** |

**All code changes are implemented but uncommitted.** Branch: `user/choskins/schema`. No end-to-end verification run has been performed yet.

### Beyond-Plan Additions

| Item | Description | Status |
|------|-------------|--------|
| `src/base_models.py` | Circular import breaker — `SourceAnchor` moved here (not anticipated in plan) | **DONE** |
| `scripts/discover_schema.py` | LLM-based schema discovery CLI — analyzes policy docs to generate schema JSON | **DONE** |
| `data/duty_of_care_schema.json` | LLM-discovered schema with 14 entity types, relationship types, frequency flags | **DONE** |

---

## Context

The extraction pipeline currently uses a single flat `Entity` class where all entities share the same structure: `id`, `type`, `name`, `description`, `attributes: dict[str, Any]`, and `source_anchor`. The `attributes` dict is completely untyped — the LLM puts whatever key-value pairs it deems relevant, with no validation or structure.

This means a `Threshold` entity and a `Policy` entity have identical shapes despite being fundamentally different domain concepts. The LLM must reason about what attributes to extract for each type from scratch on every call, with no schema guidance beyond "include numbers, dates, emails, thresholds."

By introducing **typed entity schemas** — where each entity type has its own Pydantic model with typed, named attribute fields — we:
1. Reduce LLM reasoning burden by telling it exactly what to extract per type
2. Enable Pydantic validation of extraction output (catch missing/wrong fields)
3. Make the extraction prompt auto-generated from the schema definitions (single source of truth)
4. Enforce relationship type constraints (valid source/target entity types per relationship)
5. Prepare the foundation for Phase 2's unknown-attribute protocol

**This plan covers Phase 1 only.** Phase 2 (the 4-tier Remap/Extend/Misplace/Quarantine protocol for unknown attributes) is deferred until Phase 1 is working end-to-end.

**Schema content is user-provided.** This plan designs the framework/plumbing. The actual entity attribute definitions and relationship registry entries will be supplied by the user.

**No backward compatibility with old extractions.** All previously extracted graphs are treated as stale. Old `ontology.json` files do not need to load through the new typed models. The old `Entity` class with `attributes: dict[str, Any]` is removed entirely, not kept as a fallback. After implementation, a fresh pipeline run regenerates everything.

---

## Implementation Steps

### Step 1: Create `src/schemas.py` — The Schema Framework — DONE

**New file.** This becomes the single source of truth for entity type definitions, relationship constraints, prompt generation, and validation.

**Implementation: 2,739 lines. All substeps complete.**

#### 1A: `BaseEntitySchema` base class — DONE

All typed entity subclasses inherit from this. Replaces the old `Entity` class entirely:

```python
class BaseEntitySchema(BaseModel):
    model_config = ConfigDict(extra="allow")  # Captures unexpected attrs in __pydantic_extra__

    id: str
    type: str  # Overridden as Literal["..."] in each subclass
    name: str
    description: str
    source_anchor: SourceAnchor = Field(default_factory=SourceAnchor)
    source_anchors: list[SourceAnchor] = []
```

`extra="allow"` is the Phase 1 minimal fallback for attributes the LLM returns that don't match any typed field. These get captured in `__pydantic_extra__` rather than causing validation errors. Phase 2 replaces this with the full 4-tier protocol.

All typed attribute fields on subclasses **must have defaults** (empty string, None, etc.) so partial LLM extraction (missing some attributes) doesn't fail validation.

#### 1B: Typed entity subclasses — DONE (20 types with full attributes, not stubs)

The plan originally called for stubs that the user would fill in. Implementation went further — all 20 entity types have fully typed attribute fields with `Field(description=...)`, organized into 5 groups:

**Group 1 — Core Policy Entities (4 types):** `PolicyEntity`, `PolicySectionEntity`, `PolicyRuleEntity`, `PolicyExceptionEntity`

**Group 2 — Actor & Stakeholder Entities (4 types):** `TravelerRoleEntity`, `StakeholderEntity`, `ServiceProviderEntity` + one more. Includes Enum constraints for role types, authority levels, service types.

**Group 3 — Travel Option & Context Entities (6 types):** `TransportationModeEntity`, `ClassOfServiceEntity`, `AccommodationEntity`, `BusinessContextEntity`, `TravelEventEntity`, `GeographicScopeEntity`

**Group 4 — Financial Entities (4 types):** `ExpenseCategoryEntity`, `ReimbursementLimitEntity`, `PaymentMethodEntity`, `PriorityOrderEntity`

**Group 5 — Compliance Entities (2+ types):** `ConstraintEntity`, `RequirementEntity`, `ConsequenceEntity`

#### 1C: Discriminated union (`AnyEntity`) — DONE

Uses a custom discriminator function routing to typed subclasses. Since we don't need backward compat, unknown types are a validation error (logged as warning, entity skipped):

```python
def _entity_discriminator(v: Any) -> str:
    t = v.get("type", "") if isinstance(v, dict) else getattr(v, "type", "")
    if t not in VALID_ENTITY_TYPES:
        raise ValueError(f"Unknown entity type: {t}")
    return t

AnyEntity = Annotated[
    Union[
        Annotated[RoleEntity, Tag("Role")],
        Annotated[PolicyEntity, Tag("Policy")],
        # ... all typed subclasses ...
    ],
    Discriminator(_entity_discriminator),
]
```

#### 1D: Entity type registry — DONE (with auto-discovery)

Implementation uses auto-discovery rather than manual listing:

```python
def _discover_entity_classes() -> list[type[BaseEntitySchema]]:
    # Finds all concrete BaseEntitySchema subclasses by checking:
    # - isinstance(obj, type) and issubclass(obj, BaseEntitySchema)
    # - obj is not BaseEntitySchema
    # - "type" field has Literal default (not None)

ENTITY_TYPE_CLASSES: list[type[BaseEntitySchema]]  # Auto-discovered
ENTITY_TYPE_MAP: dict[str, type[BaseEntitySchema]] = {cls.model_fields["type"].default: cls for cls in ENTITY_TYPE_CLASSES}
VALID_ENTITY_TYPES: set[str] = set(ENTITY_TYPE_MAP.keys())
```

#### 1E: `RelationshipSchema` model and registry — DONE (35 relationship types)

The plan called for user-provided entries. Implementation defines 35 relationship types across 9 groups:

- **Group 1 — Policy Structure (4):** `CONTAINS`, `HAS_EXCEPTION`, `GOVERNED_BY`, etc.
- **Group 2 — Rule Applicability (4):** `APPLIES_TO_ROLE`, `APPLIES_TO_EXPENSE`, `APPLIES_TO_MODE`, `APPLIES_IN_CONTEXT`
- **Group 3 — Constraint Logic (3):** `CONSTRAINED_BY`, `SCOPES`, `SATISFIES`
- **Group 4 — Requirement & Fulfillment (2):** `HAS_REQUIREMENT`, `FULFILLED_BY`
- **Groups 5-9 (~22):** Financial constraints, classification, conflict resolution, consequence mapping, cross-policy navigation

Auto-discovery mechanism mirrors entity discovery:
```python
def _discover_relationship_schemas() -> list[RelationshipSchema]:
    # Finds all module-level RelationshipSchema instances
    # Deduplicates by id(obj), sorts by type name

RELATIONSHIP_SCHEMAS: list[RelationshipSchema]
RELATIONSHIP_TYPE_MAP: dict[str, list[RelationshipSchema]]  # Multiple schemas per type (multi-variant)
VALID_RELATIONSHIP_TYPES: set[str]
```

#### 1F: Prompt auto-generation functions — DONE (4 functions, not 3)

Four functions implemented (plan called for 3):

- **`generate_entity_type_prompt_section()`** — Entity types with typed attributes and forbidden aliases
- **`generate_entity_structure_prompt_section(id_prefix, section_number)`** — JSON shape with per-type attributes
- **`generate_relationship_type_prompt_section()`** — Relationship types with source/target constraints
- **`generate_json_output_example()`** — Complete JSON output example (not in original plan)

Also includes `_python_type_to_json_type(annotation)` helper for mapping Python types to JSON type labels.

#### 1G: `extra="allow"` inheritance behavior — DONE

As designed. Phase 2 will replace with structured handling.

#### 1H: `get_typed_attributes()` helper — DONE

As designed.

#### 1I: `validate_entity()` — DONE

As designed. Error handling contract matches the plan exactly.

#### 1J: `validate_relationship()` and `reconstruct_merged_entity()` — DONE

As designed. Multi-variant support added: relationships like `CONTAINS` can have multiple valid source/target patterns. A relationship is valid if ANY schema variant matches.

---

### Step 2: Modify `src/models.py` — Replace Entity with Discriminated Union — DONE

**File: `src/models.py`**

Changes implemented:
1. **`Entity` class removed entirely.** Replaced by `BaseEntitySchema` and typed subclasses from `schemas.py`.
2. `OntologyGraph.entities` type changed to `list[AnyEntity]`
3. `SectionExtraction.entities` type changed to `list[AnyEntity]`
4. No migration validator needed — old data is stale

**Implementation deviation:** `SourceAnchor` was moved to a new file `src/base_models.py` (circular import breaker). The plan assumed `SourceAnchor` could stay in `models.py` without circular imports, but in practice `schemas.py` importing from `models.py` while `models.py` imports from `schemas.py` required the breakout.

---

### Step 3: Modify `src/extraction.py` — Auto-Generated Prompt + Typed Parsing — DONE

**File: `src/extraction.py`** (979 lines)

#### 3A: Replace hardcoded prompt sections — DONE

Extraction prompt now dynamically generated from schema classes:
```python
EXTRACTION_SYSTEM_PROMPT = """\
{entity_types_section}        # generate_entity_type_prompt_section()
{entity_structure_section}    # generate_entity_structure_prompt_section()
{relationship_types_section}  # generate_relationship_type_prompt_section()
{json_output_example}         # generate_json_output_example()
"""
```

#### 3B: Update entity construction in `_build_section_extraction()` — DONE

Uses `validate_entity()` from schemas.py. Invalid entities logged and skipped.

#### 3C: Update the forbidden entity types list — DONE

Moved to `schemas.py` as `FORBIDDEN_TYPE_ALIASES` dict, auto-injected into prompt.

---

### Step 4: Modify `src/merge.py` — Typed Entity Handling in Dedup — DONE

**File: `src/merge.py`** (855 lines)

#### 4A: Entity serialization for dedup prompt — DONE

Uses `get_typed_attributes(e)` with legacy `attributes` dict flattening for backward compatibility.

#### 4B: Entity reconstruction from dedup output — DONE

Uses `reconstruct_merged_entity()` with source entity context. Warns on dropped attributes, type changes, ID discontinuity.

#### 4C: Entity loading from extractions JSON — DONE

Deserialization through the discriminated union.

#### 4D: Grouping by type — DONE

Works unchanged.

**Additional feature (not in plan):** Dedup LLM can now infer new relationships between merged entities, which are integrated into the final graph.

---

### Step 5: Modify `src/graph.py` — Typed Attribute Unpacking — DONE

**File: `src/graph.py`** (117 lines)

Uses `get_typed_attributes()` as designed.

---

### Step 6: Modify `src/results.py` — Serialize Typed Attributes — DONE

**File: `src/results.py`** (268 lines)

#### 6A: `ontology.json` serialization — DONE
#### 6B: `entities.json` grouped view — DONE (uses `get_typed_attributes()`)
#### 6C: `extractions.json` — DONE

---

### Step 7: Modify `src/pipeline.py` — Validation Logging — DONE

**File: `src/pipeline.py`** (146 lines)

Post-merge relationship validation pass implemented:
1. Builds `entity_type_lookup: dict[str, str]`
2. Validates each relationship against `RelationshipSchema` constraints
3. Logs warnings to console

Advisory-only as designed.

---

### Step 8: User Provides Schema Content — DONE

All schema content has been provided:
1. 20 typed entity subclasses with full attribute definitions (with `Field(description=...)`)
2. 35 `RelationshipSchema` registry entries with source/target constraints, cardinality, traversal hints
3. `FORBIDDEN_TYPE_ALIASES` dict mapping invalid type names to corrections

---

## Files Modified (Summary)

| File | Change Type | Status | Key Changes |
|------|------------|--------|-------------|
| `src/schemas.py` | **NEW** | **DONE** | BaseEntitySchema, 20 typed subclasses, AnyEntity union, 35 RelationshipSchemas, prompt generators, validators (2,739 lines) |
| `src/base_models.py` | **NEW** (unplanned) | **DONE** | SourceAnchor class — circular import breaker |
| `scripts/discover_schema.py` | **NEW** (unplanned) | **DONE** | LLM-based schema discovery CLI |
| `data/duty_of_care_schema.json` | **NEW** (unplanned) | **DONE** | LLM-discovered schema (14 entity types, relationship types) |
| `src/models.py` | Modify | **DONE** | Remove `Entity` class, OntologyGraph.entities -> `list[AnyEntity]`, SectionExtraction.entities -> `list[AnyEntity]` |
| `src/extraction.py` | Modify | **DONE** | Template prompt with auto-generated sections, typed entity construction |
| `src/merge.py` | Modify | **DONE** | Typed entity serialization/reconstruction in dedup, relationship discovery |
| `src/graph.py` | Modify | **DONE** | Use `get_typed_attributes()` instead of `entity.attributes` |
| `src/results.py` | Modify | **DONE** | Use `get_typed_attributes()` in entities.json grouped view |
| `src/pipeline.py` | Modify | **DONE** | Relationship validation logging after merge |
| `.gitignore` | Modify | **DONE** | Updated |

## Files NOT Modified

- `src/segmenter.py` — Upstream of entity types
- `src/agent.py` — Operates on NetworkX graph data, not Pydantic models
- `src/api_models.py` — Presentation layer decoupled from internal models
- `src/frontend.py` — Loads via `OntologyGraph(**data)`, will work after fresh extraction
- `src/eval.py`, `src/test_agent.py` — Use agent, not entity models
- `src/pdf_parser.py` — PDF parsing is upstream
- Frontend React code — Same API response shape
- Playwright tests — Test UI behavior, not entity schemas

## Verification — NOT DONE

None of the verification steps have been executed yet. All code is written but untested end-to-end.

1. **Prompt generation**: Call `generate_entity_type_prompt_section()` and verify it produces a well-formatted prompt section listing each type with its typed attributes and relationship constraints
2. **Full pipeline run**: `uv run python -m src.main data/231123_Duty_of_Care_Policy.pdf` — extraction prompt includes auto-generated type sections, LLM output validates against typed schemas, merge handles typed entities, results save correctly with typed attribute fields
3. **Validation reporting**: After merge, relationship validation warnings are logged for any type constraint violations
4. **Agent**: `uv run python -m src.test_agent --graph <new_run>` — agent tools still work, typed attributes visible in `get_entity` output
5. **Frontend**: `uv run python -m src.frontend --latest` — entities display correctly with typed attributes

## What Remains

### Immediate (to complete Phase 1)
1. **End-to-end verification run** — Run the full pipeline and confirm everything works together
2. **Commit all changes** — Everything is uncommitted on `user/choskins/schema`

### Phase 2 (Deferred)
- 4-tier unknown-attribute protocol (Remap/Extend/Misplace/Quarantine) — replaces current `extra="allow"`
- Schema version tracking/migration
- Custom validators on typed attributes
- Enum constraints enforcement for attribute values
- Cardinality enforcement (one_to_many vs many_to_many)
- Mandatory relationship enforcement
