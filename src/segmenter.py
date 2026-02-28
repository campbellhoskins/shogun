"""Stage 1: LLM-based document segmentation with list detection.

Uses a single LLM call to break a document into logical sections,
identify hierarchy, and detect enumerated lists within each section.
"""

from __future__ import annotations

import json
import re
import time

from anthropic import Anthropic

from src.models import DocumentSection, EnumeratedList

SEGMENTATION_SYSTEM_PROMPT = """\
You are a document structure analyst. Your task is to identify every logical \
section and subsection in the provided document.

## What to Identify

For each section:
1. **header**: The section heading or title text exactly as it appears in the document. If the section has no explicit heading, create a short descriptive title in brackets like "[Preamble]" or "[Signature Block]".
2. **section_number**: The hierarchical number extracted from the heading (e.g., "1", "2.1", "6.4"). If the section has no number, assign one based on its position (e.g., "0" for preamble, "A" for appendices).
3. **level**: The depth in the document hierarchy (1 = top-level section, 2 = subsection, 3 = sub-subsection).
4. **start_offset**: The exact character offset where this section begins in the source text (0-indexed, inclusive). This is the position of the FIRST character of the section heading.
5. **end_offset**: The exact character offset where this section ends (exclusive). The next section's start_offset should equal this section's end_offset.
6. **parent_section**: The section_number of this section's parent, or null if it is a top-level section.
7. **enumerated_lists**: An array of any enumerated lists (numbered, lettered, or bulleted) found within this section. For each list:
   - **item_count**: The exact number of items in the list.
   - **list_type**: "numbered", "lettered", or "bulleted".
   - **preview**: The first few words of the first list item (for identification).

## Rules

- Capture EVERY section, including preambles, title blocks, appendices, and signature blocks.
- Sections must be contiguous and non-overlapping — every character in the document must belong to exactly one section.
- The first section's start_offset must be 0.
- The last section's end_offset must equal the total document length.
- Preserve the document's own hierarchy: if it uses ## for sections and ### for subsections, reflect that in levels.
- Be precise with character offsets. Count carefully — off-by-one errors make the output unusable.
- For enumerated lists, count the ACTUAL items present, not what the document claims. If the document says "seven measures" but only lists 5, report item_count: 5.

## Output Format

Return a JSON array of objects, one per section, in document order:
```json
[
  {
    "header": "Section heading text",
    "section_number": "2.1",
    "level": 2,
    "start_offset": 0,
    "end_offset": 500,
    "parent_section": "2",
    "enumerated_lists": [
      {"item_count": 7, "list_type": "numbered", "preview": "First item text..."}
    ]
  }
]
```

Return ONLY the JSON array. No other text.
"""


def segment_document(
    text: str, client: Anthropic | None = None
) -> list[DocumentSection]:
    """Segment a document into logical sections using an LLM.

    Args:
        text: The full document text.
        client: Anthropic client. Creates one if not provided.

    Returns:
        List of DocumentSection objects with text sliced from the original document.
    """
    if client is None:
        client = Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SEGMENTATION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Segment the following document (total length: {len(text)} characters).\n\n"
                    f"<document>\n{text}\n</document>"
                ),
            }
        ],
    )

    raw = response.content[0].text
    sections_data = _parse_json_response(raw)
    sections = _build_sections(sections_data, text)

    # Split oversized sections
    sections = _split_oversized_sections(sections)

    return sections


def _parse_json_response(raw: str) -> list[dict]:
    """Parse JSON from the LLM response, handling markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON array from the response
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            return json.loads(match.group())
        raise


def _build_sections(
    sections_data: list[dict], document_text: str
) -> list[DocumentSection]:
    """Build DocumentSection objects by slicing text from the original document."""
    doc_len = len(document_text)
    sections: list[DocumentSection] = []

    for i, s in enumerate(sections_data):
        start = max(0, int(s.get("start_offset", 0)))
        end = min(doc_len, int(s.get("end_offset", doc_len)))

        # Clamp to valid range
        if start >= doc_len:
            start = doc_len
        if end <= start:
            end = start

        section_text = document_text[start:end]

        # Build enumerated lists
        enum_lists = []
        for el in s.get("enumerated_lists", []):
            enum_lists.append(
                EnumeratedList(
                    item_count=int(el.get("item_count", 0)),
                    list_type=str(el.get("list_type", "")),
                    preview=str(el.get("preview", "")),
                )
            )

        sections.append(
            DocumentSection(
                header=str(s.get("header", "")),
                section_number=str(s.get("section_number", "")),
                level=int(s.get("level", 1)),
                text=section_text,
                source_offset=start,
                parent_section=s.get("parent_section"),
                enumerated_lists=enum_lists,
            )
        )

    return sections


def _split_oversized_sections(
    sections: list[DocumentSection], max_chars: int = 2000
) -> list[DocumentSection]:
    """Split sections exceeding max_chars at paragraph boundaries."""
    result: list[DocumentSection] = []

    for section in sections:
        if len(section.text) <= max_chars:
            result.append(section)
            continue

        # Split at double-newline paragraph boundaries
        paragraphs = re.split(r"\n\n+", section.text)
        current_text = ""
        current_offset = section.source_offset
        part_num = 0

        for para in paragraphs:
            # If adding this paragraph would exceed limit and we already have content
            if current_text and len(current_text) + len(para) + 2 > max_chars:
                part_num += 1
                result.append(
                    DocumentSection(
                        header=f"{section.header} (part {part_num})"
                        if part_num > 1
                        else section.header,
                        section_number=f"{section.section_number}.p{part_num}"
                        if part_num > 1
                        else section.section_number,
                        level=section.level,
                        text=current_text,
                        source_offset=current_offset,
                        parent_section=section.parent_section,
                        enumerated_lists=section.enumerated_lists
                        if part_num == 1
                        else [],
                    )
                )
                current_offset += len(current_text)
                current_text = para
            else:
                if current_text:
                    current_text += "\n\n" + para
                else:
                    current_text = para

        # Emit final chunk
        if current_text:
            part_num += 1
            result.append(
                DocumentSection(
                    header=f"{section.header} (part {part_num})"
                    if part_num > 1
                    else section.header,
                    section_number=f"{section.section_number}.p{part_num}"
                    if part_num > 1
                    else section.section_number,
                    level=section.level,
                    text=current_text,
                    source_offset=current_offset,
                    parent_section=section.parent_section,
                    enumerated_lists=section.enumerated_lists
                    if part_num == 1
                    else [],
                )
            )

    return result
