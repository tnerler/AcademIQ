"""
Tum backend parametreleri tek yerde. Degerler .env dosyasindan veya ortam
degiskenlerinden okunur; burada yazanlar varsayilanlardir.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # --- Veritabani ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # --- OpenAI ---
    openai_api_key: str
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-large"
    embedding_dim: int = 1536  # pgvector HNSW en fazla 2000 boyutu destekler
    embedding_batch_size: int = 128

    # --- Chunklama ---
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50

    # --- Arama / skorlama ---
    bm25_top_k: int = 50
    semantic_top_k: int = 50
    rrf_k: int = 60
    chunks_per_academic: int = 3  # akademisyen skoru = en iyi N chunk'in RRF ortalamasi + profil
    result_count: int = 5

    # --- Dosyalar ---
    cv_pdf_dir: Path = PROJECT_ROOT / "data" / "raw" / "fake_akademik_cvler"

    # --- API ---
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]

    # --- PGVectorStore tablolari ---
    chunk_table: str = "cv_chunks"
    profile_table: str = "hoca_profilleri"

    @property
    def database_url(self) -> str:
        # PGEngine async SQLAlchemy kullanir -> psycopg 3 surucusu
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
