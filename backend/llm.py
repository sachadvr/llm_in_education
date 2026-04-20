import hashlib
import json
import time as _time

import httpx
from fastapi import HTTPException

# Topic pool — injected into exercise prompts to force variety
_EXERCISE_TOPICS = [
    "travel and transport", "food and cooking", "work and careers",
    "technology and the internet", "health and medicine", "education and learning",
    "environment and climate", "sports and leisure", "music and arts",
    "family and relationships", "science and research", "politics and society",
    "money and finance", "history and culture", "cities and architecture",
    "animals and nature", "books and literature", "fashion and style",
    "space and astronomy", "language and communication",
    "gardening and plants", "photography and film", "social media", "volunteering",
    "cooking and recipes", "travel by train", "remote work", "mental health",
    "renewable energy", "public transport", "journalism and media", "museums",
    "university life", "job interviews", "online shopping", "tourism",
    "wildlife conservation", "artificial intelligence", "marketing", "theatre",
    "neighbourhood and community", "hobbies and crafts", "cycling", "coffee and tea",
    "architecture and design", "charity and fundraising", "podcasts",
    "weather and seasons", "migration and diversity", "startups and innovation",
]
_topic_counter = int(_time.time()) % len(_EXERCISE_TOPICS)


def _next_topic() -> str:
    global _topic_counter
    _topic_counter = (_topic_counter + 1) % len(_EXERCISE_TOPICS)
    return _EXERCISE_TOPICS[_topic_counter]

from backend.settings import OLLAMA_URL, settings
from backend.text_utils import (
    classify_error_type,
    edit_distance,
    ensure_example,
    extract_json,
    fill_blank,
    has_tense_mismatch,
    is_spelling_error,
    make_prompt,
    normalize,
    preposition_changed,
    sanitize_hint_fr,
    same_meaning,
    suggest_error_type,
    suggest_feedback,
    tokenize,
    unwrap_json_string,
    article_changed,
)

_extract_json = extract_json
_unwrap_json_string = unwrap_json_string
_normalize = normalize
_tokenize = tokenize
_edit_distance = edit_distance
_has_tense_mismatch = has_tense_mismatch
_suggest_feedback = suggest_feedback
_suggest_error_type = suggest_error_type
_make_prompt = make_prompt
_fill_blank = fill_blank
_sanitize_hint_fr = sanitize_hint_fr
_same_meaning = same_meaning
_article_changed = article_changed
_preposition_changed = preposition_changed
_is_spelling_error = is_spelling_error
_classify_error_type = classify_error_type
_ensure_example = ensure_example

CHECK_PROMPT = """You are an English grammar checker. Is this sentence grammatically correct? Reply ONLY with JSON: {{"correct": true}} or {{"correct": false}}
- FALSE: tense errors (e.g. "She go" with "yesterday" is wrong → need "went"; "drove" with "tomorrow" is wrong), subject-verb agreement, wrong article.
- TRUE: only if the sentence has no such errors.
Sentence: {phrase}
JSON only:"""

CORRECTION_PROMPT = """You are an English grammar corrector. Fix ONLY real errors. Critical: do NOT mix past and future.
    - Past (went, drove, was, had) goes with yesterday, last week, ago.
    - Future (will go, will drive) goes with tomorrow, next week.
    - Wrong: "She went to school tomorrow" (past + future). Right: "She will go to school tomorrow" or "She went to school yesterday."
    Output ONLY valid JSON: {{"corrected": "sentence here"}}
    Sentence: {phrase}"""

REFINEMENT_PROMPT = """You are an English grammar corrector. A first correction attempt was made but may still contain errors.

Original sentence: "{original}"
First correction attempt: "{first_correction}"
Detected error type: {error_type}
{similar_block}
Task: Check if the first correction is complete and grammatically correct. If it still contains errors, provide the final corrected version. If it is already correct, return it as-is.
Output ONLY valid JSON: {{"corrected": "final corrected sentence"}}"""

