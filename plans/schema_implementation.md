# Typed Entity Schemas for Ontology Extraction Pipeline

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

### Step 1: Create `src/schemas.py` — The Schema Framework

**New file.** This becomes the single source of truth for entity type definitions, relationship constraints, prompt generation, and validation.

#### 1A: `BaseEntitySchema` base class

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

#### 1B: Typed entity subclasses (stubs — user fills in attributes)

```python
class RoleEntity(BaseEntitySchema):
    """An organizational role or party type."""
    type: Literal["Role"] = "Role"
    # User adds typed attribute fields here

class PolicyEntity(BaseEntitySchema):
    """Referenced policies and documents."""
    type: Literal["Policy"] = "Policy"
    # User adds typed attribute fields here

# ... one subclass per entity type (user provides ~16 total)
```

#### 1C: Discriminated union (`AnyEntity`)

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

#### 1D: Entity type registry

```python
ENTITY_TYPE_CLASSES: list[type[BaseEntitySchema]] = [RoleEntity, PolicyEntity, ...]
ENTITY_TYPE_MAP: dict[str, type[BaseEntitySchema]] = {cls.model_fields["type"].default: cls for cls in ENTITY_TYPE_CLASSES}
VALID_ENTITY_TYPES: set[str] = set(ENTITY_TYPE_MAP.keys())
```

#### 1E: `RelationshipSchema` model and registry

```python
class RelationshipSchema(BaseModel):
    type: str
    description: str
    valid_source_types: list[str]   # Empty = any type allowed
    valid_target_types: list[str]   # Empty = any type allowed
    cardinality: str = "many_to_many"
    is_directed: bool = True
    mandatory: bool = False
    inverse_type: str | None = None
    agent_traversal_hint: str = ""

RELATIONSHIP_SCHEMAS: list[RelationshipSchema] = [...]  # User provides entries
RELATIONSHIP_TYPE_MAP: dict[str, RelationshipSchema] = {rs.type: rs for rs in RELATIONSHIP_SCHEMAS}
VALID_RELATIONSHIP_TYPES: set[str] = set(RELATIONSHIP_TYPE_MAP.keys())
```

#### 1F: Prompt auto-generation functions

Three functions that read the Pydantic schema models and produce prompt text:

- **`generate_entity_type_prompt_section()`** — Iterates `ENTITY_TYPE_CLASSES`, reads each class's `__doc__`, enumerates typed attribute fields (name, type, description from `Field(description=...)`), formats into the "Entity Types" prompt block. Replaces lines 337-367 of current extraction prompt.

- **`generate_entity_structure_prompt_section(id_prefix, section_number)`** — Generates the "Entity Structure" block showing the JSON shape with per-type attributes. Replaces lines 369-397.

- **`generate_relationship_type_prompt_section()`** — Iterates `RELATIONSHIP_SCHEMAS`, emits each type with description and valid source/target constraints. Replaces lines 476-501.

#### 1G: `extra="allow"` inheritance behavior

`model_config = ConfigDict(extra="allow")` on `BaseEntitySchema` is **inherited by all subclasses**. This is intentional for Phase 1: if the LLM returns an attribute that doesn't match any typed field, it silently goes to `__pydantic_extra__` rather than failing validation. This means:

```python
# This succeeds silently — "misspelled_field" goes to __pydantic_extra__
RoleEntity(id="R-001", type="Role", name="ED", description="...", misspelled_field="val")
```

`model_dump()` merges `__pydantic_extra__` content at the top level alongside typed fields. No key collisions with base fields are possible because Pydantic prevents extra keys from shadowing declared fields.

Phase 2's 4-tier protocol replaces this permissive behavior with structured handling.

#### 1H: `get_typed_attributes()` helper

Used by `graph.py` and `results.py` to extract type-specific fields from any entity subclass:

```python
def get_typed_attributes(entity: BaseEntitySchema) -> dict[str, Any]:
    """Extract type-specific fields + any __pydantic_extra__ overflow.

    model_dump() already merges __pydantic_extra__ at top level,
    so we just exclude the base fields that every entity shares.
    """
    base_fields = set(BaseEntitySchema.model_fields.keys())
    # base_fields = {"id", "type", "name", "description", "source_anchor", "source_anchors"}
    return {
        k: v
        for k, v in entity.model_dump().items()
        if k not in base_fields
    }
```

This returns both typed attribute fields AND any extras the LLM added beyond the schema, all as a flat dict.

#### 1I: `validate_entity()` — Error handling contract

```python
def validate_entity(entity_data: dict) -> tuple[BaseEntitySchema | None, list[str]]:
```

Explicit failure policy for each case:

