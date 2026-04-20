#!/usr/bin/env python3
"""
simulate_h2_ollama.py — H2 Functional Validation via Synthetic Learner Simulation

IMPORTANT: This script validates the *functional behavior* of the adaptive engine
using synthetic learner profiles. It does NOT validate pedagogical effectiveness
or real learner improvement. Results support H2 at an architectural/algorithmic
level only — confirming that the weight-ranking, prioritization, and adaptive
loop operate as specified, not that they improve human learning outcomes.

Usage:
    # Quick test (3 learners, 5 phrases each):
    python simulate_h2_ollama.py --learners 3 --phrases-per-learner 5

    # Overnight run (50 learners, faster model):
    python simulate_h2_ollama.py --learners 50 --phrases-per-learner 5 \\
        --model gemma2:9b --timeout 90 --output-dir benchmark_outputs/h2_overnight

    # Resume interrupted run:
    python simulate_h2_ollama.py --resume --output-dir benchmark_outputs/h2_overnight

Requirements:
    - Ollama running locally on port 11434 (or OLLAMA_HOST set in env / .env)
    - Project root in PYTHONPATH (script handles this automatically)
    - No DB, no Docker, no Redis required
"""

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Parse CLI args before any project imports (env vars must be set first) ────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="H2 overnight simulation — synthetic learner adaptive loop"
    )
    p.add_argument("--learners", type=int, default=10,
                   help="Total number of synthetic learners (default: 10)")
    p.add_argument("--phrases-per-learner", type=int, default=5,
                   help="Sentences per learner per session (default: 5)")
    p.add_argument("--model", type=str, default="",
                   help="Ollama model override (e.g. gemma2:9b). Uses OLLAMA_MODEL env if omitted.")
    p.add_argument("--resume", action="store_true",
                   help="Resume from existing progress.json in output-dir")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Per-call Ollama timeout in seconds (default: 60)")
    p.add_argument("--max-retries", type=int, default=1,
                   help="Max retries per failed Ollama call (default: 1)")
    p.add_argument("--output-dir", type=str, default="benchmark_outputs/h2_overnight",
                   help="Output directory for CSVs, logs, config (default: benchmark_outputs/h2_overnight)")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for reproducible profile generation (default: 42)")
    return p.parse_args()


_ARGS = _parse_args()

# Set critical env vars BEFORE importing backend modules (pydantic Settings reads env at import time)
if _ARGS.model:
    os.environ["OLLAMA_MODEL"] = _ARGS.model
if not os.environ.get("OLLAMA_HOST"):
    # Default to localhost for non-Docker use; .env has host.docker.internal which only works in Docker
    os.environ["OLLAMA_HOST"] = "http://localhost:11434"
os.environ.setdefault("USE_OLLAMA", "true")
os.environ.setdefault("DATABASE_URL", "")  # Prevent DB engine creation errors

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Project imports (after env setup) ─────────────────────────────────────────
from backend.llm import correct_with_ollama, generate_exercise_with_ollama  # noqa: E402
from backend.pipeline.orchestrator import PipelineOrchestrator              # noqa: E402
from backend.pedagogy.adaptivity import calculate_error_weight               # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────────

LAMBDA_DECAY = 0.1
SPACED_REPETITION_INTERVALS = [1, 3, 7, 14, 30]
PROFILE_FAMILIES = ["agreement", "preposition", "article", "mixed", "progressive"]

# Sentence banks — deterministic, seeded selection per learner
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
        "He talked about his problem to me.",
        "She arrived at Monday.",
        "He is responsible of the team.",
        "I am bored of this movie.",
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
    "mixed": [
        "She go to school every day.",
        "I depend of my parents.",
        "I bought car yesterday.",
        "They was very happy.",
        "He is good in math.",
        "She is teacher at university.",
        "The children plays outside.",
        "I listen the radio.",
        "He wants to be doctor.",
        "My friend don't like coffee.",
        "She is interested by music.",
        "I saw big dog.",
        "He make mistakes often.",
        "I arrived to the airport.",
        "She have a big family.",
    ],
    "progressive": [
        "She go to school every day.",
        "He have a new car.",
        "They was very happy yesterday.",
        "The children plays outside.",
        "My friend don't like coffee.",
        "The teacher explain the lesson.",
        "She don't know the answer.",
        "He make mistakes often.",
        "The dog run very fast.",
        "My sister work at the hospital.",
        "The boys was tired after school.",
        "She have a big family.",
        "He don't understand the rules.",
        "She always arrive late.",
        "The team are winning the game.",
    ],
}