FEEDBACK_PROMPT = """The learner wrote: "{original}". The correct form is: "{corrected}". Give a short explanation in French (1-2 sentences).
Include ONE example sentence in English showing the correct usage.
Classify the main error type using ONLY one of: none, tense, agreement, article, preposition, spelling, word_choice, punctuation, syntax, redundancy, other.
Output ONLY valid JSON: {{"feedback": "explanation in French", "error_type": "tense"}}"""

EXERCISE_PROMPT = """You generate a single English fill-in-the-blank exercise for a {level} learner.
Target focus: {focus}
Return ONLY valid JSON: {{"sentence": "full correct sentence", "blank": "single word to hide", "hint_fr": "French hint for the missing word"}}
Rules:
- The blank must be a single English word appearing exactly once in the sentence.
- Provide a short French hint that is the exact translation of the blank (one word if possible), in plain ASCII (no accents, no other language).
- Avoid vague hints (e.g. "outil", "chose", "truc", "objet").
- Keep it short (6-12 words).
- Use common words.
- Avoid famous pangrams (e.g. "quick brown fox").
- Make each exercise different from previous ones by varying subject, verb, and time marker.
- If focus is tense, prefer past/future forms.
- If focus is agreement, prefer subject-verb agreement.
- If focus is article, prefer a/an/the.
- If focus is preposition, prefer common prepositions.
- If focus is spelling, prefer common misspellings.
"""

QUIZ_PROMPT = """You generate one English grammar multiple-choice question (MCQ) for a {level} learner.
Return ONLY valid JSON: {{"question": "...", "options": ["...", "...", "...", "..."], "correct_index": 0}}
Rules:
- One and only one option is correct.
- Keep 4 options total, short and clear.
- Focus on common grammar points (tense, article, preposition, agreement).
- Use plain ASCII only.
- Avoid reusing the same pattern every time.
"""

GRADE_PROMPT = """You are grading an English fill-in-the-blank exercise.
Sentence (correct): "{sentence}"
Blank word (expected): "{blank}"
Learner answer: "{user_answer}"
Return ONLY valid JSON: {{"correct": true|false, "corrected": "full corrected sentence", "feedback": "French feedback", "error_type": "none|tense|agreement|article|preposition|spelling|word_choice|punctuation|syntax|redundancy|other"}}
"""

GRADE_STREAM_PROMPT = """You are grading an English fill-in-the-blank exercise.
Sentence (correct): "{sentence}"
Blank word (expected): "{blank}"
Learner answer: "{user_answer}"
Return ONLY one single line in French, exactly like this format:
"Correct. <short feedback>. (type: none)" or "Incorrect. <short feedback>. (type: tense)"
Use one of: none, tense, agreement, article, preposition, spelling, word_choice, punctuation, syntax, redundancy, other.
"""


async def _ollama_post(client: httpx.AsyncClient, prompt: str, temperature: float = 0.0) -> str:
    """Envoie un prompt à Ollama, renvoie le texte de réponse ou lève HTTPException."""
    r = await client.post(OLLAMA_URL, json={
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    })
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Ollama error: {r.text[:200]}")
    return (r.json().get("response") or "").strip()


async def _ollama_stream(prompt: str):
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", OLLAMA_URL, json={
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.0},
        }) as r:
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Ollama error: {await r.aread()}")
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = obj.get("response") or ""
                if chunk:
                    yield chunk


