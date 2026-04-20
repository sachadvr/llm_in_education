"""Privacy utilities for data protection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class PrivacyLevel(Enum):
    """Privacy protection levels."""
    NONE = "none"        # No anonymization
    HASHED = "hashed"    # Hash identifying fields only
    FULL = "full"        # Hash + PII redaction


@dataclass
class PrivacyConfig:
    """Configuration for privacy protection."""
    level: PrivacyLevel = PrivacyLevel.HASHED
    store_raw: bool = False  # If False, never store raw inputs
    hash_salt: str = ""      # Optional salt for hashing


# Global config (can be overridden per request)
_global_config = PrivacyConfig()


def set_privacy_config(config: PrivacyConfig) -> None:
    """Set global privacy configuration."""
    global _global_config
    _global_config = config


def get_privacy_config() -> PrivacyConfig:
    """Get current privacy configuration."""
    return _global_config


def hash_input(text: str, salt: str | None = None) -> str:
    """Create deterministic hash of input text."""
    if not text:
        return ""
    
    salted = (salt or _global_config.hash_salt) + text.strip().lower()
    return hashlib.sha256(salted.encode()).hexdigest()


def hash_id(text: str) -> str:
    """Create short hash for ID purposes."""
    full_hash = hash_input(text)
    return full_hash[:16]  # First 16 chars sufficient for IDs


# Patterns for common PII
_PII_PATTERNS = {
    "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "phone": re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
    "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    "credit_card": re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
    "ip_address": re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
    "url": re.compile(r'https?://[^\s<>"{}|\\^`[\]]+'),
}


def redact_pii(text: str, replacements: dict[str, str] | None = None) -> str:
    """Redact personally identifiable information."""
    if not text:
        return text
    
    defaults = {
        "email": "[EMAIL]",
        "phone": "[PHONE]",
        "ssn": "[SSN]",
        "credit_card": "[CC]",
        "ip_address": "[IP]",
        "url": "[URL]",
    }
    reps = {**defaults, **(replacements or {})}
    
    result = text
    for pii_type, pattern in _PII_PATTERNS.items():
        result = pattern.sub(reps.get(pii_type, f"[{pii_type.upper()}]"), result)
    
    return result


def anonymize_correction_record(
    phrase: str,
    corrected: str,
    feedback: str,
    config: PrivacyConfig | None = None,
) -> dict:
    """Anonymize a correction record based on privacy config."""
    cfg = config or _global_config
    
    record = {
        "phrase_hash": hash_input(phrase),
        "corrected_hash": hash_input(corrected),
        "timestamp": None,  # To be filled by caller
    }
    
    if cfg.level == PrivacyLevel.NONE:
        # Store everything
        record["phrase"] = phrase
        record["corrected"] = corrected
        record["feedback"] = feedback
    elif cfg.level == PrivacyLevel.HASHED:
        # Hash identifying fields, store non-identifying
        record["phrase_length"] = len(phrase)
        record["corrected_length"] = len(corrected)
        record["feedback"] = feedback  # Feedback is pedagogical, not PII
        record["error_type"] = None  # To be filled by caller
    elif cfg.level == PrivacyLevel.FULL:
        # Hash + redact PII
        record["phrase_length"] = len(phrase)
        record["corrected_length"] = len(corrected)
        record["feedback"] = redact_pii(feedback)
        record["redacted"] = True
    
    return record


def should_store_data(config: PrivacyConfig | None = None) -> bool:
    """Check if data storage is enabled based on privacy config."""
    cfg = config or _global_config
    return cfg.store_raw or cfg.level != PrivacyLevel.FULL


def create_privacy_safe_log(
    event: str,
    phrase: str,
    error_type: str | None = None,
    config: PrivacyConfig | None = None,
) -> dict:
    """Create a privacy-safe log entry."""
    cfg = config or _global_config
    
    log_entry = {
        "event": event,
        "phrase_hash": hash_input(phrase),
        "error_type": error_type,
        "phrase_length": len(phrase),
    }
    
    if cfg.level == PrivacyLevel.NONE:
        log_entry["phrase"] = phrase
    
    return log_entry


def generate_session_id(user_identifier: str | None = None) -> str:
    """Generate a privacy-safe session ID."""
    import time
    import secrets
    
    # Generate random component
    random_component = secrets.token_hex(8)
    time_component = str(int(time.time()))
    
    if user_identifier:
        # Include hashed user identifier
        user_hash = hash_input(user_identifier)[:8]
        base = f"{user_hash}_{time_component}_{random_component}"
    else:
        base = f"{time_component}_{random_component}"
    
    return hash_input(base)[:16]
