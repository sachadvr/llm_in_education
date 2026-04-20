import hashlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.cache import _cache_get, _cache_set
from backend.llm import correct_with_ollama, generate_exercise_with_ollama, grade_exercise_with_ollama, generate_quiz_with_ollama
from backend.pedagogy.feedback_generator import render_feedback_text
from backend.pedagogy.quiz_generator import (
    generate_quiz_question,
    evaluate_quiz_answer,
    select_from_similar_errors,
    mix_error_types,
)
from backend.pedagogy.adaptivity import (
    track_error,
    get_frequent_errors,
    calculate_exercise_difficulty,
    get_due_for_review,
    record_successful_review,
    spaced_repetition_interval,
    get_learning_recommendations,
    get_full_learner_profile,
)
from backend.pipeline.orchestrator import PipelineOrchestrator, create_structured_output
from backend.privacy import (
    create_privacy_safe_log,
    generate_session_id,
    hash_input,
    PrivacyConfig,
    PrivacyLevel,
)
from backend.schemas import (
    AdaptiveExerciseRequest,
    AdaptiveExerciseResponse,
    CorrectRequest,
    CorrectResponse,
    ExerciseGradeRequest,
    ExerciseGradeResponse,
    ExerciseResponse,
    FeedbackRatingRequest,
    FeedbackRatingResponse,
    LearnerProgressResponse,
    QuizGradeRequest,
    QuizGradeResponse,
    QuizResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
    QuizSimilarErrorsRequest,
    QuizSimilarErrorsResponse,
    ToggleOllamaRequest,
)
from backend.settings import settings
from sqlalchemy import Integer
from backend.storage import _get_level, _get_session_profile, _persist_correction, _persist_quiz_attempt, _record_correction_attempt, _record_grade_attempt, feedback_ratings_table, AsyncSessionLocal
from backend.text_utils import (
    classify_error_type,
    compute_diff,
    ensure_example,
    fill_blank,
    has_tense_mismatch,
    is_spelling_error,
    normalize,
    same_meaning,
    suggest_error_type,
    suggest_feedback,
    tokenize,
    unwrap_json_string,
)

def _get_user_id(request: Request, x_session_id: str | None = None) -> str:
    """Get user identifier from authenticated session or fallback to header/UUID."""
    current_user = getattr(request.state, "current_user", None)
    if current_user and current_user.get("user_id"):
        return str(current_user["user_id"])
    return x_session_id or str(uuid.uuid4())


router = APIRouter()
logger = logging.getLogger("mvp")
orchestrator = PipelineOrchestrator()


