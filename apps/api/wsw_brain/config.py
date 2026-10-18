"""Runtime settings, all overridable with environment variables (or a .env file at the repo root)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .brand import REPO_ROOT


class Settings(BaseSettings):
    """Runtime settings from WSW_* environment variables and the repository's .env file; an environment
    variable wins. Each alias is the variable name, and docs/CONFIGURATION.md lists them all. Read them with
    settings(), which validates once per process."""

    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # Storage
    falkordb_url: str = Field("falkor://127.0.0.1:6379", min_length=1, alias="WSW_FALKORDB_URL")
    graph: str = Field("wsw_demo", min_length=1, alias="WSW_GRAPH")
    data_dir: Path = Field(REPO_ROOT / "data", alias="WSW_DATA_DIR")
    models_dir: Path = Field(REPO_ROOT / "models", alias="WSW_MODELS_DIR")

    # Text model routing. "auto" prefers Gemini with a key, then Sarvam with a key, then the configured local
    # model, then fake. With only OpenAI-compatible settings, auto raises; choose openai explicitly.
    llm_provider: Literal["auto", "ollama", "gemini", "openai", "sarvam", "fake"] = Field(
        "auto", alias="WSW_LLM_PROVIDER"
    )
    ollama_url: str = Field("http://127.0.0.1:11434", alias="WSW_OLLAMA_URL")
    ollama_model: str = Field("gemma4:e4b", alias="WSW_OLLAMA_MODEL")
    gemini_api_key: str | None = Field(None, alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemma-4-31b-it", alias="WSW_GEMINI_MODEL")
    openai_base_url: str | None = Field(None, alias="WSW_OPENAI_BASE_URL")
    openai_api_key: str | None = Field(None, alias="WSW_OPENAI_API_KEY")
    openai_model: str = Field("gemma-4-31B-it", alias="WSW_OPENAI_MODEL")
    # Sarvam AI: Gemma 4 31B ("gemma4") through Sarvam's chat API, and Document AI for uploaded documents.
    sarvam_api_key: str | None = Field(None, alias="SARVAM_API_KEY")
    sarvam_base_url: str = Field("https://api.sarvam.ai", min_length=1, alias="WSW_SARVAM_BASE_URL")
    sarvam_model: str = Field("gemma4", min_length=1, alias="WSW_SARVAM_MODEL")
    # Documents: Document AI language code, pages per Sarvam job (10 is the API limit), pages per upload.
    doc_language: str = Field("en-IN", min_length=2, alias="WSW_DOC_LANGUAGE")
    doc_part_pages: int = Field(10, ge=1, le=10, alias="WSW_DOC_PART_PAGES")
    doc_max_pages: int = Field(100, ge=1, le=1000, alias="WSW_DOC_MAX_PAGES")
    doc_max_mb: float = Field(25.0, gt=0, le=200, alias="WSW_DOC_MAX_MB")
    doc_concurrency: int = Field(3, ge=1, le=10, alias="WSW_DOC_CONCURRENCY")
    # Model request scheduling. These keep local inference responsive under concurrent clients.
    model_slots: int = Field(2, ge=1, alias="WSW_MODEL_SLOTS")
    model_max_waiting: int = Field(6, ge=0, alias="WSW_MODEL_MAX_WAITING")
    model_queue_wait_s: float = Field(90.0, gt=0, alias="WSW_MODEL_QUEUE_WAIT_S")
    # Which runtime hears spoken questions natively. "ollama" = Gemma 4 E4B audio input; "whisper" = server ASR.
    question_audio: Literal["auto", "ollama", "whisper"] = Field("auto", alias="WSW_QUESTION_AUDIO")

    # Embeddings: EmbeddingGemma-300m ONNX, or a deterministic hashing fallback.
    embedder: Literal["gemma", "hash"] = Field("gemma", alias="WSW_EMBEDDER")
    embed_repo: str = Field("onnx-community/embeddinggemma-300m-ONNX", alias="WSW_EMBED_REPO")
    embed_dim: int = Field(768, gt=0, alias="WSW_EMBED_DIM")

    # Listener
    asr_model: str = Field("small", alias="WSW_ASR_MODEL")
    asr_device: str = Field("cpu", alias="WSW_ASR_DEVICE")
    asr_compute_type: str = Field("int8", alias="WSW_ASR_COMPUTE")
    asr_language: str | None = Field("en", alias="WSW_ASR_LANGUAGE")
    speaker_model: str = Field("speaker_embedding_en.onnx", alias="WSW_SPEAKER_MODEL")
    speaker_threshold: float = Field(0.55, ge=0, le=1, alias="WSW_SPEAKER_THRESHOLD")
    max_utterance_s: float = Field(12.0, gt=0, alias="WSW_MAX_UTTERANCE_S")
    # Sarvam Saaras for Indian-language and code-mixed meetings (listen/sarvam_asr.py). "auto" detects the
    # language; modes: transcribe | translate (to English) | verbatim | translit | codemix.
    sarvam_asr_model: str = Field("saaras:v4", min_length=1, alias="WSW_SARVAM_ASR_MODEL")
    sarvam_asr_mode: Literal["transcribe", "translate", "verbatim", "translit", "codemix"] = Field(
        "transcribe", alias="WSW_SARVAM_ASR_MODE"
    )
    sarvam_asr_language: str = Field("auto", alias="WSW_SARVAM_ASR_LANGUAGE")

    # Brain
    extract_every: int = Field(6, gt=0, alias="WSW_EXTRACT_EVERY")
    seed_demo: bool = Field(True, alias="WSW_SEED_DEMO")
    cors_origins: str = Field("*", alias="WSW_CORS_ORIGINS")

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"


@lru_cache(maxsize=1)
def settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.audio_dir.mkdir(parents=True, exist_ok=True)
    return s
