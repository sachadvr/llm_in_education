"""Tokenization helpers for learner sentences."""

from __future__ import annotations

from backend.text_utils import tokenize


def tokenize_text(text: str) -> list[str]:
    """Split text into deterministic tokens."""
    return tokenize(text)
