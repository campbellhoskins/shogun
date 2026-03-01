"""Stage 1: LLM-driven semantic chunking with list detection.

Uses a single LLM call to break a document into semantically complete chunks.
The LLM returns the actual text of each chunk (no offset calculation required),
then we compute source offsets post-hoc by locating each chunk in the original
document. Each chunk serves as both an extraction unit (Stage 2) and a
RAG-ready embedding chunk for future retrieval.

CLI usage:
    python -m src.segmenter <input_markdown> -o <output.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

from anthropic import Anthropic

from src.models import DocumentSection, EnumeratedList, HierarchyEntry

CHUNKING_SYSTEM_PROMPT = """\
You are a document structure analyst. Your task is to break a provided document into semantically complete chunks while preserving meaning, context, and hierarchical relationships.

Here is the document you need to analyze:

<document>
{{document}}
</document>

## Your Task

Analyze this document and break it into chunks that preserve semantic completeness and document hierarchy. Each chunk should be a meaningful unit that makes sense when read in isolation, while also maintaining clear connections to its place in the overall document structure.

Before creating your final output, work through your chunking strategy in <chunking_plan> tags:

1. **List all sections**: Identify and explicitly write out every section in the document with its header text and section number. Include any preamble or unnumbered sections. It's OK for this section to be quite long.

2. **Map hierarchical relationships**: For each section listed above, explicitly write out its complete hierarchical path from the document root. Identify the immediate parent section (if any) and note its section number and header.

3. **Determine chunk boundaries**: Mark where each chunk should begin and end. Specify clear boundaries (e.g., "Chunk 1: From document start through end of section 1.2" or "Chunk 5: Section 3.1 complete text"). Ensure boundaries respect semantic completeness - don't break mid-sentence or mid-paragraph.

4. **Verify complete coverage**: Cross-reference your chunk boundaries against the section list from step 1. Confirm that every section and every piece of text will be included in exactly one chunk with no gaps or overlaps.

This planning step is critical for ensuring that each chunk includes proper hierarchical context and that the entire document is covered without gaps or overlaps.

## Chunking Rules

Follow these rules when creating chunks:

**Semantic Completeness**: Each chunk must contain complete ideas. Never break mid-sentence or mid-paragraph. A chunk should make sense when read in isolation.

**Contiguous Coverage**: Every character in the document must belong to exactly one chunk. When you concatenate all chunks in order, they must reproduce the entire document.

**No Overlap**: Chunks must not contain duplicated text. Each portion of the document appears in exactly one chunk.

**Verbatim Text**: The "text" field must be an exact copy of the source document text for that chunk. Do not add, remove, or modify any characters.

**Preserve Headers with Content**: A section heading belongs with the content that follows it, not as a standalone chunk.

**Enumerated Lists Stay Together**: A numbered or bulleted list should remain with its introductory context in the same chunk, unless the list is extremely long.

**Adaptive Sizing**: More complex or dense sections should produce smaller chunks; simpler sections can be larger chunks. Target 500-2000 characters per chunk as a guideline, not a hard limit. Very short sections (like a title block) can be under 500 characters. A long section with a tightly coupled list can exceed 2000 characters.

**Hierarchy**: Reflect the document's own structure. If a document has top-level sections (level 1) with subsections (level 2), each subsection should generally be its own chunk unless it's very short.

## Output Format

For each chunk, create a JSON object with the following fields:

**header**: The section heading or title text exactly as it appears in the document. If the chunk has no explicit heading, create a short descriptive title in brackets like "[Preamble]" or "[Signature Block]".

**section_number**: The hierarchical number extracted from the heading (e.g., "1", "2.1", "6.4"). If the chunk has no number, assign one based on its position (e.g., "0" for preamble, "A" for appendices).

**level**: The depth in the document hierarchy (1 = top-level section, 2 = subsection, 3 = sub-subsection, etc.).

**text**: The COMPLETE, VERBATIM text of this chunk copied exactly from the source document. Do not paraphrase, reword, summarize, or alter any text. Reproduce it character-for-character including whitespace and line breaks.

**parent_section**: The section_number of this chunk's immediate parent, or null if it is a top-level chunk.

**parent_header**: The full header text of this chunk's immediate parent section, or null if it is a top-level chunk. This provides contextual information about what larger section this chunk belongs to.

**hierarchical_path**: An array of objects representing the full path from the document root to this chunk. Each object should contain "section_number" and "header" for each ancestor section, ordered from top-level to immediate parent. For top-level sections, this should be an empty array.

