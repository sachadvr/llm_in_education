"""Observability package for ALAO language learning system.

Provides metrics aggregation, error heatmaps, learner trends, and
system-wide analytics for monitoring and improving the learning pipeline.
"""

from backend.observability.metrics import (
    aggregate_errors_by_type,
    compute_learner_heatmap_data,
    compute_learner_trends,
    compute_system_metrics,
    MetricsReport,
)

__all__ = [
    "aggregate_errors_by_type",
    "compute_learner_heatmap_data",
    "compute_learner_trends",
    "compute_system_metrics",
    "MetricsReport",
]
