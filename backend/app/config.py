"""Central application configuration, loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Auth
    auth_required: bool = False               # set true in prod
    supabase_jwt_secret: str = ""             # required if auth_required=true
    supabase_jwt_audience: str = "authenticated"
    admin_emails: str = ""                    # comma-separated admin allowlist
    admin_internal_key: str = ""              # shared secret for n8n→backend admin calls

    # LLM
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"
    openai_api_key: str = ""
    # GPT-5 family — gpt-5 (smartest) | gpt-5-mini (balanced) | gpt-5-nano (cheap+fast)
    openai_model: str = "gpt-5-nano"
    openai_fast_model: str = "gpt-5-nano"   # used for classifier / verifier calls
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1"

    # Embeddings
    embeddings_provider: str = "ollama"
    embeddings_model: str = "nomic-embed-text"
    embeddings_dim: int = 768

    # Vector store
    vector_store_provider: str = "qdrant"     # qdrant | pinecone
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "rag-legal"
    qdrant_case_laws_collection: str = "case-laws"
    pinecone_api_key: str = ""
    pinecone_index: str = "rag-legal"
    pinecone_case_laws_index: str = "case-laws"
    pinecone_host: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # n8n
    n8n_webhook_base: str = "http://n8n:5678/webhook"
    n8n_fir_approval: bool = False            # if true, FIRs are gated through n8n
    n8n_notify_on_verdict: bool = True        # if true, verdicts call the fan-out webhook

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