| Case | Behavior | Return |
|------|----------|--------|
| **Unknown type** (`entity_data["type"]` not in `VALID_ENTITY_TYPES`) | Entity skipped entirely | `(None, ["Unknown entity type: {type}"])` |
| **Known type, missing required base fields** (name, description, id) | Attempt construction — Pydantic raises `ValidationError` | `(None, ["Missing required field: {field}"])` |
| **Known type, field type mismatch** (e.g. `id=12345` instead of str) | Attempt Pydantic coercion first. If coercion fails, entity skipped | `(None, ["Type mismatch on {field}: ..."])` |
| **Known type, all required fields present, extra fields** | Succeeds. Extras captured in `__pydantic_extra__` | `(entity, ["Extra field(s) not in schema: {fields}"])` — warnings only |
| **Known type, missing optional typed attribute fields** | Succeeds. Missing fields get their defaults (empty string, None, etc.) | `(entity, [])` — clean |

All callers (`extraction.py`, `merge.py`, `pipeline.py`) treat `None` as "skip this entity and log the warning."

#### 1J: `validate_relationship()` and `reconstruct_merged_entity()`

**`validate_relationship(rel, entity_type_lookup) -> list[str]`** — Checks source/target types against `RelationshipSchema` constraints. Returns list of warnings (empty = valid).

**`reconstruct_merged_entity(merged_dict, source_entities) -> tuple[BaseEntitySchema | None, list[str]]`** — Specialized validator for the merge/dedup path. Wraps `validate_entity()` with additional merge-specific checks:

1. **Dropped typed attributes**: Warns if a typed attribute field present in ALL source entities is absent from the merged dict (LLM dropped data during merge)
2. **Type change detection**: Warns if `merged_dict["type"]` differs from the source entities' types (LLM changed the type — almost always wrong)
3. **ID continuity**: Verifies the merged ID matches one of the source entity IDs or is a newly assigned canonical ID (prevents dangling relationship references)

---

### Step 2: Modify `src/models.py` — Replace Entity with Discriminated Union

**File: `src/models.py`** (lines 55-107)

Changes:
1. **Remove the `Entity` class entirely** (lines 82-89). It is replaced by `BaseEntitySchema` and its typed subclasses from `schemas.py`.
2. `OntologyGraph.entities` type changes from `list[Entity]` to `list[AnyEntity]`
3. `SectionExtraction.entities` type changes from `list[Entity]` to `list[AnyEntity]`
4. No migration validator needed — old data is stale and will be re-extracted

Import note: `models.py` imports `AnyEntity` from `schemas.py`. `schemas.py` imports `SourceAnchor` from `models.py`. No circular dependency because `SourceAnchor` is defined at the top of `models.py` before `OntologyGraph`.

---

### Step 3: Modify `src/extraction.py` — Auto-Generated Prompt + Typed Parsing

**File: `src/extraction.py`**

#### 3A: Replace hardcoded prompt sections

The `EXTRACTION_SYSTEM_PROMPT` string (currently ~639 lines) becomes a template with placeholders:

- `{entity_types_section}` — filled by `generate_entity_type_prompt_section()`
- `{entity_structure_section}` — filled by `generate_entity_structure_prompt_section()`
- `{relationship_types_section}` — filled by `generate_relationship_type_prompt_section()`

Everything else in the prompt (principles, 4-step analysis, special handling rules, output format) stays as-is.

The `_build_prompt()` function calls the generators and injects the results.

#### 3B: Update entity construction in `_build_section_extraction()`

Currently constructs `Entity(...)` with generic `attributes`. Changes to:
1. For each entity dict from LLM response, call `validate_entity()` from schemas.py
2. If valid: use the typed subclass
3. If invalid (unknown type): log warning and skip the entity
4. Collect validation warnings for pipeline-level reporting

#### 3C: Update the forbidden entity types list

Currently hardcoded in the prompt (lines 362-367). Move to `schemas.py` as a constant derived from the registry, auto-injected into the prompt by the generation function.

---

### Step 4: Modify `src/merge.py` — Typed Entity Handling in Dedup

**File: `src/merge.py`**

#### 4A: Entity serialization for dedup prompt (`_build_entities_block`)

Currently picks specific fields manually. Change to use `entity.model_dump()` which naturally includes all typed attribute fields. Exclude base fields that aren't needed for dedup comparison.

#### 4B: Entity reconstruction from dedup output

Currently constructs `Entity(...)` from LLM dedup response dicts. Change to use `reconstruct_merged_entity(merged_dict, source_entities)` from schemas.py. This wraps `validate_entity()` with merge-specific checks: warns on dropped typed attributes, type changes, and ID discontinuity. Source entities for each merge group must be passed in so the function can compare what went in vs what came out.

