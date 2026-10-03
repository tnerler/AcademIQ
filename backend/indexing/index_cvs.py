"""
CV klasoru senkronizasyonu: data/cvler (.docx / .pdf) -> metin -> LLM cikarimi -> PGVectorStore.

  - Yalnizca yeni ya da degisen dosyalar (sha256) islenir; --hepsi ile tumu yeniden islenir.
  - Klasorde artik olmayan hocalar DB'den silinir (CV Yukle ile gelenler ve YOK akademisyenleri haric).
  - .docx CV'ler icin onizleme PDF'i LibreOffice ile uretilir (data/processed/cv_onizleme).
  - Bir sey degistiyse kayitli cagri eslestirmeleri silinir ve acik akademik cagrilar icin yeniden hesaplanir.
    Calisan backend'in BM25 indeksi bellekte oldugu icin ardindan backend yeniden baslatilmalidir.

Kimlik dosya adindan gelir: '001_Prof_Dr_Ertugrul_Akbulut_Klasik.docx' -> 'C001_Ertugrul_Akbulut'.

Kullanim:
  uv run python -m backend.indexing.index_cvs                    # config'deki klasor (data/cvler)
  uv run python -m backend.indexing.index_cvs --hepsi            # degismeyenleri de yeniden isle
  uv run python -m backend.indexing.index_cvs --recreate         # vektor tablolarini sifirdan kur
  uv run python -m backend.indexing.index_cvs --dump data/processed/cv_json   # DB'ye yazmadan cikarimi kaydet
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from langchain_core.documents import Document

from backend.api.schemas import CVCikarim
from backend.config import PROJECT_ROOT, get_settings
from backend.indexing.chunker import build_chunks
from backend.indexing.cv_extract import arama_bolumleri, cikar
from backend.indexing.docx_reader import docx_text
from backend.indexing.parser import parse_pdf
from backend.indexing.profile import AkademikProfil, format_sections, profile_chain, profile_text
from backend.matching.ilan_extract import fold
from backend.vectorstore import apply_indexes, doc_id, get_chunk_store, get_profile_store, init_tables
from backend.yok import YOK_ID_ONEKI

logger = logging.getLogger("index_cvs")

CV_UZANTILARI = {".docx", ".pdf"}


@dataclass
class IslenmisCV:
    cikarim: CVCikarim
    profile: AkademikProfil
    sections: dict[str, list[str]]


# --- Okuma ve cikarim (CV Yukle de kullanir) ------------------------------------

def cv_metni(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return docx_text(path)
    from backend.matching.pipeline import PARSE_LOCK  # PyMuPDF thread-safe degil

    with PARSE_LOCK:
        return parse_pdf(path, use_ocr=False).markdown


def isle(path: Path) -> IslenmisCV:
    """CV dosyasi -> LLM cikarimi + arama bolumleri + profil ozeti (DB'ye yazmaz)."""
    c = cikar(cv_metni(path))
    sections = arama_bolumleri(c)
    if not any(sections.values()):
        raise ValueError("CV'de araştırma alanı, yayın, proje ya da tez bulunamadı")
    return IslenmisCV(c, profile_chain.invoke({"cv": format_sections(sections)}), sections)


def hoca_id_for(path: Path) -> str:
    """'001_Prof_Dr_Ertugrul_Akbulut_Klasik' -> 'C001_Ertugrul_Akbulut' (unvan ve sablon adi atilir)."""
    parts = path.stem.split("_")
    no = parts.pop(0) if parts and parts[0].isdigit() else None
    parts = [p for p in parts if fold(p) not in _UNVAN_PARCALARI]
    if len(parts) > 2 and (fold(parts[-1]) in _SABLONLAR or "-" in parts[-1]):
        parts.pop()  # sablon adi: 'Klasik', 'Kenar-Cubuklu' ...
    isim = "_".join(parts) or path.stem
    return f"C{no}_{isim}" if no else isim


_UNVAN_PARCALARI = {"prof", "doc", "dr", "ogr", "uyesi", "ars", "gor", "arastirma", "gorevlisi", "yrd"}
_SABLONLAR = {"klasik", "minimalist", "modern", "kompakt", "cv"}


def dosya_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Onizleme PDF'i -------------------------------------------------------------

def onizleme_uret(dosyalar: dict[Path, str], out_dir: Path | None = None) -> dict[Path, Path]:
    """.docx dosyalarini LibreOffice ile PDF'e cevirir (dosya -> hoca_id); donus: kaynak -> onizleme PDF'i.
    LibreOffice yoksa uyarir ve bos doner (CV'ler onizlemesiz indekslenir)."""
    docxler = [p for p in dosyalar if p.suffix.lower() == ".docx"]
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not docxler:
        return {}
    if not soffice:
        logger.warning("LibreOffice bulunamadi: %d .docx CV onizlemesiz indekslenecek", len(docxler))
        return {}
    out_dir = out_dir or get_settings().cv_onizleme_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        # Ayri profil dizini: masaustunde acik bir LibreOffice varken de calissin
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/profil", "--headless", "--convert-to", "pdf",
                        "--outdir", tmp, *map(str, docxler)], check=False, capture_output=True, timeout=1800)
        sonuc = {}
        for p in docxler:
            pdf = Path(tmp) / f"{p.stem}.pdf"
            if pdf.exists():
                hedef = out_dir / f"{dosyalar[p]}.pdf"
                shutil.move(pdf, hedef)
                sonuc[p] = hedef
            else:
                logger.warning("Onizleme uretilemedi: %s", p.name)
    return sonuc