# Session 2 alternate sentences — different error type than session 1 dominant
# Purpose: show priority shift by introducing a competing error category in S2
SESSION2_ALTERNATE: dict[str, list[str]] = {
    "agreement": [
        # Session 1 dominant = agreement → S2 introduces preposition errors
        "I depend of my parents.",
        "She is interested by music.",
        "He is good in math.",
        "I arrived to the airport.",
        "She is married with a doctor.",
        "He is afraid from spiders.",
        "I listen the radio.",
        "She is waiting the bus.",
    ],
    "preposition": [
        # Session 1 dominant = preposition → S2 introduces article errors
        "I bought car yesterday.",
        "She is teacher.",
        "I saw big dog in the park.",
        "He wants to be doctor.",
        "She went to cinema.",
        "I need advice.",
        "He is best student.",
        "She gave me interesting book.",
    ],
    "article": [
        # Session 1 dominant = article → S2 introduces agreement errors
        "She go to school every day.",
        "He have a new car.",
        "They was very happy yesterday.",
        "The children plays outside.",
        "My friend don't like coffee.",
        "The teacher explain the lesson.",
        "She don't know the answer.",
        "He make mistakes often.",
    ],
    "mixed": [
        # Mixed keeps varied errors — pick alternating families
        "She go to school every day.",
        "I bought car yesterday.",
        "I depend of my parents.",
        "He have a new car.",
        "She is teacher.",
        "He is good in math.",
        "They was very happy.",
        "I saw big dog.",
    ],
    "progressive": [
        # Progressive: session 2 has fewer dominant errors (more corrected sentences)
        # Mix of already-correct sentences and preposition errors
        "She goes to school every day.",    # correct — dominant error fixed
        "I depend of my parents.",          # preposition error
        "He has a new car.",                # correct — dominant error fixed
        "She is interested by music.",      # preposition error
        "They were very happy yesterday.",  # correct — dominant error fixed
        "He is good in math.",              # preposition error
        "The children play outside.",       # correct — dominant error fixed
        "I arrived to the airport.",        # preposition error
    ],
}

# Explicit S2 error type per family (pre-defined — no heuristic needed)
# S2 sentences are hand-crafted to introduce this specific error type.
S2_ERROR_TYPE: dict[str, Optional[str]] = {
    "agreement":   "preposition",   # S2 shifts learner to preposition errors
    "preposition": "article",       # S2 shifts learner to article errors
    "article":     "agreement",     # S2 shifts learner to agreement errors
    "mixed":       None,            # Mixed: no dominant S2 type → skip injection
    "progressive": "preposition",   # Progressive: S2 alternates correct + preposition
}

# Correct sentences embedded in progressive S2 bank (even indices)
_PROGRESSIVE_CORRECT_SENTENCES: frozenset[str] = frozenset({
    "she goes to school every day.",
    "he has a new car.",
    "they were very happy yesterday.",
    "the children play outside.",
})

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

# CSV field definitions (module-level to avoid duplication)
FIELDS_SESSIONS = [
    "learner_id", "session_id", "sentence_idx", "input_sentence",
    "corrected_sentence", "predicted_error_type", "feedback_present",
    "dominant_error_before", "dominant_error_after",
    "ollama_latency_ms", "postprocessing_latency_ms",
]
FIELDS_PRIORITIES = [
    "learner_id", "session_id", "error_type", "count",
    "last_seen_days", "weight", "rank",
]
FIELDS_EXERCISES = [
    "learner_id", "session_id", "target_error_type",
    "generated_exercise", "exercise_sentence", "blank",
    "exercise_matches_target", "generation_latency_ms",
]
FIELDS_SUMMARY = [
    "learner_id", "family",
    "expected_dominant_error", "detected_dominant_error_s1", "detected_dominant_error_s2",
    "top_priority_match", "exercise_match_rate_heuristic",
    "priority_shift_observed", "dominant_weight_decay_pct",
    "simulated_error_reduction", "adaptive_loop_success_rate",
    "failed_correction_count", "total_sentences_s1", "s2_dominant_new_count",
    "average_ollama_latency_ms", "average_postprocessing_latency_ms",
]


# ── In-memory adaptivity helpers ───────────────────────────────────────────────

def _update_error_history(
    history: dict[str, dict],
    error_type: str,
    timestamp: datetime,
) -> None:
    """Replaces track_error() — no DB. Skips 'none' and 'other'."""
    if not error_type or error_type in ("none", "other"):
        return
    if error_type not in history:
        history[error_type] = {"count": 0, "last_seen": timestamp}
    history[error_type]["count"] += 1
    history[error_type]["last_seen"] = timestamp


