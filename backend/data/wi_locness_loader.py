"""W&I+LOCNESS dataset loader for BEA2019 GEC shared task.

Format: M2 (standard GEC annotation format)
  S <space-tokenized sentence>
  A start end|||ERROR_TYPE|||correction|||REQUIRED|||-NONE-|||annotator_id

Gold spans are real human annotations — not derived algorithmically.
CEFR levels: A→A2, B→B1, C→B2, N→C1 (native).

Usage:
    python main.py load-wi-locness --path /tmp/wi+locness --split dev --levels A,B,C,N
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.storage import AsyncSessionLocal, dataset_table
from backend.text_utils import compute_diff

logger = logging.getLogger("mvp")

# BEA19 error type → internal taxonomy
_BEA19_TO_INTERNAL: dict[str, str] = {
    # Tense
    "R:VERB:TENSE": "tense",
    "M:VERB:TENSE": "tense",
    "U:VERB:TENSE": "tense",
    # Agreement (subject-verb, noun number)
    "R:VERB:SVA": "agreement",
    "M:VERB:SVA": "agreement",
    "U:VERB:SVA": "agreement",
    "R:NOUN:NUM": "agreement",
    "M:NOUN:NUM": "agreement",
    # Article / Determiner
    "U:DET": "article",
    "M:DET": "article",
    "R:DET": "article",
    # Preposition
    "U:PREP": "preposition",
    "M:PREP": "preposition",
    "R:PREP": "preposition",
    # Spelling / Orthography
    "R:SPELL": "spelling",
    "R:ORTH": "spelling",
    # Punctuation
    "U:PUNCT": "punctuation",
    "M:PUNCT": "punctuation",
    "R:PUNCT": "punctuation",
    # Verb form (infinitive, gerund, participle)
    "M:VERB:FORM": "verb_form",
    "R:VERB:FORM": "verb_form",
    "U:VERB:FORM": "verb_form",
    "M:VERB:INF": "verb_form",
    "R:VERB:INF": "verb_form",
    "M:VERB": "verb_form",
    "R:VERB": "verb_form",
    "U:VERB": "verb_form",
    "R:MORPH": "verb_form",
    # Word order / syntax
    "R:WO": "syntax",
    "M:WO": "syntax",
    # Noun
    "M:NOUN": "other",
    "R:NOUN": "other",
    "U:NOUN": "other",
    "R:NOUN:POSS": "other",
    # Adjective
    "M:ADJ": "other",
    "R:ADJ": "other",
    "U:ADJ": "other",
    "R:ADJ:FORM": "other",
    # Adverb
    "M:ADV": "other",
    "R:ADV": "other",
    "U:ADV": "other",
    # Pronoun
    "M:PRON": "other",
    "R:PRON": "other",
    "U:PRON": "other",
    # Conjunction
    "M:CONJ": "other",
    "R:CONJ": "other",
    "U:CONJ": "other",
    # Particle
    "M:PART": "other",
    "R:PART": "other",
    "U:PART": "other",
    # Other
    "R:OTHER": "other",
    "UNK": "other",
}

# Error type priority for dominant type selection
_TYPE_PRIORITY = {
    "tense": 6,
    "agreement": 5,
    "verb_form": 4,
    "article": 3,
    "preposition": 3,
    "spelling": 2,
    "syntax": 2,
    "punctuation": 1,
    "other": 0,
}

# CEFR level file prefix → our CECRL string
_CEFR_MAP = {
    "A": "A2",
    "B": "B1",
    "C": "B2",
    "N": "C1",
}

# M2 error type priority for dominant edit selection
_EDIT_OP_PRIORITY = {
    "R": 3,  # replacement
    "M": 2,  # missing (insertion)
    "U": 1,  # unnecessary (deletion)
}


def _detokenize(text: str) -> str:
    """Convert M2 tokenized text to natural text."""
    import re
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    # contractions: "you 'll" → "you'll", "it 's" → "it's"
    text = re.sub(r"(\w)\s+'(s|ll|ve|re|d|m|t)\b", r"\1'\2", text)
    # negative contractions: "do n't" → "don't", "ca n't" → "can't"
    text = re.sub(r"\b(do|does|did|ca|wo|sha|would|could|should|have|has|had|need|is|are|was|were|ai|dare|ought)\s+n't\b", lambda m: m.group(1) + "n't", text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_m2_file(filepath: Path) -> Iterator[dict]:
    """Parse M2 file, yielding one dict per sentence.

    Only uses annotator 0 edits (first annotator = gold standard).
    Skips noop-only sentences (no errors).
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        s_line = next((l for l in lines if l.startswith("S ")), None)
        if not s_line:
            continue

        sentence = s_line[2:]
        tokens = sentence.split()

        # Collect annotator 0 edits (exclude noop)
        edits = []
        for line in lines:
            if not line.startswith("A "):
                continue
            parts = line[2:].split("|||")
            if len(parts) < 3:
                continue
            annotator_id = int(parts[-1].strip()) if parts[-1].strip().isdigit() else -1
            if annotator_id != 0:
                continue
            span_part = parts[0].strip().split()
            if len(span_part) != 2:
                continue
            start, end = int(span_part[0]), int(span_part[1])
            error_type_raw = parts[1].strip()
            correction = parts[2].strip()

            if error_type_raw == "noop" or (start == -1 and end == -1):
                continue

            edits.append({
                "start": start,
                "end": end,
                "error_type_raw": error_type_raw,
                "correction": correction,
            })

        if not edits:
            continue

        # Reconstruct corrected sentence (apply edits right-to-left)
        corrected_tokens = list(tokens)
        for edit in sorted(edits, key=lambda e: e["start"], reverse=True):
            s, e = edit["start"], edit["end"]
            correction = edit["correction"]
            replacement = correction.split() if correction else []
            corrected_tokens[s:e] = replacement

        sentence = _detokenize(sentence)
        corrected = _detokenize(" ".join(corrected_tokens))

        # Skip if no actual change after detokenization
        if sentence.strip().lower() == corrected.strip().lower():
            continue

        # Gold spans: derived from diff(sentence, corrected) — consistent with
        # how predicted spans are computed, avoids M2 token→char offset issues
        gold_spans = compute_diff(sentence, corrected)

        # Dominant error type = highest priority edit
        dominant_type = max(
            (_BEA19_TO_INTERNAL.get(ed["error_type_raw"], "other") for ed in edits),
            key=lambda t: _TYPE_PRIORITY.get(t, 0),
        )

        yield {
            "input_phrase": sentence,
            "corrected_gold": corrected,
            "error_type_gold": dominant_type,
            "gold_spans": gold_spans,
        }


