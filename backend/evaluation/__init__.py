"""Evaluation package for GEC metrics and benchmark scoring.

This package re-exports legacy helpers from `backend/evaluation.py` so
existing imports keep working while modular code can import from package path.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_legacy_path = Path(__file__).resolve().parent.parent / "evaluation.py"
_spec = spec_from_file_location("backend._legacy_evaluation", _legacy_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Cannot load legacy evaluation module from {_legacy_path}")
_legacy = module_from_spec(_spec)
_spec.loader.exec_module(_legacy)

compute_gec_metrics = _legacy.compute_gec_metrics
compute_bleu = _legacy.compute_bleu
evaluate_correction = _legacy.evaluate_correction

# New modular metrics
from backend.evaluation.metrics import (
    compute_span_overlap,
    match_spans_tolerant,
    evaluate_span_level,
    compute_comprehensive_metrics,
    compute_error_type_accuracy,
    compute_other_ratio,
    evaluate_feedback,
)

__all__ = [
    "compute_gec_metrics",
    "compute_bleu",
    "evaluate_correction",
    "compute_span_overlap",
    "match_spans_tolerant",
    "evaluate_span_level",
    "compute_comprehensive_metrics",
    "compute_error_type_accuracy",
    "compute_other_ratio",
    "evaluate_feedback",
]