@router.post("/correct", response_model=CorrectResponse)
async def correct(req: CorrectRequest, request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Correct a grammatical phrase using the full NLP pipeline.

    Pipeline steps:
    1. Tokenization
    2. LLM correction (Ollama)
    3. Guardrails validation
    4. Structured diff and error span extraction
    5. Error classification
    6. Pedagogical feedback generation (CECRL-adapted)
    7. Similar error lookup
    8. Caching and persistence

    Returns structured correction with feedback, error type, and spans.
    """
    started_at = time.perf_counter()
    phrase = req.phrase.strip()
    if not phrase:
        raise HTTPException(status_code=400, detail="phrase vide")

    # Privacy: hash input for logging
    input_hash = hash_input(phrase)

    t0 = time.perf_counter()
    tokens = tokenize(phrase)
    token_count = len(tokens)
    durations = {"tokenization": round((time.perf_counter() - t0) * 1000, 2)}

    pipeline_steps = ["tokenisation", "correcteur (LLM)", "diff structure", "classification des erreurs", "feedback pédagogique"]

    session_id = _get_user_id(request, x_session_id)

    cache_key = f"correct:{normalize(phrase)}"
    cached = await _cache_get(request.app, cache_key)
    if cached:
        latency_ms = (time.perf_counter() - started_at) * 1000
        # Privacy-safe logging
        cached_error_type = cached.get("error_type", "other")
        log_data = create_privacy_safe_log("correct", phrase, cached_error_type)
        log_data.update({
            "source": "cache",
            "token_count": token_count,
            "latency_ms": round(latency_ms, 2),
            "cache_hit": True,
        })
        logger.info(json.dumps(log_data, ensure_ascii=True))
        # Track error even on cache hit — the user still made this error
        if session_id and cached_error_type and cached_error_type != "none":
            try:
                await track_error(session_id, cached_error_type)
            except Exception:
                pass
        return CorrectResponse(
            corrected=cached.get("corrected", phrase),
            feedback=cached.get("feedback", ""),
            error_type=cached_error_type,
            source="cache",
            changed=bool(cached.get("changed", False)),
            unchanged_ok=bool(cached.get("unchanged_ok", False)),
            token_count=token_count,
            pipeline=pipeline_steps,
            error_spans=cached.get("error_spans", [])
        )

    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)
    unchanged_ok = True
    llm_meta = {}
    
    t1 = time.perf_counter()
    try:
        if use_ollama:
            corrected, feedback, unchanged_ok, error_type, llm_meta = await correct_with_ollama(phrase)
            source = "ollama"
        else:
            raise HTTPException(status_code=503, detail="Ollama indisponible ou desactive")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Erreur de correction Ollama")
    durations["correction_llm"] = round((time.perf_counter() - t1) * 1000, 2)

    corrected = unwrap_json_string(corrected)
    
    from backend.pipeline.guardrails import validate_output
    guardrail_result = validate_output(phrase, corrected, error_type, llm_meta.get("raw_correction", ""))
    if guardrail_result.should_fallback:
        raise HTTPException(status_code=502, detail=f"Guardrail triggered: {guardrail_result.fallback_reason}")
    if corrected.startswith("{") or has_tense_mismatch(corrected):
        corrected = phrase.strip()
        feedback = suggest_feedback(phrase)
        unchanged_ok = False
        error_type = suggest_error_type(phrase)
    
    changed = not same_meaning(phrase, corrected)
    
    t2 = time.perf_counter()
    error_spans = compute_diff(phrase, corrected)
    durations["diff_structured"] = round((time.perf_counter() - t2) * 1000, 2)

    t3 = time.perf_counter()
    if changed is False and unchanged_ok is True:
        error_type = "none"
        if not feedback:
            feedback = "Phrase correcte."
    error_type = classify_error_type(phrase, corrected, error_type)
    durations["classification"] = round((time.perf_counter() - t3) * 1000, 2)

    t4 = time.perf_counter()
    profile = await _get_session_profile(session_id)
    level = str(profile.get("level") or "A2")
    
    pipeline_result = await orchestrator.run(
        original=phrase,
        corrected=corrected,
        model_error_type=error_type,
        level=level,
        llm_raw_output=llm_meta.get("raw_correction", ""),
    )
    structured_feedback = pipeline_result.feedback
    feedback = render_feedback_text(structured_feedback)
    durations["feedback_pedagogical"] = round((time.perf_counter() - t4) * 1000, 2)

    cache_payload = {
        "corrected": corrected,
        "feedback": feedback,
        "error_type": error_type,
        "source": source,
        "changed": changed,
        "unchanged_ok": unchanged_ok,
        "error_spans": error_spans
    }
    await _cache_set(request.app, cache_key, cache_payload)
    
    # Privacy: only store if enabled
    from backend.privacy import should_store_data
    if should_store_data():
        await _persist_correction({
            "phrase": phrase,
            "phrase_normalized": normalize(phrase),
            "corrected": corrected,
            "feedback": feedback,
            "error_type": error_type,
            "source": source,
            "changed": changed,
            "unchanged_ok": unchanged_ok,
        })

    if session_id:
        await _record_correction_attempt(session_id, success=(not changed and unchanged_ok), error_type=error_type)
        # Track error for adaptivity (async, non-blocking)
        if error_type and error_type != "none":
            try:
                await track_error(session_id, error_type)
            except Exception:
                pass  # Adaptivity tracking is best-effort

    latency_ms = (time.perf_counter() - started_at) * 1000
    
    # Privacy-safe enhanced logging
    log_data = create_privacy_safe_log("correct", phrase, error_type)
    log_data.update({
        "source": source,
        "changed": changed,
        "unchanged_ok": unchanged_ok,
        "token_count": token_count,
        "latency_ms": round(latency_ms, 2),
        "durations_ms": durations,
        "cache_hit": False,
        "json_valid": llm_meta.get("json_valid", True),
        "error_spans_count": len(error_spans),
        "prompt_version": settings.pipeline_version,
        "model_version": getattr(settings, "ollama_model", None),
        "retry_count": llm_meta.get("retry_count", 0),
        "guardrail_confidence": pipeline_result.confidence,
        "similar_errors_found": len(pipeline_result.similar_errors) if pipeline_result.similar_errors else 0,
    })
    logger.info(json.dumps(log_data, ensure_ascii=True))

    return CorrectResponse(
        corrected=corrected,
        feedback=feedback,
        error_type=error_type,
        source=source,
        changed=changed,
        unchanged_ok=unchanged_ok,
        token_count=token_count,
        pipeline=pipeline_steps,
        error_spans=pipeline_result.errors or error_spans
    )


@router.get("/exercise", response_model=ExerciseResponse)
async def exercise(request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Generate a fill-in-the-blank exercise adapted to the learner's level.

    Uses the learner's profile to select an appropriate CECRL level
    and optional focus error type. Raises 503 if Ollama is unavailable.
    """
    session_id = _get_user_id(request, x_session_id)
    profile = await _get_session_profile(session_id)
    level = str(profile.get("level") or await _get_level(session_id))
    recommended_focus = profile.get("focus")
    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)
    try:
        if use_ollama:
            prompt, sentence, blank = await generate_exercise_with_ollama(level=level, focus=recommended_focus)
            source = "ollama"
        else:
            raise HTTPException(status_code=503, detail="Ollama indisponible ou desactive")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Erreur de generation d'exercice via Ollama")
    return ExerciseResponse(prompt=prompt, sentence=sentence, blank=blank, source=source, level=level, recommended_focus=recommended_focus)


