"""
Hibrit arama:
  - Semantik : PGVectorStore (pgvector HNSW, cosine) uzerinde vektor aramasi
  - BM25     : langchain_community BM25Retriever; chunk'lar PGVectorStore'dan yuklenir,
               Turkce + Ingilizce snowball kok bulma ile tokenize edilir
  - Fuzyon   : langchain_postgres reciprocal_rank_fusion (k=60)
Ayrica akademisyen profil ozetleri icin ayri bir semantik siralama dondurulur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_postgres.v2.hybrid_search_config import reciprocal_rank_fusion

from backend.config import get_settings
from backend.vectorstore import get_chunk_store, get_profile_store

_TR = snowballstemmer.stemmer("turkish")
_EN = snowballstemmer.stemmer("english")
_WORD = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Turkce'ye uygun kucuk harf + kelime bolme + TR/EN kok bulma (BM25 icin)."""
    text = text.replace("İ", "i").replace("I", "ı").lower()
    words = [w for w in _WORD.findall(text) if len(w) > 1]
    tokens = []
    for w in words:
        tr, en = _TR.stemWord(w), _EN.stemWord(w)
        tokens.append(tr)
        if en != tr:
            tokens.append(en)
    return tokens


@lru_cache
def get_bm25() -> BM25Retriever:
    """Tum chunk'lari DB'den yukleyip bellekte BM25 indeksi kurar (reindex sonrasi refresh_bm25())."""
    data = get_chunk_store().get(include=["documents", "metadatas"])
    docs = [
        Document(id=i, page_content=text, metadata=meta)
        for i, text, meta in zip(data["ids"], data["documents"], data["metadatas"])
    ]
    return BM25Retriever.from_documents(docs, k=get_settings().bm25_top_k, preprocess_func=tokenize)


def refresh_bm25() -> None:
    get_bm25.cache_clear()


@dataclass
class ChunkHit:
    id: str
    hoca_id: str
    bolum: str
    icerik: str
    rrf: float


async def hybrid_chunk_search(
    query_vector: list[float], keyword_query: str, use_semantic: bool = True, use_bm25: bool = True
) -> list[ChunkHit]:
    """use_semantic / use_bm25 bayraklari yalnizca degerlendirme (ablasyon) icindir."""
    s = get_settings()
    semantic = (
        await get_chunk_store().asimilarity_search_with_score_by_vector(query_vector, k=s.semantic_top_k)
        if use_semantic else []
    )
    bm25 = await get_bm25().ainvoke(keyword_query) if use_bm25 else []

    docs: dict[str, Document] = {d.id: d for d, _ in semantic} | {d.id: d for d in bm25}
    primary = [{"id": d.id, "distance": dist} for d, dist in semantic]            # cosine mesafe: kucuk iyi
    secondary = [{"id": d.id, "distance": len(bm25) - r} for r, d in enumerate(bm25)]  # BM25 sirasi: buyuk iyi

    fused = reciprocal_rank_fusion(primary, secondary, rrf_k=s.rrf_k, fetch_top_k=len(docs))
    return [
        ChunkHit(
            id=row["id"],
            hoca_id=docs[row["id"]].metadata["hoca_id"],
            bolum=docs[row["id"]].metadata["bolum"],
            icerik=docs[row["id"]].page_content,
            rrf=row["distance"],
        )
        for row in fused
    ]


async def profile_ranking(query_vector: list[float]) -> list[Document]:
    """Tum akademisyenleri profil ozeti benzerligine gore siralar (en benzer ilk)."""
    store = get_profile_store()
    results = await store.asimilarity_search_with_score_by_vector(query_vector, k=1000)
    return [doc for doc, _ in results]
