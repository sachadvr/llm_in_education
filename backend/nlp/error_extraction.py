"""Deterministic error span extraction and typing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.text_utils import (
    article_changed,
    is_spelling_error,
    normalize,
    plural_changed,
    preposition_changed,
    punctuation_changed,
    redundancy_changed,
    same_meaning,
    syntax_changed,
    tokenize,
    word_choice_changed,
)

if TYPE_CHECKING:
    pass


ERROR_TYPES = {
    "tense", "agreement", "article", "preposition", "spelling",
    "word_choice", "punctuation", "syntax", "redundancy",
    "verb_form", "noun_number",
    "other", "none", "deletion", "insertion",
}


@dataclass(frozen=True)
class ErrorSpan:
    """Represents a single error span."""
    start: int  # Token start index
    end: int    # Token end index
    start_char: int  # Character start index
    end_char: int    # Character end index
    original: str
    corrected: str
    type: str
    tag: str  # 'replace', 'delete', 'insert', 'equal'
    
    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "original": self.original,
            "corrected": self.corrected,
            "type": self.type,
            "tag": self.tag,
        }


def _get_char_position(tokens: list[str], token_index: int) -> int:
    """Get character position from token index."""
    char_pos = 0
    for i, token in enumerate(tokens[:token_index]):
        if i > 0:
            char_pos += 1  # Space between tokens
        char_pos += len(token)
    return char_pos


def _classify_span(original: str, corrected: str, tag: str = "replace") -> str:
    """Classify the type of error in a span."""
    orig_lower = original.lower().strip()
    corr_lower = corrected.lower().strip()
    
    # Check spelling first
    if tag == "replace" and is_spelling_error(original, corrected):
        return "spelling"
    
    # Check article
    if article_changed(original, corrected):
        # Verify it's actually an article change
        articles = {"a", "an", "the"}
        orig_words = set(tokenize(orig_lower))
        corr_words = set(tokenize(corr_lower))
        if articles & (orig_words ^ corr_words):
            return "article"

    # Check agreement BEFORE preposition — number is structurally dominant
    if tag == "replace":
        orig_tokens = tokenize(orig_lower)
        corr_tokens = tokenize(corr_lower)
        # Plural / number change
        if plural_changed(original, corrected):
            # Distinguish subject-verb agreement from simple noun number
            agreement_verbs = {
                "is", "are", "was", "were", "has", "have",
                "does", "do", "goes", "go", "eats", "eat",
                "makes", "make", "takes", "take", "writes", "write",
            }
            has_agreement_verb = False
            for o, c in zip(orig_tokens, corr_tokens):
                if o != c and (o in agreement_verbs or c in agreement_verbs):
                    has_agreement_verb = True
                    break
            if has_agreement_verb:
                return "agreement"
            return "noun_number"
        if len(orig_tokens) == 1 and len(corr_tokens) == 1:
            orig_word = orig_tokens[0]
            corr_word = corr_tokens[0]
            # Check for s-form differences
            if orig_word.rstrip("s") == corr_word.rstrip("s"):
                return "agreement"
            # Common agreement pairs
            agreement_pairs = [
                ("is", "are"), ("was", "were"), ("has", "have"),
                ("does", "do"), ("goes", "go"), ("eats", "eat"),
            ]
            if (orig_word, corr_word) in agreement_pairs or (corr_word, orig_word) in agreement_pairs:
                return "agreement"
        if len(orig_tokens) == 1 and len(corr_tokens) == 1:
            orig_word = orig_tokens[0]
            corr_word = corr_tokens[0]
            # Check for s-form differences
            if orig_word.rstrip("s") == corr_word.rstrip("s"):
                return "agreement"
            # Common agreement patterns
            agreement_pairs = [
                ("is", "are"), ("was", "were"), ("has", "have"),
                ("does", "do"), ("goes", "go"), ("eats", "eat"),
            ]
            if (orig_word, corr_word) in agreement_pairs or (corr_word, orig_word) in agreement_pairs:
                return "agreement"

    # Check preposition
    if preposition_changed(original, corrected):
        preps = {"in", "on", "at", "to", "for", "from", "with", "by", "of"}
        orig_words = set(tokenize(orig_lower))
        corr_words = set(tokenize(corr_lower))
        if preps & (orig_words ^ corr_words):
            return "preposition"

    # Check tense markers
    tense_markers = {
        "past": ["yesterday", "last", "ago", "before"],
        "future": ["tomorrow", "next", "later", "soon"],
    }
    for tense_type, markers in tense_markers.items():
        if any(m in orig_lower or m in corr_lower for m in markers):
            return "tense"

    # Check for common verb tense patterns
    tense_patterns = [
        ("go", "went", "gone", "going", "goes"),
        ("do", "did", "done", "doing", "does"),
        ("have", "had", "has", "having"),
        ("eat", "ate", "eaten", "eating", "eats"),
        ("write", "wrote", "written", "writing", "writes"),
    ]
    orig_tokens = tokenize(orig_lower)
    corr_tokens = tokenize(corr_lower)

    for pattern_group in tense_patterns:
        if any(p in orig_tokens for p in pattern_group) and any(p in corr_tokens for p in pattern_group):
            return "tense"

    # Check for verb form errors (same verb family, no tense marker)
    verb_families = [
        {"make", "makes", "made", "making"},
        {"do", "does", "did", "done", "doing"},
        {"go", "goes", "went", "gone", "going"},
        {"have", "has", "had", "having"},
        {"eat", "eats", "ate", "eaten", "eating"},
        {"write", "writes", "wrote", "written", "writing"},
        {"take", "takes", "took", "taken", "taking"},
        {"give", "gives", "gave", "given", "giving"},
        {"see", "sees", "saw", "seen", "seeing"},
        {"run", "runs", "ran", "run", "running"},
    ]
    orig_tokens_set = set(orig_tokens)
    corr_tokens_set = set(corr_tokens)
    for family in verb_families:
        if (
            (orig_tokens_set & family)
            and (corr_tokens_set & family)
            and orig_tokens_set != corr_tokens_set
        ):
            return "verb_form"

    # Check punctuation (apostrophes, commas, etc.)
    if punctuation_changed(original, corrected):
        return "punctuation"

    # Check word choice / collocation
    if tag == "replace" and word_choice_changed(original, corrected):
        return "word_choice"

    # Check syntax (word order)
    if tag == "replace" and syntax_changed(original, corrected):
        return "syntax"

    # Length difference → often syntax or missing word
    if tag == "replace" and len(orig_tokens) != len(corr_tokens):
        return "syntax"

    # Check redundancy
    if tag == "replace" and redundancy_changed(original, corrected):
        return "redundancy"

    # Check if meaning is preserved
    if same_meaning(original, corrected) and tag != "equal":
        return "other"

    # Tag-based classification
    if tag == "delete":
        return "deletion"
    elif tag == "insert":
        return "insertion"

    return "other"


def extract_error_spans(original: str, corrected: str) -> list[dict]:
    """Extract deterministic error spans from original/corrected sentence."""
    import difflib
    
    orig_tokens = tokenize(original)
    corr_tokens = tokenize(corrected)
    
    if not orig_tokens and not corr_tokens:
        return []
    
    matcher = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
    spans: list[ErrorSpan] = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        
        orig_chunk = " ".join(orig_tokens[i1:i2])
        corr_chunk = " ".join(corr_tokens[j1:j2])
        
        # Calculate character positions
        start_char = _get_char_position(orig_tokens, i1)
        end_char = _get_char_position(orig_tokens, i2)
        if i2 > i1:
            end_char = start_char + len(orig_chunk)
        
        error_type = _classify_span(orig_chunk, corr_chunk, tag)
        
        spans.append(
            ErrorSpan(
                start=i1,
                end=i2,
                start_char=start_char,
                end_char=end_char,
                original=orig_chunk,
                corrected=corr_chunk,
                type=error_type,
                tag=tag,
            )
        )
    
    return [span.to_dict() for span in spans]


def merge_adjacent_spans(spans: list[dict], max_gap: int = 1) -> list[dict]:
    """Merge adjacent or near-adjacent error spans."""
    if not spans:
        return []
    
    # Sort by start position
    sorted_spans = sorted(spans, key=lambda s: (s.get("start", 0), s.get("end", 0)))
    
    merged = []
    current = sorted_spans[0].copy()
    
    for span in sorted_spans[1:]:
        current_end = current.get("end", 0)
        span_start = span.get("start", 0)
        
        # Check if adjacent or near-adjacent
        if span_start <= current_end + max_gap:
            # Merge spans
            current["end"] = max(current.get("end", 0), span.get("end", 0))
            current["end_char"] = max(current.get("end_char", 0), span.get("end_char", 0))
            current["original"] = current.get("original", "") + " " + span.get("original", "")
            current["corrected"] = current.get("corrected", "") + " " + span.get("corrected", "")
            # Use more specific type if possible
            if current.get("type") == "other":
                current["type"] = span.get("type", "other")
            current["tag"] = "replace"  # Merged spans become replace
        else:
            merged.append(current)
            current = span.copy()
    
    merged.append(current)
    return merged


# Dominance priority: structural errors beat surface errors
_ERROR_TYPE_PRIORITY = [
    "tense", "agreement", "article", "preposition", "spelling",
    "word_choice", "syntax", "punctuation", "redundancy",
    "verb_form", "noun_number",
]


def get_error_summary(spans: list[dict]) -> dict:
    """Generate summary statistics from error spans."""
    from collections import Counter

    if not spans:
        return {
            "total_errors": 0,
            "error_types": {},
            "primary_error": None,
        }

    type_counts = Counter(span.get("type", "other") for span in spans)

    def _priority(etype: str) -> int:
        try:
            return _ERROR_TYPE_PRIORITY.index(etype)
        except ValueError:
            return 999

    primary = sorted(
        type_counts.items(),
        key=lambda x: (-x[1], _priority(x[0])),
    )[0][0]

    return {
        "total_errors": len(spans),
        "error_types": dict(type_counts),
        "primary_error": primary,
    }
