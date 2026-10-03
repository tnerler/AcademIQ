"""Sohbette adi gecen akademisyeni hoca havuzunda bulur (Turkce karakter ve yazim hatalarina toleransli)."""

from __future__ import annotations

from difflib import SequenceMatcher

from backend.matching.ilan_extract import fold
from backend.vectorstore import get_profile_store

ESIK = 0.8  # bu benzerligin altindaki isimler "bulunamadi" sayilir
ONERI_ESIK = 0.6  # bulunamadiginda onerilecek benzer isimler
BELIRSIZ_FARK = 0.05  # en iyi iki aday bu kadar yakinsa hangisi oldugu sorulur
MAX_ADAY = 5


def _benzerlik(sorgu: list[str], ad: list[str]) -> float:
    """Sorgudaki her kelimenin addaki en benzer kelimeyle benzerliginin ortalamasi.
    'erkan' -> Erkan Kiyak ve Erkan Aydin'a esit (1.0) puan verir; 'erkan kiyak' yalnizca birine."""
    if not sorgu or not ad:
        return 0.0
    return sum(max(SequenceMatcher(None, s, a).ratio() for a in ad) for s in sorgu) / len(sorgu)


def sirala(ad: str, metas: list[dict]) -> tuple[dict | None, list[dict]]:
    """(bulunan, adaylar): tek ve net bir eslesme varsa bulunan dolu; belirsizse ya da yoksa adaylar."""
    sorgu = fold(ad).split()
    puanli = sorted(((_benzerlik(sorgu, fold(m["ad_soyad"]).split()), m) for m in metas),
                    key=lambda x: x[0], reverse=True)
    if not puanli:
        return None, []
    en_iyi = puanli[0][0]
    if en_iyi < ESIK:
        return None, [m for p, m in puanli[:MAX_ADAY] if p >= ONERI_ESIK]
    yakinlar = [m for p, m in puanli if p >= ESIK and en_iyi - p <= BELIRSIZ_FARK]
    if len(yakinlar) == 1:
        return yakinlar[0], []
    return None, yakinlar[:MAX_ADAY]


def hoca_bul(ad: str) -> tuple[dict | None, list[dict]]:
    return sirala(ad, get_profile_store().get(include=["metadatas"])["metadatas"])
