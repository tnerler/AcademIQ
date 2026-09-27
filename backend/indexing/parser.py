"""
PyMuPDF (pymupdf4llm) ile PDF dosyalarini (akademisyen CV'leri, proje ilanlari vb.)
parse eder ve JSON ve/veya Markdown olarak kaydeder.

JSON ciktisi:
  - metadata (baslik, yazar vb.)
  - her sayfanin duz metni, Markdown hali ve tablolari
  - tum dokumanin birlestirilmis temiz metni ve Markdown hali
  - metin icermeyen (muhtemelen taranmis) sayfalarin listesi

Markdown ciktisi pymupdf4llm ile uretilir: basliklar, tablolar, listeler ve
cok sutunlu duzenler otomatik olarak tespit edilir. Metin icermeyen (taranmis)
sayfalar, sistemde Tesseract kuruluysa otomatik olarak OCR ile okunur.

Cikti yapisi (her PDF icin kendi adinda bir klasor):
  parsed/cvs/
    ayse_yilmaz/
      ayse_yilmaz.json
      ayse_yilmaz.md
    muhendislik/            <- girdideki alt klasorler korunur
      mehmet_kaya/
        mehmet_kaya.json
        mehmet_kaya.md

Kullanim:
  python pdf_parser.py data/cvs -o parsed/cvs                  # JSON + MD (varsayilan)
  python pdf_parser.py data/cvs -o parsed/cvs --format md      # sadece MD
  python pdf_parser.py ilan.pdf -o parsed/ilanlar --format json
  python pdf_parser.py data/cvs -o parsed/cvs --no-ocr         # OCR kapali (daha hizli)

Gereksinim:
  pip install pymupdf pymupdf4llm

Not: PyMuPDF AGPL lisanslidir. Kapali kaynak ticari dagitimda ticari lisans gerekir.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf
import pymupdf4llm

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("pdf_parser")

# PyMuPDF'in konsola bastigi bilgi mesajlarini ("Using Tesseract..." vb.) DEBUG seviyesine indirir
pymupdf.set_messages(pylogging=True, pylogging_level=logging.DEBUG)

# Bir sayfada bu kadar karakterden az metin varsa taranmis (goruntu) sayfa sayilir.
MIN_CHARS_FOR_TEXT_PAGE = 20


@dataclass
class PageResult:
    page_number: int
    text: str
    markdown: str
    tables: list[list[list[str]]] = field(default_factory=list)
    is_empty: bool = False


@dataclass
class DocumentResult:
    source_file: str
    metadata: dict
    page_count: int
    pages: list[PageResult]
    full_text: str
    markdown: str
    empty_pages: list[int]


# ---------------------------------------------------------------------------
# Temizleme
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """PDF'ten gelen metindeki yaygin bozukluklari duzeltir."""
    if not text:
        return ""

    # Ligatur karakterlerini acar (ﬁ -> fi vb.)
    ligatures = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
    for lig, repl in ligatures.items():
        text = text.replace(lig, repl)

    # Satir sonunda tire ile bolunmus kelimeleri birlestirir: "ogren-\nme" -> "ogrenme"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Madde isaretlerini standartlastirir
    text = re.sub(r"^[\u2022\u25cf\u25aa\u25e6\uf0b7]\s*", "- ", text, flags=re.MULTILINE)

    # Fazla bosluklari temizler
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def clean_markdown(md: str) -> str:
    """Markdown'daki ligatur ve fazla bos satirlari temizler (tablo hizalamasina dokunmaz)."""
    ligatures = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
    for lig, repl in ligatures.items():
        md = md.replace(lig, repl)
    md = re.sub(r"(\w)-\n(\w)", r"\1\2", md)
    # Basliklarin icindeki kalin isaretlerini kaldirir: "# **Egitim**" -> "# Egitim"
    md = re.sub(r"^(#{1,6} )(.*)$", lambda m: m.group(1) + m.group(2).replace("**", ""), md, flags=re.MULTILINE)
    # Satir sonlarindaki bosluklari temizler
    md = re.sub(r"[ \t]+$", "", md, flags=re.MULTILINE)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def clean_table(table: list[list]) -> list[list[str]]:
    """Tablo hucrelerindeki None degerlerini ve satir iclerindeki kirilmalari temizler."""
    cleaned = []
    for row in table:
        cleaned_row = [re.sub(r"\s+", " ", cell).strip() if cell else "" for cell in row]
        if any(cleaned_row):  # tamamen bos satirlari atla
            cleaned.append(cleaned_row)
    return cleaned


# ---------------------------------------------------------------------------
# Dokuman isleme
# ---------------------------------------------------------------------------

