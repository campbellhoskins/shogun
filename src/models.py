from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# SourceAnchor lives in base_models to break circular import with schemas.py.
# Re-exported here so existing `from src.models import SourceAnchor` still works.
from src.base_models import SourceAnchor  # noqa: F401


# --- Document Structure ---


class DocumentSection(BaseModel):
    """A logical section of a document identified by the segmenter."""

    section_id: str = ""  # SEC-XX from first pass (e.g. "SEC-04")
    header: str = ""
    section_number: str = ""
    text: str
    source_offset: int = 0
    section_purpose: str = ""  # Functional classification from first pass
    section_summary: str = ""  # One-sentence summary from first pass


# --- First Pass Models ---


class FirstPassSection(BaseModel):
    """A section from the first pass document map."""

    section_id: str = ""  # SEC-01, SEC-02, SEC-02a, etc.
    section_name: str = ""  # Exact heading from document
    section_order: int = 0  # Ordinal position (1-based)
    section_purpose: str = ""  # 3-7 word functional description
    section_summary: str = ""  # One sentence in context of full doc
    beginning_text: str = ""  # First 40-60 words verbatim (for chunk location)


class FirstPassDocumentMap(BaseModel):
    """Document identity and section inventory from the first pass."""

    document_title: str = ""
    issuing_organization: str = ""
    effective_date: str | None = None
    document_purpose_summary: str = ""
    sections: list[FirstPassSection] = []


class FirstPassEntity(BaseModel):
    """A pre-registered global entity from the first pass."""

    entity_name: str = ""
    candidate_types: list[str] = []
    mentioned_in_sections: list[str] = []
    brief_description: str = ""


class FirstPassDependency(BaseModel):
    """A cross-section dependency from the first pass."""

    primary_section_id: str = ""
    dependent_section_id: str = ""
    dependency_type: str = ""  # MODIFIES|REFERENCES|CONDITIONALLY_APPLIES|DEFINES_TERM_USED_BY|OVERRIDES|REQUIRES_CONTEXT_FROM
    dependency_description: str = ""


class FirstPassResult(BaseModel):
    """Complete output of the first pass document analysis."""

    document_map: FirstPassDocumentMap = Field(default_factory=FirstPassDocumentMap)
    global_entity_pre_registration: list[FirstPassEntity] = []
    cross_section_dependencies: list[FirstPassDependency] = []


# --- Core Graph Models ---


class Relationship(BaseModel):
    source_id: str
    target_id: str
    type: str
    description: str
    source_sections: list[str] = []


# Import typed entity union after SourceAnchor is defined (schemas.py needs it).
# schemas.py imports SourceAnchor from this file, so SourceAnchor must be
# defined before this import executes.
from src.schemas import AnyEntity  # noqa: E402


# --- Pipeline Telemetry ---


class StageUsage(BaseModel):
    """Token and API call usage for a single pipeline stage."""

    stage: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0


# --- Extraction Pipeline ---


class ExtractionMetadata(BaseModel):
    """Metadata about the extraction pipeline run."""

    document_char_count: int = 0
    section_count: int = 0
    extraction_passes: int = 0
    total_api_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    final_entity_count: int = 0
    final_relationship_count: int = 0
    exact_id_dedup_merges: int = 0
    semantic_dedup_merges: int = 0
    semantic_dedup_api_calls: int = 0
    stage4_relationship_count: int = 0
    stage4_invalid_count: int = 0
    stage4_dedup_count: int = 0
    stage4_api_calls: int = 0
    stage_usages: list[StageUsage] = []


class SectionExtraction(BaseModel):
    """Extraction results from a single document section."""

    section: DocumentSection
    entities: list[AnyEntity] = []
    relationships: list[Relationship] = []


class OntologyGraph(BaseModel):
    graph_title: str = ""
    entities: list[AnyEntity]
    relationships: list[Relationship]
    source_sections: list[DocumentSection] = []
    source_document: str = ""
    extraction_metadata: ExtractionMetadata = Field(
        default_factory=ExtractionMetadata
    )


# --- Agent ---


class AgentResponse(BaseModel):
    answer: str
    referenced_entities: list[str] = []
    reasoning_path: str = ""


# --- Structured Output Schemas ---
# These models wrap LLM call outputs for Anthropic structured outputs.
# Each defines the top-level JSON object the API will return.


class ExtractedEntityItem(BaseModel):
    """Lightweight entity container for raw LLM output.

    Entity extraction uses messages.create() (not structured output) so the
    LLM can produce typed attributes freely. extra="allow" lets Pydantic
    accept any additional fields; validate_entity() maps them to the correct
    typed subclass downstream.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    name: str
    description: str
    source_anchor: SourceAnchor = Field(default_factory=SourceAnchor)


class EntityExtractionOutput(BaseModel):
    """Stage 2a entity extraction output."""

    entities: list[ExtractedEntityItem]


class RelationshipExtractionOutput(BaseModel):
    """Stage 2b / Stage 4 relationship extraction output.

    Uses plain str for type field — NOT an enum. Rationale: if the LLM
    invents even one bad type (e.g. 'DEFINES_IN'), an enum constraint
    causes Pydantic to reject the ENTIRE response (all relationships lost).
    Post-processing via validate_relationship() rejects bad types
    individually while keeping the valid ones.
    """

    relationships: list[Relationship]


class MergeRemapping(BaseModel):
    """Single entity ID remapping from semantic dedup."""

    old_id: str
    new_id: str
    reason: str


class SemanticDedupOutput(BaseModel):
    """Stage 3 semantic deduplication output (wraps bare array)."""

    remappings: list[MergeRemapping]


class CrossSectionRelationshipItem(BaseModel):
    """A relationship with cross-section metadata."""

    source_id: str
    target_id: str
    source_section: str
    target_section: str
    type: str
    description: str
    source_anchor: SourceAnchor = Field(default_factory=SourceAnchor)


class CrossSectionRelOutput(BaseModel):
    """Stage 3a cross-section relationship output."""

    relationships: list[CrossSectionRelationshipItem]


class QAPair(BaseModel):
    """Single Q&A pair."""

    question: str
    answer: str
    section: str
    difficulty: str


class QAGenerationOutput(BaseModel):
    """Q&A generation output (wraps bare array)."""

    qa_pairs: list[QAPair]


class JudgmentOutput(BaseModel):
    """Eval judge scoring output."""

    model_config = ConfigDict(populate_by_name=True)

    accuracy: int
    completeness: int
    no_hallucination: int
    total: int
    pass_result: bool = Field(alias="pass")
    explanation: str


class LegacyExtractionOutput(BaseModel):
    """Legacy single-pass extraction output."""

    entities: list[ExtractedEntityItem]
    relationships: list[Relationship]
