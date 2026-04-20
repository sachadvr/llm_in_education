#!/usr/bin/env python3
"""
simulate_h2_extended.py — H2 extended validation with multi-session spaced
repetition, mixed errors per session, probabilistic extinction, and
treatment/control split for exercise targeting effect.

Design:
- N learners (default 50), 5 sessions at days 1/3/7/14/30 from base
- Each session: phrases_per_learner sentences, mix of (dominant_error,
  secondary_error, correct) drawn from probability schedule
- Treated learners (50%) receive targeted exercise after S1; their
  P(dominant_error) decays per session per --decay-curve
- Control learners (50%) keep flat P(dominant_error) (no learning)
- All sessions hit Ollama for real corrections
- Metrics per session: extinction of S1 dominant, learning curve per
  family, exercise->reduction correlation (treated vs control)

Usage:
    python simulate_h2_extended.py --learners 50 --phrases-per-learner 5 \
        --output-dir benchmark_outputs/h2_extended

    # Resume:
    python simulate_h2_extended.py --resume --output-dir benchmark_outputs/h2_extended
"""

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── CLI args (set env before backend imports) ─────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="H2 extended multi-session simulation")
    p.add_argument("--learners", type=int, default=50)
    p.add_argument("--phrases-per-learner", type=int, default=5)
    p.add_argument("--sessions", type=int, default=5)
    p.add_argument("--intervals", type=str, default="1,3,7,14,30",
                   help="Comma-separated session day offsets from base (default: 1,3,7,14,30)")
    p.add_argument("--decay-curve", type=str, default="0.8,0.65,0.5,0.35,0.2",
                   help="P(dominant error) per session for treated learners")
    p.add_argument("--control-p", type=float, default=0.8,
                   help="Flat P(dominant) for control group (default: 0.8)")
    p.add_argument("--secondary-rate", type=float, default=0.5,
                   help="Of non-dominant slots, fraction with secondary error (rest correct)")
    p.add_argument("--treatment-fraction", type=float, default=0.5)
    p.add_argument("--model", type=str, default="")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--max-retries", type=int, default=1)
    p.add_argument("--output-dir", type=str, default="benchmark_outputs/h2_extended")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


_ARGS = _parse_args()

if _ARGS.model:
    os.environ["OLLAMA_MODEL"] = _ARGS.model
if not os.environ.get("OLLAMA_HOST"):
    os.environ["OLLAMA_HOST"] = "http://localhost:11434"
os.environ.setdefault("USE_OLLAMA", "true")
os.environ.setdefault("DATABASE_URL", "")

_PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.llm import correct_with_ollama, generate_exercise_with_ollama  # noqa: E402
from backend.pipeline.orchestrator import PipelineOrchestrator              # noqa: E402
from backend.pedagogy.adaptivity import calculate_error_weight              # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────────

LAMBDA_DECAY = 0.1
PROFILE_FAMILIES = ["agreement", "preposition", "article", "mixed", "progressive"]

# Map family → dominant canonical error type and acceptable detected set
FAMILY_DOMINANT = {
    "agreement":   ("agreement",   {"agreement", "tense"}),
    "preposition": ("preposition", {"preposition"}),
    "article":     ("article",     {"article"}),
    "mixed":       ("agreement",   {"agreement", "tense", "preposition", "article"}),
    "progressive": ("agreement",   {"agreement", "tense"}),
}

# Secondary family per primary (used for mixed errors in non-dominant slots)
SECONDARY_FAMILY = {
    "agreement":   "preposition",
    "preposition": "article",
    "article":     "agreement",
    "mixed":       "preposition",
    "progressive": "article",
}

