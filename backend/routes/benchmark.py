"""Benchmark API endpoints for running and retrieving benchmark comparisons.

Endpoints:
- POST /benchmark/run - Run benchmark comparison and store results
- GET /benchmark/compare - Get historical benchmark comparisons
- GET /benchmark/latest - Get latest benchmark results
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, text

from backend.benchmark.runner import BenchmarkRunner
from backend.storage import AsyncSessionLocal, benchmarks_table, dataset_table

router = APIRouter()
logger = logging.getLogger("mvp")


@router.post("/benchmark/run")
async def run_benchmark(request: Request):
    """Run benchmark comparison across all three configurations.

    Accepts optional JSON body:
      { "max_examples": 100, "n_runs": 3 }

    n_runs > 1: calls LLM independently N times per phrase, capturing output
    variance. Metrics are aggregated over all (phrase × run) pairs.

    Compares:
    - LLM brut baseline
    - Pipeline structuré (without memory)
    - Pipeline + mémoire (with similar errors + pgvector)

    Returns:
        Comparative benchmark report
    """
    from backend.schemas import BenchmarkRunRequest
    try:
        body = await request.json()
    except Exception:
        body = {}
    req = BenchmarkRunRequest(**body) if body else BenchmarkRunRequest()

    async with AsyncSessionLocal() as session:
        q = select(dataset_table).where(dataset_table.c.dataset_split == "test")
        result = await session.execute(q)
        rows = result.fetchall()

        if not rows:
            raise HTTPException(
                status_code=400,
                detail="No test dataset found. Seed dataset first via /dataset/seed",
            )

        runner = BenchmarkRunner(max_examples=req.max_examples)
        benchmark_output = await runner.run_benchmark(
            session, rows,
            save=True,
            verbose=False,
        )
        report = runner.generate_report(benchmark_output["results"])

        return {
            "status": "success",
            "report": report,
            "meta": benchmark_output["meta"],
        }


@router.get("/benchmark/compare")
async def compare_benchmarks(limit: int = 10):
    """Get historical benchmark comparisons.
    
    Args:
        limit: Maximum number of benchmark runs to return
    
    Returns:
        List of benchmark results grouped by run
    """
    async with AsyncSessionLocal() as session:
        q = (
            select(benchmarks_table)
            .order_by(benchmarks_table.c.created_at.desc())
            .limit(limit * 3)  # 3 configs per run
        )
        result = await session.execute(q)
        rows = result.fetchall()
        
        # Group by time bucket (within 5 minutes = same run)
        from datetime import datetime, timedelta
        runs = []
        current_run = []
        current_time = None
        
        for row in rows:
            row_time = row.created_at
            if current_time is None or (current_time - row_time) > timedelta(minutes=5):
                if current_run:
                    runs.append(current_run)
                current_run = [dict(row._mapping)]
                current_time = row_time
            else:
                current_run.append(dict(row._mapping))
        
        if current_run:
            runs.append(current_run)
        
        return {
            "status": "success",
            "runs": runs[:limit],
            "total_runs": len(runs),
        }


@router.get("/benchmark/stats")
async def benchmark_stats():
    """Aggregated stats from benchmark_rows + ERRANT means from benchmarks runs.

    Mirrors what the CLI `benchmark-stats` command computes, for the frontend.
    """
    async with AsyncSessionLocal() as session:
        # Per-config aggregated metrics from benchmark_rows (8270 rows)
        agg = (await session.execute(text("""
            SELECT
                model_name,
                count(*)                                         AS n,
                round(avg(f05)::numeric, 4)                      AS avg_f05,
                round(avg(precision)::numeric, 4)                AS avg_p,
                round(avg(recall)::numeric, 4)                   AS avg_r,
                round(avg(exact_match::int)::numeric, 4)         AS exact_match,
                round(avg(span_f05)::numeric, 4)                 AS avg_span_f05,
                round(avg(error_type_match::int)::numeric, 4)    AS type_acc,
                round(avg(feedback_present::int)::numeric, 4)    AS feedback_present,
                round(avg(feedback_type_match::int)::numeric, 4) AS feedback_type_match,
                round(avg(feedback_valid::int)::numeric, 4)      AS feedback_valid
            FROM benchmark_rows
            GROUP BY model_name
            ORDER BY model_name
        """))).fetchall()

        if not agg:
            return {"status": "no_data"}

        # ERRANT means across runs (excludes runs with errant_f05=0)
        errant = (await session.execute(text("""
            SELECT model_name,
                   count(*)           FILTER (WHERE errant_f05 > 0) AS n_runs,
                   avg(errant_f05)    FILTER (WHERE errant_f05 > 0) AS errant_f05,
                   stddev(errant_f05) FILTER (WHERE errant_f05 > 0) AS errant_f05_std,
                   avg(errant_precision) FILTER (WHERE errant_f05 > 0) AS errant_p,
                   avg(errant_recall)    FILTER (WHERE errant_f05 > 0) AS errant_r
            FROM benchmarks
            GROUP BY model_name
            ORDER BY model_name
        """))).fetchall()

        # Type alignment per error_type for pipeline_structuré
        type_align = (await session.execute(text("""
            SELECT error_type_gold,
                   count(*) AS n,
                   round(avg(error_type_match::int)::numeric, 4) AS alignment_rate
            FROM benchmark_rows
            WHERE model_name = 'pipeline_structuré'
            GROUP BY error_type_gold
            ORDER BY n DESC
        """))).fetchall()

        # Predicted type distribution for pipeline_structuré
        pred_dist = (await session.execute(text("""
            SELECT error_type_predicted,
                   count(*) AS n,
                   round(count(*) * 100.0 / sum(count(*)) OVER (), 2) AS pct
            FROM benchmark_rows
            WHERE model_name = 'pipeline_structuré'
            GROUP BY error_type_predicted
            ORDER BY n DESC
        """))).fetchall()

        errant_by_model = {r.model_name: r for r in errant}

        configs = []
        for r in agg:
            e = errant_by_model.get(r.model_name)
            configs.append({
                "model_name": r.model_name,
                "n": int(r.n),
                "avg_f05": float(r.avg_f05 or 0),
                "avg_p": float(r.avg_p or 0),
                "avg_r": float(r.avg_r or 0),
                "exact_match": float(r.exact_match or 0),
                "avg_span_f05": float(r.avg_span_f05 or 0),
                "type_acc": float(r.type_acc or 0),
                "feedback_present": float(r.feedback_present or 0),
                "feedback_type_match": float(r.feedback_type_match or 0),
                "errant_f05": float(e.errant_f05 or 0) if e and e.errant_f05 else None,
                "errant_f05_std": float(e.errant_f05_std or 0) if e and e.errant_f05_std else None,
                "errant_p": float(e.errant_p or 0) if e and e.errant_p else None,
                "errant_r": float(e.errant_r or 0) if e and e.errant_r else None,
                "errant_n_runs": int(e.n_runs or 0) if e else 0,
            })

        return {
            "status": "success",
            "configurations": configs,
            "type_alignment": [
                {"error_type": r.error_type_gold, "n": int(r.n), "alignment_rate": float(r.alignment_rate or 0)}
                for r in type_align
            ],
            "predicted_distribution": [
                {"error_type": r.error_type_predicted, "n": int(r.n), "pct": float(r.pct or 0)}
                for r in pred_dist
            ],
        }


@router.get("/benchmark/latest")
async def latest_benchmark():
    """Get the most recent benchmark results.
    
    Returns:
        Latest benchmark run with all three configurations
    """
    async with AsyncSessionLocal() as session:
        q = (
            select(benchmarks_table)
            .order_by(benchmarks_table.c.created_at.desc())
            .limit(3)
        )
        result = await session.execute(q)
        rows = result.fetchall()
        
        if not rows:
            return {
                "status": "no_data",
                "message": "No benchmarks found. Run /benchmark/run first.",
            }
        
        configs = [dict(row._mapping) for row in rows]
        
        # Determine run timestamp from most recent row
        latest_time = max(
            (r.get("created_at") for r in configs if r.get("created_at")),
            default=None,
        )
        
        return {
            "status": "success",
            "run_timestamp": latest_time.isoformat() if hasattr(latest_time, "isoformat") else str(latest_time),
            "configurations": configs,
        }