# --- DB -------------------------------------------------------------------------

def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def write_cv(hoca_id: str, kaynak: Path, cv: IslenmisCV, onizleme: Path | None, kaynak_hash: str) -> None:
    k = cv.cikarim.kimlik
    profile_doc = Document(
        page_content=profile_text(cv.profile),
        metadata={
            "hoca_id": hoca_id, "unvan": k.unvan, "ad_soyad": k.ad_soyad, "universite": k.universite,
            "fakulte": k.fakulte, "bolum": k.bolum, "email": cv.cikarim.iletisim.email,
            "kaynak_pdf": _relative(kaynak),  # kaynak CV dosyasi (.docx ya da .pdf)
            # metadata kolonu olmayan alanlar JSON metadata'ya gider
            "profil": cv.profile.model_dump(),
            "cv": cv.cikarim.model_dump(),
            "kaynak_hash": kaynak_hash,
            "onizleme_pdf": _relative(onizleme) if onizleme else None,
        },
    )
    get_profile_store().add_documents([profile_doc], ids=[doc_id(hoca_id)])

    chunk_store = get_chunk_store()
    old_ids = chunk_store.get(where={"hoca_id": hoca_id}, include=[])["ids"]
    if old_ids:
        chunk_store.delete(ids=old_ids)
    chunks = build_chunks(hoca_id, cv.sections)
    chunk_store.add_documents(chunks, ids=[doc_id(hoca_id, c.metadata["sira"]) for c in chunks])


def delete_cv(hoca_id: str) -> None:
    get_profile_store().delete(ids=[doc_id(hoca_id)])
    chunk_store = get_chunk_store()
    old_ids = chunk_store.get(where={"hoca_id": hoca_id}, include=[])["ids"]
    if old_ids:
        chunk_store.delete(ids=old_ids)


def kayitli_hocalar() -> dict[str, dict]:
    data = get_profile_store().get(include=["metadatas"])
    return {m["hoca_id"]: m for m in data["metadatas"]}


# --- Senkronizasyon -------------------------------------------------------------

def cv_dosyalari(klasor: Path) -> list[Path]:
    return sorted(p for p in klasor.rglob("*")
                  if p.suffix.lower() in CV_UZANTILARI and not p.name.startswith(("~$", ".")))


