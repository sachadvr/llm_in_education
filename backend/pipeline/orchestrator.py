"""High-level pipeline orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from backend.nlp.error_extraction import extract_error_spans, get_error_summary
from backend.nlp.tokenizer import tokenize_text
from backend.pedagogy.feedback_generator import build_feedback
from backend.pipeline.guardrails import GuardrailResult, validate_output
from backend.text_utils import classify_error_type, same_meaning


@dataclass(slots=True)
class PipelineResult:
    """Result from pipeline execution."""
    original: str
    corrected: str
    errors: list[dict]
    feedback: dict
    error_type: str
    confidence: float
    guardrail_result: GuardrailResult | None = None
    similar_errors: list[dict] | None = None


class PipelineOrchestrator:
    """Compose deterministic NLP and pedagogy steps."""

    def __init__(
        self,
        use_similar_errors: bool = True,
        min_confidence: float = 0.3,
    ):
        """Initialize orchestrator."""
        self.use_similar_errors = use_similar_errors
        self.min_confidence = min_confidence

    async def run(
        self,
        original: str,
        corrected: str,
        model_error_type: str = "other",
        level: str = "A2",
        llm_raw_output: str = "",
    ) -> PipelineResult:
        """Run the complete correction pipeline."""
        errors = extract_error_spans(original, corrected)
        error_type = classify_error_type(original, corrected, model_error_type)

        # Adjust for "none" case
        if same_meaning(original, corrected) and error_type == "other":
            error_type = "none"

        guardrail_result = validate_output(
            original, corrected, error_type, llm_raw_output
        )

        similar_errors = None
        if self.use_similar_errors and error_type != "none":
            try:
                from backend.memory.similarity import find_similar_errors
                similar_errors = await find_similar_errors(original, k=3, error_type=error_type)
            except Exception:
                similar_errors = []

        feedback = build_feedback(
            error_type=error_type,
            corrected=corrected,
            level=level,
            similar_errors=similar_errors,
        )
        
        return PipelineResult(
            original=original,
            corrected=corrected,
            errors=errors,
            feedback=feedback,
            error_type=error_type,
            confidence=guardrail_result.confidence,
            guardrail_result=guardrail_result,
            similar_errors=similar_errors,
        )

    def run_sync(
        self,
        original: str,
        corrected: str,
        model_error_type: str = "other",
        level: str = "A2",
        llm_raw_output: str = "",
    ) -> PipelineResult:
        """Synchronous version of run.
        
        Note: Similar error search is skipped in sync mode.
        """
        errors = extract_error_spans(original, corrected)
        error_type = classify_error_type(original, corrected, model_error_type)

        # Adjust for "none" case
        if same_meaning(original, corrected) and error_type == "other":
            error_type = "none"

        guardrail_result = validate_output(
            original, corrected, error_type, llm_raw_output
        )

        # Similar error search skipped in sync mode
        feedback = build_feedback(
            error_type=error_type,
            corrected=corrected,
            level=level,
            similar_errors=None,
        )
        
        return PipelineResult(
            original=original,
            corrected=corrected,
            errors=errors,
            feedback=feedback,
            error_type=error_type,
            confidence=guardrail_result.confidence,
            guardrail_result=guardrail_result,
            similar_errors=None,
        )


def create_structured_output(result: PipelineResult) -> dict:
    """Convert pipeline result to structured output format."""
    return {
        "corrected": result.corrected,
        "errors": result.errors,
        "feedback": {
            "rule": result.feedback.get("rule", ""),
            "explanation": result.feedback.get("explanation", ""),
            "example": result.feedback.get("example", ""),
            "hint": result.feedback.get("hint", ""),
            "error_type": result.error_type,
        },
        "metadata": {
            "confidence": result.confidence,
            "is_valid": result.guardrail_result.is_valid if result.guardrail_result else True,
            "should_fallback": result.guardrail_result.should_fallback if result.guardrail_result else False,
            "similar_errors_count": len(result.similar_errors) if result.similar_errors else 0,
        },
    }
