"""
Hibrit arama:
  - Semantik : PGVectorStore (pgvector HNSW, cosine) uzerinde vektor aramasi
  - BM25     : langchain_community BM25Retriever; chunk'lar PGVectorStore'dan yuklenir,
               Turkce + Ingilizce snowball kok bulma ile tokenize edilir
  - Fuzyon   : langchain_postgres reciprocal_rank_fusion (k=60)
Ayrica akademisyen profil ozetleri icin ayri bir semantik siralama dondurulur.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import re
import time
from dataclasses import dataclass

import snowballstemmer
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_postgres.v2.hybrid_search_config import reciprocal_rank_fusion
from sqlalchemy import text

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


BM25_KONTROL_SN = 60  # chunk tablosu baska bir surecte (yok-worker, indexer) degistiyse en gec bu surede fark edilir
_bm25: dict = {"retriever": None, "imza": None, "kontrol": 0.0}


def _chunk_imzasi() -> str:
    """Chunk tablosunun icerik imzasi (ucuz: tek sorgu, Postgres tarafinda hash)."""
    from backend.cagrilar.db import get_engine as sync_engine

    tablo = get_settings().chunk_table
    with sync_engine().connect() as conn:
        return conn.execute(text(
            f'SELECT count(*) || \':\' || coalesce(md5(string_agg(md5(content), \'\' ORDER BY langchain_id)), \'\') '
            f'FROM "{tablo}"')).scalar_one()


def get_bm25() -> BM25Retriever:
    """Tum chunk'lari DB'den yukleyip bellekte BM25 indeksi kurar. Chunk'lar degistiyse (imza) yeniden kurar;
    ayni surecteki degisikliklerden sonra refresh_bm25() hemen yeniletir."""
    simdi = time.monotonic()
    if _bm25["retriever"] is not None and simdi - _bm25["kontrol"] < BM25_KONTROL_SN:
        return _bm25["retriever"]
    _bm25["kontrol"] = simdi
    imza = _chunk_imzasi()
    if _bm25["retriever"] is None or imza != _bm25["imza"]:
        data = get_chunk_store().get(include=["documents", "metadatas"])
        docs = [
            Document(id=i, page_content=t, metadata=meta)
            for i, t, meta in zip(data["ids"], data["documents"], data["metadatas"])
        ]
        _bm25.update(retriever=BM25Retriever.from_documents(docs, k=get_settings().bm25_top_k, preprocess_func=tokenize),
                     imza=imza)
    return _bm25["retriever"]


def refresh_bm25() -> None:
    _bm25.update(retriever=None, imza=None)


@dataclass
class ChunkHit:
    id: str
    hoca_id: str
    bolum: str
    icerik: str
    rrf: float
    benzerlik: float = 0.0  # ilanla cosine benzerligi (yalnizca hoca_kanitlari doldurur)


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


def _hoca_chunklari(query_vector: list[float], hoca_ids: list[str]) -> list[tuple[str, str, str, str, float]]:
    """Verilen hocalarin tum chunk'lari ve ilana cosine mesafeleri. Filtreli HNSW aramasi aday kumesini
    erken kirptigi icin (hoca basina birkac sonuc) indekssiz tam tarama yapilir; tablo kucuk."""
    from backend.cagrilar.db import get_engine as sync_engine

    tablo = get_settings().chunk_table
    with sync_engine().connect() as conn:
        rows = conn.execute(text(
            f'SELECT langchain_id::text, hoca_id, bolum, content, embedding <=> CAST(:q AS vector) '
            f'FROM "{tablo}" WHERE hoca_id = ANY(:ids)'),
            {"q": str(query_vector), "ids": hoca_ids}).all()
    return [tuple(r) for r in rows]


async def hoca_kanitlari(
    query_vector: list[float], keyword_query: str, hoca_ids: list[str]
) -> dict[str, list[ChunkHit]]:
    """Gerekce icin her hocanin KENDI chunk'lari: ilana gore siralanir (semantik + BM25, RRF) ve
    kanit_karakter_butcesi dolana kadar alinir (cogu hocada CV'nin tamami).
    Skorlamadaki global ilk N chunk yetmez: bir yayin chunk'inda ~10 farkli konulu baslik oldugu icin chunk
    benzerlikleri birbirine yakin cikar ve asil ilgili makaleler secilemez; satiri modelin kendisi secer."""
    s = get_settings()
    rows = await asyncio.to_thread(_hoca_chunklari, query_vector, hoca_ids)
    by_hoca: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        by_hoca[r[1]].append(r)

    sonuc: dict[str, list[ChunkHit]] = {}
    for hoca_id in hoca_ids:
        chunks = by_hoca.get(hoca_id, [])
        sonuc[hoca_id] = []
        if not chunks:
            continue
        meta = {r[0]: r for r in chunks}
        bm25 = BM25Retriever.from_documents(
            [Document(id=r[0], page_content=r[3]) for r in chunks], k=len(chunks), preprocess_func=tokenize,
        ).invoke(keyword_query)
        fused = reciprocal_rank_fusion(
            [{"id": r[0], "distance": r[4]} for r in sorted(chunks, key=lambda r: r[4])],
            [{"id": d.id, "distance": len(bm25) - i} for i, d in enumerate(bm25)],
            rrf_k=s.rrf_k, fetch_top_k=len(chunks),
        )
        butce = s.kanit_karakter_butcesi
        for row in fused:
            _, _, bolum, icerik, mesafe = meta[row["id"]]
            if len(icerik) > butce:
                break
            butce -= len(icerik)
            sonuc[hoca_id].append(ChunkHit(row["id"], hoca_id, bolum, icerik, row["distance"], 1.0 - mesafe))
    return sonuc


async def profile_ranking(query_vector: list[float]) -> list[Document]:
    """Tum akademisyenleri profil ozeti benzerligine gore siralar (en benzer ilk)."""
    store = get_profile_store()
    results = await store.asimilarity_search_with_score_by_vector(query_vector, k=1000)
    return [doc for doc, _ in results]
