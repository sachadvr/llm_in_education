"""Guardrails for LLM output validation and quality control.

Provides:
- Confidence scoring
- Inconsistency detection
- Output validation
- Fallback mechanisms
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from backend.text_utils import (
    compute_diff,
    has_tense_mismatch,
    normalize,
    same_meaning,
    tokenize,
)


class ConfidenceLevel(Enum):
    """Confidence levels for LLM outputs."""
    HIGH = "high"      # > 0.8
    MEDIUM = "medium"  # 0.5 - 0.8
    LOW = "low"        # 0.3 - 0.5
    CRITICAL = "critical"  # < 0.3


@dataclass
class GuardrailResult:
    """Result of guardrail checks."""
    is_valid: bool
    confidence: float
    confidence_level: ConfidenceLevel
    issues: list[str]
    should_fallback: bool
    fallback_reason: str | None = None


def calculate_confidence(
    original: str,
    corrected: str,
    llm_raw_output: str,
    error_spans: list[dict],
    error_type: str,
) -> float:
    """Calculate confidence score for LLM correction.
    
    Factors:
    - JSON parseability (0.2)
    - No tense mismatch (0.2)
    - Meaningful changes detected (0.2)
    - Error spans present (0.2)
    - Reasonable length ratio (0.2)
    
    Returns:
        Confidence score between 0.0 and 1.0
    """
    scores = []
    
    # 1. JSON parseability (0.2)
    try:
        json.loads(llm_raw_output)
        scores.append(0.2)
    except json.JSONDecodeError:
        # Check if it contains JSON-like structures
        if '"corrected"' in llm_raw_output or '"feedback"' in llm_raw_output:
            scores.append(0.1)
        else:
            scores.append(0.0)
    
    # 2. No tense mismatch (0.2)
    if not has_tense_mismatch(corrected):
        scores.append(0.2)
    else:
        scores.append(0.0)
    
    # 3. Meaningful changes (0.2)
    if not same_meaning(original, corrected):
        # Real correction was made
        scores.append(0.2)
    elif error_type == "none":
        # No change was expected
        scores.append(0.2)
    else:
        # Expected change but none made
        scores.append(0.05)
    
    # 4. Error spans present (0.2)
    if error_spans:
        scores.append(0.2)
    elif error_type == "none":
        scores.append(0.2)
    else:
        scores.append(0.05)
    
    # 5. Reasonable length ratio (0.2)
    orig_len = len(tokenize(original))
    corr_len = len(tokenize(corrected))
    if orig_len > 0:
        ratio = corr_len / orig_len
        if 0.5 <= ratio <= 2.0:
            scores.append(0.2)
        elif 0.3 <= ratio <= 3.0:
            scores.append(0.1)
        else:
            scores.append(0.0)
    else:
        scores.append(0.0)
    
    return sum(scores)


def get_confidence_level(confidence: float) -> ConfidenceLevel:
    """Convert confidence score to level."""
    if confidence >= 0.8:
        return ConfidenceLevel.HIGH
    elif confidence >= 0.5:
        return ConfidenceLevel.MEDIUM
    elif confidence >= 0.3:
        return ConfidenceLevel.LOW
    else:
        return ConfidenceLevel.CRITICAL


def detect_inconsistencies(
    original: str,
    corrected: str,
    error_type: str,
    error_spans: list[dict],
) -> list[str]:
    """Detect inconsistencies between correction and metadata.
    
    Returns:
        List of detected issues
    """
    issues = []
    
    # Check 1: Error type vs error spans mismatch
    if error_type != "none" and not error_spans:
        issues.append(f"Error type '{error_type}' declared but no spans detected")
    
    if error_type == "none" and error_spans:
        issues.append("Error type 'none' but spans detected")
    
    # Check 2: Tense mismatch in correction
    if has_tense_mismatch(corrected):
        issues.append("Tense mismatch detected in corrected sentence")
    
    # Check 3: Same meaning but error declared
    if same_meaning(original, corrected) and error_type not in ("none", ""):
        issues.append("Same meaning but error type declared")
    
    # Check 4: Different meaning but no error declared
    if not same_meaning(original, corrected) and error_type == "none":
        issues.append("Sentence changed but error type is 'none'")
    
    # Check 5: Empty or too short correction
    if not corrected or len(corrected.strip()) < 3:
        issues.append("Correction is empty or too short")
    
    # Check 6: Correction is suspiciously different
    orig_tokens = set(normalize(original).split())
    corr_tokens = set(normalize(corrected).split())
    if len(corr_tokens) > 0:
        new_tokens = corr_tokens - orig_tokens
        if len(new_tokens) > len(orig_tokens) * 0.5:
            issues.append("Correction changes too many words")
    
    return issues


def validate_output(
    original: str,
    corrected: str,
    error_type: str,
    llm_raw_output: str,
) -> GuardrailResult:
    """Run all guardrail checks and return result.
    
    Args:
        original: Original input phrase
        corrected: LLM-corrected phrase
        error_type: Declared error type
        llm_raw_output: Raw LLM output for confidence calculation
    
    Returns:
        GuardrailResult with validation status and recommendations
    """
    # Compute error spans
    error_spans = compute_diff(original, corrected)
    
    # Calculate confidence
    confidence = calculate_confidence(
        original, corrected, llm_raw_output, error_spans, error_type
    )
    confidence_level = get_confidence_level(confidence)
    
    # Detect inconsistencies
    issues = detect_inconsistencies(original, corrected, error_type, error_spans)
    
    # Determine if fallback is needed
    should_fallback = False
    fallback_reason = None
    
    if confidence_level == ConfidenceLevel.CRITICAL:
        should_fallback = True
        fallback_reason = f"Critical confidence: {confidence:.2f}"
    elif confidence_level == ConfidenceLevel.LOW and len(issues) >= 2:
        should_fallback = True
        fallback_reason = f"Low confidence with multiple issues: {', '.join(issues[:2])}"
    elif has_tense_mismatch(corrected):
        should_fallback = True
        fallback_reason = "Tense mismatch detected"
    elif same_meaning(original, corrected) and error_type not in ("none", ""):
        should_fallback = True
        fallback_reason = "No actual correction made"
    
    return GuardrailResult(
        is_valid=not should_fallback and confidence >= 0.5,
        confidence=round(confidence, 3),
        confidence_level=confidence_level,
        issues=issues,
        should_fallback=should_fallback,
        fallback_reason=fallback_reason,
    )



