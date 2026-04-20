from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import func

from backend.settings import settings


metadata = MetaData()

corrections_table = Table(
    "corrections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("phrase", Text, nullable=False),
    Column("phrase_normalized", Text, nullable=False, index=True),
    Column("corrected", Text, nullable=False),
    Column("feedback", Text, nullable=False),
    Column("error_type", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("changed", Boolean, nullable=False),
    Column("unchanged_ok", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

dataset_table = Table(
    "dataset",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("input_phrase", Text, nullable=False, unique=True),
    Column("corrected_gold", Text, nullable=False),
    Column("error_type_gold", Text, nullable=False),
    Column("dataset_split", Text, nullable=True),
    Column("error_spans_gold", Text, nullable=True),  # JSON string
    Column("embedding", Text, nullable=True),  # pgvector vector stored as text
    Column("is_verified", Boolean, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

benchmarks_table = Table(
    "benchmarks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("model_name", Text, nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("prompt_version", Text, nullable=True),
    Column("dataset_version", Text, nullable=True),
    Column("dataset_size", Integer, nullable=True),
    Column("precision", Float, nullable=True),
    Column("recall", Float, nullable=True),
    Column("f05", Float, nullable=True),              # TSF0.5 (token-sequence, non-standard)
    Column("errant_f05", Float, nullable=True),        # Edit-level F0.5 (BEA-2019 standard)
    Column("errant_precision", Float, nullable=True),
    Column("errant_recall", Float, nullable=True),
    Column("exact_match_accuracy", Float, nullable=True),
    Column("error_type_accuracy", Float, nullable=True),
    Column("other_ratio", Float, nullable=True),
    Column("avg_span_f05", Float, nullable=True),
    Column("feedback_valid_rate", Float, nullable=True),
    Column("latency_avg_ms", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

benchmark_rows_table = Table(
    "benchmark_rows",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("dataset_id", Integer, nullable=False),
    Column("model_name", Text, nullable=False),
    Column("input_phrase", Text, nullable=False),
    Column("corrected", Text, nullable=False),
    Column("gold", Text, nullable=False),
    Column("match", Boolean, nullable=False),
    Column("exact_match", Boolean, server_default="false"),
    Column("soft_match", Boolean, server_default="false"),
    Column("precision", Float),
    Column("recall", Float),
    Column("f05", Float),
    Column("token_overlap", Float),
    Column("span_f05", Float),
    Column("errant_f05", Float),
    Column("error_type_gold", Text),
    Column("error_type_predicted", Text),
    Column("error_type_match", Boolean, server_default="false"),
    Column("feedback_present", Boolean, server_default="false"),
    Column("feedback_type_match", Boolean, server_default="false"),
    Column("feedback_valid", Boolean, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

quiz_attempts_table = Table(
    "quiz_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("question", Text, nullable=False),
    Column("options", Text, nullable=False),
    Column("selected_index", Integer, nullable=False),
    Column("correct_index", Integer, nullable=False),
    Column("correct", Boolean, nullable=False),
    Column("feedback", Text, nullable=False),
    Column("error_type", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

session_stats_table = Table(
    "session_stats",
    metadata,
    Column("session_id", Text, primary_key=True),
    Column("total_attempts", Integer, nullable=False, server_default="0"),
    Column("success_count", Integer, nullable=False, server_default="0"),
    Column("error_tense", Integer, nullable=False, server_default="0"),
    Column("error_agreement", Integer, nullable=False, server_default="0"),
    Column("error_article", Integer, nullable=False, server_default="0"),
    Column("error_preposition", Integer, nullable=False, server_default="0"),
    Column("error_spelling", Integer, nullable=False, server_default="0"),
    Column("error_word_choice", Integer, nullable=False, server_default="0"),
    Column("error_punctuation", Integer, nullable=False, server_default="0"),
    Column("error_syntax", Integer, nullable=False, server_default="0"),
    Column("error_redundancy", Integer, nullable=False, server_default="0"),
    Column("error_other", Integer, nullable=False, server_default="0"),
    Column("level", Text, nullable=False, server_default="A2"),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# Adaptivity: learner progression tracking with exponential decay
learner_progression_table = Table(
    "learner_progression",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", String(255), nullable=False),
    Column("error_type", String(50), nullable=False),
    Column("count", Integer, default=1),
    Column("last_seen", DateTime(timezone=True), server_default=func.now()),
    Column("weight", Float, default=1.0),
    Column("mastery_level", Integer, default=0),
    Column("next_review_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("user_id", "error_type"),
)

feedback_ratings_table = Table(
    "feedback_ratings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correction_id", Integer, nullable=True),
    Column("input_phrase", Text, nullable=False),
    Column("feedback_text", Text, nullable=False),
    Column("error_type", Text, nullable=True),
    Column("rating", Boolean, nullable=False),  # True = 👍, False = 👎
    Column("context", Text, nullable=True),  # 'correction' | 'exercise'
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(255), nullable=False, unique=True),
    Column("display_name", String(255), nullable=True),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

user_sessions_table = Table(
    "user_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("token", String(255), nullable=False, unique=True, index=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

h2_runs_table = Table(
    "h2_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(64), nullable=False, unique=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("learners", Integer, nullable=True),
    Column("phrases_per_learner", Integer, nullable=True),
    Column("seed", Integer, nullable=True),
    Column("api_url", Text, nullable=True),
    Column("top_priority_match_rate", Float, nullable=True),
    Column("priority_shift_rate", Float, nullable=True),
    Column("adaptive_loop_success_rate", Float, nullable=True),
    Column("failed_correction_rate", Float, nullable=True),
    Column("simulated_error_reduction_rate", Float, nullable=True),
    Column("average_api_latency_ms", Float, nullable=True),
    Column("by_family", Text, nullable=True),  # JSON
    Column("note", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

h2_session_rows_table = Table(
    "h2_session_rows",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(64), nullable=False, index=True),
    Column("learner_id", Text, nullable=False),
    Column("session_id", Integer, nullable=True),
    Column("sentence_idx", Integer, nullable=True),
    Column("input_sentence", Text, nullable=True),
    Column("corrected_sentence", Text, nullable=True),
    Column("predicted_error_type", Text, nullable=True),
    Column("feedback_present", Boolean, nullable=True),
    Column("dominant_error_before", Text, nullable=True),
    Column("dominant_error_after", Text, nullable=True),
    Column("api_latency_ms", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

h2_priority_rows_table = Table(
    "h2_priority_rows",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(64), nullable=False, index=True),
    Column("learner_id", Text, nullable=False),
    Column("session_id", Integer, nullable=True),
    Column("error_type", Text, nullable=False),
    Column("count", Integer, nullable=True),
    Column("weight", Float, nullable=True),
    Column("days_since", Float, nullable=True),
    Column("mastery_level", Integer, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

h2_exercise_rows_table = Table(
    "h2_exercise_rows",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(64), nullable=False, index=True),
    Column("learner_id", Text, nullable=False),
    Column("session_id", Integer, nullable=True),
    Column("target_error_type", Text, nullable=True),
    Column("exercise_prompt", Text, nullable=True),
    Column("exercise_blank", Text, nullable=True),
    Column("grade_result", Text, nullable=True),
    Column("api_latency_ms", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

engine = None
AsyncSessionLocal = None

if settings.database_url:
    engine = create_async_engine(settings.database_url, future=True)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _compute_level(stats: dict) -> str:
    """
    Calcule le niveau CECRL basé sur le taux de réussite et la complexité des erreurs.
    """
    total = stats.get("total_attempts", 0)
    success_count = stats.get("success_count", 0)
    
    if total < 5:
        return "A2" # Niveau par défaut
        
    rate = success_count / total
    
    # Si bcp d'erreurs de base (spelling, article), on reste en A1/A2
    basic_errors = stats.get("error_spelling", 0) + stats.get("error_article", 0)
    advanced_errors = stats.get("error_tense", 0) + stats.get("error_agreement", 0)
    
    if rate < 0.4:
        return "A1"
    if rate < 0.7:
        # A2 si trop d'erreurs de base, sinon potentiellement B1
        return "A2" if basic_errors > total * 0.2 else "B1"
    if rate < 0.9:
        return "B1" if advanced_errors > total * 0.1 else "B2"
    
    return "B2"


async def _persist_correction(payload: dict[str, object]) -> None:
    if not settings.database_url:
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(corrections_table.insert().values(**payload))
            await session.commit()
    except Exception:
        return


async def _persist_quiz_attempt(payload: dict[str, object]) -> None:
    if not settings.database_url:
        return
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(quiz_attempts_table.insert().values(**payload))
            await session.commit()
    except Exception:
        return


async def _get_level(session_id: str) -> str:
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row = r.fetchone()
            if row:
                return row.level or "A2"
    except Exception:
        pass
    return "A2"


async def _get_session_profile(session_id: str) -> dict[str, object]:
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row = r.fetchone()
            if not row:
                return {"level": "A2", "focus": None, "error_rates": {}}

            data = dict(row._mapping)
            total = max(int(data.get("total_attempts", 0) or 0), 0)
            errors = {
                "tense": int(data.get("error_tense", 0) or 0),
                "agreement": int(data.get("error_agreement", 0) or 0),
                "article": int(data.get("error_article", 0) or 0),
                "preposition": int(data.get("error_preposition", 0) or 0),
                "spelling": int(data.get("error_spelling", 0) or 0),
                "word_choice": int(data.get("error_word_choice", 0) or 0),
                "punctuation": int(data.get("error_punctuation", 0) or 0),
                "syntax": int(data.get("error_syntax", 0) or 0),
                "redundancy": int(data.get("error_redundancy", 0) or 0),
                "other": int(data.get("error_other", 0) or 0),
            }
            focus = None
            if total > 0:
                focus = max(errors, key=errors.get) if max(errors.values()) > 0 else None
            error_rates = {k: round(v / total, 3) for k, v in errors.items()} if total > 0 else {k: 0.0 for k in errors}
            return {
                "level": data.get("level") or "A2",
                "focus": focus,
                "error_rates": error_rates,
                "total_attempts": total,
                "success_rate": round((int(data.get("success_count", 0) or 0) / total), 3) if total > 0 else 0.0,
            }
    except Exception:
        return {"level": "A2", "focus": None, "error_rates": {}}


# Mapping error_type -> column name for session_stats
def _error_column(error_type: str | None) -> str:
    return {
        "tense": "error_tense",
        "agreement": "error_agreement",
        "article": "error_article",
        "preposition": "error_preposition",
        "spelling": "error_spelling",
        "word_choice": "error_word_choice",
        "punctuation": "error_punctuation",
        "syntax": "error_syntax",
        "redundancy": "error_redundancy",
    }.get(error_type or "", "error_other")


async def _record_correction_attempt(session_id: str, success: bool, error_type: str) -> None:
    if not session_id or not settings.database_url:
        return
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row = r.fetchone()
            if not row:
                col = _error_column(error_type)
                insert_vals: dict[str, object] = {
                    "session_id": session_id,
                    "total_attempts": 1,
                    "success_count": 1 if success else 0,
                    "error_tense": 0,
                    "error_agreement": 0,
                    "error_article": 0,
                    "error_preposition": 0,
                    "error_spelling": 0,
                    "error_word_choice": 0,
                    "error_punctuation": 0,
                    "error_syntax": 0,
                    "error_redundancy": 0,
                    "error_other": 0,
                }
                if not success:
                    insert_vals[col] = 1
                await session.execute(session_stats_table.insert().values(**insert_vals))
            else:
                vals = {
                    "total_attempts": row.total_attempts + 1,
                    "success_count": row.success_count + (1 if success else 0),
                    "updated_at": func.now(),
                }
                col = _error_column(error_type)
                vals[col] = getattr(row, col, 0) + 1
                await session.execute(session_stats_table.update().where(session_stats_table.c.session_id == session_id).values(**vals))
            await session.commit()
            r2 = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row2 = r2.fetchone()
            if row2 and row2.total_attempts > 0:
                new_level = _compute_level(dict(row2._mapping))
                await session.execute(session_stats_table.update().where(session_stats_table.c.session_id == session_id).values(level=new_level, updated_at=func.now()))
                await session.commit()
    except Exception:
        pass


async def _record_grade_attempt(session_id: str, correct: bool, error_type: str | None = None) -> None:
    if not session_id or not settings.database_url:
        return
    try:
        async with AsyncSessionLocal() as session:
            r = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row = r.fetchone()
            if not row:
                col = _error_column(error_type)
                insert_vals: dict[str, object] = {
                    "session_id": session_id,
                    "total_attempts": 1,
                    "success_count": 1 if correct else 0,
                    "error_tense": 0,
                    "error_agreement": 0,
                    "error_article": 0,
                    "error_preposition": 0,
                    "error_spelling": 0,
                    "error_word_choice": 0,
                    "error_punctuation": 0,
                    "error_syntax": 0,
                    "error_redundancy": 0,
                    "error_other": 0,
                }
                if not correct:
                    insert_vals[col] = 1
                await session.execute(session_stats_table.insert().values(**insert_vals))
            else:
                error_updates = {
                    "error_tense": 0,
                    "error_agreement": 0,
                    "error_article": 0,
                    "error_preposition": 0,
                    "error_spelling": 0,
                    "error_word_choice": 0,
                    "error_punctuation": 0,
                    "error_syntax": 0,
                    "error_redundancy": 0,
                    "error_other": 0,
                }
                if not correct:
                    col = _error_column(error_type)
                    error_updates[col] = getattr(row, col, 0) + 1
                await session.execute(
                    session_stats_table.update().where(session_stats_table.c.session_id == session_id).values(
                        total_attempts=row.total_attempts + 1,
                        success_count=row.success_count + (1 if correct else 0),
                        **error_updates,
                        updated_at=func.now(),
                    )
                )
            await session.commit()
            r2 = await session.execute(session_stats_table.select().where(session_stats_table.c.session_id == session_id))
            row2 = r2.fetchone()
            if row2 and row2.total_attempts > 0:
                new_level = _compute_level(dict(row2._mapping))
                await session.execute(session_stats_table.update().where(session_stats_table.c.session_id == session_id).values(level=new_level, updated_at=func.now()))
                await session.commit()
    except Exception:
        pass
