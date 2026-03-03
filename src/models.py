from __future__ import annotations

from pydantic import BaseModel, Field

# SourceAnchor lives in base_models to break circular import with schemas.py.
# Re-exported here so existing `from src.models import SourceAnchor` still works.
from src.base_models import SourceAnchor  # noqa: F401


# --- Document Structure ---


class EnumeratedList(BaseModel):
    """An enumerated list detected within a document section."""

    item_count: int
    list_type: str = ""  # "numbered", "lettered", "bulleted"
    preview: str = ""  # First few words of the list for identification


class HierarchyEntry(BaseModel):
    """A single entry in a section's hierarchical path from document root."""

    section_number: str = ""
    header: str = ""


class DocumentSection(BaseModel):
    """A logical section of a document identified by the segmenter."""

    chunk_id: str = ""  # Stable ID for RAG retrieval (e.g., "chunk_001")
    header: str = ""
    section_number: str = ""
    level: int = 1
    text: str
    source_offset: int = 0
    parent_section: str | None = None
    parent_header: str | None = None
    hierarchical_path: list[HierarchyEntry] = []
    enumerated_lists: list[EnumeratedList] = []
    section_id: str = ""  # SEC-XX from first pass (e.g. "SEC-04")
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
    pre_registration_scope_note: str = ""
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
    deduplication_merges: int = 0
    semantic_dedup_merges: int = 0
    semantic_dedup_api_calls: int = 0


class SectionExtraction(BaseModel):
    """Extraction results from a single document section."""

    section: DocumentSection
    entities: list[AnyEntity] = []
    relationships: list[Relationship] = []


class OntologyGraph(BaseModel):
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
