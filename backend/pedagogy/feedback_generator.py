"""Structured feedback builder for learner corrections."""

from __future__ import annotations

from backend.pedagogy.feedback_templates import get_template, SIMILAR_ERROR_TEMPLATE


def build_feedback(
    error_type: str,
    corrected: str,
    level: str = "A2",
    similar_errors: list[dict] | None = None,
) -> dict[str, str]:
    """Build structured feedback from deterministic templates."""
    template = get_template(error_type, level)
    
    feedback = {
        "rule": template["rule"],
        "explanation": template["explanation"],
        "example": template["example"],
        "hint": template["hint"],
        "error_type": error_type,
        "corrected": corrected,
        "level": level,
    }
    
    # Add similar errors if available
    if similar_errors:
        similar_text = build_similar_errors_text(similar_errors)
        if similar_text:
            feedback["similar_errors"] = similar_text
            feedback["similar_count"] = len(similar_errors)
    
    return feedback


def build_similar_errors_text(similar_errors: list[dict]) -> str:
    """Build text showing similar errors from other learners."""
    if not similar_errors:
        return ""
    
    lines = [SIMILAR_ERROR_TEMPLATE["intro"]]
    
    for err in similar_errors[:3]:  # Max 3 examples
        line = SIMILAR_ERROR_TEMPLATE["format"].format(
            input=err.get("input_phrase", ""),
            corrected=err.get("corrected_gold", ""),
            error_type=err.get("error_type", "other"),
        )
        lines.append(line)
    
    return "\n".join(lines)


def render_feedback_text(feedback: dict[str, str]) -> str:
    """Render structured feedback as compact learner-facing text."""
    parts = [
        f"Règle: {feedback.get('rule', '')}",
        f"Explication: {feedback.get('explanation', '')}",
        f"Exemple: {feedback.get('example', '')}",
        f"Indice: {feedback.get('hint', '')}",
    ]
    
    # Add similar errors if present
    if "similar_errors" in feedback:
        parts.append(f"\n{feedback['similar_errors']}")
    
    return "\n".join(parts)


def render_feedback_json(feedback: dict[str, str]) -> dict:
    """Ensure feedback is in structured JSON format."""
    return {
        "rule": feedback.get("rule", ""),
        "explanation": feedback.get("explanation", ""),
        "example": feedback.get("example", ""),
        "hint": feedback.get("hint", ""),
        "error_type": feedback.get("error_type", "other"),
        "corrected": feedback.get("corrected", ""),
        "level": feedback.get("level", "A2"),
    }


def build_detailed_feedback(
    original: str,
    corrected: str,
    error_type: str,
    error_spans: list[dict],
    level: str = "A2",
    similar_errors: list[dict] | None = None,
) -> dict:
    """Build comprehensive feedback with all details."""
    base_feedback = build_feedback(error_type, corrected, level, similar_errors)
    
    return {
        **base_feedback,
        "original": original,
        "spans": error_spans,
        "span_count": len(error_spans),
    }
