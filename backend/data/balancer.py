"""Dataset balancing module for stratified resampling.

Provides tools to balance dataset across error types using
upsampling, downsampling, and proportional strategies.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from typing import Any

from backend.data.validation import compute_error_type_distribution

logger = logging.getLogger("mvp")

# Default strategies
BALANCING_STRATEGIES = {"proportional", "equal", "median", "none"}


from dataclasses import dataclass, field


@dataclass
class BalancingReport:
    """Report from dataset balancing operation."""

    original_counts: dict[str, int] = field(default_factory=dict)
    final_counts: dict[str, int] = field(default_factory=dict)
    removed_rows: int = 0
    duplicated_rows: int = 0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "original_counts": self.original_counts,
            "final_counts": self.final_counts,
            "removed_rows": self.removed_rows,
            "duplicated_rows": self.duplicated_rows,
            "issues": self.issues,
        }


def stratified_sample(
    dataset_rows: list[dict],
    target_counts: dict[str, int] | None = None,
    target_ratio: dict[str, float] | None = None,
    random_seed: int | None = None,
) -> tuple[list[dict], BalancingReport]:
    """Perform stratified sampling to balance error types.

    Args:
        dataset_rows: List of dataset row dicts with 'error_type_gold' field
        target_counts: Target count per error type (absolute)
        target_ratio: Target ratio per error type (relative, sums to 1.0)
        random_seed: Optional random seed for reproducibility

    Returns:
        Tuple of (balanced_rows, report)
    """
    if random_seed is not None:
        random.seed(random_seed)

    report = BalancingReport()

    if not dataset_rows:
        report.issues.append("Dataset is empty")
        return [], report

    # Group rows by error type
    type_groups: dict[str, list[dict]] = {}
    for row in dataset_rows:
        error_type = row.get("error_type_gold", "unknown")
        type_groups.setdefault(error_type, []).append(row)

    report.original_counts = {et: len(rows) for et, rows in type_groups.items()}

    # Determine target counts
    if target_counts is None and target_ratio is not None:
        total = len(dataset_rows)
        target_counts = {
            et: max(1, int(total * ratio)) for et, ratio in target_ratio.items()
        }
    elif target_counts is None:
        # Default: balance to the average count
        avg_count = len(dataset_rows) // max(len(type_groups), 1)
        target_counts = {et: avg_count for et in type_groups}

    balanced_rows: list[dict] = []

    for error_type, rows in type_groups.items():
        target = target_counts.get(error_type, 0)
        if target <= 0:
            report.removed_rows += len(rows)
            continue

        current_count = len(rows)

        if current_count > target:
            # Undersample
            sampled = random.sample(rows, target)
            balanced_rows.extend(sampled)
            report.removed_rows += current_count - target
        elif current_count < target:
            # Oversample with replacement
            needed = target - current_count
            oversampled = rows + random.choices(rows, k=needed)
            balanced_rows.extend(oversampled)
            report.duplicated_rows += needed
        else:
            balanced_rows.extend(rows)

    # Compute final counts
    final_groups: dict[str, list[dict]] = {}
    for row in balanced_rows:
        error_type = row.get("error_type_gold", "unknown")
        final_groups.setdefault(error_type, []).append(row)
    report.final_counts = {et: len(rows) for et, rows in final_groups.items()}

    return balanced_rows, report


def balance_by_undersampling_majority(
    dataset_rows: list[dict],
    max_ratio: float = 2.0,
    random_seed: int | None = None,
) -> tuple[list[dict], BalancingReport]:
    """Balance dataset by undersampling majority classes.

    Reduces majority classes so no class is more than max_ratio times
    larger than the smallest class.

    Args:
        dataset_rows: List of dataset row dicts
        max_ratio: Maximum allowed ratio between largest and smallest class
        random_seed: Optional random seed

    Returns:
        Tuple of (balanced_rows, report)
    """
    if random_seed is not None:
        random.seed(random_seed)

    report = BalancingReport()

    if not dataset_rows:
        report.issues.append("Dataset is empty")
        return [], report

    # Group by error type
    type_groups: dict[str, list[dict]] = {}
    for row in dataset_rows:
        error_type = row.get("error_type_gold", "unknown")
        type_groups.setdefault(error_type, []).append(row)

    report.original_counts = {et: len(rows) for et, rows in type_groups.items()}

    if not type_groups:
        report.issues.append("No valid error types found")
        return [], report

    min_count = min(len(rows) for rows in type_groups.values())
    max_allowed = int(min_count * max_ratio)

    balanced_rows: list[dict] = []

    for error_type, rows in type_groups.items():
        current_count = len(rows)
        if current_count > max_allowed:
            sampled = random.sample(rows, max_allowed)
            balanced_rows.extend(sampled)
            report.removed_rows += current_count - max_allowed
        else:
            balanced_rows.extend(rows)

    # Compute final counts
    final_groups: dict[str, list[dict]] = {}
    for row in balanced_rows:
        error_type = row.get("error_type_gold", "unknown")
        final_groups.setdefault(error_type, []).append(row)
    report.final_counts = {et: len(rows) for et, rows in final_groups.items()}

    return balanced_rows, report


def balance_by_oversampling_minority(
    dataset_rows: list[dict],
    target_count: int | None = None,
    random_seed: int | None = None,
) -> tuple[list[dict], BalancingReport]:
    """Balance dataset by oversampling minority classes.

    Increases minority classes to match the target count (or max class size).

    Args:
        dataset_rows: List of dataset row dicts
        target_count: Target count for all classes (None = use max class size)
        random_seed: Optional random seed

    Returns:
        Tuple of (balanced_rows, report)
    """
    if random_seed is not None:
        random.seed(random_seed)

    report = BalancingReport()

    if not dataset_rows:
        report.issues.append("Dataset is empty")
        return [], report

    # Group by error type
    type_groups: dict[str, list[dict]] = {}
    for row in dataset_rows:
        error_type = row.get("error_type_gold", "unknown")
        type_groups.setdefault(error_type, []).append(row)

    report.original_counts = {et: len(rows) for et, rows in type_groups.items()}

    if target_count is None:
        target_count = max(len(rows) for rows in type_groups.values())

    balanced_rows: list[dict] = []

    for error_type, rows in type_groups.items():
        current_count = len(rows)
        if current_count < target_count:
            needed = target_count - current_count
            oversampled = rows + random.choices(rows, k=needed)
            balanced_rows.extend(oversampled)
            report.duplicated_rows += needed
        else:
            balanced_rows.extend(rows)

    # Compute final counts
    final_groups: dict[str, list[dict]] = {}
    for row in balanced_rows:
        error_type = row.get("error_type_gold", "unknown")
        final_groups.setdefault(error_type, []).append(row)
    report.final_counts = {et: len(rows) for et, rows in final_groups.items()}

    return balanced_rows, report


def compute_target_counts(
    error_type_counts: dict[str, int],
    strategy: str = "proportional",
    total_target: int | None = None,
) -> dict[str, int]:
    """Calculate target counts per error type for balancing.

    Strategies:
    - 'proportional': Maintain relative proportions but cap extremes
    - 'equal': All types get the same count (total_target / num_types)
    - 'median': All types get the median count

    Args:
        error_type_counts: Current error type distribution
        strategy: Balancing strategy to use
        total_target: Total number of samples desired (default: sum of current counts)

    Returns:
        Dict mapping error type to target count
    """
    if strategy not in BALANCING_STRATEGIES:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Choose from: {BALANCING_STRATEGIES}"
        )

    if not error_type_counts:
        return {}

    if strategy == "none":
        return error_type_counts.copy()

    total_current = sum(error_type_counts.values())
    num_types = len(error_type_counts)

    if total_target is None:
        total_target = total_current

    if strategy == "equal":
        target_per_type = total_target // num_types
        remainder = total_target % num_types
        targets = {
            error_type: target_per_type for error_type in error_type_counts
        }
        # Distribute remainder
        for i, error_type in enumerate(sorted(targets.keys())):
            if i < remainder:
                targets[error_type] += 1
        return targets

    elif strategy == "median":
        sorted_counts = sorted(error_type_counts.values())
        median = sorted_counts[len(sorted_counts) // 2]
        return {error_type: median for error_type in error_type_counts}

    elif strategy == "proportional":
        # Proportional but with smoothing to avoid extreme imbalances
        # Use a combination of current proportion and equal distribution
        alpha = 0.7  # Weight for current proportion (0=fully equal, 1=fully proportional)
        base_target = total_target / num_types

        targets = {}
        for error_type, count in error_type_counts.items():
            proportion = count / total_current if total_current > 0 else 1 / num_types
            # Blend between equal and proportional
            blended = alpha * (proportion * total_target) + (1 - alpha) * base_target
            targets[error_type] = max(1, int(round(blended)))

        # Adjust to match total_target
        current_total = sum(targets.values())
        diff = total_target - current_total
        if diff != 0:
            # Adjust largest/smallest types
            sorted_types = sorted(targets.keys(), key=lambda t: targets[t])
            if diff > 0:
                for i in range(diff):
                    targets[sorted_types[i % len(sorted_types)]] += 1
            else:
                for i in range(abs(diff)):
                    idx = len(sorted_types) - 1 - (i % len(sorted_types))
                    t = sorted_types[idx]
                    if targets[t] > 1:
                        targets[t] -= 1

        return targets

    return error_type_counts.copy()


def upsample_minority_types(
    rows: list[dict],
    min_count: int = 10,
    random_seed: int = 42,
) -> list[dict]:
    """Upsample underrepresented error types by duplicating rows.

    Args:
        rows: List of dataset row dicts
        min_count: Minimum count per error type
        random_seed: Seed for deterministic shuffling

    Returns:
        List of rows with upsampled minority types
    """
    if not rows:
        return []

    rng = random.Random(random_seed)

    # Group rows by error type
    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        error_type = row.get("error_type_gold", "unknown")
        type_buckets[error_type].append(row)

    balanced_rows: list[dict] = []

    for error_type, bucket in type_buckets.items():
        if len(bucket) >= min_count:
            balanced_rows.extend(bucket)
            continue

        # Upsample by duplication with slight variation
        current_count = len(bucket)
        multiplier = (min_count + current_count - 1) // current_count  # Ceiling division

        upsampled = []
        for i in range(multiplier):
            for row in bucket:
                # Create a copy to avoid modifying original
                new_row = row.copy()
                # Add metadata to track synthetic samples
                new_row["_synthetic"] = True
                new_row["_original_id"] = row.get("id", None)
                upsampled.append(new_row)

        # Trim to exactly min_count
        balanced_rows.extend(upsampled[:min_count])
        logger.info(
            f"Upsampled '{error_type}' from {current_count} to {min_count}"
        )

    # Shuffle to mix types
    rng.shuffle(balanced_rows)
    return balanced_rows


def downsample_majority_types(
    rows: list[dict],
    max_count: int = 100,
    random_seed: int = 42,
) -> list[dict]:
    """Downsample overrepresented error types by random selection.

    Args:
        rows: List of dataset row dicts
        max_count: Maximum count per error type
        random_seed: Seed for deterministic sampling

    Returns:
        List of rows with downsampled majority types
    """
    if not rows:
        return []

    rng = random.Random(random_seed)

    # Group rows by error type
    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        error_type = row.get("error_type_gold", "unknown")
        type_buckets[error_type].append(row)

    balanced_rows: list[dict] = []

    for error_type, bucket in type_buckets.items():
        if len(bucket) <= max_count:
            balanced_rows.extend(bucket)
            continue

        # Random downsample
        downsampled = rng.sample(bucket, max_count)
        balanced_rows.extend(downsampled)
        logger.info(
            f"Downsampled '{error_type}' from {len(bucket)} to {max_count}"
        )

    # Shuffle to mix types
    rng.shuffle(balanced_rows)
    return balanced_rows


def balance_dataset(
    rows: list[dict],
    target_per_type: dict[str, int] | None = None,
    strategy: str = "proportional",
    total_target: int | None = None,
    random_seed: int = 42,
) -> list[dict]:
    """Balance dataset using stratified resampling.

    If target_per_type is provided, uses those exact targets.
    Otherwise, computes targets using the specified strategy.

    Args:
        rows: List of dataset row dicts
        target_per_type: Optional explicit target counts per error type
        strategy: Balancing strategy if target_per_type not provided
        total_target: Total number of samples desired
        random_seed: Seed for deterministic sampling

    Returns:
        List of balanced rows
    """
    if not rows:
        return []

    rng = random.Random(random_seed)

    # Compute target counts if not provided
    if target_per_type is None:
        error_type_counts = compute_error_type_distribution(rows)
        target_per_type = compute_target_counts(
            error_type_counts, strategy=strategy, total_target=total_target
        )

    # Group rows by error type
    type_buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        error_type = row.get("error_type_gold", "unknown")
        type_buckets[error_type].append(row)

    balanced_rows: list[dict] = []

    for error_type, target in target_per_type.items():
        bucket = type_buckets.get(error_type, [])
        current_count = len(bucket)

        if current_count == 0:
            logger.warning(f"No rows found for error type '{error_type}'")
            continue

        if current_count >= target:
            # Downsample
            selected = rng.sample(bucket, target)
            balanced_rows.extend(selected)
        else:
            # Upsample with duplication
            selected = []
            for i in range(target):
                row = bucket[i % current_count].copy()
                row["_synthetic"] = True
                row["_original_id"] = bucket[i % current_count].get("id", None)
                selected.append(row)
            balanced_rows.extend(selected)

        logger.info(
            f"Balanced '{error_type}': {current_count} -> {target}"
        )

    # Shuffle to mix types
    rng.shuffle(balanced_rows)
    return balanced_rows


def get_balance_stats(rows: list[dict]) -> dict[str, Any]:
    """Get statistics about dataset balance.

    Args:
        rows: List of dataset row dicts

    Returns:
        Dict with balance statistics
    """
    if not rows:
        return {
            "total": 0,
            "num_types": 0,
            "type_counts": {},
            "imbalance_ratio": 0.0,
            "is_balanced": True,
        }

    type_counts = compute_error_type_distribution(rows)
    if not type_counts:
        return {
            "total": len(rows),
            "num_types": 0,
            "type_counts": {},
            "imbalance_ratio": 0.0,
            "is_balanced": True,
        }

    counts = list(type_counts.values())
    max_count = max(counts)
    min_count = min(counts)
    mean_count = sum(counts) / len(counts)

    # Coefficient of variation as imbalance metric
    if mean_count > 0:
        std = (
            sum((c - mean_count) ** 2 for c in counts) / len(counts)
        ) ** 0.5
        cv = std / mean_count
    else:
        cv = 0.0

    # Imbalance ratio: max / min (handle division by zero)
    imbalance_ratio = max_count / min_count if min_count > 0 else float("inf")

    # Consider balanced if CV < 0.5 and ratio < 3
    is_balanced = cv < 0.5 and imbalance_ratio < 3.0

    return {
        "total": len(rows),
        "num_types": len(type_counts),
        "type_counts": type_counts,
        "imbalance_ratio": imbalance_ratio,
        "coefficient_of_variation": round(cv, 3),
        "is_balanced": is_balanced,
    }
