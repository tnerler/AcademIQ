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
    gerekce_model: str = "gpt-4.1-mini"  # eslestirme gerekcesi: uzun CV metninde satir bulma 4o-mini'de zayif
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
    kanit_karakter_butcesi: int = 24000  # gerekce icin hoca basina CV metni (~7k token; skorlamayi etkilemez)
    result_count: int = 20  # eslestirmede donen hoca sayisi (her biri icin bir LLM gerekcesi)
    bana_uygun_sonuc: int = 5  # "Bana Uygun"da donen cagri sayisi

    # --- Dosyalar ---
    cv_dir: Path = PROJECT_ROOT / "data" / "cvler"  # ana CV klasoru (.docx / .pdf); index_cvs ile senkronize
    cv_onizleme_dir: Path = PROJECT_ROOT / "data" / "processed" / "cv_onizleme"  # .docx CV'lerin PDF onizlemeleri

    # --- API ---
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]

    # --- PGVectorStore tablolari ---
    chunk_table: str = "cv_chunks"
    profile_table: str = "hoca_profilleri"
    cagri_table: str = "cagri_vektorleri"

    # --- Cagri toplama (docs/cagri-toplama-plan.md) ---
    cagri_cekme_saati: int = 7          # her gun bu saatte (Turkiye saati) calisir
    cagri_backfill_gun: int = 365       # ilk calistirmada geriye gidilecek gun
    cagri_belirsiz_kontrol_gun: int = 90  # tarihi belirsiz cagrilar bu kadar gun yeniden kontrol edilir
    cagri_otomatik_eslestirme: bool = True
    admin_token: str | None = None      # "Kaynaklari tara" icin; tanimli degilse tetikleme kapali

    # --- YOK Akademik (backend/yok) ---
    yok_universite: str = "PİRİ REİS ÜNİVERSİTESİ"
    yok_ilk_veri: Path = PROJECT_ROOT / "data" / "yok" / "pirireis_akademisyenler.json"  # tablo bossa yuklenir
    yok_tam_tarama_gunu: int = 6        # haftalik tam tarama: 0=Pazartesi ... 6=Pazar
    yok_tam_tarama_saati: int = 3       # Turkiye saati
    yok_tarama_bekleme_dk: int = 5      # elle taramalar arasi en az bu kadar dakika (YOK'un bot korumasi icin)

    # --- CV yukleme ---
    cv_upload_dir: Path = PROJECT_ROOT / "data" / "uploads" / "cvler"

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
