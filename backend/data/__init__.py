"""Data module initialization."""

from backend.data.span_mapper import (
    map_c4200m_to_spans,
    map_conll14_to_spans,
    map_fce_to_spans,
    map_m2_to_spans,
    map_to_error_spans,
)

__all__ = [
    "load_c4_dataset",
    "map_to_error_spans",
    "map_c4200m_to_spans",
    "map_conll14_to_spans",
    "map_fce_to_spans",
    "map_m2_to_spans",
]