def _rank_errors(
    history: dict[str, dict],
    reference_time: Optional[datetime] = None,
) -> list[dict]:
    """Replaces get_frequent_errors() — pure Python. Returns list sorted by weight desc."""
    now = reference_time or datetime.now(timezone.utc)
    results = []
    for error_type, data in history.items():
        w = calculate_error_weight(data["count"], data["last_seen"], reference_time=now)
        days_since = max(0.0, (now - data["last_seen"]).total_seconds() / 86400)
        results.append({
            "error_type": error_type,
            "count": data["count"],
            "weight": round(w, 4),
            "days_since": round(days_since, 3),
            "last_seen": data["last_seen"].isoformat(),
        })
    results.sort(key=lambda x: x["weight"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


# ── Exercise target heuristic ──────────────────────────────────────────────────

def _exercise_matches_target(exercise_sentence: str, blank: str, target: str) -> bool:
    """
    Heuristic check — NOT ground truth. Returns True if blank or sentence keywords
    are consistent with target error type. Explicitly approximate.
    """
    blank_lower = blank.lower().strip(".,;:!?'\"")
    sentence_lower = exercise_sentence.lower()

    if target == "article":
        return (
            blank_lower in _ARTICLES
            or "article" in sentence_lower
            or "determiner" in sentence_lower
        )
    elif target == "preposition":
        return (
            blank_lower in _PREPOSITIONS
            or "preposition" in sentence_lower
        )
    elif target in ("agreement", "progressive"):
        return (
            blank_lower in _AGREEMENT_BLANKS
            or "agreement" in sentence_lower
            or "subject" in sentence_lower
            or "verb" in sentence_lower
        )
    elif target in ("tense", "verb_form"):
        _tense_blanks = {
            "was", "were", "had", "went", "said", "did", "could", "would",
            "will", "been", "done", "gone", "is", "are", "go", "goes",
            "has", "have", "do", "does", "come", "came", "take", "took",
            "make", "made", "see", "saw", "get", "got", "give", "gave",
        }
        return (
            blank_lower in _tense_blanks
            or "tense" in sentence_lower
            or "verb" in sentence_lower
            or "past" in sentence_lower
            or "future" in sentence_lower
        )
    elif target == "mixed":
        # Mixed target — any match counts
        return (
            blank_lower in _ARTICLES
            or blank_lower in _PREPOSITIONS
            or blank_lower in _AGREEMENT_BLANKS
        )
    return False


# ── CSV helpers ────────────────────────────────────────────────────────────────

def _ensure_csv_header(path: Path, fields: list[str]) -> None:
    """Write header only if file does not exist (safe for resume)."""
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _append_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writerows(rows)


# ── Async Ollama wrappers ──────────────────────────────────────────────────────

async def _safe_correct(
    sentence: str,
    timeout: float,
    max_retries: int,
    logger: logging.Logger,
) -> Optional[tuple[str, str, float]]:
    """
    Returns (corrected, error_type, latency_ms) or None on failure.
    Never falls back silently to original or gold sentence.
    """
    for attempt in range(max_retries + 1):
        t0 = time.perf_counter()
        try:
            corrected, _, _, error_type, _ = await asyncio.wait_for(
                correct_with_ollama(sentence), timeout=timeout
            )
            return corrected, error_type, (time.perf_counter() - t0) * 1000
        except asyncio.TimeoutError:
            logger.error(
                f"TIMEOUT correct_with_ollama (attempt {attempt+1}, {timeout}s): "
                f"{sentence[:60]!r}"
            )
        except Exception as exc:
            logger.error(
                f"ERROR correct_with_ollama (attempt {attempt+1}): "
                f"{type(exc).__name__}: {exc} — {sentence[:60]!r}"
            )
        if attempt < max_retries:
            await asyncio.sleep(2.0)
    return None


async def _safe_exercise(
    focus: str,
    timeout: float,
    logger: logging.Logger,
) -> Optional[tuple[str, str, str, float]]:
    """Returns (prompt, sentence, blank, latency_ms) or None on failure."""
    t0 = time.perf_counter()
    try:
        prompt, sentence, blank = await asyncio.wait_for(
            generate_exercise_with_ollama(level="A2", focus=focus),
            timeout=timeout,
        )
        return prompt, sentence, blank, (time.perf_counter() - t0) * 1000
    except asyncio.TimeoutError:
        logger.error(f"TIMEOUT generate_exercise focus={focus!r} ({timeout}s)")
    except Exception as exc:
        logger.error(
            f"ERROR generate_exercise focus={focus!r}: "
            f"{type(exc).__name__}: {exc}"
        )
    return None


# ── Learner profile generation ─────────────────────────────────────────────────

def _build_learner_profiles(
    n_learners: int,
    phrases_per_learner: int,
    seed: int,
) -> list[dict]:
    """
    Generate N profiles distributed evenly across 5 families.
    Profile content is deterministic given (n_learners, phrases_per_learner, seed).
    """
    import random as _rng_module
    rng = _rng_module.Random(seed)
    profiles: list[dict] = []

    family_counters: dict[str, int] = {f: 0 for f in PROFILE_FAMILIES}

    for i in range(n_learners):
        family = PROFILE_FAMILIES[i % len(PROFILE_FAMILIES)]
        idx = family_counters[family]
        family_counters[family] += 1

        learner_id = f"learner_{family}_{idx:03d}"
        bank = SENTENCE_BANK[family]
        alt_bank = SESSION2_ALTERNATE[family]

        # Session 1: pick `phrases_per_learner` sentences from bank (seeded, with wrap)
        s1 = [bank[(idx * phrases_per_learner + j) % len(bank)] for j in range(phrases_per_learner)]

        # Session 2: pick from alternate bank (different error type or reduced errors)
        s2 = [alt_bank[(idx * phrases_per_learner + j) % len(alt_bank)] for j in range(phrases_per_learner)]

        # expected_dominant_set: acceptable detected types for top_priority_match.
        # agreement/progressive accept both "agreement" and "tense" because the ALAO
        # classifier may return "tense" for subject-verb corrections (known classifier
        # limitation documented in benchmark audit).
        expected_dominant_set: Optional[set] = {
            "agreement":   {"agreement", "tense"},
            "preposition": {"preposition"},
            "article":     {"article"},
            "mixed":       None,
            "progressive": {"agreement", "tense"},
        }[family]

        # expected_dominant: canonical label for CSV reporting
        expected_dominant = {
            "agreement": "agreement",
            "preposition": "preposition",
            "article": "article",
            "mixed": None,
            "progressive": "agreement",
        }[family]

        profiles.append({
            "learner_id": learner_id,
            "family": family,
            "expected_dominant": expected_dominant,
            "expected_dominant_set": expected_dominant_set,
            "session1_sentences": s1,
            "session2_sentences": s2,
            "session2_error_type": S2_ERROR_TYPE[family],
        })

    return profiles


# ── Core per-learner simulation ────────────────────────────────────────────────

async def _simulate_learner(
    profile: dict,
    orchestrator: PipelineOrchestrator,
    timeout: float,
    max_retries: int,
    output_paths: dict[str, Path],
    logger: logging.Logger,
) -> dict:
    """
    Run full two-session simulation for one learner.
    Writes to CSVs incrementally. Returns summary dict.
    """
    learner_id = profile["learner_id"]
    family = profile["family"]
    expected_dominant = profile["expected_dominant"]
    now_base = datetime.now(timezone.utc)

    error_history: dict[str, dict] = {}
    sessions_rows: list[dict] = []
    priorities_rows: list[dict] = []
    exercises_rows: list[dict] = []

    ollama_latencies: list[float] = []
    postprocessing_latencies: list[float] = []
    failed_corrections = 0

    # ── Session 1 — Ollama corrections ────────────────────────────────────────
    for sent_idx, sentence in enumerate(profile["session1_sentences"]):
        # Stagger timestamps so each sentence has distinct last_seen
        ts = now_base - timedelta(minutes=len(profile["session1_sentences"]) - sent_idx)

        result = await _safe_correct(sentence, timeout, max_retries, logger)

        if result is None:
            failed_corrections += 1
            logger.warning(f"  Skipping sentence [{learner_id}] s1 idx={sent_idx}: Ollama failed")
            continue

        corrected_llm, error_type_llm, ollama_lat = result
        ollama_latencies.append(ollama_lat)

        # Post-processing via run_sync (no DB, no Ollama)
        t0_pp = time.perf_counter()
        try:
            pr = orchestrator.run_sync(
                original=sentence,
                corrected=corrected_llm,
                model_error_type=error_type_llm,
                level="A2",
            )
            final_error_type = pr.error_type
            feedback_present = bool(
                pr.feedback and pr.feedback.get("explanation")
            )
            pp_lat = (time.perf_counter() - t0_pp) * 1000
            postprocessing_latencies.append(pp_lat)
        except Exception as exc:
            logger.error(f"run_sync error [{learner_id}] s1 idx={sent_idx}: {exc}")
            final_error_type = error_type_llm
            feedback_present = False
            pp_lat = None

        _update_error_history(error_history, final_error_type, ts)

        sessions_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "sentence_idx": sent_idx,
            "input_sentence": sentence,
            "corrected_sentence": corrected_llm,
            "predicted_error_type": final_error_type,
            "feedback_present": feedback_present,
            "dominant_error_before": "",   # backfilled below
            "dominant_error_after": "",
            "ollama_latency_ms": round(ollama_lat, 1),
            "postprocessing_latency_ms": round(pp_lat, 1) if pp_lat else None,
        })

    # Priority after session 1
    # Reference time = now_base so S1 errors look recent
    priority_s1 = _rank_errors(error_history, reference_time=now_base)
    dominant_s1 = priority_s1[0]["error_type"] if priority_s1 else "none"

    # Backfill dominant_error_before in all S1 rows
    for row in sessions_rows:
        row["dominant_error_before"] = dominant_s1

    for p in priority_s1:
        priorities_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            **{k: p[k] for k in ("error_type", "count", "weight", "rank")},
            "last_seen_days": p["days_since"],
        })

    # ── Exercise generation for dominant S1 error ──────────────────────────────
    ex_result = await _safe_exercise(dominant_s1, timeout, logger)

    if ex_result is not None:
        ex_prompt, ex_sentence, ex_blank, ex_lat = ex_result
        ex_matches = _exercise_matches_target(ex_sentence, ex_blank, dominant_s1)
        exercises_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "target_error_type": dominant_s1,
            "generated_exercise": ex_prompt[:300],
            "exercise_sentence": ex_sentence[:300],
            "blank": ex_blank,
            "exercise_matches_target": ex_matches,
            "generation_latency_ms": round(ex_lat, 1),
        })
        exercise_match_ok = ex_matches
    else:
        exercises_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "target_error_type": dominant_s1,
            "generated_exercise": "FAILED",
            "exercise_sentence": "FAILED",
            "blank": "FAILED",
            "exercise_matches_target": False,
            "generation_latency_ms": None,
        })
        exercise_match_ok = False

    # ── Session 2 — Synthetic (no Ollama) ─────────────────────────────────────
    # S2 sentences come from the alternate bank (different error type than dominant S1).
    # Timestamps are placed 1 day after S1 to simulate a realistic study gap.
    # Priority is recalculated at S2 reference time (now_base + 2 days) so
    # the 1-day decay is visible: S1 dominant decays, S2 type is fresh.
    s2_ref_time = now_base + timedelta(days=2)
    s2_new_error_count = 0

    for sent_idx, sentence in enumerate(profile["session2_sentences"]):
        ts_s2 = now_base + timedelta(days=1, minutes=sent_idx)

        try:
            pr2 = orchestrator.run_sync(
                original=sentence,
                corrected=sentence,    # synthetic: sentence fed as-is (no Ollama)
                model_error_type="none",
                level="A2",
            )
            final_error_type_s2 = pr2.error_type
        except Exception as exc:
            logger.error(f"run_sync error [{learner_id}] s2 idx={sent_idx}: {exc}")
            final_error_type_s2 = "none"

        # Inject the pre-defined S2 error type directly (no heuristic).
        # Progressive family: correct sentences get "none", error sentences get "preposition".
        # Other families: all S2 sentences use the explicit S2 error type.
        s2_explicit_type = profile["session2_error_type"]
        if s2_explicit_type is not None:
            if family == "progressive":
                is_correct_s2 = sentence.strip().lower() in _PROGRESSIVE_CORRECT_SENTENCES
                final_error_type_s2 = "none" if is_correct_s2 else s2_explicit_type
            else:
                final_error_type_s2 = s2_explicit_type

        _update_error_history(error_history, final_error_type_s2, ts_s2)
        if final_error_type_s2 not in ("none", "other", "FAILED"):
            s2_new_error_count += 1

        sessions_rows.append({
            "learner_id": learner_id,
            "session_id": 2,
            "sentence_idx": sent_idx,
            "input_sentence": sentence,
            "corrected_sentence": sentence,   # synthetic — no LLM correction
            "predicted_error_type": final_error_type_s2,
            "feedback_present": False,
            "dominant_error_before": dominant_s1,
            "dominant_error_after": "",       # backfilled below
            "ollama_latency_ms": None,
            "postprocessing_latency_ms": None,
        })

    # Priority after session 2 (reference time = S2 ref time, 2 days after S1)
    priority_s2 = _rank_errors(error_history, reference_time=s2_ref_time)
    dominant_s2 = priority_s2[0]["error_type"] if priority_s2 else "none"

    for row in sessions_rows:
        if row["session_id"] == 2:
            row["dominant_error_after"] = dominant_s2

    for p in priority_s2:
        priorities_rows.append({
            "learner_id": learner_id,
            "session_id": 2,
            **{k: p[k] for k in ("error_type", "count", "weight", "rank")},
            "last_seen_days": p["days_since"],
        })

    # ── Metrics ────────────────────────────────────────────────────────────────
    # top_priority_match: dominant S1 in expected set for this profile.
    # agreement/progressive accept both "agreement" and "tense" (ALAO classifier
    # may return either for subject-verb corrections — documented classifier limitation).
    expected_set = profile.get("expected_dominant_set")
    top_priority_match = (expected_set is None) or (dominant_s1 in expected_set)

    # priority_shift_observed: rank of S1 dominant worsened (or disappeared) in S2
    rank_s1_dominant_in_s2 = next(
        (p["rank"] for p in priority_s2 if p["error_type"] == dominant_s1), None
    )
    priority_shift_observed = rank_s1_dominant_in_s2 is None or rank_s1_dominant_in_s2 > 1

    # dominant_weight_decay_pct: % weight reduction of S1 dominant between S1 and S2.
    # Captures adaptive signal even when rank does not change (relevant for progressive).
    weight_s1_dominant = next(
        (p["weight"] for p in priority_s1 if p["error_type"] == dominant_s1), None
    )
    weight_s2_dominant = next(
        (p["weight"] for p in priority_s2 if p["error_type"] == dominant_s1), None
    )
    if weight_s1_dominant and weight_s2_dominant:
        dominant_weight_decay_pct = round(
            (weight_s1_dominant - weight_s2_dominant) / weight_s1_dominant, 3
        )
    else:
        dominant_weight_decay_pct = None

    # simulated_error_reduction: proportion of S2 sentences NOT introducing dominant S1 error
    s2_dominant_new = sum(
        1 for row in sessions_rows
        if row["session_id"] == 2
        and row["predicted_error_type"] == dominant_s1
    )
    total_s2 = len(profile["session2_sentences"])
    simulated_error_reduction = round(1.0 - (s2_dominant_new / max(total_s2, 1)), 3)

    # adaptive_loop_success: strict (rank shift) OR relaxed for progressive (weight decay >5%)
    strict_success = top_priority_match and exercise_match_ok and priority_shift_observed
    relaxed_success = (
        top_priority_match
        and exercise_match_ok
        and (priority_shift_observed or (dominant_weight_decay_pct is not None and dominant_weight_decay_pct > 0.05))
    )
    adaptive_loop_success = relaxed_success

    summary = {
        "learner_id": learner_id,
        "family": family,
        "expected_dominant_error": expected_dominant or "mixed",
        "detected_dominant_error_s1": dominant_s1,
        "detected_dominant_error_s2": dominant_s2,
        "top_priority_match": top_priority_match,
        "exercise_match_rate_heuristic": exercise_match_ok,
        "priority_shift_observed": priority_shift_observed,
        "dominant_weight_decay_pct": dominant_weight_decay_pct,
        "simulated_error_reduction": simulated_error_reduction,
        "adaptive_loop_success_rate": adaptive_loop_success,
        "failed_correction_count": failed_corrections,
        "total_sentences_s1": len(profile["session1_sentences"]),
        "s2_dominant_new_count": s2_dominant_new,
        "average_ollama_latency_ms": (
            round(sum(ollama_latencies) / len(ollama_latencies), 1)
            if ollama_latencies else None
        ),
        "average_postprocessing_latency_ms": (
            round(sum(postprocessing_latencies) / len(postprocessing_latencies), 1)
            if postprocessing_latencies else None
        ),
    }

    # Write CSVs incrementally (safe on crash)
    _append_csv(output_paths["sessions"], sessions_rows, FIELDS_SESSIONS)
    _append_csv(output_paths["priorities"], priorities_rows, FIELDS_PRIORITIES)
    _append_csv(output_paths["exercises"], exercises_rows, FIELDS_EXERCISES)

    return summary



