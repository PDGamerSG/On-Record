"""Text embeddings for meeting indexing and search."""

from .embed import GemmaEmbedder, HashEmbedder, get_embedder

__all__ = ["GemmaEmbedder", "HashEmbedder", "get_embedder"]
