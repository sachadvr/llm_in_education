"""JFLEG dataset loader for grammatical error correction. (Previous build)

JFLEG (JHU FLuency-Extended GUG) corpus:
- 747 test sentences
- 754 dev sentences
- 4 reference corrections per sentence

Source: https://github.com/keisks/jfleg

Usage:
    python main.py load-jfleg --split test
    python main.py load-jfleg --split dev
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from backend.settings import settings
from backend.storage import AsyncSessionLocal, dataset_table

logger = logging.getLogger("mvp")


class JFLEGLoader:
    """Loader for JFLEG dataset."""
    
    def __init__(
        self,
        min_length: int = 5,
        max_length: int = 200,
    ):
        """Initialize JFLEG loader."""
        self.min_length = min_length
        self.max_length = max_length
        self.loaded_count = 0
        self.skipped_count = 0
    
    def read_jfleg_file(self, filepath: str | Path) -> Iterator[dict]:
        """Read JFLEG source file."""
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"JFLEG file not found: {filepath}")
        
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                text = line.strip()
                
                # Filter by length
                if len(text.split()) < self.min_length:
                    self.skipped_count += 1
                    continue
                if len(text.split()) > self.max_length:
                    self.skipped_count += 1
                    continue
                
                yield {
                    "input": text,
                    "line_num": line_num,
                }
    
    def read_ref_file(self, filepath: str | Path, ref_num: int = 0) -> dict[int, str]:
        """Read JFLEG reference file."""
        refs = {}
        filepath = Path(filepath)
        
        if not filepath.exists():
            return refs
        
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                refs[line_num] = line.strip()
        
        return refs
    
    async def load_from_directory(
        self,
        directory: str | Path,
        split: str = "test",
        ref_nums: list[int] = None,
        use_single_ref: bool = True,
    ) -> dict:
        """Load JFLEG dataset from directory into database."""
        import json

        directory = Path(directory)

        if ref_nums is None:
            ref_nums = [0] if use_single_ref else [0, 1, 2, 3]

        split_dir = directory / split
        if not split_dir.exists():
            return {"error": f"Split not found: {split}"}

        source_file = split_dir / f"{split}.src"
        if not source_file.exists():
            return {"error": f"Source file not found: {source_file}"}

        refs = {}
        for ref_num in ref_nums:
            ref_file = split_dir / f"{split}.ref{ref_num}"
            if ref_file.exists():
                refs[ref_num] = self.read_ref_file(ref_file)

        if not refs:
            return {"error": "No reference files found"}

        async with AsyncSessionLocal() as session:
            batch = []
            batch_size = 100
            none_count = 0
            no_change_count = 0

            for item in self.read_jfleg_file(source_file):
                input_text = item["input"]
                line_num = item["line_num"]

                ref_num = ref_nums[0]
                corrected_text = refs[ref_num].get(line_num, input_text)

                if input_text.strip().lower() == corrected_text.strip().lower():
                    no_change_count += 1
                    continue

                error_type = self.classify_error_type(input_text, corrected_text)

                if error_type == "none":
                    none_count += 1
                    continue

                record = {
                    "input_phrase": input_text,
                    "corrected_gold": corrected_text,
                    "error_type_gold": error_type,
                    "dataset_split": split,
                    "error_spans_gold": json.dumps([]),  # Will be filled by diff
                    "is_verified": True,  # JFLEG is gold-standard
                }

                batch.append(record)
                self.loaded_count += 1

                if len(batch) >= batch_size:
                    await session.execute(dataset_table.insert(), batch)
                    await session.commit()
                    batch = []

            # Insert remaining records
            if batch:
                await session.execute(dataset_table.insert(), batch)
                await session.commit()

        return {
            "loaded": self.loaded_count,
            "skipped": self.skipped_count,
            "no_change": no_change_count,
            "none_type": none_count,
            "split": split,
            "total": self.loaded_count,
        }
    
    def classify_error_type(self, input_text: str, output_text: str) -> str:
        """Classify error type based on diff (heuristic)."""
        import re

        from backend.text_utils import (
            article_changed,
            is_spelling_error,
            plural_changed,
            preposition_changed,
            punctuation_changed,
            redundancy_changed,
            syntax_changed,
            word_choice_changed,
        )

        input_lower = input_text.lower()
        output_lower = output_text.lower()

        if is_spelling_error(input_text, output_text):
            return "spelling"

        if article_changed(input_text, output_text):
            return "article"

        if plural_changed(input_text, output_text):
            return "agreement"

        if preposition_changed(input_text, output_text):
            return "preposition"

        if punctuation_changed(input_text, output_text):
            return "punctuation"

        if word_choice_changed(input_text, output_text):
            return "word_choice"

        if syntax_changed(input_text, output_text):
            return "syntax"

        if redundancy_changed(input_text, output_text):
            return "redundancy"

        # Tense errors (common auxiliary- regEx for this, the best way to do this to me)
        if re.search(r'\b(is|are|was|were|have|has|had|do|does|did)\s+[a-z]', input_lower):
            if input_lower != output_lower:
                return "tense"

        # Agreement (simple check)
        if re.search(r'\b(he|she|it|they)\s+(is|are|was|have|do)', input_lower):
            if input_lower != output_lower:
                return "agreement"

        # Check overall length diff
        if len(input_text.split()) != len(output_text.split()):
            return "other"

        return "none"


async def load_jfleg_from_path(
    jfleg_path: str,
    split: str = "test",
    sample: int | None = None,
) -> dict:
    """Load JFLEG dataset."""
    loader = JFLEGLoader()
    
    result = await loader.load_from_directory(jfleg_path, split=split)
    
    return result
