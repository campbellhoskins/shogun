"""
PDF Structure Parser for Shogun — Parser 2 (pymupdf4llm)

Converts PDF policy documents into structured markdown using pymupdf4llm,
a battle-tested LLM-optimized markdown extractor built on PyMuPDF.

Strengths: table detection, link preservation, italic handling, minimal code.
Weaknesses: misses bold ALL-CAPS section headings at body font size, does not
strip page numbers, repeated headers/footers, or TOC dot-fillers.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf4llm


def parse_pdf(pdf_path: str | Path) -> str:
    """
    Parse a PDF into structured markdown preserving document hierarchy.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Structured markdown text optimized for LLM consumption.
    """
    md = pymupdf4llm.to_markdown(
        str(pdf_path),
        page_chunks=False,
        show_progress=False,
    )
    return md


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

            heading_count = (
                md.count("\n# ") + md.count("\n## ") + md.count("\n### ")
            )
            list_count = md.count("\n- ")
            line_count = len(md.splitlines())
            print(
                f"  -> {out.name} ({len(md):,} chars, {line_count} lines, "
                f"{heading_count} headings, {list_count} list items)"
            )
            results.append(out)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback

            traceback.print_exc()

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        md = parse_pdf(sys.argv[1])
        print(md)
    else:
        root = Path(__file__).parent.parent
        parse_all_pdfs(root / "data", root / "output" / "parsed")
