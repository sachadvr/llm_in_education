"""Robust embedding computation for pgvector integration.

Supports multiple backends:
1. sentence-transformers (best quality)
2. HuggingFace transformers

Requires at least one backend to be installed.
"""

from __future__ import annotations

from typing import Callable

# Cache for embedding model
_embedding_model: Callable | None = None
_model_type: str | None = None


def _get_sentence_transformer_embedding(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Use sentence-transformers for high-quality embeddings."""
    global _embedding_model, _model_type
    
    if _embedding_model is None or _model_type != "sentence_transformers":
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(model_name)
            _model_type = "sentence_transformers"
        except ImportError:
            raise ImportError("sentence-transformers not installed")
    
    embedding = _embedding_model.encode(text, convert_to_numpy=True)
    return [float(x) for x in embedding]


def _get_transformers_embedding(text: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> list[float]:
    """Use transformers directly as fallback."""
    global _embedding_model, _model_type
    
    if _embedding_model is None or _model_type != "transformers":
        try:
            from transformers import AutoModel, AutoTokenizer
            import torch
            
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
            _embedding_model = (tokenizer, model)
            _model_type = "transformers"
        except ImportError:
            raise ImportError("transformers or torch not installed")
    
    tokenizer, model = _embedding_model
    
    # Tokenize and get embeddings
    inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
    
    with torch.no_grad():
        outputs = model(**inputs)
    
    # Mean pooling
    embeddings = outputs.last_hidden_state
    attention_mask = inputs["attention_mask"]
    mask_expanded = attention_mask.unsqueeze(-1).expand(embeddings.size()).float()
    sum_embeddings = torch.sum(embeddings * mask_expanded, 1)
    sum_mask = torch.clamp(mask_expanded.sum(1), min=1e-9)
    embedding = sum_embeddings / sum_mask
    
    return [float(x) for x in embedding[0]]


def compute_embedding(text: str, dim: int = 384) -> list[float]:
    """Compute embedding vector for text.
    
    Tries multiple backends in order:
    1. sentence-transformers (best quality)
    2. transformers (good quality, more dependencies)
    
    Args:
        text: Input text to embed
        dim: Desired embedding dimension (unused, kept for API compat)
    
    Returns:
        List of floats representing the embedding vector
    
    Raises:
        RuntimeError: If no embedding backend is available.
    """
    text = (text or "").strip()
    if not text:
        return [0.0] * dim
    
    # Try sentence-transformers first
    try:
        return _get_sentence_transformer_embedding(text)
    except Exception:
        pass
    
    # Try transformers
    try:
        return _get_transformers_embedding(text)
    except Exception:
        pass
    
    raise RuntimeError(
        "No embedding backend available. Install sentence-transformers or transformers."
    )


def compute_embedding_sync(text: str, dim: int = 384) -> list[float]:
    """Synchronous version of compute_embedding."""
    return compute_embedding(text, dim)


def embedding_to_pgvector(embedding: list[float]) -> str:
    """Convert embedding list to pgvector string format."""
    return "[" + ",".join(str(round(x, 6)) for x in embedding) + "]"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embeddings."""
    if len(a) != len(b):
        raise ValueError("Embeddings must have same dimension")
    
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return dot / (norm_a * norm_b)