# Erroneous sentences (dominant error of given type)
SENTENCE_BANK: dict[str, list[str]] = {
    "agreement": [
        "She go to school every day.",
        "He have a new car.",
        "They was very happy yesterday.",
        "The children plays outside.",
        "My friend don't like coffee.",
        "The teacher explain the lesson.",
        "She don't know the answer.",
        "He make mistakes often.",
        "The team are winning the game.",
        "She always arrive late.",
        "He don't understand the rules.",
        "The dog run very fast.",
        "My sister work at the hospital.",
        "The boys was tired after school.",
        "She have a big family.",
    ],
    "preposition": [
        "I depend of my parents.",
        "She is interested by music.",
        "He is good in math.",
        "I arrived to the airport.",
        "She is married with a doctor.",
        "He is afraid from spiders.",
        "I listen the radio.",
        "She is waiting the bus.",
        "He is proud from his son.",
        "I am angry to her.",
        "She is looking the window.",
        "She arrived at Monday.",
        "He is responsible of the team.",
        "I am bored of this movie.",
        "She apologized for me.",
    ],
    "article": [
        "I bought car yesterday.",
        "She is teacher.",
        "I saw big dog in the park.",
        "He wants to be doctor.",
        "She went to cinema.",
        "I need advice.",
        "He is best student.",
        "She gave me interesting book.",
        "I have headache.",
        "He plays piano.",
        "She is eating apple.",
        "I need to call police.",
        "He opened door.",
        "She is studying at university.",
        "I met nice person today.",
    ],
}
SENTENCE_BANK["mixed"] = SENTENCE_BANK["agreement"]
SENTENCE_BANK["progressive"] = SENTENCE_BANK["agreement"]

# Correct grammatical sentences (no error) for "learned" slots
CORRECT_BANK = [
    "She goes to school every day.",
    "He has a new car.",
    "They were very happy yesterday.",
    "The children play outside.",
    "My friend doesn't like coffee.",
    "The teacher explains the lesson.",
    "She doesn't know the answer.",
    "He makes mistakes often.",
    "I depend on my parents.",
    "She is interested in music.",
    "He is good at math.",
    "I arrived at the airport.",
    "I bought a car yesterday.",
    "She is a teacher.",
    "He wants to be a doctor.",
    "She went to the cinema.",
    "I have a headache.",
    "She is eating an apple.",
    "He plays the piano.",
    "He opened the door.",
]

# Heuristic keyword sets for exercise_matches_target check
_ARTICLES = {"a", "an", "the"}
_PREPOSITIONS = {
    "in", "on", "at", "to", "of", "by", "for", "with", "about", "from",
    "into", "out", "up", "down", "over", "under", "between", "through",
    "during", "before", "after", "since", "until", "against", "depend",
}
_AGREEMENT_BLANKS = {
    "is", "are", "was", "were", "has", "have", "do", "does",
    "go", "goes", "plays", "play", "makes", "make", "runs", "run",
}

# ── CSV schemas ───────────────────────────────────────────────────────────────

FIELDS_SESSIONS = [
    "learner_id", "treatment_group", "session_id", "session_day",
    "sentence_idx", "input_sentence", "intended_error_type",
    "corrected_sentence", "predicted_error_type", "feedback_present",
    "ollama_latency_ms", "postprocessing_latency_ms",
]
FIELDS_PRIORITIES = [
    "learner_id", "treatment_group", "session_id", "session_day",
    "error_type", "count", "last_seen_days", "weight", "rank",
]
FIELDS_EXERCISES = [
    "learner_id", "treatment_group", "session_id", "target_error_type",
    "generated_exercise", "exercise_sentence", "blank",
    "exercise_matches_target", "generation_latency_ms",
]
FIELDS_LEARNING_CURVE = [
    "learner_id", "treatment_group", "family", "session_id", "session_day",
    "dominant_s1_count", "dominant_s1_weight", "dominant_s1_rank",
    "extinction_top3", "extinction_top1",
]
FIELDS_SUMMARY = [
    "learner_id", "family", "treatment_group",
    "expected_dominant_error", "detected_dominant_error_s1",
    "top_priority_match_s1", "exercise_matches_target",
    "dominant_count_s1", "dominant_count_final",
    "dominant_weight_s1", "dominant_weight_final",
    "weight_reduction_pct", "count_reduction_pct",
    "extinct_top3_session", "extinct_top1_session",
    "failed_correction_count", "total_sentences",
    "average_ollama_latency_ms", "average_postprocessing_latency_ms",
]


# ── Adaptivity helpers (in-memory) ────────────────────────────────────────────

def _update_error_history(history: dict[str, dict], error_type: str, ts: datetime) -> None:
    if not error_type or error_type in ("none", "other"):
        return
    if error_type not in history:
        history[error_type] = {"count": 0, "last_seen": ts}
    history[error_type]["count"] += 1
    history[error_type]["last_seen"] = ts


