"""Similarity search for error memory using pgvector.

Provides find_similar_errors to retrieve similar error examples
for enhancing pedagogical feedback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from backend.memory.embeddings import compute_embedding, embedding_to_pgvector, cosine_similarity
from backend.settings import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def find_similar_errors(
    input_phrase: str,
    k: int = 3,
    error_type: str | None = None,
    min_similarity: float = 0.5,
    exclude_self: bool = True,
) -> list[dict]:
    """Find similar errors from dataset using pgvector similarity search.
    
    Args:
        input_phrase: The input phrase to find similar errors for
        k: Number of similar examples to return
        error_type: Optional filter by error type
        min_similarity: Minimum cosine similarity threshold
    
    Returns:
        List of similar error examples with similarity scores
    """
    if not settings.database_url:
        return []
    
    try:
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select, text
    except Exception:
        return []
    
    # Compute embedding for input phrase
    embedding = compute_embedding(input_phrase)
    embedding_str = embedding_to_pgvector(embedding)
    
    async with AsyncSessionLocal() as session:
        # Build query with pgvector cosine similarity
        # Using <=> operator for cosine distance (1 - similarity)
        base_query = """
            SELECT
                id,
                input_phrase,
                corrected_gold,
                error_type_gold,
                error_spans_gold,
                1 - (embedding <=> :embedding_vec) as similarity
            FROM dataset
            WHERE embedding IS NOT NULL
        """

        params = {"embedding_vec": embedding_str, "k": k}

        if exclude_self:
            base_query += " AND input_phrase != :self_phrase"
            params["self_phrase"] = input_phrase

        if error_type:
            base_query += " AND error_type_gold = :error_type"
            params["error_type"] = error_type

        base_query += """
            AND 1 - (embedding <=> :embedding_vec) >= :min_sim
            ORDER BY embedding <=> :embedding_vec
            LIMIT :k
        """
        params["min_sim"] = min_similarity
        
        result = await session.execute(text(base_query), params)
        rows = result.fetchall()
    
    # Format results
    similar_errors = []
    for row in rows:
        similar_errors.append({
            "id": row.id if hasattr(row, "id") else row[0],
            "input_phrase": row.input_phrase if hasattr(row, "input_phrase") else row[1],
            "corrected_gold": row.corrected_gold if hasattr(row, "corrected_gold") else row[2],
            "error_type": row.error_type_gold if hasattr(row, "error_type_gold") else row[3],
            "error_spans": _parse_spans(row.error_spans_gold if hasattr(row, "error_spans_gold") else row[4]),
            "similarity": round(float(row.similarity if hasattr(row, "similarity") else row[5]), 3),
        })
    
    return similar_errors


def _parse_embedding(emb_str: str) -> list[float]:
    """Parse embedding from string representation."""
    if emb_str.startswith('[') and emb_str.endswith(']'):
        emb_str = emb_str[1:-1]
    return [float(x.strip()) for x in emb_str.split(',')]


def _parse_spans(spans_json: str | None) -> list[dict]:
    """Parse error spans from JSON string."""
    if not spans_json:
        return []
    try:
        return json.loads(spans_json)
    except json.JSONDecodeError:
        return []


async def update_dataset_embeddings() -> dict:
    """Update embeddings for all dataset entries that don't have them.
    
    Returns:
        Dict with count of updated rows
    """
    if not settings.database_url:
        return {"updated": 0, "error": "No database URL"}
    
    try:
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select, update
    except Exception as e:
        return {"updated": 0, "error": str(e)}
    
    updated = 0
    async with AsyncSessionLocal() as session:
        # Get all rows without embeddings
        stmt = select(
            dataset_table.c.id,
            dataset_table.c.input_phrase,
        ).where(dataset_table.c.embedding.is_(None))
        
        result = await session.execute(stmt)
        rows = result.fetchall()
        
        for row in rows:
            embedding = compute_embedding(row.input_phrase)
            embedding_str = embedding_to_pgvector(embedding)
            
            await session.execute(
                update(dataset_table)
                .where(dataset_table.c.id == row.id)
                .values(embedding=embedding_str)
            )
            updated += 1
        
        await session.commit()
    
    return {"updated": updated}


async def find_errors_by_type(error_type: str, limit: int = 10) -> list[dict]:
    """Find errors by type without similarity search.
    
    Args:
        error_type: Type of error to find
        limit: Maximum number of results
    
    Returns:
        List of error examples
    """
    if not settings.database_url:
        return []
    
    try:
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select
    except Exception:
        return []
    
    async with AsyncSessionLocal() as session:
        stmt = select(dataset_table).where(
            dataset_table.c.error_type_gold == error_type
        ).limit(limit)
        
        result = await session.execute(stmt)
        rows = result.fetchall()
        
        return [
            {
                "id": row.id,
                "input_phrase": row.input_phrase,
                "corrected_gold": row.corrected_gold,
                "error_type": row.error_type_gold,
                "error_spans": _parse_spans(row.error_spans_gold),
            }
            for row in rows
        ]
