"""Quiz generation with pedagogical pipeline integration.

Generates quiz questions using:
- Similar error patterns from dataset
- PipelineOrchestrator for structured feedback
- Adaptive difficulty based on learner progression
"""

from __future__ import annotations

import hashlib
import random
import uuid
from typing import TYPE_CHECKING

from backend.memory.similarity import find_similar_errors, find_errors_by_type
from backend.nlp.error_extraction import extract_error_spans
from backend.pedagogy.feedback_generator import build_feedback
from backend.text_utils import classify_error_type, tokenize

if TYPE_CHECKING:
    from backend.storage import AsyncSession


def _rng_for_user(user_id: str) -> random.Random:
    """RNG seeded from user_id + nanosecond time so each call produces a different question."""
    import time
    base = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % (2**32)
    seed = (base ^ (time.time_ns() & 0xFFFFFFFF)) % (2**32)
    return random.Random(seed)


def _generate_distractors(correct_answer: str, error_type: str, count: int = 3) -> list[str]:
    """Generate plausible wrong answers based on error type.
    
    Args:
        correct_answer: The correct answer
        error_type: Type of error to target
        count: Number of distractors to generate
    
    Returns:
        List of distractor options
    """
    distractors = []
    
    if error_type == "agreement":
        # Remove or add -s
        if correct_answer.endswith("s"):
            distractors.append(correct_answer[:-1])  # Remove 's'
        else:
            distractors.append(correct_answer + "s")  # Add 's'
        distractors.append(correct_answer + "es")  # Add 'es'
        
    elif error_type == "tense":
        # Generate tense variants
        base = correct_answer.rstrip("s").rstrip("ed").rstrip("ing")
        variants = [base, base + "s", base + "ed", base + "ing", "will " + base]
        for v in variants:
            if v != correct_answer and v not in distractors:
                distractors.append(v)
                if len(distractors) >= count:
                    break
                    
    elif error_type == "article":
        articles = ["a", "an", "the", "-"]
        for a in articles:
            if a != correct_answer and a not in distractors:
                distractors.append(a)
                if len(distractors) >= count:
                    break
                    
    elif error_type == "preposition":
        preps = ["in", "on", "at", "to", "for", "with", "from", "by"]
        for p in preps:
            if p != correct_answer and p not in distractors:
                distractors.append(p)
                if len(distractors) >= count:
                    break
                    
    elif error_type == "spelling":
        # Generate spelling variants
        if len(correct_answer) > 3:
            # Swap adjacent letters
            chars = list(correct_answer)
            for i in range(len(chars) - 1):
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
                distractors.append("".join(chars))
                chars[i], chars[i + 1] = chars[i + 1], chars[i]  # Swap back
                if len(distractors) >= count:
                    break
    
    return distractors[:count]


def _mask_error_in_sentence(sentence: str, error_span: dict) -> tuple[str, str]:
    """Create a fill-in-the-blank question from an error span.

    Returns:
        Tuple of (masked_sentence, correct_answer)
    """
    original_word = error_span.get("original", "")
    corrected_word = error_span.get("corrected", "")

    if original_word and original_word in sentence:
        masked = sentence.replace(original_word, "___", 1)
    else:
        # fallback: character positions
        start = error_span.get("start_char", 0)
        end = error_span.get("end_char", len(sentence))
        masked = sentence[:start] + "___" + sentence[end:]

    return masked, corrected_word


async def generate_quiz_question(
    user_id: str,
    difficulty: str = "A2",
    error_type: str | None = None,
    session: AsyncSession | None = None,
) -> dict:
    """Generate a quiz question using similar error patterns.
    
    Args:
        user_id: User identifier for progression tracking
        difficulty: CECRL level (A1, A2, B1, B2)
        error_type: Optional specific error type to target
        session: Database session (optional)
    
    Returns:
        Quiz question dict with input_text, options, correct_answer, hint
    """
    # If no error type specified, select based on user's weak areas
    if not error_type:
        error_type = await _select_error_type_for_user(user_id)
    
    # Find similar errors from dataset
    similar_errors = await find_errors_by_type(error_type, limit=10)

    if not similar_errors:
        # Selected type not in dataset — try known available types
        fallback_types = ["tense", "agreement", "article", "preposition", "spelling", "verb_form", "punctuation", "syntax"]
        for ft in fallback_types:
            if ft != error_type:
                similar_errors = await find_errors_by_type(ft, limit=10)
                if similar_errors:
                    error_type = ft
                    break

    if not similar_errors:
        raise ValueError("No dataset examples available for quiz generation")
    
    # Select deterministic error from similar ones
    rng = _rng_for_user(user_id)
    selected = rng.choice(similar_errors)
    input_text = selected.get("input_phrase", "")
    corrected_text = selected.get("corrected_gold", "")
    
    # Extract error spans to identify what changed
    error_spans = extract_error_spans(input_text, corrected_text)
    
    # Filter out insertion spans (original="") — they produce broken blanks
    usable_spans = [s for s in error_spans if s.get("original") and s.get("tag") != "insert"]

    if not usable_spans:
        raise ValueError("No usable error span (only insertions or empty) for quiz generation")

    span = usable_spans[0]
    masked, correct_answer = _mask_error_in_sentence(input_text, span)
    
    # Generate distractors
    distractors = _generate_distractors(correct_answer, error_type)
    
    # Build options (correct + distractors)
    options = [correct_answer] + distractors
    options = list(dict.fromkeys(opt for opt in options if opt))  # deduplicate, preserve order
    if len(options) < 3:
        raise ValueError(f"Insufficient distractors for error type '{error_type}' (got {len(options)})")
    rng.shuffle(options)
    correct_index = options.index(correct_answer)
    
    # Build hint from feedback templates
    feedback = build_feedback(error_type, corrected_text, difficulty)
    hint = feedback.get("hint", "")
    
    return {
        "question_id": str(uuid.uuid4()),
        "input_text": masked,
        "original_text": input_text,
        "options": options,
        "correct_answer": correct_answer,
        "correct_index": correct_index,
        "hint": hint,
        "error_type": error_type,
        "difficulty": difficulty,
        "corrected_text": corrected_text,
    }