def _rank_errors(history: dict[str, dict], ref: datetime) -> list[dict]:
    out = []
    for et, d in history.items():
        w = calculate_error_weight(d["count"], d["last_seen"], reference_time=ref)
        days = max(0.0, (ref - d["last_seen"]).total_seconds() / 86400)
        out.append({"error_type": et, "count": d["count"], "weight": round(w, 4),
                    "days_since": round(days, 3)})
    out.sort(key=lambda x: x["weight"], reverse=True)
    for i, r in enumerate(out):
        r["rank"] = i + 1
    return out


def _exercise_matches_target(sent: str, blank: str, target: str) -> bool:
    bl = blank.lower().strip(".,;:!?'\"")
    sl = sent.lower()
    if target == "article":
        return bl in _ARTICLES or "article" in sl or "determiner" in sl
    if target == "preposition":
        return bl in _PREPOSITIONS or "preposition" in sl
    if target in ("agreement", "progressive"):
        return bl in _AGREEMENT_BLANKS or "agreement" in sl or "subject" in sl or "verb" in sl
    if target in ("tense", "verb_form"):
        return bl in _AGREEMENT_BLANKS or "tense" in sl or "verb" in sl
    if target == "mixed":
        return bl in _ARTICLES or bl in _PREPOSITIONS or bl in _AGREEMENT_BLANKS
    return False


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _ensure_header(path: Path, fields: list[str]) -> None:
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _append(path: Path, rows: list[dict], fields: list[str]) -> None:
    if not rows:
        return
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fields, extrasaction="ignore").writerows(rows)


# ── Async Ollama wrappers ─────────────────────────────────────────────────────

async def _safe_correct(sent: str, timeout: float, retries: int,
                        logger: logging.Logger) -> Optional[tuple[str, str, float]]:
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            corrected, _, _, et, _ = await asyncio.wait_for(
                correct_with_ollama(sent), timeout=timeout)
            return corrected, et, (time.perf_counter() - t0) * 1000
        except asyncio.TimeoutError:
            logger.error(f"TIMEOUT correct ({attempt+1}, {timeout}s): {sent[:60]!r}")
        except Exception as exc:
            logger.error(f"ERROR correct ({attempt+1}): {type(exc).__name__}: {exc}")
        if attempt < retries:
            await asyncio.sleep(2.0)
    return None


async def _safe_exercise(focus: str, timeout: float,
                         logger: logging.Logger) -> Optional[tuple[str, str, str, float]]:
    t0 = time.perf_counter()
    try:
        prompt, sent, blank = await asyncio.wait_for(
            generate_exercise_with_ollama(level="A2", focus=focus), timeout=timeout)
        return prompt, sent, blank, (time.perf_counter() - t0) * 1000
    except asyncio.TimeoutError:
        logger.error(f"TIMEOUT exercise focus={focus!r}")
    except Exception as exc:
        logger.error(f"ERROR exercise: {type(exc).__name__}: {exc}")
    return None


# ── Profile + sentence selection ──────────────────────────────────────────────

def _build_profiles(n: int, phrases: int, treat_frac: float, seed: int) -> list[dict]:
    rng = random.Random(seed)
    profiles = []
    fam_count: dict[str, int] = {f: 0 for f in PROFILE_FAMILIES}

    # Distribute treatment evenly across families via interleaved indexing
    treat_target = int(n * treat_frac)
    treat_assigned = 0

    for i in range(n):
        family = PROFILE_FAMILIES[i % len(PROFILE_FAMILIES)]
        idx = fam_count[family]
        fam_count[family] += 1

        # Alternate treatment so families are balanced
        treat = (i % 2 == 0) if treat_assigned < treat_target else False
        if treat:
            treat_assigned += 1

        dom_canon, dom_set = FAMILY_DOMINANT[family]
        sec = SECONDARY_FAMILY[family]

        profiles.append({
            "learner_id": f"learner_{family}_{idx:03d}",
            "family": family,
            "expected_dominant": dom_canon,
            "expected_dominant_set": dom_set,
            "secondary_family": sec,
            "treatment_group": "treated" if treat else "control",
            "rng_seed": seed + i * 1000,
        })
    return profiles


