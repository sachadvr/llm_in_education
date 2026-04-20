"""Adaptivity module for personalized learning progression tracking."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.storage import AsyncSessionLocal, learner_progression_table

logger = logging.getLogger("mvp")

# Configuration constants
LAMBDA_DECAY = 0.1  # Exponential decay rate (configurable)
DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 5

# Ebbinghaus-inspired spaced repetition intervals (in days)
SPACED_REPETITION_INTERVALS = [1, 3, 7, 14, 30]


@dataclass
class LearnerProgression:
    """Represents a learner's progression for a specific error type."""
    user_id: str
    error_type: str
    count: int = 1
    last_seen: datetime = field(default_factory=datetime.utcnow)
    weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: Optional[int] = None


def calculate_error_weight(
    count: int,
    last_seen: datetime,
    lambda_decay: float = LAMBDA_DECAY,
    reference_time: Optional[datetime] = None,
) -> float:
    """Calculate weighted error score using exponential decay."""
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    
    # Ensure both datetimes are offset-aware for comparison
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    
    # Calculate days since last seen
    days_since = (reference_time - last_seen).total_seconds() / (24 * 3600)
    days_since = max(0, days_since)  # Ensure non-negative
    
    # Apply exponential decay
    weight = count * math.exp(-lambda_decay * days_since)
    
    return round(weight, 4)


async def track_error(
    user_id: str,
    error_type: str,
    session: Optional[AsyncSession] = None,
) -> LearnerProgression:
    """Record an error occurrence for a learner."""
    now = datetime.now(timezone.utc)
    
    # Use provided session or create new one
    if session is not None:
        return await _track_error_with_session(user_id, error_type, now, session)
    
    async with AsyncSessionLocal() as session:
        return await _track_error_with_session(user_id, error_type, now, session)


async def _track_error_with_session(
    user_id: str,
    error_type: str,
    now: datetime,
    session: AsyncSession,
) -> LearnerProgression:
    """Internal helper to track error with existing session.

    When an error occurs, mastery resets to 0 and next review is scheduled
    for 1 day from now (first interval).
    """
    next_review = now + timedelta(days=SPACED_REPETITION_INTERVALS[0])

    query = select(learner_progression_table).where(
        (learner_progression_table.c.user_id == user_id) &
        (learner_progression_table.c.error_type == error_type)
    )
    result = await session.execute(query)
    row = result.fetchone()

    if row:
        new_count = row.count + 1
        new_weight = calculate_error_weight(new_count, now, reference_time=now)

        await session.execute(
            update(learner_progression_table)
            .where(learner_progression_table.c.id == row.id)
            .values(
                count=new_count,
                last_seen=now,
                weight=new_weight,
                mastery_level=0,
                next_review_at=next_review,
            )
        )
        await session.commit()

        return LearnerProgression(
            id=row.id,
            user_id=user_id,
            error_type=error_type,
            count=new_count,
            last_seen=now,
            weight=new_weight,
            created_at=row.created_at,
        )
    else:
        insert_result = await session.execute(
            insert(learner_progression_table).values(
                user_id=user_id,
                error_type=error_type,
                count=1,
                last_seen=now,
                weight=1.0,
                mastery_level=0,
                next_review_at=next_review,
                created_at=now,
            )
        )
        await session.commit()

        return LearnerProgression(
            id=insert_result.inserted_primary_key[0] if insert_result.inserted_primary_key else None,
            user_id=user_id,
            error_type=error_type,
            count=1,
            last_seen=now,
            weight=1.0,
            created_at=now,
        )


async def get_frequent_errors(
    user_id: str,
    limit: int = 5,
    min_weight: float = 0.1,
) -> list[dict]:
    """Get top weighted errors for a learner."""
    async with AsyncSessionLocal() as session:
        # Recalculate weights for freshness
        now = datetime.now(timezone.utc)
        
        query = select(learner_progression_table).where(
            learner_progression_table.c.user_id == user_id
        )
        result = await session.execute(query)
        rows = result.fetchall()
        
        # Recalculate weights and filter
        errors = []
        for row in rows:
            fresh_weight = calculate_error_weight(row.count, row.last_seen, reference_time=now)
            if fresh_weight >= min_weight:
                mastery = getattr(row, "mastery_level", 0) or 0
                next_rev = getattr(row, "next_review_at", None)
                if next_rev and next_rev.tzinfo is None:
                    next_rev = next_rev.replace(tzinfo=timezone.utc)
                interval_days = SPACED_REPETITION_INTERVALS[min(mastery, len(SPACED_REPETITION_INTERVALS) - 1)]
                is_due = next_rev is not None and next_rev <= now
                errors.append({
                    "error_type": row.error_type,
                    "count": row.count,
                    "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                    "weight": fresh_weight,
                    "days_since": (now - row.last_seen).days if row.last_seen else 0,
                    "mastery_level": mastery,
                    "next_review_at": next_rev.isoformat() if next_rev else None,
                    "next_review_in_days": max(0, (next_rev - now).days) if next_rev and not is_due else 0,
                    "is_due_for_review": is_due,
                    "interval_days": interval_days,
                })
        
        # Sort by weight descending
        errors.sort(key=lambda x: x["weight"], reverse=True)
        return errors[:limit]


