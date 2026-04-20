"""Benchmark package for comparing LLM correction configurations.

Re-exports the benchmark runner and related utilities.
"""

from __future__ import annotations

from backend.benchmark.runner import BenchmarkRunner, BenchmarkConfig

__all__ = ["BenchmarkRunner", "BenchmarkConfig"]
