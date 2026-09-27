"""
CV indeksleme akisi (tek seferlik / arka plan):
  PDF -> Markdown -> bolumler -> temizlik -> LLM profil -> chunk -> PGVectorStore (embedding otomatik)

Tekrar calistirilabilir: kimlikler deterministik oldugu icin profil kaydinin uzerine yazilir,
hocanin eski chunk'lari silinip yeniden eklenir.

Kullanim:
  uv run python -m backend.indexing.index_cvs                        # config'deki klasor
  uv run python -m backend.indexing.index_cvs --recreate             # tablolari sifirdan kur
  uv run python -m backend.indexing.index_cvs path/to/H001.pdf       # tek dosya
  uv run python -m backend.indexing.index_cvs --save data/processed/cv_output   # indeksle + ciktilari kaydet
  uv run python -m backend.indexing.index_cvs --dump data/processed/cv_output   # DB'ye yazmadan sadece kaydet

Kaydedilen ciktilar (her PDF icin ayri klasor, girdideki alt klasorler korunur):
  <id>/<id>.md          parser Markdown ciktisi
  <id>/<id>.json        parser JSON ciktisi (sayfalar, tablolar, metadata)
  <id>/<id>.clean.json  kimlik bilgileri, temizlenmis bolumler, chunk'lar ve LLM profil ozeti
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import sys
from pathlib import Path

from langchain_core.documents import Document

from backend.config import PROJECT_ROOT, get_settings
from backend.indexing.chunker import build_chunks
from backend.indexing.cleaner import clean_section
from backend.indexing.parser import DocumentResult, collect_pdfs, output_dir_for, parse_pdf
from backend.indexing.profile import AkademikProfil, format_sections, profile_chain, profile_text
from backend.indexing.sections import SEARCHABLE_SECTIONS, ParsedCV, split_sections
from backend.vectorstore import apply_indexes, doc_id, get_chunk_store, get_profile_store, init_tables

logger = logging.getLogger("index_cvs")


def prepare_cv(pdf_path: Path) -> tuple[DocumentResult, ParsedCV, dict[str, list[str]]]:
    """PDF -> temizlenmis bolumler. PyMuPDF thread-safe olmadigi icin sirayla cagrilir."""
    doc = parse_pdf(pdf_path, use_ocr=False)
    cv = split_sections(doc.markdown)
    sections = {key: clean_section(key, cv.sections[key]) for key in SEARCHABLE_SECTIONS if key in cv.sections}
    return doc, cv, sections


def save_outputs(out_dir: Path, pdf_path: Path, doc: DocumentResult, cv: ParsedCV,
                 sections: dict[str, list[str]], profile: dict | None) -> None:
    """Bir CV'nin ara ciktilarini inceleme icin kendi klasorune yazar."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    (out_dir / f"{stem}.md").write_text(doc.markdown + "\n", encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(json.dumps(asdict(doc), ensure_ascii=False, indent=2), encoding="utf-8")
    clean = {
        "id": stem,
        "kaynak_pdf": _relative(pdf_path),
        "header": asdict(cv.header),
        "profil": profile,
        "sections": sections,
        "chunks": [c.model_dump(include={"page_content", "metadata"}) for c in build_chunks(stem, sections)],
    }
    (out_dir / f"{stem}.clean.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def _existing_profile(hoca_id: str) -> dict | None:
    """--dump modunda LLM'i cagirmadan, daha once DB'ye yazilmis profil ozetini alir (yoksa None)."""
    try:
        docs = get_profile_store().get_by_ids([doc_id(hoca_id)])
    except Exception:  # DB erisilemiyorsa dump yine de profil olmadan yazilsin
        return None
    return docs[0].metadata.get("profil") if docs else None


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def write_cv(pdf_path: Path, cv: ParsedCV, profile: AkademikProfil, chunks: list[Document]) -> None:
    hoca_id = pdf_path.stem
    h = cv.header
    profile_doc = Document(
        page_content=profile_text(profile),
        metadata={
            "hoca_id": hoca_id, "unvan": h.unvan, "ad_soyad": h.ad_soyad, "universite": h.universite,
            "fakulte": h.fakulte, "bolum": h.bolum, "email": h.email, "kaynak_pdf": _relative(pdf_path),
            "profil": profile.model_dump(),  # metadata kolonu olmayan alanlar JSON metadata'ya gider
        },
    )
    get_profile_store().add_documents([profile_doc], ids=[doc_id(hoca_id)])

    chunk_store = get_chunk_store()
    old_ids = chunk_store.get(where={"hoca_id": hoca_id}, include=[])["ids"]
    if old_ids:
        chunk_store.delete(ids=old_ids)
    chunk_store.add_documents(chunks, ids=[doc_id(hoca_id, c.metadata["sira"]) for c in chunks])


def main() -> int:
    ap = argparse.ArgumentParser(description="Akademisyen CV'lerini indeksler.")
    ap.add_argument("input", type=Path, nargs="?", default=get_settings().cv_pdf_dir,
                    help="CV PDF dosyasi veya klasoru")
    ap.add_argument("--recreate", action="store_true", help="Vektor tablolarini silip yeniden olusturur")
    ap.add_argument("--concurrency", type=int, default=8, help="Paralel LLM profil cagrisi sayisi")
    ap.add_argument("--save", type=Path, help="Indekslerken ara ciktilari bu klasore kaydeder")
    ap.add_argument("--dump", type=Path, help="DB'ye yazmadan ara ciktilari bu klasore kaydeder (LLM cagrilmaz)")
    args = ap.parse_args()

    pdfs = collect_pdfs(args.input)
    if not pdfs:
        logger.error("PDF bulunamadi: %s", args.input)
        return 1

    prepared = [(p, *prepare_cv(p)) for p in pdfs]

    if args.dump:
        for p, doc, cv, sections in prepared:
            save_outputs(output_dir_for(p, args.input, args.dump), p, doc, cv, sections, _existing_profile(p.stem))
        logger.info("%d CV %s klasorune yazildi", len(pdfs), args.dump)
        return 0

    init_tables(recreate=args.recreate)

    # LLM profil ozetleri paralel (LangChain batch); hatali olanlar exception olarak doner
    profiles = profile_chain.batch(
        [{"cv": format_sections(sections)} for _, _, _, sections in prepared],
        config={"max_concurrency": args.concurrency},
        return_exceptions=True,
    )

    failed: list[str] = []
    for (p, doc, cv, sections), profile in zip(prepared, profiles):
        try:
            if isinstance(profile, Exception):
                raise profile
            chunks = build_chunks(p.stem, sections)
            write_cv(p, cv, profile, chunks)
            if args.save:
                save_outputs(output_dir_for(p, args.input, args.save), p, doc, cv, sections, profile.model_dump())
            logger.info("OK    %s (%d chunk)", p.stem, len(chunks))
        except Exception as exc:  # tek bir CV'nin hatasi tum indekslemeyi durdurmasin
            logger.error("HATA  %s: %s", p.stem, exc)
            failed.append(p.stem)

    apply_indexes()
    logger.info("Tamamlandi: %d basarili, %d hatali", len(pdfs) - len(failed), len(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