**enumerated_lists**: An array of any enumerated lists (numbered, lettered, or bulleted) found within this chunk. For each list include:
   - **item_count**: The exact number of items in the list
   - **list_type**: "numbered", "lettered", or "bulleted"
   - **preview**: The first few words of the first list item (for identification)

## Example Output Structure

Your output should be a JSON array of objects, one per chunk, in document order:

```json
[
  {
    "header": "Responsibilities of the Organization for Security and Rights Protection",
    "section_number": "6",
    "level": 1,
    "text": "6. Responsibilities of the Organization for Security and Rights Protection\n\nThe organization shall ensure...",
    "parent_section": null,
    "parent_header": null,
    "hierarchical_path": [],
    "enumerated_lists": []
  },
  {
    "header": "Physical Security",
    "section_number": "6.1",
    "level": 2,
    "text": "6.1 Physical Security\n\nAll facilities must maintain...",
    "parent_section": "6",
    "parent_header": "Responsibilities of the Organization for Security and Rights Protection",
    "hierarchical_path": [
      {
        "section_number": "6",
        "header": "Responsibilities of the Organization for Security and Rights Protection"
      }
    ],
    "enumerated_lists": [
      {
        "item_count": 3,
        "list_type": "numbered",
        "preview": "Access control systems must..."
      }
    ]
  },
  {
    "header": "Access Control Requirements",
    "section_number": "6.1.2",
    "level": 3,
    "text": "6.1.2 Access Control Requirements\n\nThe following requirements apply...",
    "parent_section": "6.1",
    "parent_header": "Physical Security",
    "hierarchical_path": [
      {
        "section_number": "6",
        "header": "Responsibilities of the Organization for Security and Rights Protection"
      },
      {
        "section_number": "6.1",
        "header": "Physical Security"
      }
    ],
    "enumerated_lists": []
  }
]
```

Return ONLY the JSON array. No other text outside the analysis and JSON output.
"""


def segment_document(
    text: str, client: Anthropic | None = None
) -> list[DocumentSection]:
    """Segment a document into semantic chunks using an LLM.

    The LLM returns the actual text of each chunk. We then compute source
    offsets post-hoc by locating each chunk in the original document.

    Args:
        text: The full document text.
        client: Anthropic client. Creates one if not provided.

    Returns:
        List of DocumentSection objects with text and computed source offsets.
    """
    if client is None:
        client = Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16384,
        system=CHUNKING_SYSTEM_PROMPT.replace("{{document}}", text),
        messages=[
            {
                "role": "user",
                "content": f"Break the document above into semantic chunks. The document is {len(text)} characters long.",
            }
        ],
    )

    raw = response.content[0].text
    chunks_data = _parse_json_response(raw)
    sections = _build_sections(chunks_data, text)

    return sections


def _parse_json_response(raw: str) -> list[dict]:
    """Parse JSON from the LLM response, handling chain-of-thought and markdown fences.

    The updated segmenter prompt asks the LLM to output a <chunking_plan> block
    before the JSON array.  We strip that block (and any other XML-style thinking
    tags) before attempting to parse the JSON.
    """
    # Strip <chunking_plan>...</chunking_plan> (and any similar thinking tags)
    cleaned = re.sub(
        r"<chunking_plan>[\s\S]*?</chunking_plan>", "", raw
    ).strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening fence line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # remove closing fence line
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group())
        raise


def _normalize(s: str) -> str:
    """Normalize a string for fuzzy matching: collapse whitespace, strip."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def _find_offset(chunk_text: str, document_text: str, search_start: int) -> int:
    """Find the source offset of chunk_text within document_text.

    Tries exact match first (fast), then falls back to normalized matching
    (handles minor whitespace differences from LLM reproduction).

    Args:
        chunk_text: The chunk text to locate.
        document_text: The full document text.
        search_start: Minimum offset to search from (ensures forward progress).

    Returns:
        The character offset where the chunk starts, or -1 if not found.
    """
    # Exact match: search from search_start onward
    idx = document_text.find(chunk_text, search_start)
    if idx >= 0:
        return idx

    # Normalized match: use the first 80 chars of the chunk as an anchor
    # This handles cases where the LLM slightly altered whitespace
    anchor_len = min(80, len(chunk_text))
    chunk_anchor = _normalize(chunk_text[:anchor_len])
    if not chunk_anchor:
        return -1

    # Slide a window over the document looking for a normalized match
    best_pos = -1
    for pos in range(search_start, len(document_text) - anchor_len + 1):
        window = _normalize(document_text[pos : pos + anchor_len + 20])
        if window.startswith(chunk_anchor) or chunk_anchor in window:
            best_pos = pos
            break

    return best_pos


