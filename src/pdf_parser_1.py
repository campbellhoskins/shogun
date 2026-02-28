"""
PDF Structure Parser for Shogun

Converts PDF policy documents into structured markdown that preserves
the inherent document hierarchy for optimal LLM reasoning.

Approach:
  1. Extract text spans with font metadata (size, bold, position) via PyMuPDF
  2. Remove noise: page numbers, repeated headers/footers, TOC dot-fillers
  3. Classify fonts: body text size vs heading sizes via character-count histogram
  4. Render as markdown: headings (#/##/###), lists (-), definitions (**term:**),
     and properly joined paragraphs

The output is optimized for LLM consumption: an LLM reading the markdown can
reason over the document's hierarchical structure as accurately as a human
reading the original PDF.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class Span:
    """A contiguous run of text with uniform formatting."""

    text: str
    font_size: float
    is_bold: bool
    is_italic: bool
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Line:
    """A visual line of text (one or more Spans at the same y-position)."""

    spans: list[Span] = field(default_factory=list)
    page: int = 0

    @property
    def text(self) -> str:
        """Reconstruct line text, inserting spaces at span gaps."""
        if not self.spans:
            return ""
        parts: list[str] = []
        for i, s in enumerate(self.spans):
            if i > 0 and parts:
                prev = self.spans[i - 1]
                gap = s.x0 - prev.x1
                last_char = parts[-1][-1] if parts[-1] else ""
                first_char = s.text[0] if s.text else ""
                if gap > 2.0 and last_char != " " and first_char != " ":
                    parts.append(" ")
            parts.append(s.text)
        return "".join(parts).strip()

    @property
    def dominant_size(self) -> float:
        """The font size carrying the most non-whitespace characters."""
        if not self.spans:
            return 0.0
        counts: Counter[float] = Counter()
        for s in self.spans:
            t = s.text.strip()
            if t:
                counts[round(s.font_size, 1)] += len(t)
        return counts.most_common(1)[0][0] if counts else 0.0

    @property
    def is_bold(self) -> bool:
        """True if >50% of non-whitespace chars come from bold spans."""
        bold = sum(len(s.text.strip()) for s in self.spans if s.is_bold)
        total = sum(len(s.text.strip()) for s in self.spans)
        return total > 0 and bold / total > 0.5

    @property
    def x_start(self) -> float:
        """Left edge of the first non-whitespace span."""
        for s in self.spans:
            if s.text.strip():
                return s.x0
        return self.spans[0].x0 if self.spans else 0.0

    @property
    def y_top(self) -> float:
        return min(s.y0 for s in self.spans) if self.spans else 0.0

    @property
    def y_bottom(self) -> float:
        return max(s.y1 for s in self.spans) if self.spans else 0.0

    def get_bold_prefix(self) -> tuple[str, str] | None:
        """If line starts bold then switches to non-bold, return (bold, rest)."""
        bold_parts: list[str] = []
        rest_parts: list[str] = []
        switched = False
        for s in self.spans:
            if not switched:
                if s.is_bold:
                    bold_parts.append(s.text)
                elif s.text.strip():
                    switched = True
                    rest_parts.append(s.text)
                else:
                    bold_parts.append(s.text)
            else:
                rest_parts.append(s.text)
        bold = "".join(bold_parts).strip()
        rest = "".join(rest_parts).strip()
        if switched and bold:
            return (bold, rest)
        return None


# ── Regex patterns ───────────────────────────────────────────────────────────

_SECTION_NUM = re.compile(r"^(\d+\.(?:\d+\.?)*)\s")
_BULLET_CHAR = re.compile(r"^[\u2022\u2023\u25E6\u2043\u2219\u25CF\u25CB\u25A0•●○◦‣⁃▪]\s*")
_DASH_ITEM = re.compile(r"^[−–—]\s+")
_LETTER_ITEM = re.compile(r"^[a-z]\)\s")
_PAGE_NUM = re.compile(r"^\d{1,3}$")
_TOC_DOTS = re.compile(r"^.+?\.{4,}\s*\d+\s*$")
_ALL_UPPER = re.compile(r"^[A-Z\d\s\.,;:\-\(\)&/'\"\u00AB\u00BB\u2013\u2014]+$")


# ── Main entry point ─────────────────────────────────────────────────────────


def parse_pdf(pdf_path: str | Path) -> str:
    """
    Parse a PDF into structured markdown preserving document hierarchy.

    Extracts headings, subheadings, numbered clauses, bullet lists,
    definition lists, and body paragraphs using font-metric analysis.
    Strips page numbers, repeated headers/footers, and TOC filler.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Structured markdown text optimized for LLM consumption.
    """
    import pymupdf

    doc = pymupdf.open(str(pdf_path))

    # Phase 1: Extract formatted lines from every page
    pages: list[list[Line]] = []
    heights: list[float] = []
    for idx, page in enumerate(doc):
        pages.append(_extract_lines(page, idx))
        heights.append(page.rect.height)

    # Phase 2: Identify and remove noise
    repeated = _find_repeated(pages)
    lines: list[Line] = []
    for idx, page_lines in enumerate(pages):
        for ln in page_lines:
            if not _is_noise(ln, heights[idx], repeated):
                lines.append(ln)

    if not lines:
        doc.close()
        return ""

    # Phase 3: Font analysis
    body_size = _body_font_size(lines)
    h_map = _heading_sizes(lines, body_size)
    margin = _left_margin(lines)

    # Phase 4: Render
    result = _render(lines, body_size, h_map, margin)
    doc.close()
    return result


# ── Phase 1: Extraction ──────────────────────────────────────────────────────


def _extract_lines(page, page_idx: int) -> list[Line]:
    """Extract all text lines from a PDF page with font metadata."""
    import pymupdf

    try:
        flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES
    except AttributeError:
        flags = 3  # fallback for older pymupdf versions

    data = page.get_text("dict", flags=flags)
    out: list[Line] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:  # text blocks only
            continue
        for ld in block.get("lines", []):
            spans: list[Span] = []
            for sd in ld.get("spans", []):
                text = sd.get("text", "")
                if not text:
                    continue
                bbox = sd["bbox"]
                f = sd.get("flags", 0)
                spans.append(
                    Span(
                        text=text,
                        font_size=round(sd["size"], 1),
                        is_bold=bool(f & 16),  # bit 4 = bold
                        is_italic=bool(f & 2),  # bit 1 = italic
                        x0=bbox[0],
                        y0=bbox[1],
                        x1=bbox[2],
                        y1=bbox[3],
                    )
                )
            if spans and any(s.text.strip() for s in spans):
                out.append(Line(spans=spans, page=page_idx))

    return out


# ── Phase 2: Noise detection ─────────────────────────────────────────────────


def _find_repeated(pages: list[list[Line]]) -> set[str]:
    """Find text that appears on many pages (headers/footers to strip)."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page_lines in pages:
        seen: set[str] = set()
        for ln in page_lines:
            t = ln.text
            if t and len(t) < 120 and t not in seen:
                counts[t] += 1
                seen.add(t)
    threshold = len(pages) * 0.5
    return {t for t, c in counts.items() if c >= threshold}