def _build_session_sentences(profile: dict, session_idx: int, n_phrases: int,
                             p_dominant: float, secondary_rate: float,
                             rng: random.Random) -> list[tuple[str, str]]:
    """Returns list of (sentence, intended_error_type) for one session.

    intended_error_type ∈ {"dominant", "secondary", "none"}.
    """
    fam = profile["family"]
    sec = profile["secondary_family"]
    dom_bank = SENTENCE_BANK[fam]
    sec_bank = SENTENCE_BANK[sec]

    out = []
    for j in range(n_phrases):
        r = rng.random()
        if r < p_dominant:
            s = dom_bank[(session_idx * n_phrases + j) % len(dom_bank)]
            out.append((s, "dominant"))
        elif r < p_dominant + (1 - p_dominant) * secondary_rate:
            s = sec_bank[(session_idx * n_phrases + j) % len(sec_bank)]
            out.append((s, "secondary"))
        else:
            s = CORRECT_BANK[(session_idx * n_phrases + j) % len(CORRECT_BANK)]
            out.append((s, "none"))
    return out


# ── Per-learner simulation ────────────────────────────────────────────────────

async def _simulate_learner(profile: dict, orch: PipelineOrchestrator,
                            args: argparse.Namespace, intervals: list[int],
                            decay_curve: list[float], paths: dict[str, Path],
                            logger: logging.Logger) -> dict:
    learner_id = profile["learner_id"]
    family = profile["family"]
    treat = profile["treatment_group"]
    base = datetime.now(timezone.utc)
    rng = random.Random(profile["rng_seed"])

    history: dict[str, dict] = {}
    sess_rows, prio_rows, ex_rows, curve_rows = [], [], [], []
    o_lats, p_lats = [], []
    failed = 0

    dominant_s1: Optional[str] = None
    expected_set = profile["expected_dominant_set"]
    exercise_match_ok = False
    dom_s1_count = 0
    dom_s1_weight = 0.0
    extinct_top3_session: Optional[int] = None
    extinct_top1_session: Optional[int] = None
    final_count_dom_s1 = 0
    final_weight_dom_s1 = 0.0

    for s_idx in range(args.sessions):
        day = intervals[s_idx]
        ref_time = base + timedelta(days=day)

        # Decide P(dominant) for this session
        if treat == "treated":
            p_dom = decay_curve[s_idx] if s_idx < len(decay_curve) else decay_curve[-1]
        else:
            p_dom = args.control_p

        sentences = _build_session_sentences(
            profile, s_idx, args.phrases_per_learner,
            p_dom, args.secondary_rate, rng,
        )

        # Process each sentence via Ollama
        for sent_idx, (sent, intended) in enumerate(sentences):
            ts = base + timedelta(days=day, minutes=sent_idx)

            res = await _safe_correct(sent, args.timeout, args.max_retries, logger)
            if res is None:
                failed += 1
                logger.warning(f"  Skip [{learner_id}] s{s_idx+1} idx={sent_idx}")
                continue
            corrected, et_llm, ol = res
            o_lats.append(ol)

            t0 = time.perf_counter()
            try:
                pr = orch.run_sync(original=sent, corrected=corrected,
                                   model_error_type=et_llm, level="A2")
                final_et = pr.error_type
                fb = bool(pr.feedback and pr.feedback.get("explanation"))
                pp = (time.perf_counter() - t0) * 1000
                p_lats.append(pp)
            except Exception as exc:
                logger.error(f"run_sync err [{learner_id}] s{s_idx+1}: {exc}")
                final_et = et_llm
                fb = False
                pp = None

            _update_error_history(history, final_et, ts)

            sess_rows.append({
                "learner_id": learner_id,
                "treatment_group": treat,
                "session_id": s_idx + 1,
                "session_day": day,
                "sentence_idx": sent_idx,
                "input_sentence": sent,
                "intended_error_type": intended,
                "corrected_sentence": corrected,
                "predicted_error_type": final_et,
                "feedback_present": fb,
                "ollama_latency_ms": round(ol, 1),
                "postprocessing_latency_ms": round(pp, 1) if pp else None,
            })

        # Priorities at end of session
        priorities = _rank_errors(history, ref=ref_time)
        for p in priorities:
            prio_rows.append({
                "learner_id": learner_id,
                "treatment_group": treat,
                "session_id": s_idx + 1,
                "session_day": day,
                "error_type": p["error_type"],
                "count": p["count"],
                "last_seen_days": p["days_since"],
                "weight": p["weight"],
                "rank": p["rank"],
            })

        # Capture S1 dominant + generate exercise (treated only)
        if s_idx == 0:
            dominant_s1 = priorities[0]["error_type"] if priorities else "none"
            dom_s1_count = priorities[0]["count"] if priorities else 0
            dom_s1_weight = priorities[0]["weight"] if priorities else 0.0

            if treat == "treated":
                ex = await _safe_exercise(dominant_s1, args.timeout, logger)
                if ex is not None:
                    pr_text, sent_text, blank, ex_lat = ex
                    matches = _exercise_matches_target(sent_text, blank, dominant_s1)
                    exercise_match_ok = matches
                    ex_rows.append({
                        "learner_id": learner_id,
                        "treatment_group": treat,
                        "session_id": 1,
                        "target_error_type": dominant_s1,
                        "generated_exercise": pr_text[:300],
                        "exercise_sentence": sent_text[:300],
                        "blank": blank,
                        "exercise_matches_target": matches,
                        "generation_latency_ms": round(ex_lat, 1),
                    })
                else:
                    ex_rows.append({
                        "learner_id": learner_id,
                        "treatment_group": treat,
                        "session_id": 1,
                        "target_error_type": dominant_s1,
                        "generated_exercise": "FAILED",
                        "exercise_sentence": "FAILED",
                        "blank": "FAILED",
                        "exercise_matches_target": False,
                        "generation_latency_ms": None,
                    })

        # Learning curve row + extinction tracking (relative to S1 dominant)
        if dominant_s1 is not None:
            top3_types = [p["error_type"] for p in priorities[:3]]
            top1_type = priorities[0]["error_type"] if priorities else None
            in_top3 = dominant_s1 in top3_types
            in_top1 = (top1_type == dominant_s1)
            dom_entry = next((p for p in priorities if p["error_type"] == dominant_s1), None)

            curve_rows.append({
                "learner_id": learner_id,
                "treatment_group": treat,
                "family": family,
                "session_id": s_idx + 1,
                "session_day": day,
                "dominant_s1_count": dom_entry["count"] if dom_entry else 0,
                "dominant_s1_weight": dom_entry["weight"] if dom_entry else 0.0,
                "dominant_s1_rank": dom_entry["rank"] if dom_entry else None,
                "extinction_top3": not in_top3,
                "extinction_top1": not in_top1,
            })

            if s_idx >= 1:
                if extinct_top3_session is None and not in_top3:
                    extinct_top3_session = s_idx + 1
                if extinct_top1_session is None and not in_top1:
                    extinct_top1_session = s_idx + 1

            if s_idx == args.sessions - 1:
                final_count_dom_s1 = dom_entry["count"] if dom_entry else 0
                final_weight_dom_s1 = dom_entry["weight"] if dom_entry else 0.0

    # ── Summary ────────────────────────────────────────────────────────────────
    top_match_s1 = (expected_set is None) or (dominant_s1 in expected_set)
    weight_red = (
        round((dom_s1_weight - final_weight_dom_s1) / dom_s1_weight, 3)
        if dom_s1_weight else None
    )
    count_red = (
        round((dom_s1_count - final_count_dom_s1) / dom_s1_count, 3)
        if dom_s1_count else None
    )

    summary = {
        "learner_id": learner_id,
        "family": family,
        "treatment_group": treat,
        "expected_dominant_error": profile["expected_dominant"],
        "detected_dominant_error_s1": dominant_s1,
        "top_priority_match_s1": top_match_s1,
        "exercise_matches_target": exercise_match_ok,
        "dominant_count_s1": dom_s1_count,
        "dominant_count_final": final_count_dom_s1,
        "dominant_weight_s1": dom_s1_weight,
        "dominant_weight_final": final_weight_dom_s1,
        "weight_reduction_pct": weight_red,
        "count_reduction_pct": count_red,
        "extinct_top3_session": extinct_top3_session,
        "extinct_top1_session": extinct_top1_session,
        "failed_correction_count": failed,
        "total_sentences": args.phrases_per_learner * args.sessions,
        "average_ollama_latency_ms": (
            round(sum(o_lats) / len(o_lats), 1) if o_lats else None),
        "average_postprocessing_latency_ms": (
            round(sum(p_lats) / len(p_lats), 1) if p_lats else None),
    }

    _append(paths["sessions"], sess_rows, FIELDS_SESSIONS)
    _append(paths["priorities"], prio_rows, FIELDS_PRIORITIES)
    _append(paths["exercises"], ex_rows, FIELDS_EXERCISES)
    _append(paths["curve"], curve_rows, FIELDS_LEARNING_CURVE)

    return summary


