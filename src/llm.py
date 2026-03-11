"""Shared LLM utilities for the Shogun pipeline."""

from __future__ import annotations

from src.models import Relationship


def deduplicate_relationships(
    existing: list[Relationship],
    new: list[Relationship],
) -> tuple[list[Relationship], int]:
    """Merge new relationships into existing, deduplicating by (source_id, target_id, type).

    Returns (combined list, number of duplicates skipped).
    """
    seen: set[tuple[str, str, str]] = {
        (r.source_id, r.target_id, r.type) for r in existing
    }
    combined = list(existing)
    dupes = 0
    for r in new:
        key = (r.source_id, r.target_id, r.type)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        combined.append(r)
    return combined, dupes


def thinking_config(model: str, budget_tokens: int = 16384) -> dict:
    """Build a thinking configuration dict appropriate for the given model.

    Opus 4+ models use adaptive thinking (no budget parameter).
    All other models use enabled thinking with an explicit budget.
    """
    if "opus-4" in model:
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": budget_tokens}
