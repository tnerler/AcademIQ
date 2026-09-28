"""Tek CV yukleme (.pdf / .docx): ayni LLM cikarim akisi (index_cvs.isle); istenirse hoca havuzuna indeksleme.
CV Yukle sayfasi ve "Bana Uygun"daki "CV'mi kaydet" bu modulu kullanir."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
import uuid

from backend.config import get_settings
from backend.indexing.index_cvs import IslenmisCV, dosya_hash, isle, onizleme_uret, write_cv
from backend.matching.ilan_extract import fold
from backend.matching.search import refresh_bm25
from backend.vectorstore import get_profile_store


class CVOkunamadi(ValueError):
    pass


@dataclass
class AnalizEdilenCV:
    icerik: bytes
    uzanti: str  # ".pdf" | ".docx"
    cv: IslenmisCV


def analiz_et(icerik: bytes, uzanti: str) -> AnalizEdilenCV:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"cv{uzanti}"
        path.write_bytes(icerik)
        try:
            cv = isle(path)
        except ValueError as exc:
            raise CVOkunamadi(str(exc)) from None
    return AnalizEdilenCV(icerik, uzanti, cv)


def kaydet(a: AnalizEdilenCV) -> str:
    """Dosyayi yukleme klasorune yazar ve hoca havuzuna indeksler. Ayni e-postayla kayitli bir hoca varsa
    onun kaydinin uzerine yazilir. Donus: hoca_id."""
    kimlik = a.cv.cikarim.kimlik
    if not kimlik.ad_soyad:
        raise CVOkunamadi("CV'den ad soyad okunamadı")
    hoca_id = _mevcut_hoca(a.cv.cikarim.iletisim.email) or _yeni_id(kimlik.ad_soyad)
    upload_dir = get_settings().cv_upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{hoca_id}{a.uzanti}"
    path.write_bytes(a.icerik)
    # backend data/'yi salt okunur baglar; yuklenenlerin onizlemesi de yukleme klasorune yazilir
    onizleme = onizleme_uret({path: hoca_id}, upload_dir / "onizleme").get(path) or (path if a.uzanti == ".pdf" else None)
    write_cv(hoca_id, path, a.cv, onizleme, dosya_hash(path))
    refresh_bm25()
    return hoca_id


def _mevcut_hoca(email: str | None) -> str | None:
    if not email:
        return None
    docs = get_profile_store().get(where={"email": email}, include=["metadatas"])
    return docs["metadatas"][0]["hoca_id"] if docs["metadatas"] else None


def _yeni_id(ad_soyad: str) -> str:
    slug = "_".join(w.capitalize() for w in re.findall(r"[a-z]+", fold(ad_soyad)))
    return f"U{uuid.uuid4().hex[:6]}_{slug}"