# ── Global summary ─────────────────────────────────────────────────────────────

def _compute_and_print_summary(
    summaries: list[dict],
    output_dir: Path,
    logger: logging.Logger,
) -> None:
    if not summaries:
        logger.warning("No completed learners to summarize.")
        return

    def _rate(vals: list) -> float:
        return round(sum(1 for v in vals if v) / len(vals), 3) if vals else 0.0

    def _avg(vals: list) -> Optional[float]:
        clean = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(clean) / len(clean), 2) if clean else None

    global_stats = {
        "total_learners": len(summaries),
        "top_priority_match_rate": _rate([s["top_priority_match"] for s in summaries]),
        "priority_shift_rate": _rate([s["priority_shift_observed"] for s in summaries]),
        "exercise_match_rate_heuristic": _rate([s["exercise_match_rate_heuristic"] for s in summaries]),
        "adaptive_loop_success_rate": _rate([s["adaptive_loop_success_rate"] for s in summaries]),
        "failed_correction_rate": round(
            sum(s["failed_correction_count"] for s in summaries)
            / max(sum(s["total_sentences_s1"] for s in summaries), 1),
            3,
        ),
        "simulated_error_reduction_rate": _avg([s["simulated_error_reduction"] for s in summaries]),
        "average_ollama_latency_ms": _avg([s["average_ollama_latency_ms"] for s in summaries]),
        "average_postprocessing_latency_ms": _avg([s["average_postprocessing_latency_ms"] for s in summaries]),
    }

    family_stats: dict[str, dict] = {}
    for family in PROFILE_FAMILIES:
        fs = [s for s in summaries if s["family"] == family]
        if not fs:
            continue
        family_stats[family] = {
            "n": len(fs),
            "top_priority_match_rate": _rate([s["top_priority_match"] for s in fs]),
            "priority_shift_rate": _rate([s["priority_shift_observed"] for s in fs]),
            "avg_weight_decay_pct": _avg([s.get("dominant_weight_decay_pct") for s in fs]),
            "exercise_match_rate_heuristic": _rate([s["exercise_match_rate_heuristic"] for s in fs]),
            "adaptive_loop_success_rate": _rate([s["adaptive_loop_success_rate"] for s in fs]),
            "simulated_error_reduction_rate": _avg([s.get("simulated_error_reduction") for s in fs]),
            "failed_correction_rate": round(
                sum(s["failed_correction_count"] for s in fs)
                / max(sum(s["total_sentences_s1"] for s in fs), 1),
                3,
            ),
        }

    full_report = {"global": global_stats, "by_family": family_stats}
    report_path = output_dir / "h2_global_summary.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)

    # ── Console / log output ───────────────────────────────────────────────────
    sep = "=" * 72
    logger.info(f"\n{sep}")
    logger.info("H2 SIMULATION — GLOBAL RESULTS")
    logger.info(f"  IMPORTANT: Functional validation only — NOT pedagogical proof")
    logger.info(sep)
    logger.info(f"  Total learners              : {global_stats['total_learners']}")
    logger.info(f"  top_priority_match_rate     : {global_stats['top_priority_match_rate']:.1%}")
    logger.info(f"  priority_shift_rate         : {global_stats['priority_shift_rate']:.1%}")
    logger.info(f"  exercise_match_rate         : {global_stats['exercise_match_rate_heuristic']:.1%}  ← heuristic, not ground truth")
    logger.info(f"  adaptive_loop_success_rate  : {global_stats['adaptive_loop_success_rate']:.1%}")
    logger.info(f"  failed_correction_rate      : {global_stats['failed_correction_rate']:.1%}")
    logger.info(f"  simulated_error_reduction   : {global_stats['simulated_error_reduction_rate']:.1%}")
    if global_stats["average_ollama_latency_ms"]:
        logger.info(f"  avg Ollama latency          : {global_stats['average_ollama_latency_ms']:.0f} ms / call")
    if global_stats["average_postprocessing_latency_ms"]:
        logger.info(f"  avg postprocessing latency  : {global_stats['average_postprocessing_latency_ms']:.1f} ms / sentence")

    logger.info(f"\n  {'Family':<14} {'n':>3}  {'top_match':>9}  {'shift':>7}  {'decay%':>7}  {'ex_match':>8}  {'loop_ok':>7}")
    logger.info(f"  {'-'*66}")
    for fam, fs in family_stats.items():
        decay = fs.get("avg_weight_decay_pct")
        decay_str = f"{decay:.1%}" if decay is not None else "   N/A"
        logger.info(
            f"  {fam:<14} {fs['n']:>3}  "
            f"{fs['top_priority_match_rate']:>8.1%}  "
            f"{fs['priority_shift_rate']:>6.1%}  "
            f"{decay_str:>6}  "
            f"{fs['exercise_match_rate_heuristic']:>7.1%}  "
            f"{fs['adaptive_loop_success_rate']:>6.1%}"
        )
    logger.info(f"  (decay%: % reduction of dominant error weight from S1→S2 at T+2d)")
    logger.info(sep)
    logger.info(f"  Full report: {report_path}")

    # ── Decay table (analytical, no Ollama needed) ─────────────────────────────
    logger.info(f"\n  DECAY TABLE (count=5, λ=0.1) — weight = count × exp(−λ × days)")
    logger.info(f"  {'days_since':>10}  {'weight':>8}  {'vs_day_0':>9}")
    w0 = 5 * math.exp(-LAMBDA_DECAY * 0)
    for days in [0, 1, 3, 7, 14, 30, 60]:
        w = 5 * math.exp(-LAMBDA_DECAY * days)
        logger.info(f"  {days:>10}  {w:>8.4f}  {w/w0:>8.1%}")
    logger.info(sep)


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = _ARGS
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Logging ────────────────────────────────────────────────────────────────
    log_path = output_dir / "errors.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("h2_sim")

    output_paths = {
        "sessions":   output_dir / "h2_ollama_sessions.csv",
        "priorities": output_dir / "h2_ollama_priorities.csv",
        "exercises":  output_dir / "h2_ollama_exercises.csv",
        "summary":    output_dir / "h2_ollama_summary.csv",
    }

    # ── Progress + config ──────────────────────────────────────────────────────
    progress_path    = output_dir / "progress.json"
    run_config_path  = output_dir / "run_config.json"

    run_config = {
        "learners": args.learners,
        "phrases_per_learner": args.phrases_per_learner,
        "model": os.environ.get("OLLAMA_MODEL", ""),
        "ollama_host": os.environ.get("OLLAMA_HOST", ""),
        "timeout_s": args.timeout,
        "max_retries": args.max_retries,
        "seed": args.seed,
        "output_dir": str(output_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "note": "Functional validation only — NOT pedagogical proof",
    }

    completed_learners: set[str] = set()

    if args.resume and progress_path.exists():
        with open(progress_path, encoding="utf-8") as f:
            progress_data = json.load(f)
        completed_learners = set(progress_data.get("completed_learners", []))
        logger.info(f"Resume mode: {len(completed_learners)} learners already complete")
    else:
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(run_config, f, indent=2)
        # Init CSV headers (only if files don't exist)
        for path, fields in [
            (output_paths["sessions"],   FIELDS_SESSIONS),
            (output_paths["priorities"], FIELDS_PRIORITIES),
            (output_paths["exercises"],  FIELDS_EXERCISES),
            (output_paths["summary"],    FIELDS_SUMMARY),
        ]:
            _ensure_csv_header(path, fields)

    logger.info(f"Model     : {os.environ.get('OLLAMA_MODEL', '(not set)')}")
    logger.info(f"Host      : {os.environ.get('OLLAMA_HOST', '(not set)')}")
    logger.info(f"Learners  : {args.learners}, phrases/learner: {args.phrases_per_learner}")
    logger.info(f"Timeout   : {args.timeout}s, max_retries: {args.max_retries}")
    logger.info(f"Output    : {output_dir}")
    logger.info(f"Seed      : {args.seed}")

    profiles = _build_learner_profiles(args.learners, args.phrases_per_learner, args.seed)
    orchestrator = PipelineOrchestrator(use_similar_errors=False)
    summaries: list[dict] = []

    # ── Load existing summaries for accurate global stats after resume ─────────
    if args.resume and output_paths["summary"].exists():
        with open(output_paths["summary"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Coerce booleans
                for bool_col in ("top_priority_match", "exercise_match_rate_heuristic",
                                 "priority_shift_observed", "adaptive_loop_success_rate"):
                    row[bool_col] = row[bool_col].lower() in ("true", "1", "yes")
                for num_col in ("simulated_error_reduction", "average_ollama_latency_ms",
                                "average_postprocessing_latency_ms"):
                    try:
                        row[num_col] = float(row[num_col]) if row[num_col] not in ("", "None") else None
                    except (ValueError, TypeError):
                        row[num_col] = None
                for int_col in ("failed_correction_count", "total_sentences_s1"):
                    try:
                        row[int_col] = int(row[int_col])
                    except (ValueError, TypeError):
                        row[int_col] = 0
                summaries.append(row)

    # ── Main loop ──────────────────────────────────────────────────────────────
    for idx, profile in enumerate(profiles):
        learner_id = profile["learner_id"]

        if learner_id in completed_learners:
            logger.info(f"[{idx+1}/{len(profiles)}] Skip {learner_id} (done)")
            continue

        logger.info(
            f"[{idx+1}/{len(profiles)}] {learner_id}  "
            f"family={profile['family']}  "
            f"expected_dominant={profile['expected_dominant'] or 'mixed'}"
        )
        t_start = time.perf_counter()

        try:
            summary = await _simulate_learner(
                profile=profile,
                orchestrator=orchestrator,
                timeout=args.timeout,
                max_retries=args.max_retries,
                output_paths=output_paths,
                logger=logger,
            )
            summaries.append(summary)
            _append_csv(output_paths["summary"], [summary], FIELDS_SUMMARY)
            elapsed = time.perf_counter() - t_start
            logger.info(
                f"  → OK  top_match={summary['top_priority_match']}  "
                f"shift={summary['priority_shift_observed']}  "
                f"ex_match={summary['exercise_match_rate_heuristic']}  "
                f"({elapsed:.1f}s)"
            )
        except Exception as exc:
            logger.error(f"FATAL [{learner_id}]: {type(exc).__name__}: {exc}")
            failed_summary = {
                "learner_id": learner_id,
                "family": profile["family"],
                "expected_dominant_error": profile.get("expected_dominant") or "mixed",
                "detected_dominant_error_s1": "ERROR",
                "detected_dominant_error_s2": "ERROR",
                "top_priority_match": False,
                "exercise_match_rate_heuristic": False,
                "priority_shift_observed": False,
                "simulated_error_reduction": 0.0,
                "adaptive_loop_success_rate": False,
                "failed_correction_count": args.phrases_per_learner,
                "total_sentences_s1": args.phrases_per_learner,
                "s2_dominant_new_count": 0,
                "average_ollama_latency_ms": None,
                "average_postprocessing_latency_ms": None,
            }
            summaries.append(failed_summary)
            _append_csv(output_paths["summary"], [failed_summary], FIELDS_SUMMARY)

        # Update progress after each learner — never lose completed work
        completed_learners.add(learner_id)
        with open(progress_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "completed_learners": sorted(completed_learners),
                    "total": len(profiles),
                    "completed": len(completed_learners),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                },
                f,
                indent=2,
            )

    _compute_and_print_summary(summaries, output_dir, logger)


if __name__ == "__main__":
    asyncio.run(main())
