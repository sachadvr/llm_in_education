"""Benchmark runner for comparing LLM correction configurations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.evaluation.metrics import (
    compute_comprehensive_metrics,
    compute_gain_metric,
    compute_soft_match,
    compute_token_sequence_metrics,
    evaluate_span_level,
)
from backend.pipeline.orchestrator import PipelineOrchestrator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mvp")

# Normalize predicted error types to match dataset gold taxonomy
ERROR_TYPE_NORMALIZATION: dict[str, str] = {
    "noun_number": "agreement",
    "verb_tense": "tense",
    "determiner": "article",
    "word_order": "syntax",
    "missing_word": "other",
    "unnecessary_word": "other",
    "missing_punct": "punctuation",
    "unnecessary_punct": "punctuation",
    # verb_form intentionally NOT mapped to tense — BEA2019 uses verb_form directly
}


def normalize_error_type(error_type: str | None) -> str | None:
    if not error_type:
        return error_type
    return ERROR_TYPE_NORMALIZATION.get(error_type.lower(), error_type.lower())


def _compute_type_analysis(predictions: list[dict]) -> dict:
    """Per-gold-error-type count and classifier alignment rate."""
    from collections import defaultdict
    counts: dict[str, int] = defaultdict(int)
    aligned: dict[str, int] = defaultdict(int)
    for p in predictions:
        gold = normalize_error_type(p.get("gold_error_type") or "unknown") or "unknown"
        pred = normalize_error_type(p.get("predicted_error_type") or "other") or "other"
        counts[gold] += 1
        if pred == gold:
            aligned[gold] += 1
    return {
        gt: {
            "count": counts[gt],
            "alignment_rate": round(aligned[gt] / counts[gt], 4),
        }
        for gt in sorted(counts, key=lambda x: -counts[x])
    }


def _compute_predicted_type_distribution(predictions: list[dict]) -> dict:
    """Count and percentage of each predicted error type (raw, not normalized)."""
    from collections import defaultdict
    counts: dict[str, int] = defaultdict(int)
    for p in predictions:
        pred = (p.get("predicted_error_type") or "none").lower().strip()
        counts[pred] += 1
    total = sum(counts.values()) or 1
    return {
        pt: {
            "count": counts[pt],
            "percentage": round(counts[pt] / total * 100, 2),
        }
        for pt in sorted(counts, key=lambda x: -counts[x])
    }


@dataclass(frozen=True)
class BenchmarkConfig:
    """Configuration for a benchmark run."""
    name: str
    description: str
    use_pipeline: bool = False
    use_memory: bool = False


# Predefined configurations
LLM_BRUT_CONFIG = BenchmarkConfig(
    name="llm_brut",
    description="Raw LLM correction via Ollama (no structured pipeline)",
    use_pipeline=False,
    use_memory=False,
)

PIPELINE_CONFIG = BenchmarkConfig(
    name="pipeline_structuré",
    description="Full structured pipeline without memory integration",
    use_pipeline=True,
    use_memory=False,
)

PIPELINE_MEMORY_CONFIG = BenchmarkConfig(
    name="pipeline+mémoire",
    description="Full structured pipeline with similar error memory",
    use_pipeline=True,
    use_memory=True,
)


def compute_target_counts(
    counts: dict[str, int],
    strategy: str = "equal",
    target_per_type: int = 20,
    min_count: int = 5,
) -> dict[str, int]:
    """Compute target sample counts per error type for balanced benchmarking."""
    if not counts:
        return {}

    if strategy == "equal":
        return {etype: max(target_per_type, min_count) for etype in counts}

    # proportional strategy
    total = sum(counts.values())
    avg = total / len(counts) if counts else 0
    targets = {}
    for etype, count in counts.items():
        if strategy == "proportional":
            # Scale proportionally but cap at 2x average to avoid over-representing one type
            target = max(min_count, int(count / total * avg * len(counts)) if total else min_count)
            target = min(target, int(avg * 2)) if avg else target
            targets[etype] = max(target, min_count)
    return targets


class BenchmarkRunner:
    """Runner for benchmark comparisons across configurations."""

    def __init__(self, max_examples: int | None = None):
        """Initialize benchmark runner."""
        self.max_examples = max_examples
        self._pipeline = PipelineOrchestrator(use_similar_errors=False)
        self._pipeline_with_memory = PipelineOrchestrator(use_similar_errors=True)

    async def run_comparison(
        self,
        db_session: AsyncSession,
        dataset_rows: list,
    ) -> dict:
        """Run all three benchmark configurations and return raw results."""
        if self.max_examples:
            dataset_rows = dataset_rows[: self.max_examples]

        results = {}
        configs = [LLM_BRUT_CONFIG, PIPELINE_CONFIG, PIPELINE_MEMORY_CONFIG]

        for config in configs:
            logger.info(f"Running benchmark: {config.name}")
            start_time = time.perf_counter()
            config_results = await self._run_config(config, dataset_rows)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            avg_latency = elapsed_ms / len(dataset_rows) if dataset_rows else 0

            # Compute comprehensive metrics
            predictions = []
            for row in dataset_rows:
                original = row.input_phrase
                gold = row.corrected_gold
                result = config_results.get(row.id)
                if result is None:
                    # Never silently fallback to gold or original — skip missing rows
                    logger.warning(f"Missing correction for row {row.id}, skipping")
                    continue
                model_corrected = result["corrected"]
                gold_spans = self._parse_spans(row.error_spans_gold)
                predictions.append({
                    "original": original,
                    "gold_corrected": gold,
                    "model_corrected": model_corrected,
                    "gold_spans": gold_spans,
                    "gold_error_type": row.error_type_gold or "unknown",
                    "predicted_error_type": result.get("error_type"),
                    "predicted_spans": result.get("spans", []),
                    "feedback": result.get("feedback"),
                })

            metrics = compute_comprehensive_metrics(predictions)
            results[config.name] = {
                "config": config,
                "metrics": metrics,
                "latency_avg_ms": round(avg_latency, 2),
                "dataset_size": len(dataset_rows),
                "elapsed_ms": round(elapsed_ms, 2),
                "sample_predictions": predictions[:5],
                "type_analysis": _compute_type_analysis(predictions),
                "predicted_type_distribution": _compute_predicted_type_distribution(predictions),
            }

        return results

    async def _run_config(
        self,
        config: BenchmarkConfig,
        dataset_rows: list,
    ) -> dict[str, dict]:
        """Run a single configuration against dataset."""
        results: dict[str, dict] = {}

        total = len(dataset_rows)
        for idx, row in enumerate(dataset_rows, 1):
            original = row.input_phrase
            gold = row.corrected_gold

            predicted_spans = []
            feedback = None
            predicted_type = "other"

            # Always get LLM correction first — shared across configs (fair benchmark)
            from backend.llm import correct_with_ollama
            from backend.text_utils import classify_error_type, compute_diff
            llm_corrected, _, _, _, _ = await correct_with_ollama(original)

            if config.name == "llm_brut":
                corrected = llm_corrected
                predicted_spans = compute_diff(original, corrected)
                predicted_type = classify_error_type(original, corrected, "other")
            elif config.name == "pipeline_structuré":
                result = self._pipeline.run_sync(original, llm_corrected, level="A2")
                corrected = result.corrected
                predicted_spans = result.errors
                feedback = result.feedback
                predicted_type = result.error_type
            else:  # pipeline+mémoire
                result = await self._pipeline_with_memory.run(original, llm_corrected, level="A2")
                corrected = result.corrected
                predicted_spans = result.errors
                feedback = result.feedback
                predicted_type = result.error_type

            results[row.id] = {
                "corrected": corrected,
                "spans": predicted_spans,
                "feedback": feedback,
                "error_type": predicted_type,
            }

            # Log en temps réel
            logger.info(f"[{config.name}] {idx}/{total}")
            logger.info(f"  Original: {original[:60]}...")
            logger.info(f"  Gold:    {gold[:60]}...")
            logger.info(f"  Corrected: {corrected[:60]}...")
            logger.info(f"  Match:   {corrected.lower().strip() == gold.lower().strip()}")
            logger.info("---")

        return results

    def _parse_spans(self, spans_raw: str | None) -> list[dict]:
        """Parse JSON error spans from database."""
        import json
        if not spans_raw:
            return []
        try:
            spans = json.loads(spans_raw)
            if isinstance(spans, list):
                return spans
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def generate_report(self, comparison_results: dict) -> dict:
        """Generate structured comparative report from raw results."""
        report = {
            "summary": {},
            "configurations": {},
            "comparative": {},
            "synthetic_table": [],
            "qualitative_analysis": [],
            "typological_analysis": {},
            "predicted_type_distribution": {},
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        for config_name, result in comparison_results.items():
            metrics = result["metrics"]
            # Prefer token_sequence when available (run_benchmark), else span_level (run_comparison)
            primary = metrics.get("token_sequence") or metrics.get("span_level", {})
            exact_match = metrics.get("exact_match", {})
            gain = metrics.get("gain", {})
            error_type = metrics.get("error_type", {})
            other_ratio = metrics.get("other_ratio", {})
            feedback = metrics.get("feedback", {})
            avg_span_f05 = metrics.get("avg_span_f05", 0.0)
            errant = metrics.get("errant_gec", {})

            report["configurations"][config_name] = {
                "description": result["config"].description,
                "dataset_size": result["dataset_size"],
                "errant_precision": errant.get("precision", 0.0),
                "errant_recall": errant.get("recall", 0.0),
                "errant_f05": errant.get("f05", 0.0),        # BEA-2019 standard edit-level F0.5
                "tsf05": primary.get("f_score", 0.0),         # token-sequence F0.5 (non-standard)
                "exact_match_accuracy": exact_match.get("accuracy", 0.0),
                "improvement_rate": gain.get("improvement_rate", 0.0),
                "latency_avg_ms": result["latency_avg_ms"],
                "error_type_accuracy": error_type.get("accuracy", 0.0),
                "other_ratio": other_ratio.get("ratio", 0.0),
                "avg_span_f05": avg_span_f05,
                "feedback_type_gold_rate": feedback.get("type_gold_match_rate", 0.0),
            }

            report["typological_analysis"][config_name] = result.get("type_analysis", {})
            report["predicted_type_distribution"][config_name] = result.get("predicted_type_distribution", {})

            # Build synthetic table row
            report["synthetic_table"].append({
                "model": config_name,
                # GEC metrics — identical across configs (LLM correction shared)
                "errant_f05": round(errant.get("f05", 0.0), 4),
                "errant_precision": round(errant.get("precision", 0.0), 4),
                "errant_recall": round(errant.get("recall", 0.0), 4),
                "tsf05": round(primary.get("f_score", 0.0), 4),
                "exact_match": round(exact_match.get("accuracy", 0.0), 4),
                # Pipeline metrics — vary between configs
                "error_type_accuracy": round(error_type.get("accuracy", 0.0), 4),
                "other_ratio": round(other_ratio.get("ratio", 0.0), 4),
                "avg_span_f05": round(avg_span_f05, 4),
                "feedback_type_gold_rate": round(feedback.get("type_gold_match_rate", 0.0), 4),
                "latency_ms": result["latency_avg_ms"],
            })

            # Qualitative micro-analysis: up to 5 examples
            samples = result.get("sample_predictions", [])
            for sample in samples[:5]:
                pred_type = sample.get("predicted_error_type", "other")
                gold_type = sample.get("gold_error_type", "unknown")
                pred_spans = sample.get("predicted_spans", [])
                gold_spans = sample.get("gold_spans", [])
                feedback = sample.get("feedback", {})

                # Determine qualitative category
                if not sample.get("model_corrected") or sample["model_corrected"].strip() == sample["original"].strip():
                    category = "uncorrected"
                elif pred_type == "other":
                    category = "other_type"
                elif pred_type.lower() == gold_type.lower() and gold_type not in ("unknown", "none"):
                    category = "well_categorized"
                else:
                    category = "partial"

                report["qualitative_analysis"].append({
                    "model": config_name,
                    "original": sample["original"],
                    "gold": sample["gold_corrected"],
                    "corrected": sample["model_corrected"],
                    "predicted_type": pred_type,
                    "gold_type": gold_type,
                    "span_count_pred": len(pred_spans),
                    "span_count_gold": len(gold_spans),
                    "feedback_present": bool(feedback and feedback.get("rule") and feedback.get("explanation")),
                    "feedback_type_matches_gold": bool(
                        feedback
                        and normalize_error_type(feedback.get("error_type")) == normalize_error_type(gold_type)
                        and normalize_error_type(gold_type) not in ("none", "unknown", None)
                    ),
                    "category": category,
                })

        # Comparative analysis
        configs = list(report["configurations"].items())
        if len(configs) >= 2:
            baseline = configs[0][1]
            for name, metrics in configs[1:]:
                report["comparative"][name] = {
                    "vs_baseline_tsf05_delta": round(
                        metrics["tsf05"] - baseline["tsf05"], 4
                    ),
                    "vs_baseline_precision_delta": round(
                        metrics["errant_precision"] - baseline["errant_precision"], 4
                    ),
                    "vs_baseline_recall_delta": round(
                        metrics["errant_recall"] - baseline["errant_recall"], 4
                    ),
                    "vs_baseline_exact_match_delta": round(
                        metrics["exact_match_accuracy"] - baseline["exact_match_accuracy"], 4
                    ),
                    "vs_baseline_improvement_rate_delta": round(
                        metrics["improvement_rate"] - baseline["improvement_rate"], 4
                    ),
                    "vs_baseline_error_type_accuracy_delta": round(
                        metrics["error_type_accuracy"] - baseline["error_type_accuracy"], 4
                    ),
                    "vs_baseline_other_ratio_delta": round(
                        metrics["other_ratio"] - baseline["other_ratio"], 4
                    ),
                    "vs_baseline_feedback_type_gold_delta": round(
                        metrics["feedback_type_gold_rate"] - baseline["feedback_type_gold_rate"], 4
                    ),
                }

        # Overall best config by error_type_accuracy (pipeline value proposition)
        if report["configurations"]:
            best_tsf05 = max(
                report["configurations"].items(),
                key=lambda x: x[1]["tsf05"],
            )
            best_type_acc = max(
                report["configurations"].items(),
                key=lambda x: x[1]["error_type_accuracy"],
            )
            report["summary"]["best_config_by_tsf05"] = best_tsf05[0]
            report["summary"]["best_tsf05_score"] = best_tsf05[1]["tsf05"]
            report["summary"]["best_config_by_error_type_accuracy"] = best_type_acc[0]
            report["summary"]["best_error_type_accuracy_score"] = best_type_acc[1]["error_type_accuracy"]
            report["summary"]["key_message"] = (
                "Le pipeline n'est pas concu pour ameliorer systematiquement la correction brute, "
                "mais pour transformer une sortie LLM en objet pedagogique structure, mesurable et exploitable."
            )
            report["summary"]["protocol_note"] = (
                "PROTOCOLE : llm_brut = 1 appel LLM (baseline). pipeline_structure et pipeline+memoire = 2 appels "
                "LLM par phrase : 1er appel partage (correction brute), 2e appel refine avec contexte pipeline "
                "(error_type detecte, +exemple similaire pgvector leave-one-out pour pipeline+memoire). "
                "ERRANT F0.5 mesure la qualite edit-level vs gold (BEA-2019). "
                "Metriques discriminantes : ERRANT F0.5, error_type_accuracy, avg_span_f05, feedback_type_gold_rate."
            )

        return report

    async def run_benchmark(
        self,
        db_session: AsyncSession,
        dataset_rows: list,
        configs: list[str] | None = None,
        level: str = "A2",
        verbose: bool = False,
        save: bool = True,
        split: str = "dev",
    ) -> dict:
        """Run full benchmark with per-row, per-config DB persistence."""
        from backend.llm import correct_with_ollama
        from backend.storage import benchmark_rows_table, benchmarks_table
        from backend.settings import settings
        from backend.text_utils import classify_error_type, compute_diff
        from backend.evaluation.metrics import evaluate_feedback
        from backend.evaluation.errant_eval import evaluate_errant
        from sqlalchemy import select, and_

        config_map = {
            "llm_brut": LLM_BRUT_CONFIG,
            "pipeline_structuré": PIPELINE_CONFIG,
            "pipeline+mémoire": PIPELINE_MEMORY_CONFIG,
        }
        selected = configs or list(config_map.keys())

        rows = list(dataset_rows)
        if self.max_examples:
            rows = rows[: self.max_examples]

        # Per-(row, config) skip: only skip a row for a config that already has a result
        already_done: set[tuple[int, str]] = set()
        if save:
            for cfg in selected:
                existing = await db_session.execute(
                    select(benchmark_rows_table.c.dataset_id)
                    .where(benchmark_rows_table.c.model_name == cfg)
                )
                for (row_id,) in existing.fetchall():
                    already_done.add((row_id, cfg))

        # Pipelines instantiated once — shared across all rows
        pipeline_no_mem = PipelineOrchestrator(use_similar_errors=False)
        pipeline_with_mem = PipelineOrchestrator(use_similar_errors=True)

        # Accumulate predictions per config for end-of-run aggregation
        config_predictions: dict[str, list[dict]] = {cfg: [] for cfg in selected}
        config_latencies: dict[str, float] = {cfg: 0.0 for cfg in selected}
        errors_by_config: dict[str, list] = {cfg: [] for cfg in selected}
        skipped_llm_errors = 0
        skipped_already_tested = 0
        total = len(rows)

        start_global = time.perf_counter()

        for idx, row in enumerate(rows, 1):
            original = row.input_phrase
            gold = row.corrected_gold
            error_type_gold_val = row.error_type_gold or "unknown"
            gold_spans = self._parse_spans(row.error_spans_gold)

            # Check if all selected configs already done for this row
            configs_needed = [c for c in selected if (row.id, c) not in already_done]
            if not configs_needed:
                skipped_already_tested += 1
                if verbose:
                    print(f"  [{idx}/{total}] SKIP (all configs done)")
                continue

            # LLM call — shared across all configs for this row (fair comparison)
            try:
                llm_output, _, _, _, _ = await correct_with_ollama(original)
            except Exception as e:
                skipped_llm_errors += 1
                for cfg in configs_needed:
                    errors_by_config[cfg].append({"row_id": row.id, "error": f"LLM: {e}"})
                if verbose:
                    print(f"  [{idx}/{total}] LLM ERROR: {e}")
                continue

            # Run each needed config
            for config_name in configs_needed:
                predicted_error_type = None
                predicted_spans: list[dict] = []
                feedback = None
                similar_found = 0
                t0 = time.perf_counter()

                try:
                    from backend.llm import refine_with_ollama
                    if config_name == "llm_brut":
                        # No refinement — raw LLM output only
                        corrected = llm_output
                        predicted_spans = compute_diff(original, corrected)
                        predicted_error_type = classify_error_type(original, corrected, "other")
                    elif config_name == "pipeline_structuré":
                        # Pipeline detects error type, then LLM refines with that context
                        result = pipeline_no_mem.run_sync(original, llm_output, level=level)
                        predicted_error_type = result.error_type
                        predicted_spans = result.errors
                        feedback = result.feedback
                        corrected = await refine_with_ollama(
                            original, llm_output, predicted_error_type,
                            similar_example=None,
                        )
                    else:  # pipeline+mémoire
                        # Pipeline detects error + finds similar example, LLM refines with both
                        result = await pipeline_with_mem.run(original, llm_output, level=level)
                        predicted_error_type = result.error_type
                        predicted_spans = result.errors
                        feedback = result.feedback
                        similar_found = len(result.similar_errors or [])
                        best_similar = result.similar_errors[0] if result.similar_errors else None
                        corrected = await refine_with_ollama(
                            original, llm_output, predicted_error_type,
                            similar_example=best_similar,
                        )
                except Exception as e:
                    errors_by_config[config_name].append({"row_id": row.id, "error": str(e)})
                    if verbose:
                        print(f"  [{idx}/{total}] {config_name} ERROR: {e}")
                    continue

                config_latencies[config_name] += (time.perf_counter() - t0) * 1000

                # Per-row metrics
                exact = corrected.strip().lower() == gold.strip().lower()
                seq_metrics = compute_token_sequence_metrics(corrected, gold)
                token_seq_f05 = seq_metrics["f_score"]
                gain_metrics = compute_gain_metric(original, corrected, gold)

                span_f05 = None
                if gold_spans:
                    span_result = evaluate_span_level(original, gold, corrected, gold_spans)
                    span_f05 = span_result.get("f_score")

                soft_result = compute_soft_match(corrected, gold, original, span_f05=span_f05)
                soft_match_val = soft_result["soft_match"]
                token_overlap = seq_metrics.get("token_sequence_ratio", 0.0)

                error_type_match = None
                if predicted_error_type and error_type_gold_val != "unknown":
                    error_type_match = (
                        normalize_error_type(predicted_error_type) == error_type_gold_val.lower()
                    )

                fb_eval = evaluate_feedback(feedback, predicted_error_type, error_type_gold_val)

                row_errant_f05 = 0.0
                try:
                    row_errant = evaluate_errant([original], [corrected], [gold])
                    row_errant_f05 = row_errant.get("f05", 0.0)
                except Exception:
                    pass

                if save:
                    await db_session.execute(
                        benchmark_rows_table.insert().values(
                            dataset_id=row.id,
                            model_name=config_name,
                            input_phrase=original,
                            corrected=corrected,
                            gold=gold,
                            match=exact,
                            exact_match=exact,
                            soft_match=soft_match_val,
                            precision=float(seq_metrics["precision"]),
                            recall=float(seq_metrics["recall"]),
                            f05=token_seq_f05,
                            token_overlap=round(token_overlap, 4),
                            span_f05=span_f05,
                            error_type_gold=error_type_gold_val,
                            error_type_predicted=predicted_error_type,
                            error_type_match=error_type_match,
                            feedback_present=fb_eval["feedback_present"],
                            feedback_type_match=fb_eval["type_matches_gold"],
                            feedback_valid=fb_eval["feedback_valid"],
                            errant_f05=row_errant_f05,
                        )
                    )
                    await db_session.commit()

                config_predictions[config_name].append({
                    "original": original,
                    "gold_corrected": gold,
                    "model_corrected": corrected,
                    "gold_spans": gold_spans,
                    "gold_error_type": error_type_gold_val,
                    "predicted_error_type": predicted_error_type,
                    "predicted_spans": predicted_spans,
                    "feedback": feedback,
                    "similar_found": similar_found,
                })

            if verbose:
                print(f"  [{idx}/{total}] row {row.id} — {len(configs_needed)} configs saved")

        results: dict[str, dict] = {}

        for config_name in selected:
            preds = config_predictions[config_name]
            if not preds:
                continue

            evaluated = len(preds)
            avg_latency = config_latencies[config_name] / evaluated if evaluated else 0.0

            metrics = compute_comprehensive_metrics(preds)

            # similar_errors_found_rate: % phrases where pgvector found ≥1 similar example
            # Only meaningful for pipeline+mémoire; 0 for other configs by construction
            similar_hits = sum(1 for p in preds if p.get("similar_found", 0) > 0)
            metrics["similar_errors_found_rate"] = round(similar_hits / len(preds), 4) if preds else 0.0

            # ERRANT — only needed for one config (scores are identical since corrected = llm_output)
            # Compute for all configs to keep structure consistent; ERRANT annotator is cached
            errant_metrics = evaluate_errant(
                originals=[p["original"] for p in preds],
                predictions=[p["model_corrected"] for p in preds],
                golds=[p["gold_corrected"] for p in preds],
            )
            metrics["errant_gec"] = errant_metrics

            results[config_name] = {
                "config": config_map[config_name],
                "metrics": metrics,
                "latency_avg_ms": round(avg_latency, 2),
                "dataset_size": len(dataset_rows),
                "evaluated_size": evaluated,
                "elapsed_ms": round((time.perf_counter() - start_global) * 1000, 2),
                "sample_predictions": preds[:5],
                "type_analysis": _compute_type_analysis(preds),
                "predicted_type_distribution": _compute_predicted_type_distribution(preds),
            }

        # Save aggregated summary (one row per config per run)
        if save and results:
            for config_name, result in results.items():
                metrics = result["metrics"]
                token_seq = metrics.get("token_sequence", {})
                exact_match = metrics.get("exact_match", {})
                error_type = metrics.get("error_type", {})
                other_ratio = metrics.get("other_ratio", {})
                feedback = metrics.get("feedback", {})
                errant_m = metrics.get("errant_gec", {})
                await db_session.execute(
                    benchmarks_table.insert().values(
                        model_name=config_name,
                        pipeline_version=settings.pipeline_version,
                        prompt_version=settings.pipeline_version,
                        dataset_version=f"benchmark:{split}",
                        dataset_size=result["dataset_size"],
                        precision=token_seq.get("precision", 0.0),
                        recall=token_seq.get("recall", 0.0),
                        f05=token_seq.get("f_score", 0.0),
                        errant_f05=errant_m.get("f05", 0.0),
                        errant_precision=errant_m.get("precision", 0.0),
                        errant_recall=errant_m.get("recall", 0.0),
                        exact_match_accuracy=exact_match.get("accuracy", 0.0),
                        error_type_accuracy=error_type.get("accuracy", 0.0),
                        other_ratio=other_ratio.get("ratio", 0.0),
                        avg_span_f05=metrics.get("avg_span_f05", 0.0),
                        feedback_valid_rate=feedback.get("type_gold_match_rate", 0.0),
                        latency_avg_ms=result["latency_avg_ms"],
                    )
                )
                await db_session.commit()

        return {
            "results": results,
            "meta": {
                "total_input_rows": len(dataset_rows),
                "skipped_already_tested": skipped_already_tested,
                "skipped_llm_errors": skipped_llm_errors,
                "unique_evaluated_rows": sum(len(p) for p in config_predictions.values()),
                "errors_by_config": errors_by_config,
            },
        }


