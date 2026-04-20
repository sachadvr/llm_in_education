"""Metric helpers for grammatical error correction."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from backend.evaluation import compute_bleu, compute_gec_metrics, evaluate_correction
from backend.text_utils import tokenize

if TYPE_CHECKING:
    pass

_ERROR_TYPE_NORMALIZATION: dict[str, str] = {
    # Pipeline-specific terms → BEA2019 canonical
    "noun_number": "agreement",
    "verb_tense": "tense",
    "determiner": "article",
    "word_order": "syntax",
    "word_choice": "other",
    "redundancy": "other",
    "missing_word": "other",
    "unnecessary_word": "other",
    "missing_punct": "punctuation",
    "unnecessary_punct": "punctuation",
    # verb_form intentionally NOT mapped to tense — BEA2019 uses verb_form directly
}


def _normalize_error_type(error_type: str | None) -> str | None:
    if not error_type:
        return error_type
    return _ERROR_TYPE_NORMALIZATION.get(error_type.lower(), error_type.lower())


def compute_token_sequence_metrics(pred: str, gold: str) -> dict:
    """Compute Token-Sequence F0.5 (TSF0.5) between corrected sentence and gold sentence."""
    pred_tokens = tokenize(pred)
    gold_tokens = tokenize(gold)

    matcher = difflib.SequenceMatcher(None, pred_tokens, gold_tokens)
    tp = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in matcher.get_opcodes() if tag == "equal")
    fp = len(pred_tokens) - tp
    fn = len(gold_tokens) - tp

    metrics = compute_gec_metrics(tp, fp, fn, beta=0.5)
    metrics["tp"] = tp
    metrics["fp"] = fp
    metrics["fn"] = fn
    metrics["token_sequence_ratio"] = round(
        2 * tp / (len(pred_tokens) + len(gold_tokens)), 4
        if (len(pred_tokens) + len(gold_tokens)) > 0 else 0.0
    )
    return metrics


def compute_gain_metric(original: str, pred: str, gold: str) -> dict:
    """Measure whether pred brings us closer to gold than original was."""
    orig_tokens = tokenize(original)
    pred_tokens = tokenize(pred)
    gold_tokens = tokenize(gold)

    pred_dist = 1.0 - difflib.SequenceMatcher(None, pred_tokens, gold_tokens).ratio()
    orig_dist = 1.0 - difflib.SequenceMatcher(None, orig_tokens, gold_tokens).ratio()

    gain = orig_dist - pred_dist
    relative_gain = (gain / orig_dist) if orig_dist > 0 else 0.0

    return {
        "gain": round(gain, 4),
        "relative_gain": round(relative_gain, 4),
        "improved": gain > 0,
        "worsened": gain < 0,
        "unchanged": gain == 0,
    }


def compute_soft_match(
    pred: str,
    gold: str,
    original: str,
    span_f05: float | None = None,
    token_seq_f05_threshold: float = 0.85,
    span_f05_threshold: float = 0.7,
) -> dict:
    """Strict composite soft match that actually discriminates GEC quality."""
    seq_metrics = compute_token_sequence_metrics(pred, gold)
    gain_metrics = compute_gain_metric(original, pred, gold)

    token_seq_f05 = seq_metrics["f_score"]

    cond1 = token_seq_f05 >= token_seq_f05_threshold
    cond2 = gain_metrics["improved"] or (
        gain_metrics["unchanged"] and token_seq_f05 >= 0.98
    )
    cond3 = (span_f05 >= span_f05_threshold) if span_f05 is not None else True

    pred_len = len(tokenize(pred))
    gold_len = len(tokenize(gold))
    cond4 = abs(pred_len - gold_len) <= 2

    return {
        "soft_match": cond1 and cond2 and cond3 and cond4,
        "token_sequence_f05": token_seq_f05,
        "token_sequence_precision": seq_metrics["precision"],
        "token_sequence_recall": seq_metrics["recall"],
        "gain": gain_metrics["gain"],
        "relative_gain": gain_metrics["relative_gain"],
        "improved": gain_metrics["improved"],
        "worsened": gain_metrics["worsened"],
        "span_f05": span_f05,
    }


def compute_span_overlap(
    pred_span: dict,
    gold_span: dict,
    iou_threshold: float = 0.5,
) -> tuple[bool, float]:
    """Compute overlap between predicted and gold spans using IoU."""
    # Token-level overlap
    pred_start = pred_span.get("start", 0)
    pred_end = pred_span.get("end", 0)
    gold_start = gold_span.get("start", 0)
    gold_end = gold_span.get("end", 0)
    
    # Compute intersection
    inter_start = max(pred_start, gold_start)
    inter_end = min(pred_end, gold_end)
    intersection = max(0, inter_end - inter_start)
    
    # Compute union
    union_start = min(pred_start, gold_start)
    union_end = max(pred_end, gold_end)
    union = union_end - union_start
    
    if union == 0:
        return False, 0.0
    
    iou = intersection / union
    return iou >= iou_threshold, iou


def match_spans_tolerant(
    pred_spans: list[dict],
    gold_spans: list[dict],
    iou_threshold: float = 0.5,
    type_match_required: bool = True,
) -> dict:
    """Match predicted spans to gold spans with tolerance."""
    matched_pred = set()
    matched_gold = set()
    matched_pairs = []
    
    # Sort gold spans by start position for deterministic matching
    sorted_gold = sorted(enumerate(gold_spans), key=lambda x: x[1].get("start", 0))
    
    for gold_idx, gold_span in sorted_gold:
        if gold_idx in matched_gold:
            continue
        
        best_match = None
        best_iou = 0.0
        
        for pred_idx, pred_span in enumerate(pred_spans):
            if pred_idx in matched_pred:
                continue
            
            # Check type match if required
            if type_match_required:
                pred_type = pred_span.get("type", "other")
                gold_type = gold_span.get("type", "other")
                if pred_type != gold_type:
                    continue
            
            # Compute overlap
            is_match, iou = compute_span_overlap(pred_span, gold_span, iou_threshold)
            
            if is_match and iou > best_iou:
                best_match = pred_idx
                best_iou = iou
        
        if best_match is not None:
            matched_pred.add(best_match)
            matched_gold.add(gold_idx)
            matched_pairs.append({
                "pred_idx": best_match,
                "gold_idx": gold_idx,
                "iou": round(best_iou, 3),
            })
    
    tp = len(matched_pairs)
    fp = len(pred_spans) - len(matched_pred)
    fn = len(gold_spans) - len(matched_gold)
    
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "matched_pairs": matched_pairs,
    }


def evaluate_span_level(
    original: str,
    gold_corrected: str,
    model_corrected: str,
    gold_spans: list[dict],
    iou_threshold: float = 0.5,
) -> dict:
    """Evaluate correction at span level with tolerant matching."""
    from backend.text_utils import compute_diff
    
    # Compute model spans
    model_spans = compute_diff(original, model_corrected)
    
    # Match spans
    match_result = match_spans_tolerant(
        model_spans, gold_spans, iou_threshold
    )
    
    # Compute metrics
    metrics = compute_gec_metrics(
        match_result["tp"],
        match_result["fp"],
        match_result["fn"],
        beta=0.5,
    )
    
    return {
        **match_result,
        **metrics,
        "model_spans": model_spans,
        "gold_spans": gold_spans,
        "iou_threshold": iou_threshold,
    }


def compute_error_type_accuracy(predictions: list[dict]) -> dict:
    """Compute error type classification accuracy against gold labels.

    Only counts predictions where gold type is known and not 'none'.
    """
    total = 0
    correct = 0
    for pred in predictions:
        gold_type = pred.get("gold_error_type")
        pred_type = pred.get("predicted_error_type")
        if not gold_type or gold_type.lower() in ("none", "unknown"):
            continue
        if not pred_type:
            continue
        total += 1
        normalized_pred = _normalize_error_type(pred_type)
        if normalized_pred == gold_type.lower():
            correct += 1
    return {
        "accuracy": round(correct / total, 4) if total else 0.0,
        "correct": correct,
        "total": total,
    }


def compute_other_ratio(predictions: list[dict]) -> dict:
    """Compute ratio of 'other' error types among predictions with errors."""
    total_errors = 0
    other_count = 0
    for pred in predictions:
        pred_type = pred.get("predicted_error_type")
        if not pred_type or pred_type.lower() == "none":
            continue
        total_errors += 1
        if pred_type.lower() == "other":
            other_count += 1
    return {
        "ratio": round(other_count / total_errors, 4) if total_errors else 0.0,
        "other_count": other_count,
        "total_errors": total_errors,
    }


def evaluate_feedback(
    feedback: dict | None,
    predicted_type: str | None,
    gold_type: str | None = None,
) -> dict:
    """Evaluate feedback quality and alignment with gold annotations.

    type_matches_prediction is always True when feedback exists (circular by construction —
    feedback["error_type"] is set from predicted_type in build_feedback).
    type_matches_gold normalizes BOTH sides to BEA2019 before comparing, so ALAO-specific
    types (noun_number, verb_tense, determiner…) align correctly with BEA2019 gold labels.

    # IMPORTANT:
    # feedback_valid is equivalent to type_matches_gold because feedback always contains
    # rule and explanation via templates (has_rule/has_explanation always True).
    # Use feedback_present for structural presence, feedback_type_gold_rate for alignment.

    Returns:
        Dict with feedback_present, type_matches_prediction, type_matches_gold, feedback_valid.
    """
    if not feedback or not isinstance(feedback, dict):
        return {
            "feedback_present": False,
            "type_matches_prediction": False,
            "type_matches_gold": False,
            "feedback_valid": False,
        }
    has_rule = bool(feedback.get("rule"))
    has_explanation = bool(feedback.get("explanation"))
    feedback_type = feedback.get("error_type", "other")
    # Circular by construction — feedback["error_type"] == predicted_type always
    type_matches_prediction = bool(
        predicted_type and feedback_type.lower() == predicted_type.lower()
    )
    # Normalize BOTH sides to BEA2019 before comparing.
    # feedback_type is in ALAO taxonomy (noun_number, verb_tense, determiner…).
    # gold_type is in BEA2019 taxonomy (agreement, tense, article…).
    # Without normalizing feedback_type, ALAO-specific types always fail even when correct.
    normalized_feedback = _normalize_error_type(feedback_type) if feedback_type else None
    normalized_gold = _normalize_error_type(gold_type) if gold_type else None
    type_matches_gold = bool(
        normalized_feedback
        and normalized_gold
        and normalized_gold not in ("none", "unknown")
        and normalized_feedback == normalized_gold
    )
    # feedback_valid ≡ type_matches_gold (has_rule and has_explanation always True via templates)
    return {
        "feedback_present": has_rule and has_explanation,
        "type_matches_prediction": type_matches_prediction,
        "type_matches_gold": type_matches_gold,
        "feedback_valid": type_matches_gold,
    }


def compute_comprehensive_metrics(
    predictions: list[dict],
) -> dict:
    """Compute comprehensive metrics over multiple predictions."""
    total_tp, total_fp, total_fn = 0, 0, 0
    total_seq_tp, total_seq_fp, total_seq_fn = 0, 0, 0
    exact_matches = 0
    improved_count = 0
    worsened_count = 0
    span_metrics_list = []
    span_f05_scores = []

    for pred in predictions:
        original = pred["original"]
        gold = pred["gold_corrected"]
        model = pred["model_corrected"]
        gold_spans = pred.get("gold_spans", [])
        pred_spans = pred.get("predicted_spans", [])

        # Exact match
        if gold.strip().lower() == model.strip().lower():
            exact_matches += 1

        # Span-level evaluation
        if gold_spans:
            span_result = evaluate_span_level(
                original, gold, model, gold_spans
            )
            total_tp += span_result["tp"]
            total_fp += span_result["fp"]
            total_fn += span_result["fn"]
            span_metrics_list.append(span_result)
            span_f05_scores.append(span_result.get("f_score", 0.0))
        else:
            # Fallback to simple evaluation
            result = evaluate_correction(original, gold, model, None)
            total_tp += result["tp"]
            total_fp += result["fp"]
            total_fn += result["fn"]

        # Token-sequence evaluation (ordered, not set-based)
        seq_metrics = compute_token_sequence_metrics(model, gold)
        total_seq_tp += seq_metrics["tp"]
        total_seq_fp += seq_metrics["fp"]
        total_seq_fn += seq_metrics["fn"]

        # Gain metric
        gain_m = compute_gain_metric(original, model, gold)
        if gain_m["improved"]:
            improved_count += 1
        elif gain_m["worsened"]:
            worsened_count += 1

    # Aggregate metrics
    gec_metrics = compute_gec_metrics(total_tp, total_fp, total_fn, beta=0.5)
    seq_gec = compute_gec_metrics(total_seq_tp, total_seq_fp, total_seq_fn, beta=0.5)
    n = len(predictions)

    # Error type accuracy and other ratio
    type_acc = compute_error_type_accuracy(predictions)
    other_r = compute_other_ratio(predictions)

    # Feedback evaluation — type_matches_gold requires gold_error_type in predictions
    feedback_evals = []
    for pred in predictions:
        fe = evaluate_feedback(
            pred.get("feedback"),
            pred.get("predicted_error_type"),
            pred.get("gold_error_type"),
        )
        feedback_evals.append(fe)

    feedback_present_rate = (
        sum(1 for f in feedback_evals if f["feedback_present"]) / len(feedback_evals)
        if feedback_evals else 0.0
    )
    feedback_type_gold_rate = (
        sum(1 for f in feedback_evals if f["type_matches_gold"]) / len(feedback_evals)
        if feedback_evals else 0.0
    )
    # Average span F0.5 per row (when gold spans available)
    avg_span_f05 = round(sum(span_f05_scores) / len(span_f05_scores), 4) if span_f05_scores else 0.0

    return {
        "token_sequence": {
            "tp": total_seq_tp,
            "fp": total_seq_fp,
            "fn": total_seq_fn,
            **seq_gec,
        },
        "span_level": {
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            **gec_metrics,
        },
        "exact_match": {
            "correct": exact_matches,
            "total": n,
            "accuracy": round(exact_matches / n, 4) if n else 0.0,
        },
        "gain": {
            "improved": improved_count,
            "worsened": worsened_count,
            "unchanged": n - improved_count - worsened_count,
            "improvement_rate": round(improved_count / n, 4) if n else 0.0,
        },
        "error_type": type_acc,
        "other_ratio": other_r,
        "avg_span_f05": avg_span_f05,
        "feedback": {
            "present_rate": round(feedback_present_rate, 4),
            # type_gold_match_rate: normalized comparison ALAO↔BEA2019 (both sides normalized)
            "type_gold_match_rate": round(feedback_type_gold_rate, 4),
            "total_evaluated": len(feedback_evals),
        },
        "individual_results": span_metrics_list,
    }