def _is_noise(ln: Line, page_height: float, repeated: set[str]) -> bool:
    """Determine if a line is noise that should be stripped."""
    t = ln.text
    if not t:
        return True

    # Standalone page numbers near top or bottom of page
    if _PAGE_NUM.match(t):
        y_mid = (ln.y_top + ln.y_bottom) / 2
        if y_mid < page_height * 0.07 or y_mid > page_height * 0.93:
            return True

    # Repeated headers/footers
    if t in repeated:
        return True

    # TOC filler lines (section name followed by dots and page number)
    if _TOC_DOTS.match(t):
        return True

    return False


# ── Phase 3: Font analysis ───────────────────────────────────────────────────


def _body_font_size(lines: list[Line]) -> float:
    """Find the most common font size (= body text) by character count."""
    counts: Counter[float] = Counter()
    for ln in lines:
        for s in ln.spans:
            t = s.text.strip()
            if t:
                counts[round(s.font_size, 1)] += len(t)
    return counts.most_common(1)[0][0] if counts else 12.0


def _heading_sizes(lines: list[Line], body: float) -> dict[float, int]:
    """
    Map font sizes larger than body to heading levels.

    Returns {font_size: heading_level} where level 1 = largest (#),
    level 2 = next (##), etc., capped at 4.
    """
    sizes: set[float] = set()
    for ln in lines:
        s = ln.dominant_size
        if s > body + 0.5:
            sizes.add(s)
    if not sizes:
        return {}
    ordered = sorted(sizes, reverse=True)
    return {s: min(i + 1, 4) for i, s in enumerate(ordered)}


