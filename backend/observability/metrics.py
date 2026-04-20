"""Metrics aggregation and analytics for the ALAO observability system.

Provides:
- Error type aggregation from corrections table
- Learner heatmap data from session_stats table
- Learner trend analysis over time
- System-wide metrics computation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from backend.storage import (
    corrections_table,
    quiz_attempts_table,
    session_stats_table,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mvp")


@dataclass
class MetricsReport:
    """System-wide metrics report."""

    generated_at: str = ""
    period_days: int = 30
    total_corrections: int = 0
    total_quiz_attempts: int = 0
    error_counts: dict = field(default_factory=dict)
    accuracy_rate: float = 0.0
    avg_latency_ms: float | None = None
    confidence_avg: float | None = None
    top_error_types: list[dict] = field(default_factory=list)
    learner_summary: dict = field(default_factory=dict)


async def aggregate_errors_by_type(session: AsyncSession) -> dict[str, int]:
    """Aggregate correction counts by error_type.

    Args:
        session: Database session

    Returns:
        Dict mapping error_type to count
    """
    query = select(
        corrections_table.c.error_type,
        func.count(corrections_table.c.id).label("count"),
    ).group_by(corrections_table.c.error_type)

    result = await session.execute(query)
    rows = result.fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        error_type = row.error_type
        count = row.count
        counts[error_type] = count

    return counts


async def compute_learner_heatmap_data(session: AsyncSession) -> list[dict]:
    """Compute per-session error counts for heatmap visualization.

    Args:
        session: Database session

    Returns:
        List of dicts with session_id, error_type, count
    """
    query = select(
        session_stats_table.c.session_id,
        session_stats_table.c.error_tense,
        session_stats_table.c.error_agreement,
        session_stats_table.c.error_article,
        session_stats_table.c.error_preposition,
        session_stats_table.c.error_spelling,
        session_stats_table.c.error_word_choice,
        session_stats_table.c.error_punctuation,
        session_stats_table.c.error_syntax,
        session_stats_table.c.error_redundancy,
        session_stats_table.c.error_other,
    )

    result = await session.execute(query)
    rows = result.fetchall()

    data: list[dict] = []
    error_type_columns = [
        ("tense", "error_tense"),
        ("agreement", "error_agreement"),
        ("article", "error_article"),
        ("preposition", "error_preposition"),
        ("spelling", "error_spelling"),
        ("word_choice", "error_word_choice"),
        ("punctuation", "error_punctuation"),
        ("syntax", "error_syntax"),
        ("redundancy", "error_redundancy"),
        ("other", "error_other"),
    ]

    for row in rows:
        session_id = row.session_id
        for error_type, col_name in error_type_columns:
            count = getattr(row, col_name, 0) or 0
            if count > 0:
                data.append({
                    "session_id": session_id,
                    "error_type": error_type,
                    "count": count,
                })

    return data


async def compute_learner_trends(
    session: AsyncSession,
    user_id: str,
    days: int = 30,
) -> list[dict]:
    """Compute daily error/success trends for a learner.

    Args:
        session: Database session
        user_id: Learner identifier (session_id)
        days: Number of days to look back

    Returns:
        List of daily trend dicts
    """
    # Query session stats for this user
    query = select(session_stats_table).where(
        session_stats_table.c.session_id == user_id
    )

    result = await session.execute(query)
    rows = result.fetchall()

    if not rows:
        return []

    trends: list[dict] = []
    for row in rows:
        total_attempts = row.total_attempts or 0
        success_count = row.success_count or 0
        error_count = total_attempts - success_count

        error_breakdown = {
            "tense": row.error_tense or 0,
            "agreement": row.error_agreement or 0,
            "article": row.error_article or 0,
            "preposition": row.error_preposition or 0,
            "spelling": row.error_spelling or 0,
            "word_choice": row.error_word_choice or 0,
            "punctuation": row.error_punctuation or 0,
            "syntax": row.error_syntax or 0,
            "redundancy": row.error_redundancy or 0,
            "other": row.error_other or 0,
        }

        trends.append({
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "total_attempts": total_attempts,
            "success_count": success_count,
            "error_count": error_count,
            "error_breakdown": error_breakdown,
        })

    return trends


async def compute_system_metrics(session: AsyncSession) -> MetricsReport:
    """Compute system-wide aggregated metrics.

    Args:
        session: Database session

    Returns:
        MetricsReport with aggregated statistics
    """
    report = MetricsReport()
    report.generated_at = datetime.utcnow().isoformat() + "Z"
    report.period_days = 30

    # Total corrections
    corr_query = select(func.count(corrections_table.c.id))
    corr_result = await session.execute(corr_query)
    report.total_corrections = corr_result.scalar() or 0

    # Total quiz attempts
    quiz_query = select(func.count(quiz_attempts_table.c.id))
    quiz_result = await session.execute(quiz_query)
    report.total_quiz_attempts = quiz_result.scalar() or 0

    # Error counts by type from corrections
    report.error_counts = await aggregate_errors_by_type(session)

    # Quiz accuracy
    if report.total_quiz_attempts > 0:
        correct_query = select(func.count(quiz_attempts_table.c.id)).where(
            quiz_attempts_table.c.correct == True  # noqa: E712
        )
        correct_result = await session.execute(correct_query)
        correct_count = correct_result.scalar() or 0
        report.accuracy_rate = round(correct_count / report.total_quiz_attempts, 4)

    # Top error types
    if report.error_counts:
        sorted_types = sorted(
            report.error_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        report.top_error_types = [
            {"error_type": et, "count": cnt} for et, cnt in sorted_types[:5]
        ]

    # Learner summary
    session_query = select(func.count(session_stats_table.c.session_id))
    session_result = await session.execute(session_query)
    active_sessions = session_result.scalar() or 0

    total_attempts_query = select(func.sum(session_stats_table.c.total_attempts))
    total_attempts_result = await session.execute(total_attempts_query)
    total_attempts = total_attempts_result.scalar() or 0

    total_success_query = select(func.sum(session_stats_table.c.success_count))
    total_success_result = await session.execute(total_success_query)
    total_success = total_success_result.scalar() or 0

    report.learner_summary = {
        "active_sessions": active_sessions,
        "total_attempts": int(total_attempts),
        "total_success": int(total_success),
        "overall_success_rate": (
            round(total_success / total_attempts, 4) if total_attempts > 0 else 0.0
        ),
    }

    return report
