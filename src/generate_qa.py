"""Standalone script to generate question-answer pairs from a policy document.

Usage:
    uv run python -m src.generate_qa <path_to_document> [output_path]

This script reads a policy document and generates factual question-answer
pairs about its contents. It has no knowledge of or dependency on any
downstream system that may consume these Q&A pairs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from pypdf import PdfReader


def load_document(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


SYSTEM_PROMPT = """\
You are a compliance analyst reviewing a corporate policy document.

Your task: Generate question-answer pairs that thoroughly test someone's understanding of this document.

Create questions that cover:
- Specific rules, thresholds, and numerical values stated in the document
- Actions required when specific situations occur
- Who is responsible for what
- What is permitted vs prohibited
- Escalation chains and approval requirements
- Edge cases and conditional logic ("If X happens, then what?")

For each question:
- The question should be answerable ONLY from the document content
- The answer must be specific and cite concrete details from the document (names, numbers, timeframes, roles)
- Do not ask vague or opinion-based questions
- Vary the difficulty: some should be straightforward lookups, others should require synthesizing information from multiple sections

Return a JSON array of objects with this structure:
[
  {
    "question": "The specific question",
    "answer": "The correct answer based on the document, citing specific details",
    "section": "Which section(s) of the document the answer comes from",
    "difficulty": "easy | medium | hard"
  }
]

Generate as many question-answer pairs as you can — aim for at least 100. Be exhaustive. Cover every section, every rule, every threshold, every role, every conditional. Return ONLY the JSON array."""


def main() -> None:
    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: uv run python -m src.generate_qa <path_to_document> [output_path]")
        sys.exit(1)

    doc_path = Path(sys.argv[1])
    if not doc_path.is_absolute():
        doc_path = Path.cwd() / doc_path

    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else doc_path.with_suffix(".qa.json")

    print(f"Reading: {doc_path.name}")
    text = load_document(doc_path)
    print(f"  {len(text):,} characters")

    print("\nGenerating Q&A pairs (streaming)...")
    client = Anthropic()

    raw = ""
    with client.messages.stream(
        model="claude-opus-4-20250514",
        max_tokens=16384,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Generate question-answer pairs from this document:\n\n{text}",
            }
        ],
    ) as stream:
        for text_chunk in stream.text_stream:
            raw += text_chunk
            # Print a dot every 500 chars to show progress
            if len(raw) % 500 < len(text_chunk):
                print(".", end="", flush=True)
    print()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    qa_pairs = json.loads(raw)

    output_path.write_text(json.dumps(qa_pairs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(qa_pairs)} Q&A pairs to {output_path.name}")

    for i, qa in enumerate(qa_pairs, 1):
        print(f"\n  {i}. [{qa['difficulty']}] {qa['question']}")
        print(f"     A: {qa['answer'][:120]}{'...' if len(qa['answer']) > 120 else ''}")


if __name__ == "__main__":
    main()
