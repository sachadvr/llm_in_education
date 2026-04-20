from typing import Optional

from pydantic import BaseModel, Field


class FeedbackRatingRequest(BaseModel):
    input_phrase: str = Field(..., min_length=1, max_length=2000)
    feedback_text: str = Field(..., min_length=1, max_length=2000)
    error_type: Optional[str] = None
    rating: bool = Field(..., description="True = utile, False = inutile")
    context: Optional[str] = Field("correction", description="'correction' | 'exercise'")


class FeedbackRatingResponse(BaseModel):
    saved: bool
    human_approval_rate: Optional[float] = None


class CorrectRequest(BaseModel):
    phrase: str = Field(..., min_length=1, max_length=2000, description="Phrase à corriger")


class CorrectResponse(BaseModel):
    corrected: str = Field(..., description="Phrase corrigée ou identique si pas de changement")
    feedback: str = Field(..., description="Explication ou retour pédagogique court")
    error_type: str = Field(..., description="Type d'erreur: none|tense|agreement|article|preposition|spelling|word_choice|punctuation|syntax|redundancy|other|unknown")
    source: str = Field(..., description="'ollama' | 'cache'")
    changed: bool = Field(..., description="True si une vraie correction a été appliquée")
    unchanged_ok: bool = Field(True, description="True si 'pas de changement' car phrase correcte")
    token_count: Optional[int] = Field(None, description="Nombre de tokens (pipeline NLP poster)")
    pipeline: Optional[list[str]] = Field(None, description="Étapes du pipeline : tokenisation → correcteur → classification → feedback")
    error_spans: Optional[list[dict]] = Field(None, description="Spans d'erreurs détectés par diff")


class ExerciseResponse(BaseModel):
    prompt: str = Field(..., description="Phrase avec trou, ex: She ____ to school yesterday.")
    sentence: str = Field(..., description="Phrase complète correcte")
    blank: str = Field(..., description="Mot attendu dans le trou")
    source: str = Field(..., description="'ollama'")
    level: Optional[str] = Field(None, description="Niveau CECRL estimé (adaptativité poster)")
    recommended_focus: Optional[str] = Field(None, description="Type d'erreur dominant à travailler")


class ExerciseGradeRequest(BaseModel):
    sentence: str = Field(..., min_length=1, max_length=2000, description="Phrase complète correcte")
    blank: str = Field(..., min_length=1, max_length=200, description="Mot attendu")
    user_answer: str = Field(..., min_length=1, max_length=200, description="Réponse de l'utilisateur")


class ExerciseGradeResponse(BaseModel):
    correct: bool = Field(..., description="True si la réponse est correcte")
    corrected: str = Field(..., description="Phrase corrigée")
    feedback: str = Field(..., description="Feedback en français")
    error_type: str = Field(..., description="Type d'erreur: none|tense|agreement|article|preposition|spelling|word_choice|punctuation|syntax|redundancy|other|unknown")
    source: str = Field(..., description="'ollama'")


class QuizResponse(BaseModel):
    question_id: str = Field(..., description="Unique question identifier")
    input_text: str = Field(..., description="Question text with blank or error")
    options: list[str] = Field(..., description="Liste d'options")
    correct_answer: str = Field(..., description="The correct answer text")
    correct_index: int = Field(..., description="Index de la bonne reponse")
    hint: str = Field(..., description="Hint for the question")
    error_type: str = Field(..., description="Type of error this question tests")
    source: str = Field(..., description="'pipeline' | 'ollama'")


class QuizSubmitRequest(BaseModel):
    question_id: str = Field(..., description="Question identifier")
    input_text: str = Field(..., description="Original question text")
    user_answer: str = Field(..., description="User's submitted answer")
    correct_answer: str = Field(..., description="Expected correct answer")
    error_type: str = Field(..., description="Type of error")


class QuizSubmitResponse(BaseModel):
    question_id: str = Field(..., description="Question identifier")
    user_answer: str = Field(..., description="User's submitted answer")
    is_correct: bool = Field(..., description="True si la reponse est correcte")
    feedback: dict = Field(..., description="Structured feedback with rule, explanation, example, hint")
    error_type: str = Field(..., description="Type d'erreur: none|tense|agreement|article|preposition|spelling|word_choice|punctuation|syntax|redundancy|other")
    source: str = Field(..., description="'pipeline' | 'ollama'")


class QuizGradeRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="Question QCM (legacy)")
    options: list[str] = Field(..., min_length=2, max_length=6, description="Liste d'options")
    selected_index: int = Field(..., ge=0, le=5, description="Index choisi par l'utilisateur")
    correct_index: int = Field(..., ge=0, le=5, description="Index de la bonne reponse")


class QuizGradeResponse(BaseModel):
    correct: bool = Field(..., description="True si la reponse est correcte")
    feedback: str = Field(..., description="Feedback en francais (legacy)")
    error_type: str = Field(..., description="Type d'erreur: none|tense|agreement|article|preposition|spelling|word_choice|punctuation|syntax|redundancy|other")
    source: str = Field(..., description="'ollama'")