async def load_wi_locness(
    directory: str | Path,
    split: str = "dev",
    levels: list[str] | None = None,
    max_examples: int | None = None,
    min_length: int = 3,
    max_length: int = 200,
) -> dict:
    """Load W&I+LOCNESS dataset into the database.

    Args:
        directory: Path to extracted wi+locness directory
        split: "dev" or "train"
        levels: List of CEFR levels to load, e.g. ["A", "B", "C", "N"]
        max_examples: Cap total rows loaded
        min_length: Min token count
        max_length: Max token count

    Returns:
        Dict with load stats
    """
    directory = Path(directory)
    m2_dir = directory / "m2"

    if levels is None:
        levels = ["A", "B", "C", "N"]

    # N level only has dev, not train
    if split == "train":
        levels = [lv for lv in levels if lv != "N"]

    loaded = 0
    skipped_length = 0
    skipped_nochange = 0

    async with AsyncSessionLocal() as session:
        batch: list[dict] = []
        batch_size = 100

        for level in levels:
            fname = f"{level}.{split}.gold.bea19.m2"
            fpath = m2_dir / fname
            if not fpath.exists():
                logger.warning("M2 file not found: %s", fpath)
                continue

            cecrl = _CEFR_MAP.get(level, "B1")

            for item in _parse_m2_file(fpath):
                if max_examples and loaded >= max_examples:
                    break

                token_count = len(item["input_phrase"].split())
                if token_count < min_length or token_count > max_length:
                    skipped_length += 1
                    continue

                record = {
                    "input_phrase": item["input_phrase"],
                    "corrected_gold": item["corrected_gold"],
                    "error_type_gold": item["error_type_gold"],
                    "dataset_split": split,
                    "error_spans_gold": json.dumps(item["gold_spans"]),
                    "is_verified": True,
                }
                batch.append(record)
                loaded += 1

                if len(batch) >= batch_size:
                    stmt = pg_insert(dataset_table).values(batch).on_conflict_do_nothing(index_elements=["input_phrase"])
                    await session.execute(stmt)
                    await session.commit()
                    batch = []

            if max_examples and loaded >= max_examples:
                break

        if batch:
            stmt = pg_insert(dataset_table).values(batch).on_conflict_do_nothing(index_elements=["input_phrase"])
            await session.execute(stmt)
            await session.commit()

    return {
        "loaded": loaded,
        "skipped_length": skipped_length,
        "levels": levels,
        "split": split,
    }