def senkronize(klasor: Path, hepsi: bool = False, concurrency: int = 6) -> dict[str, int]:
    s = get_settings()
    dosyalar = cv_dosyalari(klasor)
    ids = {p: hoca_id_for(p) for p in dosyalar}
    if len(set(ids.values())) != len(ids):
        raise ValueError("Ayni hoca kimligine dusen dosyalar var; dosya adlarini kontrol edin")

    kayitli = kayitli_hocalar()
    hashler = {p: dosya_hash(p) for p in dosyalar}
    islenecek = [p for p in dosyalar if hepsi or kayitli.get(ids[p], {}).get("kaynak_hash") != hashler[p]]
    upload_dir = _relative(s.cv_upload_dir)
    # CV Yukle ile gelenler ve YOK akademisyenleri (backend/yok/index.py) bu klasore bagli degil
    silinecek = [h for h, m in kayitli.items()
                 if h not in set(ids.values()) and not str(m.get("kaynak_pdf", "")).startswith(upload_dir)
                 and not h.startswith(YOK_ID_ONEKI)]
    logger.info("%d dosya: %d islenecek, %d degismemis; %d hoca silinecek",
                len(dosyalar), len(islenecek), len(dosyalar) - len(islenecek), len(silinecek))

    for hoca_id in silinecek:
        delete_cv(hoca_id)
        logger.info("SILINDI %s", hoca_id)

    onizlemeler = onizleme_uret({p: ids[p] for p in islenecek})
    sayac = {"islenen": 0, "hatali": 0, "silinen": len(silinecek)}
    # LLM cagrilari paralel; DB yazimi sirali (ayni tabloya es zamanli yazma yok)
    with ThreadPoolExecutor(concurrency) as ex:
        futures = {p: ex.submit(isle, p) for p in islenecek}
        for p, fut in futures.items():
            try:
                cv = fut.result()
                onizleme = onizlemeler.get(p) or (p if p.suffix.lower() == ".pdf" else None)
                write_cv(ids[p], p, cv, onizleme, hashler[p])
                sayac["islenen"] += 1
                logger.info("OK    %s (%s, %d yayin, %d proje, %d tez)", ids[p], cv.cikarim.kimlik.ad_soyad,
                            len(cv.cikarim.yayinlar), len(cv.cikarim.projeler), len(cv.cikarim.yonetilen_tezler))
            except Exception as exc:  # tek bir CV'nin hatasi tum senkronizasyonu durdurmasin
                logger.error("HATA  %s: %s", p.name, exc)
                sayac["hatali"] += 1
    return sayac


def eslesmeleri_yenile() -> None:
    from backend.cagrilar.db import init_schema
    from backend.cagrilar.eslesme import acik_akademik_cagrilari_eslestir, tum_eslesmeleri_sil

    init_schema()
    tum_eslesmeleri_sil()
    basarili, hatali = asyncio.run(acik_akademik_cagrilari_eslestir())
    logger.info("Kayitli cagri eslestirmeleri yenilendi: %d basarili, %d hatali", basarili, hatali)


def dump(klasor: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in cv_dosyalari(klasor):
        text = cv_metni(p)
        c = cikar(text)
        (out_dir / f"{hoca_id_for(p)}.txt").write_text(text, encoding="utf-8")
        (out_dir / f"{hoca_id_for(p)}.json").write_text(
            json.dumps({"cikarim": c.model_dump(), "arama_bolumleri": arama_bolumleri(c)}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        logger.info("DUMP  %s", p.name)


def main() -> int:
    ap = argparse.ArgumentParser(description="CV klasorunu vektor veritabaniyla senkronize eder.")
    ap.add_argument("klasor", type=Path, nargs="?", default=get_settings().cv_dir, help="CV klasoru")
    ap.add_argument("--hepsi", action="store_true", help="Degismemis dosyalari da yeniden isle")
    ap.add_argument("--recreate", action="store_true", help="Vektor tablolarini silip yeniden olusturur")
    ap.add_argument("--concurrency", type=int, default=6, help="Paralel islenen CV sayisi")
    ap.add_argument("--dump", type=Path, help="DB'ye yazmadan cikarimi bu klasore kaydeder")
    ap.add_argument("--eslesme-atla", action="store_true", help="Kayitli cagri eslestirmelerini yenileme")
    args = ap.parse_args()

    if not args.klasor.is_dir():
        logger.error("Klasor bulunamadi: %s", args.klasor)
        return 1
    if args.dump:
        dump(args.klasor, args.dump)
        return 0

    init_tables(recreate=args.recreate)
    sayac = senkronize(args.klasor, hepsi=args.hepsi or args.recreate, concurrency=args.concurrency)
    if sayac["islenen"] or sayac["silinen"]:
        apply_indexes()
        if not args.eslesme_atla:
            eslesmeleri_yenile()
    logger.info("Tamamlandi: %s", sayac)
    return 0 if not sayac["hatali"] else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
