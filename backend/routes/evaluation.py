import time
import asyncio
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, update
from backend.storage import AsyncSessionLocal, dataset_table, benchmarks_table, engine
from backend.llm import correct_with_ollama
from backend.evaluation import evaluate_correction, compute_gec_metrics, compute_bleu
from backend.text_utils import unwrap_json_string

router = APIRouter()

EVAL_PHRASE_TIMEOUT_S = 20.0

@router.post("/evaluate")
async def run_evaluation(request: Request):
    """
    Lance une évaluation du modèle actuel contre le dataset annoté.
    Calcule F0.5, Précision, Rappel et Latence moy.
    """
    async with AsyncSessionLocal() as session:
        # 1. Récupérer le dataset
        q = select(dataset_table).where(dataset_table.c.dataset_split == "test")
        result = await session.execute(q)
        rows = result.fetchall()
        
        if not rows:
            return {"status": "error", "message": "Aucune donnée dans le dataset pour l'évaluation."}
            
        total_tp, total_fp, total_fn = 0, 0, 0
        latencies = []
        references: list[list[str]] = []
        hypotheses: list[list[str]] = []
        
        # 2. Tester chaque phrase
        for row in rows:
            phrase = row.input_phrase
            gold = row.corrected_gold
            
            start = time.perf_counter()
            try:
                # On utilise directement correct_with_ollama pour avoir le output brut du pipeline
                corrected_raw, _, _, _, _ = await asyncio.wait_for(correct_with_ollama(phrase), timeout=EVAL_PHRASE_TIMEOUT_S)
                corrected = unwrap_json_string(corrected_raw)
            except Exception:
                continue
                
            latency = (time.perf_counter() - start) * 1000
            latencies.append(latency)

            from backend.text_utils import tokenize
            references.append(tokenize(gold))
            hypotheses.append(tokenize(corrected))
            
            scores = evaluate_correction(phrase, gold, corrected, row.error_spans_gold)
            total_tp += scores["tp"]
            total_fp += scores["fp"]
            total_fn += scores["fn"]
            
        # 3. Calculer métriques aggrégées
        metrics = compute_gec_metrics(total_tp, total_fp, total_fn, beta=0.5)
        bleu = compute_bleu(references, hypotheses)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        
        # 4. Persister le benchmark
        from backend.settings import settings
        bench_payload = {
            "model_name": settings.ollama_model,
            "pipeline_version": settings.pipeline_version,
            "prompt_version": settings.pipeline_version,
            "dataset_version": "default:test",
            "dataset_size": len(rows),
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f05": metrics["f_score"],
            "latency_avg_ms": avg_latency
        }
        
        await session.execute(benchmarks_table.insert().values(**bench_payload))
        await session.commit()
        
        return {
            "status": "success",
            "metrics": metrics,
            "bleu": bleu,
            "latency_avg_ms": round(avg_latency, 2),
            "total_tested": len(latencies)
        }

@router.get("/benchmarks")
async def get_benchmarks():
    async with AsyncSessionLocal() as session:
        q = select(benchmarks_table).order_by(benchmarks_table.c.created_at.desc()).limit(10)
        result = await session.execute(q)
        return [dict(r._mapping) for r in result.fetchall()]


@router.get("/dataset")
async def get_dataset(dataset_split: str | None = None):
    async with AsyncSessionLocal() as session:
        q = select(dataset_table)
        if dataset_split:
            q = q.where(dataset_table.c.dataset_split == dataset_split)
        result = await session.execute(q.order_by(dataset_table.c.created_at.desc()))
        return [dict(r._mapping) for r in result.fetchall()]


@router.get("/dataset/stats")
async def dataset_stats():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(dataset_table))
        rows = result.fetchall()

    split_counts: dict[str, int] = {}
    error_type_counts: dict[str, int] = {}
    verified_count = 0

    for row in rows:
        split = row.dataset_split or "unknown"
        split_counts[split] = split_counts.get(split, 0) + 1
        error_type = row.error_type_gold or "unknown"
        error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1
        if row.is_verified:
            verified_count += 1

    return {
        "total": len(rows),
        "verified": verified_count,
        "splits": split_counts,
        "error_types": error_type_counts,
    }


@router.get("/dataset/export")
async def export_dataset(dataset_split: str | None = None):
    async with AsyncSessionLocal() as session:
        q = select(dataset_table)
        if dataset_split:
            q = q.where(dataset_table.c.dataset_split == dataset_split)
        result = await session.execute(q.order_by(dataset_table.c.created_at.asc()))
        rows = [dict(r._mapping) for r in result.fetchall()]

    return {
        "dataset_split": dataset_split,
        "count": len(rows),
        "items": rows,
    }
