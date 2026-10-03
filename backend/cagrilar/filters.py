"""Baslik kara listesi: proje cagrisi olmadigi basliktan belli olan duyurular LLM'e gitmeden elenir.

Kaliplar 2025-09 / 2026-09 arasindaki 252 TUBITAK duyuru basligina, sonra ayni donemin TUSEB (25), kalkinma
ajanslari (36) ve AB Baskanligi (27) basliklarina gore secildi. "Suresi uzatildi /
guncellendi" duyurulari bilerek listede yok: mevcut bir cagrinin tarihlerini guncellerler.
Kaliplar sadelestirilmis (kucuk harf, Turkce karaktersiz) basliga \\b ile kelime basindan uygulanir.
"""

from __future__ import annotations

import re

from backend.matching.ilan_extract import fold

KARA_LISTE = [
    "sonuc",                  # "... sonuclari aciklandi", "... cagrisi sonuclandi"
    "finalist",
    "yarisma",
    "odul",
    "olimpiyat",
    "lise", "ortaokul", "ilkokul", "ogrencileri",  # ogrenci projeleri (2204, 2209, 2242)
    "burs",                   # burs / bursiyer programlari kapsam disi (yalnizca Ar-Ge proje cagrilari)
    "bilim fuar", "bilim senlik", "bilim soylesi", "bilim merkez",
    "okullar",                # 4004 bilim okullari, 4009 koy okullari
    "yenilikci egitim uygulama", "kapsayici toplum",
    "etkinlikleri destekle", "etkinliklere katilim", "egitim etkinlik", "gozlem etkinlik",
    "katilim destegi", "toplantisina katilim",
    "kis okulu", "calistay", "seminer", "zirve", "kongre", "bilgi gunu", "proje pazari",
    "rehber", "onaylandi", "son asamaya",
    # TUSEB / kalkinma ajanslari / AB Baskanligi
    "ziyaret", "hakem", "webinar", "tamamlandi", "hak kazan", "protokol imza", "mesaji", "sikca sorulan",
    "toplantisi", "bilgilendirme etkinli", "bilgilendirme program", "egitimi duzenlen", "mentorlu",
    "yardim masasi", "satin alma", "yururluge gir",
    "kpss", "sinav", "atama", "uzman yardimci", "personel alim", "alim ilani", "alinacaktir",
]

_PATTERN = re.compile(r"\b(" + "|".join(re.escape(k) for k in KARA_LISTE) + ")")


def kara_liste(baslik: str) -> str | None:
    """Baslik kara listedeyse eslesen kalibi, degilse None doner."""
    m = _PATTERN.search(fold(baslik))
    return m.group(1) if m else None
