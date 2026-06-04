"""Build the configured LLM provider from settings (cached singleton)."""
from functools import lru_cache

from app.config import settings

from .base import LLMProvider
from .ollama_provider import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


@lru_cache
def get_llm() -> LLMProvider:
    provider = settings.llm_provider.lower()

    if provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is missing")
        return OpenAICompatibleProvider(
            name="groq",
            api_key=settings.groq_api_key,
            base_url=GROQ_BASE_URL,
            model=settings.groq_model,
            fast_model=settings.groq_fast_model,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is missing")
        return OpenAICompatibleProvider(
            name="openai",
            api_key=settings.openai_api_key,
            base_url=OPENAI_BASE_URL,
            model=settings.openai_model,
            fast_model=settings.openai_fast_model,
        )

    if provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )

    raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