@router.get("/exercice", response_model=ExerciseResponse)
async def exercice_alias(request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """French alias for /exercise endpoint."""
    return await exercise(request, x_session_id)


@router.get("/quiz", response_model=QuizResponse)
async def quiz(request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Generate a quiz question using the pedagogical pipeline.
    
    Uses similar error patterns from dataset and generates structured
    questions targeting the user's weak areas.
    """
    session_id = _get_user_id(request, x_session_id)
    profile = await _get_session_profile(session_id)
    level = str(profile.get("level") or await _get_level(session_id))
    
    # Try dataset-based quiz only when user has error history — otherwise go straight to Ollama
    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)
    _profile_for_level = await _get_session_profile(session_id)
    _has_history = _profile_for_level.get("total_attempts", 0) > 5
    try:
        if not _has_history:
            raise ValueError("No error history — skip dataset quiz")
        question_data = await generate_quiz_question(user_id=session_id, difficulty=level)
        return QuizResponse(
            question_id=question_data["question_id"],
            input_text=question_data["input_text"],
            options=question_data["options"],
            correct_answer=question_data["correct_answer"],
            correct_index=question_data["correct_index"],
            hint=question_data["hint"],
            error_type=question_data["error_type"],
            source="pipeline",
        )
    except (ValueError, Exception) as e:
        logger.warning(f"Dataset quiz failed ({e}), falling back to Ollama")

    if not use_ollama:
        raise HTTPException(status_code=503, detail="Quiz unavailable: dataset empty and Ollama disabled")

    # Pick a focus from the user's weak areas for the Ollama fallback too
    profile_for_quiz = await _get_session_profile(session_id)
    error_rates = profile_for_quiz.get("error_rates", {})
    _QUIZ_TYPES = {"tense", "agreement", "article", "preposition", "spelling", "verb_form", "punctuation", "syntax"}
    quiz_focus = max(
        ((k, v) for k, v in error_rates.items() if k in _QUIZ_TYPES and v > 0),
        key=lambda x: x[1], default=(None, 0)
    )[0]

    try:
        question, options, correct_index = await generate_quiz_with_ollama(level=level, focus=quiz_focus)
    except Exception:
        raise HTTPException(status_code=502, detail="Erreur de génération du quiz via Ollama")

    from backend.pedagogy.feedback_templates import get_template
    error_type = quiz_focus or "tense"
    tmpl = get_template(error_type, level)

    import uuid as _uuid
    return QuizResponse(
        question_id=str(_uuid.uuid4()),
        input_text=question,
        options=options,
        correct_answer=options[correct_index],
        correct_index=correct_index,
        hint=tmpl.get("hint", ""),
        error_type=error_type,
        source="ollama",
    )


@router.post("/quiz/submit", response_model=QuizSubmitResponse)
async def submit_quiz(
    req: QuizSubmitRequest,
    request: Request,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
):
    """Evaluate a quiz answer using the full pedagogical pipeline.
    
    Returns structured feedback with rule, explanation, example, and hint.
    Tracks results in learner progression.
    """
    session_id = _get_user_id(request, x_session_id)
    profile = await _get_session_profile(session_id)
    level = str(profile.get("level") or "A2")
    
    # Evaluate using the pipeline
    result = await evaluate_quiz_answer(
        question_id=req.question_id,
        input_text=req.input_text,
        user_answer=req.user_answer,
        correct_answer=req.correct_answer,
        error_type=req.error_type,
        difficulty=level,
    )
    source = "pipeline"

    # Persist quiz attempt
    await _persist_quiz_attempt({
        "question": req.input_text,
        "options": json.dumps([]),
        "selected_index": -1,
        "correct_index": -1,
        "correct": result["is_correct"],
        "feedback": json.dumps(result["feedback"]),
        "error_type": result["error_type"],
        "source": source,
    })
    
    # Track for adaptivity + spaced repetition
    if session_id and result["error_type"] != "none":
        try:
            if result["is_correct"]:
                # Correct answer: advance mastery, push next review forward
                await record_successful_review(session_id, result["error_type"])
            else:
                # Wrong answer: reset mastery to 0, schedule review for tomorrow
                await track_error(session_id, result["error_type"])
            await _record_grade_attempt(session_id, result["is_correct"], result["error_type"])
        except Exception:
            pass  # Adaptivity tracking is best-effort
    
    return QuizSubmitResponse(
        question_id=result["question_id"],
        user_answer=result["user_answer"],
        is_correct=result["is_correct"],
        feedback=result["feedback"],
        error_type=result["error_type"],
        source=source,
    )


@router.get("/quiz/similar-errors", response_model=QuizSimilarErrorsResponse)
async def get_similar_errors(
    input_text: str,
    error_type: str | None = None,
    k: int = 3,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
):
    """Get similar errors for quiz generation.
    
    Retrieves similar error patterns from the dataset to help generate
    targeted quiz questions.
    """
    try:
        similar = await select_from_similar_errors(input_text, k=k)
        
        # If error_type specified, filter results
        if error_type and similar:
            similar = [s for s in similar if s.get("error_type") == error_type][:k]
        
        # Detect error type if not provided
        if not error_type:
            from backend.text_utils import classify_error_type
            error_type = classify_error_type(input_text, input_text, "other")
        
        return QuizSimilarErrorsResponse(
            input_text=input_text,
            similar_errors=similar,
            error_type=error_type,
        )
    except Exception as e:
        logger.error(f"Similar errors retrieval failed: {e}")
        return QuizSimilarErrorsResponse(
            input_text=input_text,
            similar_errors=[],
            error_type=error_type or "other",
        )


@router.post("/quiz/mix", response_model=list[QuizResponse])
async def generate_quiz_mix(
    request: Request,
    count: int = 5,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
):
    """Generate a balanced mix of quiz questions targeting user's weak areas.
    
    Uses learner progression data to weight error types and generate
    a personalized quiz mix.
    """
    session_id = _get_user_id(request, x_session_id)
    
    try:
        questions = await mix_error_types(session_id, count=count)
        
        responses = []
        for q in questions:
            responses.append(QuizResponse(
                question_id=q["question_id"],
                input_text=q["input_text"],
                options=q["options"],
                correct_answer=q["correct_answer"],
                correct_index=q["correct_index"],
                hint=q["hint"],
                error_type=q["error_type"],
                source="pipeline",
            ))
        
        return responses
    except Exception as e:
        logger.error(f"Quiz mix generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate quiz mix")


@router.post("/quiz/grade", response_model=QuizGradeResponse)
async def grade_quiz(req: QuizGradeRequest, request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Legacy quiz grading endpoint (multiple-choice).

    Compares selected_index with correct_index and returns basic feedback.
    Also persists the attempt and tracks errors for adaptivity.

    Deprecated: prefer /quiz/submit for structured pedagogical feedback.
    """
    session_id = _get_user_id(request, x_session_id)
    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)
    if not use_ollama:
        raise HTTPException(status_code=503, detail="Ollama indisponible ou desactive")

    if req.correct_index >= len(req.options) or req.selected_index >= len(req.options):
        raise HTTPException(status_code=400, detail="Indices invalides")

    correct = req.selected_index == req.correct_index
    if correct:
        feedback = "Correct, tu as bien utilise la reponse attendue."
        error_type = "none"
    else:
        feedback = "Incorrect, voici comment bien utiliser cela: choisis l'option correcte."
        error_type = "other"

    await _persist_quiz_attempt({"question": req.question, "options": json.dumps(req.options), "selected_index": req.selected_index, "correct_index": req.correct_index, "correct": correct, "feedback": feedback, "error_type": error_type, "source": "ollama"})

    # Track error for adaptivity (async, non-blocking)
    if session_id and not correct and error_type != "none":
        try:
            await track_error(session_id, error_type)
        except Exception:
            pass  # Adaptivity tracking is best-effort

    return QuizGradeResponse(correct=correct, feedback=feedback, error_type=error_type, source="ollama")


@router.post("/config/ollama")
async def toggle_ollama(req: ToggleOllamaRequest, request: Request):
    """Toggle Ollama availability at runtime.

    Overrides the Ollama enabled state for the current app instance.
    Useful for testing scenarios without restarting the server.
    """
    request.app.state.use_ollama_override = req.enabled
    return {"use_ollama": settings.is_ollama_enabled(request)}


@router.post("/exercise/grade", response_model=ExerciseGradeResponse)
async def grade_exercise(req: ExerciseGradeRequest, request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Grade a fill-in-the-blank exercise answer.

    Compares the user's answer with the expected blank using Ollama
    or deterministic matching. Returns correctness, correction, feedback,
    and error type. Tracks the result for learner adaptivity.
    """
    session_id = _get_user_id(request, x_session_id)
    sentence = req.sentence.strip()
    blank = req.blank.strip()
    user_answer = req.user_answer.strip()
    if not sentence or not blank or not user_answer:
        raise HTTPException(status_code=400, detail="Données invalides")

    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)
    try:
        if use_ollama:
            correct, corrected, feedback, error_type, _ = await grade_exercise_with_ollama(sentence, blank, user_answer)
            source = "ollama"
        else:
            raise HTTPException(status_code=503, detail="Ollama indisponible ou desactive")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"grade_exercise error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="Erreur de correction d'exercice via Ollama")

    from backend.text_utils import ERROR_TYPES
    if error_type not in ERROR_TYPES:
        error_type = "other"
    if session_id:
        await _record_grade_attempt(session_id, correct, error_type)
        # Track error for adaptivity (async, non-blocking)
        if not correct and error_type and error_type != "none":
            try:
                await track_error(session_id, error_type)
            except Exception:
                pass  # Adaptivity tracking is best-effort
    return ExerciseGradeResponse(correct=correct, corrected=corrected, feedback=feedback, error_type=error_type, source=source)


@router.post("/exercise/grade/stream")
async def grade_exercise_stream(req: ExerciseGradeRequest, request: Request):
    """Streamed version of exercise grading.

    Returns a plain-text streaming response with immediate feedback.
    Useful for real-time UI updates.
    """
    sentence = req.sentence.strip()
    blank = req.blank.strip()
    user_answer = req.user_answer.strip()
    if not sentence or not blank or not user_answer:
        raise HTTPException(status_code=400, detail="Données invalides")

    use_ollama = settings.is_ollama_enabled(request) and getattr(request.app.state, "ollama_available", False)

    async def generator():
        correct = normalize(user_answer) == normalize(blank)
        error_type = "none" if correct else ("spelling" if is_spelling_error(user_answer, blank) else "other")
        feedback = "Bonne réponse." if correct else "Réponse incorrecte."
        if use_ollama:
            try:
                _, corrected_llm, feedback_llm, model_error_type = await grade_exercise_with_ollama(sentence, blank, user_answer)
                if feedback_llm:
                    feedback = feedback_llm
                from backend.text_utils import ERROR_TYPES
                if not correct and model_error_type in ERROR_TYPES:
                    error_type = model_error_type
            except Exception:
                pass
        example = fill_blank(sentence, blank, blank)
        if correct:
            yield f"Correct. {feedback} Corrected: {example} Exemple : {example} (type: none)"
        else:
            yield f"Incorrect. La réponse attendue est '{blank}'. {feedback} Corrected: {example} Exemple : {example} (type: {error_type})"

    return StreamingResponse(generator(), media_type="text/plain")


@router.post("/exercice/grade", response_model=ExerciseGradeResponse)
async def grade_exercice_alias(req: ExerciseGradeRequest, request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """French alias for /exercise/grade endpoint."""
    return await grade_exercise(req, request, x_session_id)


@router.post("/exercice/grade/stream")
async def grade_exercice_stream_alias(req: ExerciseGradeRequest, request: Request):
    """French alias for /exercise/grade/stream endpoint."""
    return await grade_exercise_stream(req, request)


@router.post("/exercise/adaptive", response_model=AdaptiveExerciseResponse)
async def generate_adaptive_exercise(
    req: AdaptiveExerciseRequest,
    request: Request,
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
):
    """Generate an adaptive exercise based on learner's weak points.

    Analyzes the learner's error history to:
    1. Identify frequent/weighted errors
    2. Calculate appropriate difficulty level
    3. Generate exercise targeting specific error types
    """
    # Prefer authenticated DB user_id over the client-supplied UUID
    user_id = _get_user_id(request, x_session_id) or req.user_id

    # Get learner's progression data
    frequent_errors = await get_frequent_errors(user_id, limit=5)
    difficulty_info = await calculate_exercise_difficulty(user_id)

    # Determine target error type
    if req.focus_error_type:
        target_error = req.focus_error_type
        reasoning = f"User-requested focus on {target_error}"
    elif frequent_errors:
        target_error = frequent_errors[0]["error_type"]
        reasoning = f"Targeting most frequent error: {target_error} (weight: {frequent_errors[0]['weight']:.2f})"
    else:
        target_error = "general"
        reasoning = "No error history found, using general exercise"

    difficulty = difficulty_info.get("difficulty", 3)

    # Map CECRL level → exercise level label for Ollama
    profile = await _get_session_profile(user_id)
    cecrl_level = profile.get("level") or "B1"
    exercise_level = cecrl_level if cecrl_level in ("A1", "A2", "B1", "B2") else f"difficulty_{difficulty}"

    # Generate exercise using Ollama with adaptive parameters
    use_ollama = settings.is_ollama_enabled(request) and getattr(
        request.app.state, "ollama_available", False
    )

    if not use_ollama:
        raise HTTPException(status_code=503, detail="Ollama unavailable for adaptive exercise")

    try:
        from backend.llm import generate_exercise_with_ollama

        prompt, sentence, blank = await generate_exercise_with_ollama(
            level=exercise_level,
            focus=target_error,
        )
        source = "ollama"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Adaptive exercise generation failed: {exc}")

    return AdaptiveExerciseResponse(
        prompt=prompt,
        sentence=sentence,
        blank=blank,
        difficulty=difficulty,
        target_error_type=target_error,
        source=source,
        reasoning=reasoning,
    )


@router.get("/learner/{user_id}/progress", response_model=LearnerProgressResponse)
async def get_learner_progress(user_id: str, request: Request, x_session_id: str | None = Header(None, alias="X-Session-Id")):
    """Get comprehensive learner progress and recommendations.

    Returns:
        - Error history with weighted scores
        - Difficulty assessment
        - Personalized recommendations
        - Learning statistics
    """
    # Use authenticated user_id when available — the URL param may be a session UUID
    # that doesn't match where data is actually stored (DB user_id takes precedence)
    resolved_id = _get_user_id(request, x_session_id)
    profile = await get_full_learner_profile(resolved_id)
    return LearnerProgressResponse(**profile)


@router.post("/feedback/rate", response_model=FeedbackRatingResponse)
async def rate_feedback(req: FeedbackRatingRequest):
    """Save a human rating (👍/👎) for a feedback and return the current approval rate."""
    from sqlalchemy import select, func as sqlfunc
    async with AsyncSessionLocal() as session:
        await session.execute(
            feedback_ratings_table.insert().values(
                input_phrase=req.input_phrase,
                feedback_text=req.feedback_text,
                error_type=req.error_type,
                rating=req.rating,
                context=req.context,
            )
        )
        await session.commit()

        result = await session.execute(
            select(
                sqlfunc.count().label("total"),
                sqlfunc.sum(feedback_ratings_table.c.rating.cast(Integer)).label("positive"),
            )
        )
        row = result.fetchone()
        total = row.total or 0
        positive = row.positive or 0
        approval_rate = round(positive / total, 4) if total else None

    return FeedbackRatingResponse(saved=True, human_approval_rate=approval_rate)