async def correct_with_ollama(phrase: str) -> tuple[str, str, bool, str, dict]:
    """Retourne (corrected, feedback, unchanged_ok, error_type, meta)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        meta = {
            "retry_count": 0,
            "raw_check": "",
            "raw_correction": "",
            "raw_feedback": "",
            "json_valid": True,
        }
        raw0 = await _ollama_post(client, CHECK_PROMPT.format(phrase=phrase))
        meta["raw_check"] = raw0
        obj0 = _extract_json(raw0)
        # On ne dit "correct" que si le JSON dit explicitement true (bool ou chaîne "true")
        is_correct = False
        if isinstance(obj0, dict):
            val = obj0.get("correct")
            if val is True:
                is_correct = True
            elif isinstance(val, str) and val.strip().lower() == "true":
                is_correct = True
        # Pas de fallback "TRUE/YES dans le texte" : si pas de JSON valide, on passe à la correction

        if is_correct:
            return phrase.strip(), "Phrase correcte.", True, "none", meta

        raw1 = await _ollama_post(client, CORRECTION_PROMPT.format(phrase=phrase))
        meta["raw_correction"] = raw1
        obj1 = _extract_json(raw1)
        if isinstance(obj1, dict) and isinstance(obj1.get("corrected"), str):
            corrected = _unwrap_json_string(obj1["corrected"])
        else:
            corrected = _unwrap_json_string(raw1.strip().split("\n")[0])
        if not corrected:
            corrected = phrase.strip()

        if _same_meaning(phrase, corrected):
            meta["retry_count"] = 1
            retry_raw = await _ollama_post(
                client,
                f'The sentence is grammatically wrong. Correct it. Output ONLY: {{"corrected": "corrected sentence"}}\nSentence: {phrase}',
            )
            meta["raw_correction_retry"] = retry_raw
            retry_obj = _extract_json(retry_raw)
            if isinstance(retry_obj, dict) and isinstance(retry_obj.get("corrected"), str):
                corrected = _unwrap_json_string(retry_obj["corrected"])
            elif retry_raw.strip():
                corrected = _unwrap_json_string(retry_raw.strip().split("\n")[0])

        # Rejeter une "correction" qui contient elle-même une erreur (ex. went + tomorrow)
        if _has_tense_mismatch(corrected):
            raise HTTPException(status_code=502, detail="LLM produced a tense-mismatched correction")
        if _same_meaning(phrase, corrected):
            # Le LLM n'a pas vraiment corrigé (même phrase renvoyée).
            raise HTTPException(status_code=502, detail="LLM did not produce a meaningful correction")

        raw2 = await _ollama_post(
            client,
            FEEDBACK_PROMPT.format(original=phrase, corrected=corrected),
        )
        meta["raw_feedback"] = raw2
        obj2 = _extract_json(raw2)
        error_type = "other"
        if isinstance(obj2, dict) and isinstance(obj2.get("feedback"), str):
            feedback = _unwrap_json_string(obj2["feedback"])
            if isinstance(obj2.get("error_type"), str):
                error_type = obj2["error_type"].strip().lower()
        else:
            feedback = _unwrap_json_string(raw2.strip().split("\n")[0]) or "Correction effectuée."
        feedback = _ensure_example(feedback, corrected)
        if error_type not in {"none", "tense", "agreement", "article", "preposition", "spelling", "word_choice", "punctuation", "syntax", "redundancy", "other"}:
            error_type = _suggest_error_type(phrase)
        return corrected, feedback, True, error_type, meta  # unchanged_ok non utilisé (changed=True)


async def generate_exercise_with_ollama(level: str = "A2", focus: str | None = None) -> tuple[str, str, str]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            topic = _next_topic()
            prompt = (
                EXERCISE_PROMPT.format(level=level, focus=focus or "general")
                + f"\nRequired topic: {topic}. The sentence MUST be about {topic}.\n"
            )
            raw = await _ollama_post(client, prompt, temperature=0.9)
            obj = _extract_json(raw)
            if not isinstance(obj, dict):
                continue
            sentence = str(obj.get("sentence") or "").strip()
            blank = str(obj.get("blank") or "").strip()
            hint_fr = _sanitize_hint_fr(str(obj.get("hint_fr") or "").strip())
            if not sentence or not blank:
                continue
            low = sentence.lower()
            if "quick brown" in low or "lazy dog" in low:
                continue
            if sentence.count(blank) != 1:
                continue
            prompt = _make_prompt(sentence, blank)
            if hint_fr:
                prompt = f"{prompt} (Indice FR: {hint_fr})"
            return prompt, sentence, blank
    raise HTTPException(status_code=503, detail="Exercise generation failed after 3 retries")


async def generate_quiz_with_ollama(level: str = "A2", focus: str | None = None) -> tuple[str, list[str], int]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        for _ in range(3):
            topic = _next_topic()
            focus_hint = f" Focus on {focus} errors." if focus else ""
            prompt = (
                QUIZ_PROMPT.format(level=level)
                + f"\nRequired topic: {topic}. The question MUST be about {topic}.{focus_hint}\n"
            )
            raw = await _ollama_post(client, prompt, temperature=0.9)
            obj = _extract_json(raw)
            if not isinstance(obj, dict):
                continue
            question = str(obj.get("question") or "").strip()
            options_raw = obj.get("options")
            try:
                correct_index = int(obj.get("correct_index"))
            except (TypeError, ValueError):
                continue
            if not isinstance(options_raw, list):
                continue
            options = [str(opt).strip() for opt in options_raw]
            options = [opt for opt in options if opt]
            if not question or len(options) != 4:
                continue
            if correct_index < 0 or correct_index >= len(options):
                continue
            if len({opt.lower() for opt in options}) != len(options):
                continue
            return question, options, correct_index
    raise HTTPException(status_code=503, detail="Quiz generation failed after 3 retries")


async def grade_exercise_with_ollama(sentence: str, blank: str, user_answer: str) -> tuple[bool, str, str, str, dict]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        raw = await _ollama_post(
            client,
            GRADE_PROMPT.format(sentence=sentence, blank=blank, user_answer=user_answer),
        )
        meta = {"raw_output": raw, "json_valid": False}
        obj = _extract_json(raw)
        if isinstance(obj, dict):
            meta["json_valid"] = True
            correct = bool(obj.get("correct") is True or str(obj.get("correct")).lower() == "true")
            corrected = _unwrap_json_string(str(obj.get("corrected") or "").strip())
            feedback = _unwrap_json_string(str(obj.get("feedback") or "").strip())
            error_type = str(obj.get("error_type") or "").strip().lower()
            if not corrected:
                corrected = _fill_blank(sentence, blank, blank)
            if error_type not in {"none", "tense", "agreement", "article", "preposition", "spelling", "word_choice", "punctuation", "syntax", "redundancy", "other"}:
                error_type = _suggest_error_type(corrected)
            if not feedback:
                feedback = "Correction effectuée."
            expected_correct = _normalize(user_answer) == _normalize(blank)
            correct = expected_correct
            return correct, corrected, feedback, error_type, meta
    raise HTTPException(status_code=502, detail="Exercise grading failed")


async def refine_with_ollama(
    original: str,
    first_correction: str,
    error_type: str,
    similar_example: dict | None = None,
) -> str:
    """Second LLM call: refine first correction using pipeline context."""
    if similar_example:
        similar_block = (
            f'Similar example from memory:\n'
            f'  Wrong: "{similar_example.get("input_phrase", "")}"\n'
            f'  Correct: "{similar_example.get("corrected_gold", "")}"\n'
            f'  Error type: {similar_example.get("error_type", "")}'
        )
    else:
        similar_block = ""

    prompt = REFINEMENT_PROMPT.format(
        original=original,
        first_correction=first_correction,
        error_type=error_type,
        similar_block=similar_block,
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        raw = await _ollama_post(client, prompt)

    obj = _extract_json(raw)
    if isinstance(obj, dict) and isinstance(obj.get("corrected"), str):
        refined = _unwrap_json_string(obj["corrected"]).strip()
        if refined:
            return refined
    return first_correction
