"""Text models, embeddings, hybrid retrieval, meeting-note extraction and summaries for meetings."""

from .agent import MeetingAgent
from .embed import GemmaEmbedder, HashEmbedder, get_embedder
from .extract import Extractor, heuristic_extract
from .gemma import (
    FakeGemmaClient,
    GemmaClient,
    LLMConfigurationError,
    LLMResponseError,
    make_client,
)
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
from .summary import heuristic_summary, summarize_meeting

__all__ = [
    "Extractor",
    "FakeGemmaClient",
    "FakeLLM",
    "GeminiLLM",
    "GemmaClient",
    "GemmaEmbedder",
    "HashEmbedder",
    "LLMConfigurationError",
    "LLMError",
    "LLMResponseError",
    "MeetingAgent",
    "ModelGate",
    "OllamaLLM",
    "OpenAICompatLLM",
    "Retriever",
    "SarvamLLM",
    "get_embedder",
    "get_llm",
    "heuristic_extract",
    "heuristic_summary",
    "llm_priority",
    "make_client",
    "summarize_meeting",
]