def _build_sections(
    chunks_data: list[dict], document_text: str
) -> list[DocumentSection]:
    """Build DocumentSection objects from LLM chunk output.

    Assigns chunk_ids, computes source offsets by locating each chunk's text
    in the original document, and validates coverage.
    """
    doc_len = len(document_text)
    sections: list[DocumentSection] = []
    search_start = 0
    total_chunk_chars = 0

    for i, chunk in enumerate(chunks_data):
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue

        total_chunk_chars += len(chunk_text)

        # Compute source offset post-hoc
        offset = _find_offset(chunk_text, document_text, search_start)
        if offset >= 0:
            # Advance search_start past this chunk for the next one
            search_start = offset + len(chunk_text)
        else:
            print(
                f"  WARNING: Could not locate chunk {i + 1} "
                f"({chunk.get('header', 'unknown')!r}) in document. "
                f"Offset set to -1."
            )

        # Build enumerated lists
        enum_lists = []
        for el in chunk.get("enumerated_lists", []):
            enum_lists.append(
                EnumeratedList(
                    item_count=int(el.get("item_count", 0)),
                    list_type=str(el.get("list_type", "")),
                    preview=str(el.get("preview", "")),
                )
            )

        # Build hierarchical path
        hier_path = [
            HierarchyEntry(**entry)
            for entry in chunk.get("hierarchical_path", [])
        ]

        chunk_id = f"chunk_{i + 1:03d}"

        sections.append(
            DocumentSection(
                chunk_id=chunk_id,
                header=str(chunk.get("header", "")),
                section_number=str(chunk.get("section_number", "")),
                level=int(chunk.get("level", 1)),
                text=chunk_text,
                source_offset=offset if offset >= 0 else 0,
                parent_section=chunk.get("parent_section"),
                parent_header=chunk.get("parent_header"),
                hierarchical_path=hier_path,
                enumerated_lists=enum_lists,
            )
        )

    # Coverage validation
    coverage_ratio = total_chunk_chars / max(doc_len, 1)
    located = sum(1 for s in sections if s.source_offset > 0 or sections.index(s) == 0)

    if coverage_ratio < 0.9:
        print(
            f"  WARNING: Chunks cover {total_chunk_chars} chars vs "
            f"{doc_len} document chars ({coverage_ratio:.0%}). "
            f"Some text may have been omitted by the LLM."
        )
    elif coverage_ratio > 1.1:
        print(
            f"  WARNING: Chunks total {total_chunk_chars} chars vs "
            f"{doc_len} document chars ({coverage_ratio:.0%}). "
            f"The LLM may have duplicated some text across chunks."
        )

    unlocated = len(sections) - sum(
        1 for s in sections
        if _find_offset(s.text[:40], document_text, 0) >= 0
    )
    if unlocated > 0:
        print(
            f"  WARNING: {unlocated}/{len(sections)} chunks could not be "
            f"located in the original document."
        )

    return sections


def serialize_sections(sections: list[DocumentSection]) -> list[dict]:
    """Serialize DocumentSection objects to plain dicts for JSON output.

    This is the canonical Stage 1 JSON contract. Each dict contains the
    fields needed by downstream stages (extraction, merge) without requiring
    Pydantic reconstruction on the caller's side.
    """
    out = []
    for s in sections:
        out.append({
            "chunk_id": s.chunk_id,
            "header": s.header,
            "section_number": s.section_number,
            "level": s.level,
            "text": s.text,
            "char_count": len(s.text),
            "source_offset": s.source_offset,
            "parent_section": s.parent_section,
            "parent_header": s.parent_header,
            "hierarchical_path": [
                entry.model_dump() for entry in s.hierarchical_path
            ],
            "enumerated_lists": [el.model_dump() for el in s.enumerated_lists],
        })
    return out


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: segment a markdown document into semantic chunks."""
    parser = argparse.ArgumentParser(
        prog="python -m src.segmenter",
        description="Stage 1: Segment a document into semantic chunks via LLM.",
    )
    parser.add_argument(
        "input",
        help="Path to the input markdown/text file.",
    )
    parser.add_argument(
        "-o", "--output",
        default="data/chunks.json",
        help="Path to write the output chunks JSON (default: data/chunks.json).",
    )
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv()

    input_text = open(args.input, encoding="utf-8").read()
    print(f"Read {len(input_text)} chars from {args.input}")

    sections = segment_document(input_text)

    data = serialize_sections(sections)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(data)} chunks to {args.output}")


if __name__ == "__main__":
    main()