async def calculate_exercise_difficulty(
    user_id: str,
    min_errors_for_difficulty: int = 3,
) -> dict:
    """Calculate appropriate exercise difficulty based on error history."""
    errors = await get_frequent_errors(user_id, limit=10, min_weight=0.05)
    
    if not errors:
        return {
            "difficulty": 1,
            "reasoning": "no_error_history",
            "total_weighted_errors": 0,
        }
    
    total_weight = sum(e["weight"] for e in errors)
    max_weight = errors[0]["weight"] if errors else 0
    error_count = len(errors)
    
    # Calculate difficulty based on weighted metrics
    if total_weight < min_errors_for_difficulty:
        difficulty = 1
        reasoning = "insufficient_error_history"
    elif max_weight < 2.0 and error_count <= 2:
        difficulty = 2
        reasoning = "few_recent_errors"
    elif max_weight < 5.0 and error_count <= 4:
        difficulty = 3
        reasoning = "moderate_error_rate"
    elif max_weight < 10.0 or error_count <= 6:
        difficulty = 4
        reasoning = "frequent_errors"
    else:
        difficulty = 5
        reasoning = "persistent_errors"
    
    return {
        "difficulty": difficulty,
        "reasoning": reasoning,
        "total_weighted_errors": round(total_weight, 2),
        "max_error_weight": round(max_weight, 2),
        "error_type_count": error_count,
        "top_error": errors[0]["error_type"] if errors else None,
    }


def spaced_repetition_interval(
    error_type: str,
    user_history: list[dict],
) -> dict:
    """Calculate optimal review interval based on Ebbinghaus forgetting curve."""
    if not user_history:
        # First time seeing this error
        interval_days = SPACED_REPETITION_INTERVALS[0]
        mastery_level = 0
    else:
        # Calculate mastery level based on recent success rate
        recent_history = user_history[-5:]  # Look at last 5 attempts
        success_count = sum(1 for h in recent_history if h.get("success", False))
        total_recent = len(recent_history)
        
        # Mastery level 0-4 based on success rate
        if total_recent == 0:
            mastery_level = 0
        else:
            success_rate = success_count / total_recent
            if success_rate < 0.4:
                mastery_level = 0  # Need more practice
            elif success_rate < 0.6:
                mastery_level = 1
            elif success_rate < 0.8:
                mastery_level = 2
            elif success_rate < 1.0:
                mastery_level = 3
            else:
                mastery_level = 4  # Mastered
        
        # Cap at max interval
        interval_index = min(mastery_level, len(SPACED_REPETITION_INTERVALS) - 1)
        interval_days = SPACED_REPETITION_INTERVALS[interval_index]
    
    review_date = datetime.now(timezone.utc) + timedelta(days=interval_days)
    
    return {
        "error_type": error_type,
        "interval_days": interval_days,
        "review_date": review_date.isoformat(),
        "mastery_level": mastery_level,
        "intervals_available": SPACED_REPETITION_INTERVALS,
    }


async def get_learning_recommendations(
    user_id: str,
    max_recommendations: int = 3,
) -> dict:
    """Generate personalized learning recommendations based on error history."""
    errors = await get_frequent_errors(user_id, limit=10)
    difficulty_info = await calculate_exercise_difficulty(user_id)
    
    if not errors:
        return {
            "recommendations": ["continue_general_practice"],
            "focus_areas": [],
            "difficulty": difficulty_info,
            "next_review": None,
        }
    
    # Generate focus areas from top errors
    focus_areas = [e["error_type"] for e in errors[:max_recommendations]]
    
    # Generate recommendations
    recommendations = []
    
    # Primary recommendation: focus on top error
    if errors:
        top_error = errors[0]
        if top_error["weight"] > 5.0:
            recommendations.append(f"urgent_review_{top_error['error_type']}")
        else:
            recommendations.append(f"practice_{top_error['error_type']}")
    
    # Secondary recommendations based on pattern
    if len(errors) >= 3:
        recommendations.append("diverse_error_types")
    
    if difficulty_info["difficulty"] >= 4:
        recommendations.append("intensive_practice_needed")
    
    # Calculate next review for top error
    next_review = spaced_repetition_interval(
        errors[0]["error_type"],
        []
    )
    
    return {
        "recommendations": recommendations,
        "focus_areas": focus_areas,
        "difficulty": difficulty_info,
        "next_review": next_review,
        "error_summary": errors[:max_recommendations],
    }


