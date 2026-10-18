"""Text models, embeddings, hybrid retrieval and meeting-note extraction for meetings."""

from .agent import MeetingAgent
from .embed import GemmaEmbedder, HashEmbedder, get_embedder
from .extract import Extractor, heuristic_extract
from .llm import (
    FakeLLM,
    GeminiLLM,
    LLMError,
    ModelGate,
    OllamaLLM,
    OpenAICompatLLM,
    SarvamLLM,
    get_llm,
    llm_priority,
)
from .retrieve import Retriever

__all__ = [
    "Extractor",
    "FakeLLM",
    "GeminiLLM",
    "GemmaEmbedder",
    "HashEmbedder",
    "LLMError",
    "MeetingAgent",
    "ModelGate",
    "OllamaLLM",
    "OpenAICompatLLM",
    "Retriever",
    "SarvamLLM",
    "get_embedder",
    "get_llm",
    "heuristic_extract",
    "llm_priority",
]