#### 4C: Entity loading from extractions JSON (`_extractions_from_json`)

Currently: `entities = [Entity(**e) for e in ext.get("entities", [])]`. Change to deserialize through the discriminated union.

#### 4D: Grouping by type

`by_type[entity.type].append(entity)` — works unchanged because every subclass has `type`.

---

### Step 5: Modify `src/graph.py` — Typed Attribute Unpacking

**File: `src/graph.py`** (line 20)

Currently:
```python
attrs = {k: str(v) for k, v in entity.attributes.items() if k not in reserved}
```

Changes to use `get_typed_attributes()` helper from schemas.py:
```python
from src.schemas import get_typed_attributes
typed_attrs = get_typed_attributes(entity)
attrs = {k: str(v) for k, v in typed_attrs.items() if k not in reserved}
```

This extracts type-specific fields + extra attributes, stringifies them for NetworkX. Rest of graph.py is unchanged.

---

### Step 6: Modify `src/results.py` — Serialize Typed Attributes

**File: `src/results.py`** (lines 142-166)

#### 6A: `ontology.json` serialization (line 140)

`ontology.model_dump()` — works automatically. Pydantic serializes the discriminated union correctly, including typed fields as top-level keys.

#### 6B: `entities.json` grouped view (lines 142-166)

Currently accesses `e.attributes` (line 149). Change to use `get_typed_attributes(e)` to collect the type-specific fields into the human-readable view:

```python
entity_data = {
    "id": e.id,
    "name": e.name,
    "description": e.description,
    "typed_attributes": get_typed_attributes(e),  # Replaces generic "attributes"
    "source_section": e.source_anchor.source_section,
    "source_text": e.source_anchor.source_text,
}
```

#### 6C: `extractions.json` (line 134)

`e.model_dump()` — works automatically for typed entities.

---

### Step 7: Modify `src/pipeline.py` — Validation Logging

**File: `src/pipeline.py`**

Add post-merge validation pass:
1. Build `entity_type_lookup: dict[str, str]` mapping entity IDs to their types
2. Validate each relationship against `RelationshipSchema` constraints
3. Log warnings to console and include validation summary in `run_meta.json`

This is advisory-only in Phase 1 (warnings, not errors).

---

### Step 8: User Provides Schema Content

User fills in:
1. Typed attribute fields on each entity subclass (with `Field(description=...)`)
2. Complete `RELATIONSHIP_SCHEMAS` registry entries
3. Any forbidden type aliases

---

## Files Modified (Summary)

| File | Change Type | Key Changes |
|------|------------|-------------|
| `src/schemas.py` | **NEW** | BaseEntitySchema, typed subclasses (stubs), AnyEntity union, RelationshipSchema, prompt generators, validators |
| `src/models.py` | Modify | Remove `Entity` class, OntologyGraph.entities -> `list[AnyEntity]`, SectionExtraction.entities -> `list[AnyEntity]` |
| `src/extraction.py` | Modify | Template prompt with auto-generated sections, typed entity construction in `_build_section_extraction()` |
| `src/merge.py` | Modify | Typed entity serialization/reconstruction in dedup, `_extractions_from_json` |
| `src/graph.py` | Modify | Use `get_typed_attributes()` instead of `entity.attributes` (line 20) |
| `src/results.py` | Modify | Use `get_typed_attributes()` in entities.json grouped view (lines 142-166) |
| `src/pipeline.py` | Modify | Add relationship validation logging after merge |

## Files NOT Modified

- `src/segmenter.py` — Upstream of entity types
- `src/agent.py` — Operates on NetworkX graph data, not Pydantic models
- `src/api_models.py` — Presentation layer decoupled from internal models
- `src/frontend.py` — Loads via `OntologyGraph(**data)`, will work after fresh extraction
- `src/eval.py`, `src/test_agent.py` — Use agent, not entity models
- `src/pdf_parser.py` — PDF parsing is upstream
- Frontend React code — Same API response shape
- Playwright tests — Test UI behavior, not entity schemas

## Verification

1. **Prompt generation**: Call `generate_entity_type_prompt_section()` and verify it produces a well-formatted prompt section listing each type with its typed attributes and relationship constraints
2. **Full pipeline run**: `uv run python -m src.main data/231123_Duty_of_Care_Policy.pdf` — extraction prompt includes auto-generated type sections, LLM output validates against typed schemas, merge handles typed entities, results save correctly with typed attribute fields
3. **Validation reporting**: After merge, relationship validation warnings are logged for any type constraint violations
4. **Agent**: `uv run python -m src.test_agent --graph <new_run>` — agent tools still work, typed attributes visible in `get_entity` output
5. **Frontend**: `uv run python -m src.frontend --latest` — entities display correctly with typed attributes
