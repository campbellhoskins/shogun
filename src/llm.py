"""Shared LLM utilities for the Shogun pipeline."""

from __future__ import annotations


def thinking_config(model: str, budget_tokens: int = 16384) -> dict:
    """Build a thinking configuration dict appropriate for the given model.

    Opus 4+ models use adaptive thinking (no budget parameter).
    All other models use enabled thinking with an explicit budget.
    """
    if "opus-4" in model:
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": budget_tokens}