async def select_from_similar_errors(input_text: str, k: int = 3) -> list[dict]:
    """Select similar errors for a given input text.
    
    Args:
        input_text: The input text to find similar errors for
        k: Number of similar examples to return
    
    Returns:
        List of similar error examples
    """
    # Classify error type first
    error_type = classify_error_type(input_text, input_text, "other")
    
    # Find similar errors
    similar = await find_similar_errors(input_text, k=k, error_type=error_type)
    
    return similar


async def mix_error_types(user_id: str, count: int = 5) -> list[dict]:
    """Generate a balanced mix of quiz questions targeting user's weak areas.
    
    Args:
        user_id: User identifier
        count: Number of questions to generate
    
    Returns:
        List of quiz question dicts
    """
    from backend.storage import _get_session_profile
    
    # Get user profile to identify weak areas
    profile = await _get_session_profile(user_id)
    error_rates = profile.get("error_rates", {})
    
    # Define all error types
    all_types = ["tense", "agreement", "article", "preposition", "spelling"]
    
    # Weight selection based on error rates (higher rate = more likely to be selected)
    weights = []
    for et in all_types:
        rate = error_rates.get(et, 0)
        # Add base weight so all types appear, but focus on weak areas
        weights.append(0.2 + rate * 2)
    
    # Normalize weights
    total_weight = sum(weights)
    if total_weight > 0:
        weights = [w / total_weight for w in weights]
    else:
        weights = [0.2] * len(all_types)
    
    # Select error types based on weights
    rng = _rng_for_user(user_id)
    selected_types = rng.choices(all_types, weights=weights, k=count)
    
    # Generate questions for each type
    questions = []
    for error_type in selected_types:
        question = await generate_quiz_question(user_id, error_type=error_type)
        questions.append(question)
    
    return questions


async def _select_error_type_for_user(user_id: str) -> str:
    """Select an error type based on spaced repetition schedule, then weak areas.

    Priority order:
    1. Error types overdue for review (next_review_at <= now) — spaced repetition
    2. Weak areas by error rate — frequency-based targeting
    3. Random default
    """
    from backend.storage import _get_session_profile
    from backend.pedagogy.adaptivity import get_due_for_review

    _QUIZ_UNUSABLE = {"other", "none", "deletion", "insertion"}
    _DATASET_TYPES = {"tense", "agreement", "article", "preposition", "spelling", "verb_form", "punctuation", "syntax"}

    # Priority 1: spaced repetition — serve overdue reviews first
    try:
        due = await get_due_for_review(user_id)
        for item in due:
            et = item["error_type"]
            if et not in _QUIZ_UNUSABLE and et in _DATASET_TYPES:
                return et
    except Exception:
        pass

    # Priority 2: weak areas from session profile (exclude unusable types)
    profile = await _get_session_profile(user_id)
    error_rates = {k: v for k, v in profile.get("error_rates", {}).items()
                   if k not in _QUIZ_UNUSABLE and k in _DATASET_TYPES}

    rng = _rng_for_user(user_id)
    if error_rates and max(error_rates.values()) > 0:
        types = list(error_rates.keys())
        weights = list(error_rates.values())
        return rng.choices(types, weights=weights, k=1)[0]

    # Priority 3: default random (exclude "other" — produces unusable quiz questions)
    return rng.choice(["tense", "agreement", "article", "preposition", "spelling"])


async def evaluate_quiz_answer(
    question_id: str,
    input_text: str,
    user_answer: str,
    correct_answer: str,
    error_type: str,
    difficulty: str = "A2",
) -> dict:
    """Evaluate a quiz answer using the pedagogical pipeline.
    
    Args:
        question_id: Question identifier
        input_text: The question text (with blank or original)
        user_answer: User's submitted answer
        correct_answer: The correct answer
        error_type: Type of error the question targets
        difficulty: CECRL level
    
    Returns:
        Evaluation result with structured feedback
    """
    is_correct = user_answer.strip().lower() == correct_answer.strip().lower()
    
    if is_correct:
        # Correct answer - simple positive feedback
        feedback = build_feedback("none", correct_answer, difficulty)
    else:
        # Wrong answer - generate feedback with the error
        # Create a "corrected" version by replacing user answer with correct
        corrected_text = input_text.replace("___", correct_answer)
        user_text = input_text.replace("___", user_answer)
        
        # Build feedback using pipeline
        feedback = build_feedback(error_type, corrected_text, difficulty)
    
    return {
        "question_id": question_id,
        "user_answer": user_answer,
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "feedback": {
            "rule": feedback.get("rule", ""),
            "explanation": feedback.get("explanation", ""),
            "example": feedback.get("example", ""),
            "hint": feedback.get("hint", ""),
            "error_type": error_type if not is_correct else "none",
        },
        "error_type": error_type if not is_correct else "none",
    }
