from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Source Anchoring ---


class SourceAnchor(BaseModel):
    """Provenance information linking an entity back to its source text."""

    source_text: str = ""
    source_section: str = ""
    source_offset: int = -1


# --- Document Structure ---


class EnumeratedList(BaseModel):
    """An enumerated list detected within a document section."""

    item_count: int
    list_type: str = ""  # "numbered", "lettered", "bulleted"
    preview: str = ""  # First few words of the list for identification


class DocumentSection(BaseModel):
    """A logical section of a document identified by the segmenter."""

    header: str = ""
    section_number: str = ""
    level: int = 1
    text: str
    source_offset: int = 0
    parent_section: str | None = None
    enumerated_lists: list[EnumeratedList] = []


# --- Extraction Pipeline ---


class SectionExtraction(BaseModel):
    """Extraction results from a single document section."""

    section: DocumentSection
    entities: list[Entity] = []
    relationships: list[Relationship] = []


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


# --- Core Graph Models ---


class Entity(BaseModel):
    id: str
    type: str
    name: str
    description: str
    attributes: dict[str, Any] = {}
    source_anchor: SourceAnchor = Field(default_factory=SourceAnchor)


class Relationship(BaseModel):
    source_id: str
    target_id: str
    type: str
    description: str
    source_sections: list[str] = []


class OntologyGraph(BaseModel):
    entities: list[Entity]
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
