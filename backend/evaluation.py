import json
import math
from collections import Counter
from typing import Dict, Iterable

from backend.text_utils import compute_diff, tokenize

def compute_gec_metrics(tp: int, fp: int, fn: int, beta: float = 0.5) -> Dict[str, float]:
    """
    Calcule Precision, Recall et F-beta score.
    Par défaut beta=0.5 (F0.5) pour privilégier la précision (évite les fausses corrections).
    """
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    
    if precision + recall == 0:
        f_score = 0.0
    else:
        beta_sq = beta ** 2
        f_score = (1 + beta_sq) * (precision * recall) / ((beta_sq * precision) + recall)
        
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f_score": round(f_score, 4)
    }


def compute_bleu(references: list[list[str]], hypotheses: list[list[str]], max_n: int = 4) -> float:
    if not references or not hypotheses or len(references) != len(hypotheses):
        return 0.0

    precisions: list[float] = []
    for n in range(1, max_n + 1):
        clipped = 0
        total = 0
        for ref, hyp in zip(references, hypotheses):
            if len(hyp) < n:
                continue
            ref_counts = Counter(tuple(ref[i : i + n]) for i in range(max(0, len(ref) - n + 1)))
            hyp_counts = Counter(tuple(hyp[i : i + n]) for i in range(max(0, len(hyp) - n + 1)))
            total += sum(hyp_counts.values())
            for gram, count in hyp_counts.items():
                clipped += min(count, ref_counts.get(gram, 0))
        precisions.append((clipped / total) if total else 0.0)

    if any(p == 0 for p in precisions):
        return 0.0

    ref_len = sum(len(ref) for ref in references)
    hyp_len = sum(len(hyp) for hyp in hypotheses)
    if hyp_len == 0:
        return 0.0

    bp = 1.0 if hyp_len > ref_len else math.exp(1 - (ref_len / hyp_len))
    score = bp * math.exp(sum(math.log(p) for p in precisions) / max_n)
    return round(score, 4)

def _load_spans(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return obj if isinstance(obj, list) else []


def _span_key(span: dict) -> tuple:
    return (
        span.get("type"),
        span.get("tag"),
        str(span.get("original") or "").strip().lower(),
        str(span.get("corrected") or "").strip().lower(),
        int(span.get("start") or 0),
        int(span.get("end") or 0),
    )


def evaluate_correction(
    original: str,
    gold_corrected: str,
    model_corrected: str,
    gold_spans_json: str | None = None,
) -> Dict[str, int]:
    """
    Évalue si la correction du modèle est correcte par rapport à la vérité terrain.
    Retourne TP, FP, FN pour une phrase donnée.
    
    Simplification : 
    - TP: Le modèle a corrigé qqch que l'humain a aussi corrigé (et de la même manière).
    - FP: Le modèle a corrigé qqch que l'humain n'a pas corrigé, ou a mal corrigé.
    - FN: Le modèle n'a pas corrigé qqch que l'humain a corrigé.
    - TN: Ni humain ni modèle n'ont corrigé (phrase déjà correcte).
    """
    gold_spans = _load_spans(gold_spans_json)
    model_spans = compute_diff(original, model_corrected)

    tp, fp, fn = 0, 0, 0

    if gold_spans:
        gold_keys = [_span_key(span) for span in gold_spans]
        model_keys = [_span_key(span) for span in model_spans]
        matched = set(gold_keys) & set(model_keys)
        tp = len(matched)
        fp = len([key for key in model_keys if key not in matched])
        fn = len([key for key in gold_keys if key not in matched])
        return {"tp": tp, "fp": fp, "fn": fn}

    # Fallback phrase-level si pas de spans gold
    from backend.text_utils import same_meaning

    human_changed = not same_meaning(original, gold_corrected)
    model_changed = not same_meaning(original, model_corrected)

    if human_changed:
        if model_changed:
            if tokenize(gold_corrected) == tokenize(model_corrected):
                tp = 1
            else:
                fp = 1
                fn = 1
        else:
            fn = 1
    elif model_changed:
        fp = 1

    return {"tp": tp, "fp": fp, "fn": fn}