def _left_margin(lines: list[Line]) -> float:
    """Find the standard left margin (most common x_start position)."""
    xs: Counter[int] = Counter()
    for ln in lines:
        t = ln.text
        if t and len(t) > 20:
            xs[round(ln.x_start / 3) * 3] += 1
    return float(xs.most_common(1)[0][0]) if xs else 50.0


# ── Phase 4: Rendering ───────────────────────────────────────────────────────

# Role constants
_HEADING = "heading"
_SUBHEADING = "subheading"
_LIST = "list"
_SUBLIST = "sublist"
_DEFINITION = "definition"
_BODY = "body"


def _classify(
    ln: Line, body: float, h_map: dict[float, int], margin: float
) -> tuple[str, int]:
    """
    Classify a line's structural role in the document.

    Returns (role, heading_level). heading_level is only meaningful
    when role is HEADING.
    """
    t = ln.text
    if not t:
        return (_BODY, 0)

    size = ln.dominant_size

    # ── Heading by font size ────────────────────────────────────────────
    if size in h_map:
        return (_HEADING, h_map[size])

    # Close match to a known heading size (handles rounding)
    for hs, lv in h_map.items():
        if abs(size - hs) < 0.6:
            return (_HEADING, lv)

    # Bold and measurably larger than body text
    if size > body + 0.3 and ln.is_bold:
        fallback_level = min(len(h_map) + 1, 4) if h_map else 2
        return (_HEADING, fallback_level)

    # ── Bold ALL-CAPS at body size → section heading ────────────────────
    if (
        ln.is_bold
        and abs(size - body) < 1.0
        and _ALL_UPPER.match(t)
        and 5 < len(t) < 200
    ):
        return (_HEADING, 2)

    # ── Bold, body-sized, short line → subheading ───────────────────────
    # e.g. "Physical security", "Legal protection"
    if (
        ln.is_bold
        and abs(size - body) < 1.0
        and len(t) < 80
        and not _SECTION_NUM.match(t)
        and not _BULLET_CHAR.match(t)
        and not _DASH_ITEM.match(t)
    ):
        return (_SUBHEADING, 3)

    # ── List items ──────────────────────────────────────────────────────
    if _BULLET_CHAR.match(t) or _DASH_ITEM.match(t):
        return (_LIST, 0)

    # Indented letter/roman items: a), b), i), ii)
    indent = ln.x_start - margin
    if indent > 12 and _LETTER_ITEM.match(t):
        return (_SUBLIST, 0)

    # ── Definition: bold prefix ending with colon or em-dash ────────────
    bp = ln.get_bold_prefix()
    if bp:
        bold_part = bp[0]
        if ":" in bold_part or bold_part.rstrip().endswith("—"):
            return (_DEFINITION, 0)

    return (_BODY, 0)


def _strip_bullet(t: str) -> str:
    """Remove leading bullet/dash characters from text."""
    t = _BULLET_CHAR.sub("", t)
    t = _DASH_ITEM.sub("", t)
    return t.strip()


def _format_bold_spans(ln: Line) -> str:
    """Reconstruct line text with **bold** markdown markers for mixed-bold lines."""
    all_bold = all(s.is_bold for s in ln.spans if s.text.strip())
    any_bold = any(s.is_bold for s in ln.spans if s.text.strip())

    if not any_bold or all_bold:
        return ln.text

    parts: list[str] = []
    in_bold = False
    for i, s in enumerate(ln.spans):
        should_bold = s.is_bold and s.text.strip()

        if should_bold and not in_bold:
            # Insert space before ** if previous char isn't a space
            if parts and parts[-1] and not parts[-1][-1].isspace():
                # Check gap
                if i > 0:
                    prev = ln.spans[i - 1]
                    if s.x0 - prev.x1 > 2.0:
                        parts.append(" ")
            parts.append("**")
            in_bold = True
        elif not s.is_bold and in_bold:
            parts.append("**")
            in_bold = False
            # Check gap
            if i > 0:
                prev = ln.spans[i - 1]
                if s.x0 - prev.x1 > 2.0 and not s.text.startswith(" "):
                    parts.append(" ")

        parts.append(s.text)

    if in_bold:
        parts.append("**")

    result = "".join(parts).strip()
    # Clean up artifacts
    result = re.sub(r"\*\*\s+\*\*", " ", result)  # merge close-open
    result = result.replace("****", "")  # empty bold
    return result


