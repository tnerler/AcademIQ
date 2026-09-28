"""
langchain_postgres PGVectorStore katmani.

Uc tablo:
  cv_chunks        : CV parcalari. Metadata kolonlari: hoca_id, bolum, sira
  hoca_profilleri  : akademisyen basina tek kayit (profil ozeti metni + embedding).
                     Kimlik bilgileri metadata kolonlarinda, LLM profili JSON metadata'da.
  cagri_vektorleri : toplanan proje cagrilari (id = cagrilar.id); "Bana Uygun" CV -> cagri aramasi icin.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from langchain_postgres import Column, PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex
from sqlalchemy.exc import ProgrammingError

from backend.config import get_settings
from backend.llm import get_store_embeddings

CHUNK_COLUMNS = [
    Column("hoca_id", "TEXT", nullable=False),
    Column("bolum", "TEXT", nullable=False),
    Column("sira", "INTEGER", nullable=False),
]
PROFILE_COLUMNS = [
    Column("hoca_id", "TEXT", nullable=False),
    Column("unvan", "TEXT"),
    Column("ad_soyad", "TEXT", nullable=False),
    Column("universite", "TEXT"),
    Column("fakulte", "TEXT"),
    Column("bolum", "TEXT"),
    Column("email", "TEXT"),
    Column("kaynak_pdf", "TEXT", nullable=False),
]
CAGRI_COLUMNS = [
    Column("hedef_kitle", "TEXT", nullable=False),
]

_ID_NAMESPACE = uuid.UUID("5b0c1d9e-7a43-4c55-9d3e-acade1a00001")


def doc_id(*parts: object) -> str:
    """Deterministik kimlik: ayni CV yeniden indekslenince ayni kayitlarin uzerine yazilir."""
    return str(uuid.uuid5(_ID_NAMESPACE, "/".join(map(str, parts))))


@lru_cache
def get_engine() -> PGEngine:
    return PGEngine.from_connection_string(url=get_settings().database_url)


def init_tables(recreate: bool = False) -> None:
    """CV tablolarini olusturur. recreate=True mevcut tablolari silip bastan kurar."""
    s = get_settings()
    _init(((s.chunk_table, CHUNK_COLUMNS), (s.profile_table, PROFILE_COLUMNS)), recreate)
    get_chunk_store.cache_clear()
    get_profile_store.cache_clear()


def init_cagri_table() -> None:
    _init(((get_settings().cagri_table, CAGRI_COLUMNS),), recreate=False)
    get_cagri_store.cache_clear()


def _init(tables, recreate: bool) -> None:
    s = get_settings()
    engine = get_engine()
    for table, columns in tables:
        try:
            engine.init_vectorstore_table(
                table_name=table,
                vector_size=s.embedding_dim,
                metadata_columns=columns,
                overwrite_existing=recreate,
            )
        except ProgrammingError as exc:  # tablo zaten var (CREATE TABLE'da IF NOT EXISTS yok)
            if "already exists" not in str(exc):
                raise


def apply_indexes() -> None:
    """HNSW (cosine) vektor indekslerini olusturur/yeniler."""
    for store in (get_chunk_store(), get_profile_store()):
        if store.is_valid_index():
            store.reindex()
        else:
            store.apply_vector_index(HNSWIndex())


@lru_cache
def get_chunk_store() -> PGVectorStore:
    return PGVectorStore.create_sync(
        engine=get_engine(),
        table_name=get_settings().chunk_table,
        embedding_service=get_store_embeddings(),
        metadata_columns=[c.name for c in CHUNK_COLUMNS],
    )


@lru_cache
def get_profile_store() -> PGVectorStore:
    return PGVectorStore.create_sync(
        engine=get_engine(),
        table_name=get_settings().profile_table,
        embedding_service=get_store_embeddings(),
        metadata_columns=[c.name for c in PROFILE_COLUMNS],
    )


@lru_cache
def get_cagri_store() -> PGVectorStore:
    return PGVectorStore.create_sync(
        engine=get_engine(),
        table_name=get_settings().cagri_table,
        embedding_service=get_store_embeddings(),
        metadata_columns=[c.name for c in CAGRI_COLUMNS],
    )
