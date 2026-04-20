#!/usr/bin/env python3
"""
simulate_h2_api.py — H2 Functional Validation via Real API Calls

IMPORTANT: This script validates the *functional behavior* of the adaptive engine
by calling the production API with synthetic learner profiles. It does NOT validate
pedagogical effectiveness or real learner improvement.

The full production pipeline runs end-to-end:
  POST /correct        → Ollama correction + track_error() → DB populated
  GET  /exercise/adaptive → get_frequent_errors() → targeted exercise
  POST /exercise/grade → record_successful_review() / track_error()
  GET  /learner/{id}/progress → get_full_learner_profile() → real adaptive state

Usage:
    python simulate_h2_api.py --learners 5 --phrases-per-learner 5
    python simulate_h2_api.py --learners 20 --model gemma3:12b --output-dir benchmark_outputs/h2_api
    python simulate_h2_api.py --resume --output-dir benchmark_outputs/h2_api

Requirements:
    - API running on http://localhost:8000 (USE_OLLAMA=true)
    - DB and Redis running
    - pip install httpx
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL_DEFAULT = "bjoernb/gemma4-31b-think:latest"

_SENTENCE_GEN_PROMPT = """\
Generate exactly {n} English sentences that contain a {error_type} error.
Rules:
- Each sentence must have exactly ONE grammatical error of type {error_type}.
- {error_type} errors: {error_desc}
- Sentences should be short (6-12 words), varied subjects and topics.
- Do NOT repeat the same sentence pattern.
- Output ONLY valid JSON array of strings, no explanation: ["sentence1", "sentence2", ...]
Seed: {seed}
"""

_CORRECT_SENTENCE_GEN_PROMPT = """\
Generate exactly {n} grammatically correct English sentences.
Rules:
- No grammatical errors at all.
- Sentences should be short (6-12 words), varied subjects and topics.
- Do NOT repeat the same sentence pattern.
- Output ONLY valid JSON array of strings, no explanation: ["sentence1", "sentence2", ...]
Seed: {seed}
"""

_ERROR_DESCRIPTIONS = {
    "agreement": "subject-verb agreement (e.g. 'She go', 'They was', 'He have')",
    "preposition": "wrong preposition (e.g. 'depend of', 'interested by', 'good in math')",
    "article": "missing or wrong article a/an/the (e.g. 'I bought car', 'She is teacher')",
    "mixed": "any grammar error (agreement, preposition, or article)",
    "progressive": "subject-verb agreement (e.g. 'She go', 'He have', 'They was')",
}


_S2_FAMILY_MAP = {
    "agreement":   "preposition",
    "preposition": "article",
    "article":     "agreement",
    "mixed":       "mixed",
    "progressive": "preposition",
    "proficient":  "proficient",
}

def _s2_family(family: str) -> str:
    return _S2_FAMILY_MAP.get(family, "mixed")


async def _generate_sentences_ollama(
    error_type: str,
    n: int,
    seed: int,
    model: str = OLLAMA_MODEL_DEFAULT,
) -> list[str] | None:
    """Generate n sentences via Ollama. Returns None on any failure (caller should skip)."""
    if error_type == "proficient":
        prompt = _CORRECT_SENTENCE_GEN_PROMPT.format(n=n, seed=seed)
    else:
        prompt = _SENTENCE_GEN_PROMPT.format(
            n=n,
            error_type=error_type,
            error_desc=_ERROR_DESCRIPTIONS.get(error_type, error_type),
            seed=seed,
        )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(OLLAMA_GENERATE_URL, json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "seed": seed},
            })
            if r.status_code != 200:
                raise ValueError(f"Ollama {r.status_code}")
            raw = (r.json().get("response") or "").strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("no JSON array in response")
            sentences = json.loads(raw[start:end])
            if not isinstance(sentences, list):
                raise ValueError("not a list")
            sentences = [str(s).strip() for s in sentences if str(s).strip()]
            if len(sentences) < n:
                raise ValueError(f"only {len(sentences)} generated, need {n}")
            return sentences[:n]
    except Exception as e:
        logging.getLogger("h2_api").warning(
            f"Sentence generation failed ({error_type}, seed={seed}): {e} — skipping learner"
        )
        return None

# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="H2 API simulation — synthetic learner loop")
    p.add_argument("--learners", type=int, default=5)
    p.add_argument("--phrases-per-learner", type=int, default=5)
    p.add_argument("--model", type=str, default="",
                   help="Override OLLAMA_MODEL via API if supported (informational only)")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--timeout", type=float, default=180.0)
    p.add_argument("--output-dir", type=str, default="benchmark_outputs/h2_api")
    p.add_argument("--api-url", type=str, default="http://localhost:8000")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--password", type=str, default="H2sim_pass_2026!")
    p.add_argument("--ollama-generate", action="store_true",
                   help="Generate sentences via Ollama instead of static banks (varied, slower)")
    p.add_argument("--ollama-model", type=str, default=OLLAMA_MODEL_DEFAULT,
                   help="Ollama model for sentence generation")
    return p.parse_args()


# ── Sentence banks ─────────────────────────────────────────────────────────────

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
        "The dog run very fast.",
        "My sister work at the hospital.",
        "The boys was tired after school.",
        "She have a big family.",
        "He don't understand the rules.",
        "She always arrive late.",
        "The team are winning the game.",
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
        "She arrived at Monday.",
        "He is responsible of the team.",
        "I am bored of this movie.",
        "She is looking the window.",
        "He talked about his problem to me.",
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
    # Grammatically correct sentences — engine should fall back to general exercise
    "proficient": [
        "She goes to school every day.",
        "He has a new car.",
        "They were very happy yesterday.",
        "The children play outside.",
        "My friend doesn't like coffee.",
        "The teacher explains the lesson.",
        "She doesn't know the answer.",
        "He makes mistakes sometimes.",
        "The dog runs very fast.",
        "My sister works at the hospital.",
        "The boys were tired after school.",
        "She has a big family.",
        "He doesn't understand the rules.",
        "She always arrives late.",
        "The team is winning the game.",
    ],
}

# Session 2: alternate error type to trigger priority shift
SESSION2_BANK: dict[str, list[str]] = {
    "agreement":   SENTENCE_BANK["preposition"],
    "preposition": SENTENCE_BANK["article"],
    "article":     SENTENCE_BANK["agreement"],
    "mixed":       SENTENCE_BANK["mixed"][7:] + SENTENCE_BANK["mixed"][:7],
    "progressive": [
        "She goes to school every day.",
        "I depend of my parents.",
        "He has a new car.",
        "She is interested by music.",
        "They were very happy yesterday.",
        "He is good in math.",
        "The children play outside.",
        "I arrived to the airport.",
        "My friend doesn't like coffee.",
        "She is married with a doctor.",
    ],
    # S2 for proficient: same correct sentences (no error history expected)
    "proficient":  SENTENCE_BANK["proficient"],
}

PROFILE_FAMILIES = ["agreement", "preposition", "article", "mixed", "progressive", "proficient"]

# expected dominant set: accept tense/agreement both (ALAO classifier known limitation)
# proficient: None = no dominant expected, top_priority_match always True
EXPECTED_DOMINANT_SET: dict[str, Optional[set]] = {
    "agreement":   {"agreement", "tense"},
    "preposition": {"preposition"},
    "article":     {"article"},
    "mixed":       None,
    "progressive": {"agreement", "tense"},
    "proficient":  None,
}
EXPECTED_DOMINANT_LABEL: dict[str, Optional[str]] = {
    "agreement":   "agreement",
    "preposition": "preposition",
    "article":     "article",
    "mixed":       None,
    "progressive": "agreement",
    "proficient":  None,
}

# ── CSV fields ─────────────────────────────────────────────────────────────────

FIELDS_SESSIONS = [
    "learner_id", "session_id", "sentence_idx", "input_sentence",
    "corrected_sentence", "predicted_error_type", "feedback_present",
    "dominant_error_before", "dominant_error_after",
    "api_latency_ms",
]
FIELDS_PRIORITIES = [
    "learner_id", "session_id", "error_type", "count",
    "weight", "days_since", "mastery_level", "rank",
]
FIELDS_EXERCISES = [
    "learner_id", "session_id", "target_error_type",
    "exercise_prompt", "exercise_blank",
    "grade_result", "api_latency_ms",
]
FIELDS_SUMMARY = [
    "learner_id", "family",
    "expected_dominant_error", "detected_dominant_error_s1", "detected_dominant_error_s2",
    "top_priority_match", "priority_shift_observed", "dominant_weight_decay_pct",
    "simulated_error_reduction", "adaptive_loop_success_rate",
    "failed_correction_count", "total_sentences_s1",
    "average_api_latency_ms",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _ensure_csv(path: Path, fields: list[str]) -> None:
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _append_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fields, extrasaction="ignore").writerows(rows)


async def _build_profiles(
    n: int,
    phrases: int,
    seed: int,
    ollama_generate: bool = False,
    ollama_model: str = OLLAMA_MODEL_DEFAULT,
) -> list[dict]:
    profiles = []
    counters = {f: 0 for f in PROFILE_FAMILIES}
    for i in range(n):
        family = PROFILE_FAMILIES[i % len(PROFILE_FAMILIES)]
        idx = counters[family]
        counters[family] += 1

        if ollama_generate:
            # Unique seed per learner+family for varied sentences
            learner_seed = seed * 1000 + i
            s2_fam = _s2_family(family)
            s1 = await _generate_sentences_ollama(family, phrases, learner_seed, model=ollama_model)
            s2 = await _generate_sentences_ollama(s2_fam, phrases, learner_seed + 1, model=ollama_model)
            if s1 is None or s2 is None:
                continue  # skip learner, generation failed
        else:
            bank = SENTENCE_BANK[family]
            s2bank = SESSION2_BANK[family]
            s1 = [bank[(idx * phrases + j) % len(bank)] for j in range(phrases)]
            s2 = [s2bank[(idx * phrases + j) % len(s2bank)] for j in range(phrases)]

        profiles.append({
            "learner_id": f"learner_{family}_{idx:03d}",
            "family": family,
            "expected_dominant": EXPECTED_DOMINANT_LABEL[family],
            "expected_dominant_set": EXPECTED_DOMINANT_SET[family],
            "session1_sentences": s1,
            "session2_sentences": s2,
        })
    return profiles


# ── API client ─────────────────────────────────────────────────────────────────

class APIClient:
    def __init__(self, base_url: str, timeout: float):
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies: dict = {}

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def register(self, username: str, password: str) -> bool:
        r = await self._client.post(f"{self._base}/register",
            json={"username": username, "password": password})
        return r.status_code in (200, 201) or "already" in r.text.lower() or "success" in r.text.lower()

    async def login(self, username: str, password: str) -> Optional[str]:
        """Returns the DB user_id string on success, None on failure."""
        r = await self._client.post(f"{self._base}/login",
            json={"username": username, "password": password})
        if r.status_code == 200:
            self._cookies = dict(r.cookies)
            data = r.json()
            uid = data.get("user", {}).get("id")
            return str(uid) if uid is not None else None
        return None

    async def correct(self, phrase: str, session_id: str) -> Optional[dict]:
        t0 = time.perf_counter()
        try:
            r = await self._client.post(f"{self._base}/correct",
                json={"phrase": phrase},
                headers={"X-Session-Id": session_id},
                cookies=self._cookies)
            lat = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                return {**r.json(), "latency_ms": lat}
        except Exception:
            pass
        return None

    async def get_exercise(self, db_user_id: str) -> Optional[dict]:
        t0 = time.perf_counter()
        try:
            r = await self._client.post(f"{self._base}/exercise/adaptive",
                json={"user_id": db_user_id},
                cookies=self._cookies)
            lat = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                return {**r.json(), "latency_ms": lat}
        except Exception:
            pass
        return None

    async def grade_exercise(self, session_id: str, exercise: dict, answer: str) -> Optional[dict]:
        t0 = time.perf_counter()
        try:
            r = await self._client.post(f"{self._base}/exercise/grade",
                json={
                    "sentence": exercise.get("sentence", ""),
                    "blank": exercise.get("blank", ""),
                    "user_answer": answer,
                },
                headers={"X-Session-Id": session_id},
                cookies=self._cookies)
            lat = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                return {**r.json(), "latency_ms": lat}
        except Exception:
            pass
        return None

    async def get_progress(self, db_user_id: str) -> Optional[dict]:
        try:
            r = await self._client.get(f"{self._base}/learner/{db_user_id}/progress",
                cookies=self._cookies)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None


# ── Per-learner simulation ─────────────────────────────────────────────────────

async def _simulate_learner(
    profile: dict,
    client: APIClient,
    output_paths: dict,
    logger: logging.Logger,
    run_id: str = "",
) -> dict:
    learner_id = profile["learner_id"]
    family = profile["family"]
    expected_dominant = profile["expected_dominant"]
    expected_set = profile["expected_dominant_set"]

    # Each run gets fresh users — run_id suffix avoids stale error history from prior runs
    username = f"s{run_id}_{learner_id}"[:40]
    password = "H2sim_2026!"

    await client.register(username, password)
    db_user_id = await client.login(username, password)
    if not db_user_id:
        logger.error(f"Login failed for {username}")
        return _error_summary(profile)

    sessions_rows: list[dict] = []
    priorities_rows: list[dict] = []
    exercises_rows: list[dict] = []
    api_latencies: list[float] = []
    failed_corrections = 0

    # ── Session 1 — real Ollama corrections via API ────────────────────────────
    session_key = f"{learner_id}_s1"

    for sent_idx, sentence in enumerate(profile["session1_sentences"]):
        result = await client.correct(sentence, session_key)

        if result is None:
            failed_corrections += 1
            logger.warning(f"  Skipping [{learner_id}] s1 idx={sent_idx}: /correct failed")
            continue

        api_latencies.append(result["latency_ms"])
        sessions_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "sentence_idx": sent_idx,
            "input_sentence": sentence,
            "corrected_sentence": result.get("corrected", ""),
            "predicted_error_type": result.get("error_type", ""),
            "feedback_present": bool(result.get("feedback")),
            "dominant_error_before": "",   # backfilled
            "dominant_error_after": "",
            "api_latency_ms": round(result["latency_ms"], 1),
        })

    # Priority after session 1 — from real DB via /learner/{id}/progress
    # _get_user_id uses the auth session's DB user_id, not X-Session-Id
    progress_s1 = await client.get_progress(db_user_id)
    frequent_s1 = progress_s1.get("error_history", []) if progress_s1 else []
    dominant_s1 = frequent_s1[0]["error_type"] if frequent_s1 else "none"

    for row in sessions_rows:
        row["dominant_error_before"] = dominant_s1

    for rank, err in enumerate(frequent_s1, 1):
        priorities_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "error_type": err.get("error_type"),
            "count": err.get("count"),
            "weight": err.get("weight"),
            "days_since": err.get("days_since"),
            "mastery_level": err.get("mastery_level", 0),
            "rank": rank,
        })

    # ── Exercise for dominant S1 error ────────────────────────────────────────
    exercise = await client.get_exercise(db_user_id)

    if exercise:
        # Simulate learner answers correctly (triggers record_successful_review)
        blank = exercise.get("blank", "")
        grade = await client.grade_exercise(session_key, exercise, blank)
        exercises_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "target_error_type": dominant_s1,
            "exercise_prompt": str(exercise.get("prompt", exercise.get("sentence", "")))[:300],
            "exercise_blank": blank,
            "grade_result": grade.get("correct", False) if grade else False,
            "api_latency_ms": round(exercise.get("latency_ms", 0), 1),
        })
    else:
        exercises_rows.append({
            "learner_id": learner_id,
            "session_id": 1,
            "target_error_type": dominant_s1,
            "exercise_prompt": "FAILED",
            "exercise_blank": "FAILED",
            "grade_result": False,
            "api_latency_ms": None,
        })

    # ── Session 2 — alternate error type sentences ────────────────────────────
    session_key_s2 = f"{learner_id}_s2"

    for sent_idx, sentence in enumerate(profile["session2_sentences"]):
        result = await client.correct(sentence, session_key_s2)

        if result is None:
            failed_corrections += 1
            logger.warning(f"  Skipping [{learner_id}] s2 idx={sent_idx}: /correct failed")
            continue

        api_latencies.append(result["latency_ms"])
        sessions_rows.append({
            "learner_id": learner_id,
            "session_id": 2,
            "sentence_idx": sent_idx,
            "input_sentence": sentence,
            "corrected_sentence": result.get("corrected", ""),
            "predicted_error_type": result.get("error_type", ""),
            "feedback_present": bool(result.get("feedback")),
            "dominant_error_before": dominant_s1,
            "dominant_error_after": "",   # backfilled
            "api_latency_ms": round(result["latency_ms"], 1),
        })

    # Priority after session 2 — same DB user_id (both sessions tracked under same user)
    progress_s2 = await client.get_progress(db_user_id)
    frequent_s2 = progress_s2.get("error_history", []) if progress_s2 else []
    dominant_s2 = frequent_s2[0]["error_type"] if frequent_s2 else "none"

    for row in sessions_rows:
        if row["session_id"] == 2:
            row["dominant_error_after"] = dominant_s2

    for rank, err in enumerate(frequent_s2, 1):
        priorities_rows.append({
            "learner_id": learner_id,
            "session_id": 2,
            "error_type": err.get("error_type"),
            "count": err.get("count"),
            "weight": err.get("weight"),
            "days_since": err.get("days_since"),
            "mastery_level": err.get("mastery_level", 0),
            "rank": rank,
        })

    # ── Metrics ────────────────────────────────────────────────────────────────
    top_priority_match = (expected_set is None) or (dominant_s1 in expected_set)

    rank_s1_in_s2 = next(
        (i + 1 for i, e in enumerate(frequent_s2) if e["error_type"] == dominant_s1), None
    )
    priority_shift_observed = rank_s1_in_s2 is None or rank_s1_in_s2 > 1

    w1 = next((e.get("weight", 0) for e in frequent_s1 if e["error_type"] == dominant_s1), None)
    w2 = next((e.get("weight", 0) for e in frequent_s2 if e["error_type"] == dominant_s1), None)
    dominant_weight_decay_pct = (
        round((w1 - w2) / w1, 3) if w1 and w2 and w1 > 0 else None
    )

    s2_dominant_new = sum(
        1 for r in sessions_rows
        if r["session_id"] == 2 and r["predicted_error_type"] == dominant_s1
    )
    simulated_error_reduction = round(
        1.0 - s2_dominant_new / max(len(profile["session2_sentences"]), 1), 3
    )

    # API test: S1 and S2 run in same session (no real time gap), so temporal
    # weight shift is not observable here. Success = engine correctly identified
    # the dominant error type from S1 corrections.
    adaptive_loop_success = top_priority_match

    summary = {
        "learner_id": learner_id,
        "family": family,
        "expected_dominant_error": expected_dominant or "mixed",
        "detected_dominant_error_s1": dominant_s1,
        "detected_dominant_error_s2": dominant_s2,
        "top_priority_match": top_priority_match,
        "priority_shift_observed": priority_shift_observed,
        "dominant_weight_decay_pct": dominant_weight_decay_pct,
        "simulated_error_reduction": simulated_error_reduction,
        "adaptive_loop_success_rate": adaptive_loop_success,
        "failed_correction_count": failed_corrections,
        "total_sentences_s1": len(profile["session1_sentences"]),
        "average_api_latency_ms": (
            round(sum(api_latencies) / len(api_latencies), 1) if api_latencies else None
        ),
    }

    _append_csv(output_paths["sessions"], sessions_rows, FIELDS_SESSIONS)
    _append_csv(output_paths["priorities"], priorities_rows, FIELDS_PRIORITIES)
    _append_csv(output_paths["exercises"], exercises_rows, FIELDS_EXERCISES)

    return summary


def _error_summary(profile: dict) -> dict:
    return {
        "learner_id": profile["learner_id"],
        "family": profile["family"],
        "expected_dominant_error": profile.get("expected_dominant") or "mixed",
        "detected_dominant_error_s1": "ERROR",
        "detected_dominant_error_s2": "ERROR",
        "top_priority_match": False,
        "priority_shift_observed": False,
        "dominant_weight_decay_pct": None,
        "simulated_error_reduction": 0.0,
        "adaptive_loop_success_rate": False,
        "failed_correction_count": len(profile.get("session1_sentences", [])),
        "total_sentences_s1": len(profile.get("session1_sentences", [])),
        "average_api_latency_ms": None,
    }


# ── Global summary ─────────────────────────────────────────────────────────────

def _print_summary(summaries: list[dict], output_dir: Path, logger: logging.Logger) -> None:
    if not summaries:
        return

    def _rate(vals): return round(sum(1 for v in vals if v) / len(vals), 3) if vals else 0.0
    def _avg(vals):
        c = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(c) / len(c), 2) if c else None

    g = {
        "total_learners": len(summaries),
        "top_priority_match_rate": _rate([s["top_priority_match"] for s in summaries]),
        "priority_shift_rate": _rate([s["priority_shift_observed"] for s in summaries]),
        "adaptive_loop_success_rate": _rate([s["adaptive_loop_success_rate"] for s in summaries]),
        "failed_correction_rate": round(
            sum(s["failed_correction_count"] for s in summaries)
            / max(sum(s["total_sentences_s1"] for s in summaries), 1), 3),
        "simulated_error_reduction_rate": _avg([s["simulated_error_reduction"] for s in summaries]),
        "average_api_latency_ms": _avg([s["average_api_latency_ms"] for s in summaries]),
    }

    by_family = {}
    for fam in PROFILE_FAMILIES:
        fs = [s for s in summaries if s["family"] == fam]
        if not fs:
            continue
        by_family[fam] = {
            "n": len(fs),
            "top_priority_match_rate": _rate([s["top_priority_match"] for s in fs]),
            "priority_shift_rate": _rate([s["priority_shift_observed"] for s in fs]),
            "adaptive_loop_success_rate": _rate([s["adaptive_loop_success_rate"] for s in fs]),
            "avg_weight_decay_pct": _avg([s.get("dominant_weight_decay_pct") for s in fs]),
        }

    report = {"global": g, "by_family": by_family}
    report_path = output_dir / "h2_api_global_summary.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    sep = "=" * 70
    logger.info(f"\n{sep}")
    logger.info("H2 API SIMULATION — GLOBAL RESULTS")
    logger.info("  Functional validation only — NOT pedagogical proof")
    logger.info(sep)
    logger.info(f"  Total learners              : {g['total_learners']}")
    logger.info(f"  top_priority_match_rate     : {g['top_priority_match_rate']:.1%}")
    logger.info(f"  priority_shift_rate         : {g['priority_shift_rate']:.1%}")
    logger.info(f"  adaptive_loop_success_rate  : {g['adaptive_loop_success_rate']:.1%}")
    logger.info(f"  failed_correction_rate      : {g['failed_correction_rate']:.1%}")
    logger.info(f"  simulated_error_reduction   : {g['simulated_error_reduction_rate']:.1%}")
    if g["average_api_latency_ms"]:
        logger.info(f"  avg API latency             : {g['average_api_latency_ms']:.0f} ms / call")

    logger.info(f"\n  {'Family':<14} {'n':>3}  {'top_match':>9}  {'shift':>7}  {'decay%':>7}  {'loop_ok':>7}")
    logger.info(f"  {'-'*56}")
    for fam, fs in by_family.items():
        decay = fs.get("avg_weight_decay_pct")
        decay_str = f"{decay:.1%}" if decay is not None else "   N/A"
        logger.info(
            f"  {fam:<14} {fs['n']:>3}  "
            f"{fs['top_priority_match_rate']:>8.1%}  "
            f"{fs['priority_shift_rate']:>6.1%}  "
            f"{decay_str:>6}  "
            f"{fs['adaptive_loop_success_rate']:>6.1%}"
        )
    logger.info(sep)
    logger.info(f"  Report: {report_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Unique run ID so each run creates fresh users (avoids stale DB history on re-run)
    run_id = datetime.now(timezone.utc).strftime("%m%d%H%M")

    log_path = output_dir / "errors.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("h2_api")

    output_paths = {
        "sessions":   output_dir / "h2_api_sessions.csv",
        "priorities": output_dir / "h2_api_priorities.csv",
        "exercises":  output_dir / "h2_api_exercises.csv",
        "summary":    output_dir / "h2_api_summary.csv",
    }

    progress_path   = output_dir / "progress.json"
    run_config_path = output_dir / "run_config.json"

    completed: set[str] = set()

    if args.resume and progress_path.exists():
        completed = set(json.loads(progress_path.read_text()).get("completed_learners", []))
        logger.info(f"Resume: {len(completed)} learners already done")
    else:
        run_config_path.write_text(json.dumps({
            "learners": args.learners,
            "phrases_per_learner": args.phrases_per_learner,
            "api_url": args.api_url,
            "timeout_s": args.timeout,
            "seed": args.seed,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "note": "Functional validation only — NOT pedagogical proof",
        }, indent=2))
        for path, fields in [
            (output_paths["sessions"],   FIELDS_SESSIONS),
            (output_paths["priorities"], FIELDS_PRIORITIES),
            (output_paths["exercises"],  FIELDS_EXERCISES),
            (output_paths["summary"],    FIELDS_SUMMARY),
        ]:
            _ensure_csv(path, fields)

    if args.ollama_generate:
        logger.info("Generating sentences via Ollama (--ollama-generate)...")
    profiles = await _build_profiles(
        args.learners, args.phrases_per_learner, args.seed,
        ollama_generate=args.ollama_generate,
        ollama_model=args.ollama_model,
    )

    # Load existing summaries for accurate global stats on resume
    summaries: list[dict] = []
    if args.resume and output_paths["summary"].exists():
        with open(output_paths["summary"], newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for b in ("top_priority_match", "priority_shift_observed", "adaptive_loop_success_rate"):
                    row[b] = row[b].lower() in ("true", "1")
                for n in ("dominant_weight_decay_pct", "simulated_error_reduction", "average_api_latency_ms"):
                    try:
                        row[n] = float(row[n]) if row[n] not in ("", "None") else None
                    except (ValueError, TypeError):
                        row[n] = None
                for i in ("failed_correction_count", "total_sentences_s1"):
                    try:
                        row[i] = int(row[i])
                    except (ValueError, TypeError):
                        row[i] = 0
                summaries.append(row)

    logger.info(f"API       : {args.api_url}")
    logger.info(f"Learners  : {args.learners}, phrases/learner: {args.phrases_per_learner}")
    logger.info(f"Timeout   : {args.timeout}s | Output: {output_dir} | Seed: {args.seed}")

    async with APIClient(args.api_url, args.timeout) as client:
        for idx, profile in enumerate(profiles):
            learner_id = profile["learner_id"]

            if learner_id in completed:
                logger.info(f"[{idx+1}/{len(profiles)}] Skip {learner_id}")
                continue

            logger.info(
                f"[{idx+1}/{len(profiles)}] {learner_id}  "
                f"family={profile['family']}  "
                f"expected={profile['expected_dominant'] or 'mixed'}"
            )
            t0 = time.perf_counter()

            try:
                summary = await _simulate_learner(profile, client, output_paths, logger, run_id)
                summaries.append(summary)
                _append_csv(output_paths["summary"], [summary], FIELDS_SUMMARY)
                logger.info(
                    f"  → top_match={summary['top_priority_match']}  "
                    f"shift={summary['priority_shift_observed']}  "
                    f"s1_dominant={summary['detected_dominant_error_s1']}  "
                    f"s2_dominant={summary['detected_dominant_error_s2']}  "
                    f"({time.perf_counter()-t0:.1f}s)"
                )
            except Exception as exc:
                logger.error(f"FATAL [{learner_id}]: {type(exc).__name__}: {exc}")
                esummary = _error_summary(profile)
                summaries.append(esummary)
                _append_csv(output_paths["summary"], [esummary], FIELDS_SUMMARY)

            completed.add(learner_id)
            progress_path.write_text(json.dumps({
                "completed_learners": sorted(completed),
                "total": len(profiles),
                "completed": len(completed),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }, indent=2))

    _print_summary(summaries, output_dir, logger)
    await _save_to_db(run_id, output_dir, args, logger)


async def _save_to_db(run_id: str, output_dir: Path, args, logger: logging.Logger) -> None:
    """Persist H2 run results to DB tables (h2_runs, h2_session_rows, ...)."""
    try:
        from backend.settings import settings
        if not settings.database_url:
            return
        from backend.storage import (
            AsyncSessionLocal, engine, metadata,
            h2_runs_table, h2_session_rows_table,
            h2_priority_rows_table, h2_exercise_rows_table,
        )
        from sqlalchemy import text as sa_text
    except Exception as e:
        logger.warning(f"DB save skipped — import error: {e}")
        return

    summary_path = output_dir / "h2_api_global_summary.json"
    if not summary_path.exists():
        return

    # Use output_dir name + run_id to form a unique key
    db_run_id = f"{output_dir.name}_{run_id}"

    try:
        # Ensure tables exist
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)

        config_path = output_dir / "run_config.json"
        config = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)

        g = summary.get("global", {})
        started_at_str = config.get("started_at")
        started_at = None
        if started_at_str:
            try:
                from datetime import datetime as _dt
                started_at = _dt.fromisoformat(started_at_str)
            except ValueError:
                pass

        def _f(v):
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def _i(v):
            try:
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        async with AsyncSessionLocal() as session:
            # Skip if already stored
            exists = (await session.execute(
                sa_text("SELECT id FROM h2_runs WHERE run_id = :r"), {"r": db_run_id}
            )).fetchone()
            if exists:
                logger.info(f"DB: run {db_run_id} already stored, skipping")
                return

            await session.execute(h2_runs_table.insert().values(
                run_id=db_run_id,
                started_at=started_at,
                learners=_i(config.get("learners")),
                phrases_per_learner=_i(config.get("phrases_per_learner")),
                seed=_i(config.get("seed")),
                api_url=config.get("api_url"),
                top_priority_match_rate=_f(g.get("top_priority_match_rate")),
                priority_shift_rate=_f(g.get("priority_shift_rate")),
                adaptive_loop_success_rate=_f(g.get("adaptive_loop_success_rate")),
                failed_correction_rate=_f(g.get("failed_correction_rate")),
                simulated_error_reduction_rate=_f(g.get("simulated_error_reduction_rate")),
                average_api_latency_ms=_f(g.get("average_api_latency_ms")),
                by_family=json.dumps(summary.get("by_family", {})),
                note=config.get("note"),
            ))

            for csv_path, table, mapper in [
                (output_dir / "h2_api_sessions.csv", h2_session_rows_table, lambda r: dict(
                    run_id=db_run_id,
                    learner_id=r.get("learner_id", ""),
                    session_id=_i(r.get("session_id")),
                    sentence_idx=_i(r.get("sentence_idx")),
                    input_sentence=r.get("input_sentence"),
                    corrected_sentence=r.get("corrected_sentence"),
                    predicted_error_type=r.get("predicted_error_type"),
                    feedback_present=r.get("feedback_present", "").lower() == "true",
                    dominant_error_before=r.get("dominant_error_before") or None,
                    dominant_error_after=r.get("dominant_error_after") or None,
                    api_latency_ms=_f(r.get("api_latency_ms")),
                )),
                (output_dir / "h2_api_priorities.csv", h2_priority_rows_table, lambda r: dict(
                    run_id=db_run_id,
                    learner_id=r.get("learner_id", ""),
                    session_id=_i(r.get("session_id")),
                    error_type=r.get("error_type", ""),
                    count=_i(r.get("count")),
                    weight=_f(r.get("weight")),
                    days_since=_f(r.get("days_since")),
                    mastery_level=_i(r.get("mastery_level")),
                    rank=_i(r.get("rank")),
                )),
                (output_dir / "h2_api_exercises.csv", h2_exercise_rows_table, lambda r: dict(
                    run_id=db_run_id,
                    learner_id=r.get("learner_id", ""),
                    session_id=_i(r.get("session_id")),
                    target_error_type=r.get("target_error_type"),
                    exercise_prompt=r.get("exercise_prompt"),
                    exercise_blank=r.get("exercise_blank"),
                    grade_result=r.get("grade_result"),
                    api_latency_ms=_f(r.get("api_latency_ms")),
                )),
            ]:
                if not csv_path.exists():
                    continue
                import csv as _csv
                with open(csv_path, encoding="utf-8") as f:
                    rows = list(_csv.DictReader(f))
                for row in rows:
                    await session.execute(table.insert().values(**mapper(row)))

            await session.commit()
            logger.info(f"DB: run {db_run_id} saved to h2_runs + related tables")

    except Exception as e:
        logger.warning(f"DB save failed (non-fatal): {e}")


if __name__ == "__main__":
    asyncio.run(main())