class QuizSimilarErrorsRequest(BaseModel):
    input_text: str = Field(..., min_length=1, max_length=2000, description="Input text to find similar errors")
    error_type: str | None = Field(None, description="Optional error type filter")
    k: int = Field(3, ge=1, le=10, description="Number of similar errors to return")


class QuizSimilarErrorsResponse(BaseModel):
    input_text: str = Field(..., description="Original input text")
    similar_errors: list[dict] = Field(..., description="List of similar error examples")
    error_type: str = Field(..., description="Detected or specified error type")


class ToggleOllamaRequest(BaseModel):
    enabled: bool = Field(..., description="True pour activer Ollama, False pour le desactiver")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255, description="Username")
    password: str = Field(..., min_length=1, max_length=255, description="Password")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=255, description="Unique username")
    password: str = Field(..., min_length=4, max_length=255, description="Password (min 4 characters)")
    display_name: str | None = Field(None, max_length=255, description="Optional display name")


class UserResponse(BaseModel):
    id: int = Field(..., description="User ID")
    username: str = Field(..., description="Username")
    display_name: str | None = Field(None, description="Display name")
    created_at: str | None = Field(None, description="Creation timestamp")


class AdaptiveExerciseRequest(BaseModel):
    user_id: str = Field(..., description="Unique learner identifier")
    focus_error_type: Optional[str] = Field(None, description="Optional specific error type to focus on")


class AdaptiveExerciseResponse(BaseModel):
    prompt: str = Field(..., description="Exercise prompt with appropriate difficulty")
    sentence: str = Field(..., description="Complete correct sentence")
    blank: str = Field(..., description="Expected answer")
    difficulty: int = Field(..., ge=1, le=5, description="Difficulty level 1-5")
    target_error_type: str = Field(..., description="Error type this exercise targets")
    source: str = Field(default="adaptive", description="'adaptive' | 'ollama'")
    reasoning: str = Field(..., description="Why this exercise was selected")


class LearnerProgressResponse(BaseModel):
    user_id: str = Field(..., description="Learner identifier")
    error_history: list[dict] = Field(default_factory=list, description="Weighted error history")
    difficulty_assessment: dict = Field(default_factory=dict, description="Current difficulty level")
    recommendations: dict = Field(default_factory=dict, description="Learning recommendations")
    stats: dict = Field(default_factory=dict, description="Summary statistics")
    generated_at: str = Field(..., description="Timestamp of generation")


class BenchmarkRunRequest(BaseModel):
    max_examples: int = Field(100, ge=1, le=1000, description="Maximum number of examples to benchmark")


class BenchmarkResponse(BaseModel):
    status: str = Field(..., description="Benchmark execution status")
    report: dict = Field(default_factory=dict, description="Benchmark comparison report")


class ErrorHeatmapResponse(BaseModel):
    data: list[dict] = Field(default_factory=list, description="List of {session_id, error_type, count}")


class LearnerTrendItem(BaseModel):
    date: str = Field(..., description="Date string YYYY-MM-DD")
    total_attempts: int = Field(..., description="Total attempts that day")
    success_count: int = Field(..., description="Successful attempts that day")
    error_count: int = Field(..., description="Failed attempts that day")
    error_breakdown: dict = Field(default_factory=dict, description="Counts per error type")


class LearnerTrendsResponse(BaseModel):
    user_id: str = Field(..., description="Learner identifier")
    days: int = Field(..., description="Number of days in the trend window")
    trends: list[LearnerTrendItem] = Field(default_factory=list, description="Daily trend data")


class SystemMetricsResponse(BaseModel):
    generated_at: str = Field(..., description="ISO timestamp of generation")
    period_days: int = Field(..., description="Metrics aggregation period")
    total_corrections: int = Field(..., description="Total corrections processed")
    total_quiz_attempts: int = Field(..., description="Total quiz attempts")
    error_counts: dict = Field(default_factory=dict, description="Counts per error type")
    accuracy_rate: float = Field(..., description="Quiz accuracy rate 0.0-1.0")
    avg_latency_ms: float | None = Field(None, description="Average latency in milliseconds")
    confidence_avg: float | None = Field(None, description="Average confidence score")
    top_error_types: list[dict] = Field(default_factory=list, description="Top error types sorted by count")
    learner_summary: dict = Field(default_factory=dict, description="Active sessions and success rates")


class BenchmarkRunRequest(BaseModel):
    """Request to run a benchmark comparison."""
    max_examples: int | None = Field(None, description="Maximum examples to evaluate")


class BenchmarkResponse(BaseModel):
    """Response from benchmark run."""
    status: str = Field(..., description="Run status")
    results: dict = Field(default_factory=dict, description="Benchmark results per configuration")
