"""Stage 1: Deterministic chunking via first-pass beginning_text matching.

Uses the document_map from Stage 0 (first pass) to locate section boundaries
deterministically — no LLM call required. Each section's `beginning_text` is
matched against the source document to find body start positions, then heading
zones are found by walking backward through markdown heading lines.

CLI usage:
    python -m src.segmenter <input_markdown> --first-pass <first_pass.json> -o <output.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

from src.models import DocumentSection, FirstPassResult, FirstPassSection


class SegmenterError(Exception):
    """Raised when section boundary detection fails."""


# ---------------------------------------------------------------------------
# Text normalization (reused from original)
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Normalize a string for fuzzy matching: collapse whitespace, strip."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_markdown(s: str) -> str:
    """Strip markdown inline formatting for robust text matching.

    Removes bold/italic markers (**, *, __, _), heading markers (#),
    and normalizes smart quotes to ASCII equivalents.
    """
    # Strip bold/italic markers (order matters: ** before *, __ before _)
    s = s.replace("**", "")
    s = s.replace("__", "")
    s = re.sub(r"(?<!\w)_|_(?!\w)", "", s)  # strip _ not inside words
    s = re.sub(r"(?<!\w)\*|\*(?!\w)", "", s)  # strip * not inside words
    # Normalize smart quotes
    s = s.replace("\u2018", "'").replace("\u2019", "'")  # single quotes
    s = s.replace("\u201c", '"').replace("\u201d", '"')  # double quotes
    return s


def _normalize_for_match(s: str) -> str:
    """Full normalization: strip markdown, collapse whitespace."""
    return _normalize(_strip_markdown(s))


# ---------------------------------------------------------------------------
# Step 1: Locate each section's body start via beginning_text
# ---------------------------------------------------------------------------

def _find_beginning_text(doc: str, beginning_text: str, search_from: int) -> int:
    """Multi-strategy text locator for a section's beginning_text.

    Matching cascade:
      1. Exact match
      2. Normalized match (first 100 chars as anchor)
      3. Token-prefix match (first 10 words as regex)
      4. Heading fallback (never used here — handled separately)

    Returns character offset into doc, or -1 if not found.
    """
    if not beginning_text:
        return -1

    # Strategy 1: Exact match
    idx = doc.find(beginning_text, search_from)
    if idx >= 0:
        return idx

    # Strategy 2: Normalized match — strip markdown + collapse whitespace, first 100 chars
    norm_bt = _normalize_for_match(beginning_text[:100])
    if norm_bt:
        # Slide a window over the document looking for a normalized match
        window_extra = 60  # extra chars for markdown formatting expansion
        search_end = len(doc)
        for pos in range(search_from, search_end):
            window = _normalize_for_match(doc[pos:pos + len(beginning_text[:100]) + window_extra])
            if window.startswith(norm_bt):
                return pos

    # Strategy 3: Token-prefix match — first 10 words as \s+ joined regex
    # Strip markdown from both sides for robust matching
    stripped_doc = _strip_markdown(doc[search_from:])
    words = _strip_markdown(beginning_text).split()[:10]
    if len(words) >= 3:
        # Escape each word for regex, join with flexible whitespace
        pattern = r"\s+".join(re.escape(w) for w in words)
        m = re.search(pattern, stripped_doc)
        if m:
            # Map back to original doc position — find the matched text start
            # by searching for the first word near the expected position
            first_word = re.escape(words[0])
            for offset_m in re.finditer(first_word, doc[search_from:]):
                if abs(offset_m.start() - m.start()) < 50:
                    return search_from + offset_m.start()
            # Fall back to approximate position
            return search_from + m.start()

    return -1


# ---------------------------------------------------------------------------
# Step 2: Find heading zone start (backward search from body offset)
# ---------------------------------------------------------------------------

def _find_heading_start(doc: str, body_offset: int) -> int:
    """Walk backward from body_offset to find the start of the heading zone.

    Scans backward through lines:
      - Skip blank lines immediately before the body
      - Collect consecutive lines starting with '#'
      - If stopped by a non-heading line, continue scanning backward
        (up to ~500 chars) looking for markdown headings (^#{1,4} )

    Returns the character offset of the first heading line, or body_offset
    if no heading lines are found.
    """
    # Split doc up to body_offset into lines to walk backward
    text_before = doc[:body_offset]
    lines = text_before.split("\n")

    # Walk backward from the last line
    heading_line_start = body_offset
    in_heading_zone = False
    i = len(lines) - 1

    while i >= 0:
        line = lines[i].strip()

        if not line:
            # Blank line — skip if we haven't found headings yet,
            # or stop if we're past the heading zone
            if in_heading_zone:
                break
            i -= 1
            continue

        if line.startswith("#"):
            in_heading_zone = True
            # Compute character offset of this line's start
            heading_line_start = sum(len(l) + 1 for l in lines[:i])  # +1 for \n
            i -= 1
            continue

        # Non-blank, non-heading line — if we already found headings, stop.
        # Otherwise, continue scanning backward (up to ~500 chars) to find
        # a markdown heading that the LLM's beginning_text may have skipped past.
        if in_heading_zone:
            break

        # Extended backward scan: skip past non-heading content lines
        # (e.g., **2.1** bold items) to find the ## heading above
        chars_scanned = 0
        j = i
        while j >= 0 and chars_scanned < 500:
            scan_line = lines[j].strip()
            chars_scanned += len(lines[j]) + 1

            if not scan_line:
                j -= 1
                continue

            if re.match(r"^#{1,4}\s", scan_line):
                # Found a heading — update heading_start to include it
                in_heading_zone = True
                heading_line_start = sum(len(l) + 1 for l in lines[:j])
                # Continue walking backward to capture any parent headings
                i = j - 1
                break

            j -= 1
        else:
            # Extended scan exhausted without finding a heading — stop
            break

        if not in_heading_zone:
            break

        continue

    return heading_line_start


# ---------------------------------------------------------------------------
# Step 3: Compute section boundaries
# ---------------------------------------------------------------------------

def _compute_section_boundaries(
    doc: str,
    fp_sections: list[FirstPassSection],
) -> list[tuple[int, int, int, FirstPassSection]]:
    """Core algorithm: locate each section and compute (heading_start, body_start, end).

    Returns list of (heading_start, body_start, section_end, fp_section) tuples.
    Raises SegmenterError if a section's beginning_text cannot be found.
    """
    # Sort sections by section_order to enforce document-order scanning
    sorted_sections = sorted(fp_sections, key=lambda s: s.section_order)

    # Phase 1: Find body offsets for all sections
    body_offsets: list[tuple[int, FirstPassSection]] = []
    search_from = 0

    for fps in sorted_sections:
        body_offset = _find_beginning_text(doc, fps.beginning_text, search_from)

        if body_offset < 0:
            # Try heading fallback: search for section_name after # markers
            # Try full name first, then progressively shorter prefixes
            # (handles "Quick Reference for Site Visitors" → "### Quick Reference")
            name_candidates = [fps.section_name]
            # Also try the portion before " / " (handles "Travel Arrangements / Air Travel")
            if " / " in fps.section_name:
                name_candidates.extend(fps.section_name.split(" / "))
            # Try progressively shorter word prefixes (min 2 words)
            words = fps.section_name.split()
            for length in range(len(words) - 1, 1, -1):
                name_candidates.append(" ".join(words[:length]))

            for candidate in name_candidates:
                # Search line by line, stripping markdown before matching
                # (handles headings like ### **_Quick Reference_**)
                pos = search_from
                found = False
                for line in doc[search_from:].split("\n"):
                    stripped_line = _strip_markdown(line).strip()
                    if stripped_line.startswith("#") and candidate.lower() in stripped_line.lower():
                        # Found the heading — body starts after this line
                        heading_pos = pos
                        eol = pos + len(line)
                        body_offset = eol + 1
                        while body_offset < len(doc) and doc[body_offset] == "\n":
                            body_offset += 1
                        found = True
                        break
                    pos += len(line) + 1  # +1 for \n
                if found:
                    break

        if body_offset < 0:
            raise SegmenterError(
                f"Cannot locate section {fps.section_id} ({fps.section_name!r}) "
                f"in document. beginning_text starts with: "
                f"{fps.beginning_text[:80]!r}"
            )

        if body_offsets and body_offset < body_offsets[-1][0]:
            raise SegmenterError(
                f"Section {fps.section_id} ({fps.section_name!r}) found at offset "
                f"{body_offset}, which is before previous section at "
                f"{body_offsets[-1][0]}. First pass output may be stale."
            )

        body_offsets.append((body_offset, fps))
        search_from = body_offset + 1

    # Phase 2: Find heading zone starts by walking backward from each body offset
    boundaries: list[tuple[int, int, int, FirstPassSection]] = []

    for idx, (body_offset, fps) in enumerate(body_offsets):
        heading_start = _find_heading_start(doc, body_offset)

        # Section end = next section's heading_start, or end of document
        if idx + 1 < len(body_offsets):
            next_body = body_offsets[idx + 1][0]
            next_heading = _find_heading_start(doc, next_body)
            section_end = next_heading
        else:
            section_end = len(doc)

        boundaries.append((heading_start, body_offset, section_end, fps))

    return boundaries



def _section_id_to_number(section_id: str) -> str:
    """Convert SEC-NNx to a dotted section number.

    Examples:
        SEC-01  → "1"
        SEC-02a → "2.1"
        SEC-02b → "2.2"
        SEC-03a1 → "3.1.1"
    """
    m = re.match(r"^SEC-(\d+)([a-z]?)(\d*)$", section_id)
    if not m:
        return section_id

    num_str, letter, sub = m.groups()
    num = int(num_str)

    if not letter:
        return str(num)

    letter_offset = ord(letter) - ord("a") + 1
    if not sub:
        return f"{num}.{letter_offset}"

    return f"{num}.{letter_offset}.{int(sub)}"



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def segment_document(
    text: str,
    client: object | None = None,  # DEPRECATED: ignored, kept for call-site compat
    first_pass_result: FirstPassResult | None = None,
) -> list[DocumentSection]:
    """Segment a document into chunks using deterministic boundary detection.

    Uses the document_map from Stage 0 (first pass) to locate section boundaries
    via beginning_text matching. No LLM call is made.

    Args:
        text: The full document text.
        client: DEPRECATED — ignored. Kept for pipeline.py call-site compatibility.
        first_pass_result: Required. First pass output with document_map sections.

    Returns:
        List of DocumentSection objects with text and computed source offsets.

    Raises:
        ValueError: If first_pass_result is None or has no sections.
        SegmenterError: If a section cannot be located in the document.
    """
    if first_pass_result is None or not first_pass_result.document_map.sections:
        raise ValueError(
            "first_pass_result with non-empty document_map.sections is required "
            "for deterministic segmentation."
        )

    fp_sections = first_pass_result.document_map.sections

    # Compute boundaries
    boundaries = _compute_section_boundaries(text, fp_sections)

    sections: list[DocumentSection] = []

    # Emit preamble if there's significant text before first section
    first_heading_start = boundaries[0][0] if boundaries else len(text)
    preamble_text = text[:first_heading_start].strip()
    if len(preamble_text) > 50:
        sections.append(DocumentSection(
            section_id="SEC-00",
            header="[Preamble]",
            section_number="0",
            text=text[:first_heading_start].rstrip("\n") + "\n",
            source_offset=0,
        ))

    # Build sections from boundaries
    for heading_start, body_start, section_end, fps in boundaries:
        section_text = text[heading_start:section_end]

        # Post-processing: trim trailing next-section headers that bled through.
        # Catches patterns like "\n---\n\n## N. HEADING\n" or just "\n## N. HEADING\n"
        # at the end of a section's text.
        trail_match = re.search(
            r"\n(?:---\s*\n\s*)?\n*(?=#{1,4}\s+\S)",
            section_text,
            re.MULTILINE,
        )
        if trail_match:
            # Only trim if the matched heading is near the end (last 20% of text)
            # to avoid trimming legitimate sub-headings within the section
            match_pos = trail_match.start()
            remaining_after = len(section_text) - match_pos
            # Check if what follows is a top-level heading (## N.) not a sub-heading
            # belonging to this section
            after_text = section_text[match_pos:].strip()
            is_next_section_heading = bool(
                re.match(r"(?:---\s*\n\s*)?#{1,3}\s+\d+[\.\)]\s", after_text)
            )
            if is_next_section_heading and remaining_after < len(section_text) * 0.25:
                section_text = section_text[:match_pos].rstrip("\n") + "\n"

        sec_num = _section_id_to_number(fps.section_id)

        if not section_text.strip():
            print(f"  WARNING: Section {fps.section_id} ({fps.section_name!r}) has empty text after slicing.")

        sections.append(DocumentSection(
            section_id=fps.section_id,
            header=fps.section_name,
            section_number=sec_num,
            text=section_text,
            source_offset=heading_start,
            section_purpose=fps.section_purpose,
            section_summary=fps.section_summary,
        ))

    # Coverage check
    total_section_chars = sum(len(s.text) for s in sections)
    coverage = total_section_chars / max(len(text), 1)
    if coverage < 0.85:
        print(
            f"  WARNING: Sections cover {total_section_chars} chars vs "
            f"{len(text)} document chars ({coverage:.0%}). "
            f"Some text may not be captured."
        )

    return sections


# ---------------------------------------------------------------------------
# Serialization (unchanged contract)
# ---------------------------------------------------------------------------

def serialize_sections(sections: list[DocumentSection]) -> list[dict]:
    """Serialize DocumentSection objects to plain dicts for JSON output.

    This is the canonical Stage 1 JSON contract. Each dict contains the
    fields needed by downstream stages (extraction, merge) without requiring
    Pydantic reconstruction on the caller's side.
    """
    out = []
    for s in sections:
        out.append({
            "section_id": s.section_id,
            "header": s.header,
            "section_number": s.section_number,
            "text": s.text,
            "char_count": len(s.text),
            "source_offset": s.source_offset,
            "section_purpose": s.section_purpose,
            "section_summary": s.section_summary,
        })
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """CLI entry point: segment a markdown document using first-pass boundaries."""
    parser = argparse.ArgumentParser(
        prog="python -m src.segmenter",
        description="Stage 1: Deterministic document chunking via first-pass boundaries.",
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
    parser.add_argument(
        "--first-pass",
        required=True,
        help="Path to first_pass.json (Stage 0 output). Required.",
    )
    args = parser.parse_args(argv)

    input_text = open(args.input, encoding="utf-8").read()
    print(f"Read {len(input_text)} chars from {args.input}")

    with open(args.first_pass, encoding="utf-8") as f:
        fp_result = FirstPassResult(**json.load(f))
    print(f"Loaded first pass from {args.first_pass}")

    sections = segment_document(input_text, first_pass_result=fp_result)

    data = serialize_sections(sections)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(data)} chunks to {args.output}")


if __name__ == "__main__":
    main()
