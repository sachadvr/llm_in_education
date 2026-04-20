"""Token-level diff helpers."""

from __future__ import annotations

from backend.text_utils import compute_diff


def diff_tokens(original: str, corrected: str) -> list[dict]:
    """Return token-level diff spans."""
    return compute_diff(original, corrected)
