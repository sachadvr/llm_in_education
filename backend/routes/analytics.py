"""FastAPI router for analytics and observability endpoints.

Provides endpoints for:
- Error heatmap data
- Learner progression trends
- System-wide metrics
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.observability.metrics import (
    aggregate_errors_by_type,
    compute_learner_heatmap_data,
    compute_learner_trends,
    compute_system_metrics,
)
from backend.schemas import (
    ErrorHeatmapResponse,
    LearnerTrendsResponse,
    SystemMetricsResponse,
)
from backend.storage import AsyncSessionLocal

router = APIRouter()
logger = logging.getLogger("mvp")


@router.get("/analytics/error-heatmap", response_model=ErrorHeatmapResponse)
async def error_heatmap():
    """Return aggregated error counts by session and error type for heatmap visualization."""
    try:
        async with AsyncSessionLocal() as session:
            data = await compute_learner_heatmap_data(session)
            return ErrorHeatmapResponse(data=data)
    except Exception:
        logger.exception("Failed to compute error heatmap")
        raise HTTPException(status_code=500, detail="Failed to compute error heatmap")


@router.get("/analytics/learner-trends", response_model=LearnerTrendsResponse)
async def learner_trends(
    user_id: str = Query(..., description="Learner identifier (session_id)"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
):
    """Return daily error/success trends for a specific learner."""
    try:
        async with AsyncSessionLocal() as session:
            trends = await compute_learner_trends(session, user_id=user_id, days=days)
            return LearnerTrendsResponse(user_id=user_id, days=days, trends=trends)
    except Exception:
        logger.exception("Failed to compute learner trends")
        raise HTTPException(status_code=500, detail="Failed to compute learner trends")


@router.get("/analytics/system-metrics", response_model=SystemMetricsResponse)
async def system_metrics():
    """Return system-wide aggregated metrics."""
    try:
        async with AsyncSessionLocal() as session:
            report = await compute_system_metrics(session)
            return SystemMetricsResponse(
                generated_at=report.generated_at,
                period_days=report.period_days,
                total_corrections=report.total_corrections,
                total_quiz_attempts=report.total_quiz_attempts,
                error_counts=report.error_counts,
                accuracy_rate=report.accuracy_rate,
                avg_latency_ms=report.avg_latency_ms,
                confidence_avg=report.confidence_avg,
                top_error_types=report.top_error_types,
                learner_summary=report.learner_summary,
            )
    except Exception:
        logger.exception("Failed to compute system metrics")
        raise HTTPException(status_code=500, detail="Failed to compute system metrics")
