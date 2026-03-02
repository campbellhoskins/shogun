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
