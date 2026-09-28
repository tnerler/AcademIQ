"""Aramaya giren CV bolumleri ve etiketleri (chunk basligi, kanit gruplari). Bolum maddeleri
cv_extract.arama_bolumleri ile LLM cikarimindan uretilir."""

from __future__ import annotations

SECTION_LABELS = {
    "arastirma": "Araştırma ve Uzmanlık Alanları",
    "egitim": "Eğitim",
    "yayinlar": "Yayınlar",
    "projeler": "Projeler",
    "yonetilen_tezler": "Yönetilen Tezler",
}