def extract_tables(page: pymupdf.Page) -> list[list[list[str]]]:
    tables = []
    try:
        for table in page.find_tables().tables:
            data = clean_table(table.extract())
            if data:
                tables.append(data)
    except Exception as exc:  # tablo tespiti basarisiz olursa sayfanin geri kalani islenmeye devam etsin
        logger.debug("Tablo cikarilamadi (sayfa %d): %s", page.number + 1, exc)
    return tables


def parse_pdf(path: Path, use_ocr: bool = True) -> DocumentResult:
    with pymupdf.open(path) as doc:
        metadata = {k: v for k, v in (doc.metadata or {}).items() if v}

        # page_chunks=True -> her sayfa icin ayri Markdown dondurur.
        # use_ocr=True -> metni olmayan (taranmis) sayfalar Tesseract kuruluysa OCR ile okunur.
        md_chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=False, use_ocr=use_ocr)

        pages = []
        for page, chunk in zip(doc, md_chunks):
            # sort=True: metni sayfadaki okuma sirasina gore (yukaridan asagi, soldan saga) dizer
            text = clean_text(page.get_text("text", sort=True))
            markdown = clean_markdown(chunk.get("text", ""))
            tables = extract_tables(page)
            # OCR metni yalnizca Markdown'da yer alir; bu yuzden ikisine de bakilir
            is_empty = len(text) < MIN_CHARS_FOR_TEXT_PAGE and len(markdown) < MIN_CHARS_FOR_TEXT_PAGE and not tables
            pages.append(PageResult(
                page_number=page.number + 1,
                text=text,
                markdown=markdown,
                tables=tables,
                is_empty=is_empty,
            ))

    empty_pages = [p.page_number for p in pages if p.is_empty]
    if empty_pages:
        logger.warning(
            "%s: %d sayfada metin bulunamadi (taranmis olabilir; Tesseract kurulu mu?): %s",
            path.name, len(empty_pages), empty_pages,
        )

    return DocumentResult(
        source_file=path.name,
        metadata=metadata,
        page_count=len(pages),
        pages=pages,
        full_text="\n\n".join(p.text for p in pages if p.text),
        markdown="\n\n".join(p.markdown for p in pages if p.markdown),
        empty_pages=empty_pages,
    )


# ---------------------------------------------------------------------------
# Dosya/klasor islemleri
# ---------------------------------------------------------------------------

def collect_pdfs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".pdf" else []
    return sorted(p for p in input_path.rglob("*") if p.suffix.lower() == ".pdf")


def output_dir_for(pdf_path: Path, input_root: Path, output_root: Path) -> Path:
    """Her PDF icin, PDF'in adini tasiyan bir klasor dondurur.

    Girdi klasorundeki alt klasor yapisi korunur, boylece kategoriler ciktida da kalir:
      data/cvs/muhendislik/ayse.pdf -> parsed/muhendislik/ayse/ayse.json + ayse.md
    """
    if input_root.is_file():
        return output_root / pdf_path.stem
    relative_parent = pdf_path.parent.relative_to(input_root)
    return output_root / relative_parent / pdf_path.stem


def main() -> int:
    parser = argparse.ArgumentParser(description="PyMuPDF ile PDF'leri parse edip JSON/Markdown olarak kaydeder.")
    parser.add_argument("input", type=Path, help="PDF dosyasi veya PDF'lerin bulundugu klasor")
    parser.add_argument("-o", "--output", type=Path, default=Path("parsed"), help="Cikti klasoru (varsayilan: parsed)")
    parser.add_argument("--format", choices=["json", "md", "both"], default="both",
                        help="Cikti formati (varsayilan: both)")
    parser.add_argument("--no-ocr", action="store_true", help="Taranmis sayfalar icin OCR'i kapatir (daha hizli)")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Girdi bulunamadi: %s", args.input)
        return 1

    pdfs = collect_pdfs(args.input)
    if not pdfs:
        logger.error("Hic PDF bulunamadi: %s", args.input)
        return 1

    success, failed = 0, []

    for pdf_path in pdfs:
        try:
            result = parse_pdf(pdf_path, use_ocr=not args.no_ocr)
            out_dir = output_dir_for(pdf_path, args.input, args.output)
            out_dir.mkdir(parents=True, exist_ok=True)
            if args.format in ("json", "both"):
                out = out_dir / f"{pdf_path.stem}.json"
                out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            if args.format in ("md", "both"):
                out = out_dir / f"{pdf_path.stem}.md"
                out.write_text(result.markdown + "\n", encoding="utf-8")
            logger.info("OK  %s -> %s/ (%d sayfa)", pdf_path.name, out_dir, result.page_count)
            success += 1
        except Exception as exc:  # bozuk/sifreli PDF'ler tum islemi durdurmasin
            logger.error("HATA  %s: %s", pdf_path.name, exc)
            failed.append(pdf_path.name)

    logger.info("Tamamlandi: %d basarili, %d hatali", success, len(failed))
    if failed:
        logger.info("Hatali dosyalar: %s", ", ".join(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())