# ── Global summary ────────────────────────────────────────────────────────────

def _compute_summary(summaries: list[dict], output_dir: Path,
                     logger: logging.Logger) -> None:
    if not summaries:
        logger.warning("No summaries.")
        return

    def rate(vals): return round(sum(1 for v in vals if v) / len(vals), 3) if vals else 0.0
    def avg(vals):
        clean = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(clean) / len(clean), 3) if clean else None

    treated = [s for s in summaries if s["treatment_group"] == "treated"]
    control = [s for s in summaries if s["treatment_group"] == "control"]

    def group_stats(group):
        if not group:
            return {}
        return {
            "n": len(group),
            "top_priority_match_rate": rate([s["top_priority_match_s1"] for s in group]),
            "exercise_match_rate": rate([s["exercise_matches_target"] for s in group]),
            "weight_reduction_avg": avg([s["weight_reduction_pct"] for s in group]),
            "count_reduction_avg": avg([s["count_reduction_pct"] for s in group]),
            "extinct_top3_rate": rate([s["extinct_top3_session"] for s in group]),
            "extinct_top1_rate": rate([s["extinct_top1_session"] for s in group]),
            "avg_extinct_top3_session": avg([s["extinct_top3_session"] for s in group]),
        }

    by_family: dict[str, dict] = {}
    for fam in PROFILE_FAMILIES:
        fs = [s for s in summaries if s["family"] == fam]
        if fs:
            by_family[fam] = {
                "n": len(fs),
                "treated": group_stats([s for s in fs if s["treatment_group"] == "treated"]),
                "control": group_stats([s for s in fs if s["treatment_group"] == "control"]),
            }

    report = {
        "global": {
            "total_learners": len(summaries),
            "treated": group_stats(treated),
            "control": group_stats(control),
        },
        "by_family": by_family,
    }

    path = output_dir / "h2_extended_global_summary.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    sep = "=" * 78
    logger.info(f"\n{sep}")
    logger.info("H2 EXTENDED — TREATED vs CONTROL")
    logger.info(sep)
    logger.info(f"  {'metric':<32}  {'treated':>12}  {'control':>12}")
    logger.info(f"  {'-'*60}")
    t, c = report["global"]["treated"], report["global"]["control"]
    for k in ["n", "top_priority_match_rate", "exercise_match_rate",
              "weight_reduction_avg", "count_reduction_avg",
              "extinct_top3_rate", "extinct_top1_rate", "avg_extinct_top3_session"]:
        tv, cv = t.get(k), c.get(k)
        logger.info(f"  {k:<32}  {str(tv):>12}  {str(cv):>12}")
    logger.info(f"\n  Full report: {path}")
    logger.info(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = _ARGS
    intervals = [int(x) for x in args.intervals.split(",")]
    decay_curve = [float(x) for x in args.decay_curve.split(",")]
    if len(intervals) < args.sessions:
        raise SystemExit(f"--intervals needs >= {args.sessions} values")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_path = output_dir / "errors.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, mode="a", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("h2_ext")

    paths = {
        "sessions":   output_dir / "h2_ext_sessions.csv",
        "priorities": output_dir / "h2_ext_priorities.csv",
        "exercises":  output_dir / "h2_ext_exercises.csv",
        "curve":      output_dir / "h2_ext_learning_curve.csv",
        "summary":    output_dir / "h2_ext_summary.csv",
    }

    progress_path = output_dir / "progress.json"
    config_path   = output_dir / "run_config.json"

    config = {
        "learners": args.learners,
        "phrases_per_learner": args.phrases_per_learner,
        "sessions": args.sessions,
        "intervals_days": intervals,
        "decay_curve": decay_curve,
        "control_p": args.control_p,
        "secondary_rate": args.secondary_rate,
        "treatment_fraction": args.treatment_fraction,
        "model": os.environ.get("OLLAMA_MODEL", ""),
        "ollama_host": os.environ.get("OLLAMA_HOST", ""),
        "timeout_s": args.timeout,
        "seed": args.seed,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "note": "Functional validation — synthetic learners, NOT pedagogical proof",
    }

    completed: set[str] = set()
    if args.resume and progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            completed = set(json.load(f).get("completed_learners", []))
        logger.info(f"Resume: {len(completed)} done")
    else:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        for p, fields in [(paths["sessions"], FIELDS_SESSIONS),
                          (paths["priorities"], FIELDS_PRIORITIES),
                          (paths["exercises"], FIELDS_EXERCISES),
                          (paths["curve"], FIELDS_LEARNING_CURVE),
                          (paths["summary"], FIELDS_SUMMARY)]:
            _ensure_header(p, fields)

    logger.info(f"Model    : {os.environ.get('OLLAMA_MODEL', '(unset)')}")
    logger.info(f"Host     : {os.environ.get('OLLAMA_HOST', '(unset)')}")
    logger.info(f"Learners : {args.learners} ({int(args.learners*args.treatment_fraction)} treated / "
                f"{args.learners - int(args.learners*args.treatment_fraction)} control)")
    logger.info(f"Sessions : {args.sessions} at days {intervals[:args.sessions]}")
    logger.info(f"Decay    : {decay_curve}")
    logger.info(f"Output   : {output_dir}")

    profiles = _build_profiles(args.learners, args.phrases_per_learner,
                               args.treatment_fraction, args.seed)
    orch = PipelineOrchestrator(use_similar_errors=False)
    summaries: list[dict] = []

    if args.resume and paths["summary"].exists():
        with open(paths["summary"], newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for b in ("top_priority_match_s1", "exercise_matches_target"):
                    row[b] = row[b].lower() in ("true", "1", "yes")
                for n in ("dominant_count_s1", "dominant_count_final",
                         "failed_correction_count", "total_sentences",
                         "extinct_top3_session", "extinct_top1_session"):
                    try: row[n] = int(row[n]) if row[n] not in ("", "None") else None
                    except (ValueError, TypeError): row[n] = None
                for fl in ("dominant_weight_s1", "dominant_weight_final",
                           "weight_reduction_pct", "count_reduction_pct",
                           "average_ollama_latency_ms", "average_postprocessing_latency_ms"):
                    try: row[fl] = float(row[fl]) if row[fl] not in ("", "None") else None
                    except (ValueError, TypeError): row[fl] = None
                summaries.append(row)

    for i, profile in enumerate(profiles):
        lid = profile["learner_id"]
        if lid in completed:
            logger.info(f"[{i+1}/{len(profiles)}] Skip {lid}")
            continue

        logger.info(f"[{i+1}/{len(profiles)}] {lid}  fam={profile['family']}  "
                    f"group={profile['treatment_group']}")
        t_start = time.perf_counter()

        try:
            summary = await _simulate_learner(
                profile=profile, orch=orch, args=args,
                intervals=intervals, decay_curve=decay_curve,
                paths=paths, logger=logger,
            )
            summaries.append(summary)
            _append(paths["summary"], [summary], FIELDS_SUMMARY)
            elapsed = time.perf_counter() - t_start
            logger.info(f"  → OK  s1_match={summary['top_priority_match_s1']}  "
                        f"weight_red={summary['weight_reduction_pct']}  "
                        f"extinct@s={summary['extinct_top3_session']}  ({elapsed:.1f}s)")
        except Exception as exc:
            logger.error(f"FATAL [{lid}]: {type(exc).__name__}: {exc}")

        completed.add(lid)
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump({"completed_learners": sorted(completed),
                       "total": len(profiles), "completed": len(completed),
                       "last_updated": datetime.now(timezone.utc).isoformat()},
                      f, indent=2)

    _compute_summary(summaries, output_dir, logger)


if __name__ == "__main__":
    asyncio.run(main())