async def get_due_for_review(user_id: str) -> list[dict]:
    """Return error types whose next_review_at is past due.

    Used by the quiz/exercise engine to prioritise spaced repetition reviews
    over random weak-area selection.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        query = select(learner_progression_table).where(
            learner_progression_table.c.user_id == user_id
        )
        result = await session.execute(query)
        rows = result.fetchall()

    due = []
    for row in rows:
        next_review = getattr(row, "next_review_at", None)
        if next_review is None:
            continue
        if next_review.tzinfo is None:
            next_review = next_review.replace(tzinfo=timezone.utc)
        if next_review <= now:
            overdue_days = (now - next_review).days
            fresh_weight = calculate_error_weight(row.count, row.last_seen, reference_time=now)
            due.append({
                "error_type": row.error_type,
                "count": row.count,
                "mastery_level": getattr(row, "mastery_level", 0) or 0,
                "next_review_at": next_review.isoformat(),
                "overdue_by_days": overdue_days,
                "weight": round(fresh_weight, 4),
            })

    due.sort(key=lambda x: x["overdue_by_days"], reverse=True)
    return due


async def record_successful_review(user_id: str, error_type: str) -> dict:
    """Advance mastery and reschedule next review after a correct answer.

    Mastery levels map to spaced repetition intervals:
    0 → 1 day, 1 → 3 days, 2 → 7 days, 3 → 14 days, 4 → 30 days

    A correct answer advances mastery by 1 (up to max 4).
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        query = select(learner_progression_table).where(
            (learner_progression_table.c.user_id == user_id) &
            (learner_progression_table.c.error_type == error_type)
        )
        result = await session.execute(query)
        row = result.fetchone()

        if row is None:
            return {"status": "no_record", "error_type": error_type}

        current_mastery = getattr(row, "mastery_level", 0) or 0
        new_mastery = min(current_mastery + 1, len(SPACED_REPETITION_INTERVALS) - 1)
        interval_days = SPACED_REPETITION_INTERVALS[new_mastery]
        next_review = now + timedelta(days=interval_days)

        await session.execute(
            update(learner_progression_table)
            .where(learner_progression_table.c.id == row.id)
            .values(
                mastery_level=new_mastery,
                next_review_at=next_review,
            )
        )
        await session.commit()

    return {
        "status": "advanced",
        "error_type": error_type,
        "mastery_level": new_mastery,
        "interval_days": interval_days,
        "next_review_at": next_review.isoformat(),
    }


async def get_full_learner_profile(user_id: str) -> dict:
    """Get complete learner profile with all adaptivity metrics."""
    errors = await get_frequent_errors(user_id, limit=20)
    difficulty = await calculate_exercise_difficulty(user_id)
    recommendations = await get_learning_recommendations(user_id)

    # Read CECRL level from session_stats (computed by _compute_level)
    cecrl_level = "A2"
    try:
        from backend.storage import AsyncSessionLocal, session_stats_table
        from sqlalchemy import select as _select
        async with AsyncSessionLocal() as _s:
            _r = await _s.execute(_select(session_stats_table).where(session_stats_table.c.session_id == user_id))
            _row = _r.fetchone()
            if _row and _row.level:
                cecrl_level = _row.level
    except Exception:
        pass

    difficulty["level"] = cecrl_level

    # Calculate overall stats
    total_errors = sum(e["count"] for e in errors)
    total_weighted = sum(e["weight"] for e in errors)

    # Determine learning trend (simplified)
    recent_errors = [e for e in errors if e.get("days_since", 999) <= 7]
    trend = "improving" if len(recent_errors) < len(errors) * 0.3 else "stable"
    if len(recent_errors) > len(errors) * 0.7:
        trend = "needs_attention"

    return {
        "user_id": user_id,
        "error_history": errors,
        "difficulty_assessment": difficulty,
        "recommendations": recommendations,
        "stats": {
            "total_error_occurrences": total_errors,
            "total_weighted_score": round(total_weighted, 2),
            "unique_error_types": len(errors),
            "learning_trend": trend,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
