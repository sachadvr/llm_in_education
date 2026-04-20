"""Span mapper for converting various dataset formats to error spans."""

from __future__ import annotations

from backend.nlp.error_extraction import extract_error_spans


def map_to_error_spans(original: str, corrected: str) -> list[dict]:
    """Map any input/correction pair to error spans."""
    return extract_error_spans(original, corrected)


def map_conll14_to_spans(
    original: str,
    corrections: list[str],
) -> list[dict]:
    """Map CoNLL-2014 format to error spans."""
    if not corrections:
        return []
    
    return extract_error_spans(original, corrections[0])


def map_fce_to_spans(
    original: str,
    corrected: str,
    annotations: list[dict] | None = None,
) -> list[dict]:
    """Map FCE (First Certificate in English) format to error spans."""
    if annotations:
        # Convert FCE annotations to our format
        spans = []
        for ann in annotations:
            spans.append({
                "start": ann.get("start", 0),
                "end": ann.get("end", 0),
                "start_char": ann.get("char_start", 0),
                "end_char": ann.get("char_end", 0),
                "original": ann.get("original", ""),
                "corrected": ann.get("correction", ""),
                "type": ann.get("error_type", "other"),
                "tag": ann.get("operation", "replace"),
            })
        return spans
    
    return extract_error_spans(original, corrected)


def map_m2_to_spans(m2_lines: list[str]) -> list[dict]:
    """Map M2 (MaxMatch) format to error spans."""
    spans = []
    
    for line in m2_lines:
        if not line.startswith("A "):
            continue
        
        # Parse M2 annotation line
        # Format: A start end|||error_type|||correction|||...|||annotator_id
        parts = line[2:].split("|||")
        if len(parts) < 3:
            continue
        
        try:
            start_end = parts[0].split()
            start = int(start_end[0])
            end = int(start_end[1])
            error_type = parts[1]
            correction = parts[2]
            
            spans.append({
                "start": start,
                "end": end,
                "start_char": -1,  # Not available in M2
                "end_char": -1,
                "original": "",  # Need to extract from source
                "corrected": correction,
                "type": error_type.lower().replace(":", "_"),
                "tag": "replace",
            })
        except (ValueError, IndexError):
            continue
    
    return spans


def map_c4200m_to_spans(original: str, output: str) -> list[dict]:
    """Map C4_200M format to error spans."""
    return extract_error_spans(original, output)


def validate_spans(spans: list[dict], original: str) -> list[dict]:
    """Validate and clean error spans."""
    validated = []
    
    for span in spans:
        # Ensure required fields
        if "start" not in span or "end" not in span:
            continue
        
        # Ensure start < end
        if span["start"] >= span["end"]:
            continue
        
        # Ensure valid type
        valid_types = {
            "tense", "agreement", "article", "preposition", "spelling",
            "word_choice", "punctuation", "syntax", "redundancy",
            "other", "none", "deletion", "insertion",
        }
        if span.get("type") not in valid_types:
            span["type"] = "other"
        
        validated.append(span)
    
    return validated