def _render(
    lines: list[Line],
    body: float,
    h_map: dict[float, int],
    margin: float,
) -> str:
    """Convert classified lines into structured markdown."""
    parts: list[str] = []
    para: list[str] = []  # paragraph accumulator
    prev_role = ""
    prev_text = ""

    def flush():
        nonlocal para
        if para:
            parts.append(" ".join(para))
            parts.append("")
            para = []

    for ln in lines:
        t = ln.text
        if not t:
            continue

        role, level = _classify(ln, body, h_map, margin)

        # ── List-item continuation detection ────────────────────────────
        # If previous was a list item and current is indented body text,
        # append to the last list item instead of starting a new paragraph.
        if role == _BODY and prev_role in (_LIST, _SUBLIST):
            indent = ln.x_start - margin
            if indent > 5 and parts and (
                parts[-1].startswith("- ") or parts[-1].startswith("  ")
            ):
                parts[-1] += " " + t
                prev_text = t
                continue

        if role == _HEADING:
            flush()
            hashes = "#" * level
            parts.append(f"{hashes} {_clean_heading(t)}")
            parts.append("")

        elif role == _SUBHEADING:
            flush()
            parts.append(f"### {t}")
            parts.append("")

        elif role == _LIST:
            flush()
            # Preserve inline bold (e.g. "**Low** - description")
            formatted = _format_bold_spans(ln)
            formatted = _strip_bullet(formatted)
            parts.append(f"- {formatted}")

        elif role == _SUBLIST:
            flush()
            parts.append(f"  {t}")

        elif role == _DEFINITION:
            flush()
            bp = ln.get_bold_prefix()
            if bp:
                bold, rest = bp
                parts.append(f"**{bold}** {rest}")
            else:
                parts.append(t)
            parts.append("")

        else:  # BODY
            if para and not _should_join(prev_text, t, ln, body, margin):
                flush()
            para.append(t)

        prev_role = role
        prev_text = t

    flush()

    out = "\n".join(parts)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def _should_join(prev: str, curr: str, ln: Line, body: float, margin: float) -> bool:
    """Decide if current body line should be joined to the previous paragraph."""
    # New numbered clause → new paragraph
    if _SECTION_NUM.match(curr):
        return False

    # Previous ended with colon → next is likely a list
    if prev.rstrip().endswith(":"):
        return False

    # Different font size → different structural element
    if abs(ln.dominant_size - body) > 1.0:
        return False

    # Bullet or dash → list item, not continuation
    if _BULLET_CHAR.match(curr) or _DASH_ITEM.match(curr):
        return False

    # Significantly indented → probably a list or block quote
    if ln.x_start - margin > 20:
        return False

    return True


def _clean_heading(t: str) -> str:
    """Fix common heading formatting issues."""
    # Missing space after section number: "1.INTRODUCTION" → "1. INTRODUCTION"
    t = re.sub(r"^(\d+\.)\s*([A-Z])", r"\1 \2", t)
    return t


# ── Batch processing & CLI ───────────────────────────────────────────────────


def parse_all_pdfs(data_dir: str | Path, output_dir: str | Path) -> list[Path]:
    """Parse all PDFs in data_dir, write structured markdown to output_dir."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for pdf in sorted(data_dir.glob("*.pdf")):
        print(f"Parsing: {pdf.name}")
        try:
            md = parse_pdf(pdf)
            out = output_dir / f"{pdf.stem}.md"
            out.write_text(md, encoding="utf-8")

            # Report stats
            heading_count = md.count("\n# ") + md.count("\n## ") + md.count("\n### ")
            list_count = md.count("\n- ")
            line_count = len(md.splitlines())
            print(f"  -> {out.name} ({len(md):,} chars, {line_count} lines, "
                  f"{heading_count} headings, {list_count} list items)")
            results.append(out)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Parse a single PDF and print to stdout
        md = parse_pdf(sys.argv[1])
        print(md)
    else:
        # Parse all PDFs in data/ → output/parsed/
        root = Path(__file__).parent.parent
        parse_all_pdfs(root / "data", root / "output" / "parsed")
