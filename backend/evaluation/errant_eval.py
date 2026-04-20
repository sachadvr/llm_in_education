"""ERRANT-based GEC evaluation (BEA-2019 standard).

Uses errant==3.0.0 with spaCy 3.x.

Difference from TSF0.5 (token-sequence F0.5):
    TSF0.5    — token overlap between two full sentences. Structurally high (≈0.90+)
                because most tokens are already correct. NOT comparable to literature.
    ERRANT F0.5 — edit-level P/R/F0.5. A no-op model scores 0. Directly comparable
                  to BEA-2019 published scores (best systems ≈ 0.59–0.73).

In this system ERRANT scores are identical across pipeline configs because the
pipeline does not modify the LLM correction — only adds annotation metadata.
This is expected and documented in the benchmark protocol_note.
"""

from __future__ import annotations

import errant


_annotator: errant.Annotator | None = None


def _get_annotator() -> errant.Annotator:
    global _annotator
    if _annotator is None:
        _annotator = errant.load("en")
    return _annotator


def _match_edits(hyp_edits: list, ref_edits: list) -> tuple[int, int, int]:
    """TP/FP/FN between hypothesis and reference edit sets.

    Type-independent matching: two edits match when they span the same
    original tokens (o_start, o_end). This is the BEA-2019 default variant.
    """
    matched_ref: set[int] = set()
    tp = 0

    for h in hyp_edits:
        for r_idx, r in enumerate(ref_edits):
            if r_idx in matched_ref:
                continue
            if h.o_start == r.o_start and h.o_end == r.o_end:
                tp += 1
                matched_ref.add(r_idx)
                break

    fp = len(hyp_edits) - tp
    fn = len(ref_edits) - len(matched_ref)
    return tp, fp, fn


def _f05(precision: float, recall: float) -> float:
    denom = (0.25 * precision) + recall
    if denom == 0.0:
        return 0.0
    return round(1.25 * precision * recall / denom, 4)


def evaluate_errant(
    originals: list[str],
    predictions: list[str],
    golds: list[str],
) -> dict:
    """Compute ERRANT edit-level precision, recall, F0.5 at corpus level.

    Args:
        originals:   Original (erroneous) sentences.
        predictions: Model-corrected sentences (LLM output).
        golds:       Gold-standard corrections.

    Returns:
        {
            "precision": float,
            "recall": float,
            "f05": float,       # edit-level F0.5 — comparable to BEA-2019 literature
            "tp": int,
            "fp": int,
            "fn": int,
            "evaluated": int,
            "skipped": int,
        }
    """
    annotator = _get_annotator()
    total_tp = total_fp = total_fn = 0
    evaluated = skipped = 0

    for orig, pred, gold in zip(originals, predictions, golds):
        try:
            orig_doc = annotator.parse(orig)
            pred_doc = annotator.parse(pred)
            gold_doc = annotator.parse(gold)

            hyp_edits = annotator.annotate(orig_doc, pred_doc)
            ref_edits = annotator.annotate(orig_doc, gold_doc)

            tp, fp, fn = _match_edits(hyp_edits, ref_edits)
            total_tp += tp
            total_fp += fp
            total_fn += fn
            evaluated += 1
        except Exception:
            skipped += 1
            continue

    precision = round(total_tp / (total_tp + total_fp), 4) if (total_tp + total_fp) > 0 else 0.0
    recall = round(total_tp / (total_tp + total_fn), 4) if (total_tp + total_fn) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f05": _f05(precision, recall),
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "evaluated": evaluated,
        "skipped": skipped,
    }
