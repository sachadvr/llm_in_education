"""Dataset validation module for annotation quality checks.

Provides tools to validate dataset annotations, check span coverage,
analyze error type distributions, and verify train/test split balance.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from backend.text_utils import compute_diff, tokenize

logger = logging.getLogger("mvp")

# Expected error types in the dataset
EXPECTED_ERROR_TYPES = {
    "tense",
    "agreement",
    "article",
    "preposition",
    "spelling",
    "word_choice",
    "punctuation",
    "syntax",
    "redundancy",
    "other",
    "none",
    "deletion",
    "insertion",
}

# Recommended train/test split ratio
RECOMMENDED_TRAIN_RATIO = 0.8
SPLIT_TOLERANCE = 0.1  # Allow 10% deviation from recommended ratio


@dataclass
class DatasetValidationReport:
    """Report from dataset validation."""

    total_rows: int = 0
    error_type_counts: dict[str, int] = field(default_factory=dict)
    split_ratio: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "total_rows": self.total_rows,
            "error_type_counts": self.error_type_counts,
            "split_ratio": self.split_ratio,
            "issues": self.issues,
            "is_valid": len(self.issues) == 0,
        }

    def __str__(self) -> str:
        lines = [
            f"Dataset Validation Report",
            f"========================",
            f"Total rows: {self.total_rows}",
            f"",
            f"Error type distribution:",
        ]
        for error_type, count in sorted(self.error_type_counts.items()):
            pct = (count / self.total_rows * 100) if self.total_rows > 0 else 0
            lines.append(f"  {error_type}: {count} ({pct:.1f}%)")
        lines.append("")
        lines.append("Split ratio:")
        for split, ratio in sorted(self.split_ratio.items()):
            lines.append(f"  {split}: {ratio:.2%}")
        lines.append("")
        if self.issues:
            lines.append(f"Issues found ({len(self.issues)}):")
            for issue in self.issues:
                lines.append(f"  - {issue}")
        else:
            lines.append("No issues found. Dataset is valid.")
        return "\n".join(lines)


def validate_annotations(dataset_rows: list[dict]) -> list[str]:
    """Validate annotation quality for dataset rows.

    Checks:
    - Required fields present (input_phrase, corrected_gold, error_type_gold)
    - Input and corrected phrases are different (unless error_type is 'none')
    - Error type is in expected set
    - Spans are valid JSON (if present)
    - Span coverage matches actual differences

    Args:
        dataset_rows: List of dataset row dicts

    Returns:
        List of issue descriptions
    """
    issues: list[str] = []

    for i, row in enumerate(dataset_rows):
        row_id = row.get("id", f"row_{i}")
        prefix = f"Row {row_id}:"

        # Check required fields
        required_fields = ["input_phrase", "corrected_gold", "error_type_gold"]
        for field_name in required_fields:
            if field_name not in row or row[field_name] is None:
                issues.append(f"{prefix} Missing required field '{field_name}'")
                continue

        input_phrase = row.get("input_phrase", "")
        corrected_gold = row.get("corrected_gold", "")
        error_type = row.get("error_type_gold", "")

        # Check error type is valid
        if error_type and error_type not in EXPECTED_ERROR_TYPES:
            issues.append(
                f"{prefix} Unknown error type '{error_type}'. Expected one of: {EXPECTED_ERROR_TYPES}"
            )

        # Check input and corrected are different (unless error_type is 'none')
        if error_type != "none":
            if not input_phrase or not corrected_gold:
                issues.append(f"{prefix} Empty input or corrected phrase")
            elif input_phrase.strip().lower() == corrected_gold.strip().lower():
                issues.append(
                    f"{prefix} Input and corrected are identical but error_type is not 'none'"
                )

        # Validate spans if present
        spans_str = row.get("error_spans_gold")
        if spans_str:
            try:
                spans = json.loads(spans_str) if isinstance(spans_str, str) else spans_str
                if not isinstance(spans, list):
                    issues.append(f"{prefix} error_spans_gold is not a list")
                else:
                    span_issues = check_span_coverage(input_phrase, corrected_gold, spans)
                    for issue in span_issues:
                        issues.append(f"{prefix} {issue}")
            except json.JSONDecodeError:
                issues.append(f"{prefix} error_spans_gold is not valid JSON")

    return issues


def check_span_coverage(
    original: str, corrected: str, spans: list[dict]
) -> list[str]:
    """Verify that spans cover actual differences between original and corrected.

    Compares the provided spans against a computed diff to ensure:
    - All actual differences are covered by spans
    - Spans don't cover non-different regions
    - Span positions are within bounds

    Args:
        original: Original sentence
        corrected: Corrected sentence
        spans: List of error span dicts with start, end, start_char, end_char

    Returns:
        List of issue descriptions
    """
    issues: list[str] = []

    if not original or not corrected:
        return issues

    # Compute expected diffs
    expected_spans = compute_diff(original, corrected)

    # Extract changed regions from expected spans
    expected_changed_tokens: set[int] = set()
    for span in expected_spans:
        if span.get("tag") != "equal":
            for i in range(span.get("start", 0), span.get("end", 0)):
                expected_changed_tokens.add(i)

    # Extract changed regions from provided spans
    provided_changed_tokens: set[int] = set()
    for span in spans:
        if not isinstance(span, dict):
            issues.append(f"Span is not a dict: {span}")
            continue

        # Check required fields
        if "start" not in span or "end" not in span:
            issues.append(f"Span missing start/end: {span}")
            continue

        start = span.get("start", 0)
        end = span.get("end", 0)

        # Validate bounds
        orig_tokens = tokenize(original)
        if start < 0 or end > len(orig_tokens):
            issues.append(
                f"Span out of bounds: start={start}, end={end}, token_count={len(orig_tokens)}"
            )
            continue

        # Check character positions if present
        start_char = span.get("start_char")
        end_char = span.get("end_char")
        if start_char is not None and end_char is not None:
            if start_char < 0 or end_char > len(original):
                issues.append(
                    f"Span char positions out of bounds: start_char={start_char}, end_char={end_char}, text_len={len(original)}"
                )
            elif end_char <= start_char:
                issues.append(
                    f"Span has invalid char range: start_char={start_char}, end_char={end_char}"
                )

        # Add to provided changed tokens
        if span.get("tag") != "equal":
            for i in range(start, end):
                provided_changed_tokens.add(i)

    # Check coverage: are all expected changes covered?
    missing = expected_changed_tokens - provided_changed_tokens
    if missing:
        issues.append(
            f"Missing spans for tokens at indices: {sorted(missing)}"
        )

    # Check for extra spans (covering non-changed regions)
    extra = provided_changed_tokens - expected_changed_tokens
    if extra:
        issues.append(
            f"Spans cover non-changed tokens at indices: {sorted(extra)}"
        )

    return issues


def compute_error_type_distribution(dataset_rows: list[dict]) -> dict[str, int]:
    """Compute error type distribution from dataset rows.

    Args:
        dataset_rows: List of dataset row dicts

    Returns:
        Dict mapping error type to count
    """
    if not dataset_rows:
        return {}

    type_counts: Counter[str] = Counter()
    for row in dataset_rows:
        error_type = row.get("error_type_gold", "unknown")
        if error_type:
            type_counts[error_type] += 1

    return dict(type_counts)


def validate_dataset_split_balance(rows: list[dict]) -> list[str]:
    """Validate train/test split ratio.

    Checks that the dataset has a reasonable train/test split.

    Args:
        rows: List of dataset row dicts with 'dataset_split' field

    Returns:
        List of issue descriptions
    """
    issues: list[str] = []

    if not rows:
        issues.append("Dataset is empty")
        return issues

    split_counts: Counter[str] = Counter()
    for row in rows:
        split = row.get("dataset_split", "unknown")
        if split:
            split_counts[split] += 1

    total = len(rows)
    train_count = split_counts.get("train", 0)
    test_count = split_counts.get("test", 0)
    unknown_count = split_counts.get("unknown", 0)

    if unknown_count > 0:
        issues.append(f"{unknown_count} rows have no dataset_split assigned")

    if train_count == 0:
        issues.append("No training data found (dataset_split='train')")
    if test_count == 0:
        issues.append("No test data found (dataset_split='test')")

    if train_count > 0 and test_count > 0:
        train_ratio = train_count / (train_count + test_count)
        if abs(train_ratio - RECOMMENDED_TRAIN_RATIO) > SPLIT_TOLERANCE:
            issues.append(
                f"Train/test split is unbalanced: {train_ratio:.2%} train, "
                f"{1 - train_ratio:.2%} test (recommended: {RECOMMENDED_TRAIN_RATIO:.0%} train)"
            )

    # Check if any split is too small
    min_split_size = max(10, total * 0.05)  # At least 5% or 10 rows
    if train_count > 0 and train_count < min_split_size:
        issues.append(f"Training set is very small: {train_count} rows")
    if test_count > 0 and test_count < min_split_size:
        issues.append(f"Test set is very small: {test_count} rows")

    return issues


def generate_validation_report(dataset_rows: list[dict]) -> DatasetValidationReport:
    """Generate a complete validation report for a dataset.

    Args:
        dataset_rows: List of dataset row dicts

    Returns:
        DatasetValidationReport with all validation results
    """
    report = DatasetValidationReport()
    report.total_rows = len(dataset_rows)
    report.error_type_counts = compute_error_type_distribution(dataset_rows)
    report.issues = validate_annotations(dataset_rows)
    report.issues.extend(validate_dataset_split_balance(dataset_rows))

    # Compute split ratio
    split_counts: Counter[str] = Counter()
    for row in dataset_rows:
        split = row.get("dataset_split", "unknown")
        if split:
            split_counts[split] += 1

    total = len(dataset_rows)
    report.split_ratio = {
        split: count / total for split, count in split_counts.items() if total > 0
    }

    # Check for severely imbalanced error types
    if report.error_type_counts:
        max_count = max(report.error_type_counts.values())
        min_count = min(report.error_type_counts.values())
        if max_count > 0 and min_count / max_count < 0.1:
            report.issues.append(
                f"Error types are severely imbalanced: max={max_count}, min={min_count} "
                f"(ratio {min_count/max_count:.2f})"
            )

    return report
