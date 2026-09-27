"""
CV bolumlerini aramaya uygun hale getirir: yalnizca akademik icerik (baslik/konu) kalir.

  - Yayinlar / Yonetilen Tezler : yazar/ogrenci adlari, yil, dergi/kongre, cilt/sayfa atilir; sadece baslik
  - Projeler                    : destek programi, gorev, tarih, butce, durum atilir; sadece baslik
  - Egitim                      : derece + alan + tez basligi; universite ve yil atilir
  - Arastirma alanlari, dersler : "·" ile ayrilmis liste olarak alinir

Her fonksiyon madde listesi dondurur; chunker bu maddeleri bolum sinirinda birlestirir.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_FOOTER = re.compile(r"_?DEMO VERİSİ\s*–[^_\n]*?(?:ilgisi yoktur\.|temsil etmez\.)_?(?:\s*_?Sayfa\s+\d+_?)?")
_PAGE = re.compile(r"_?Sayfa\s+\d+_?")

# Proje maddesinde basligin bittigi yer: destek programi adi
_PROGRAM = re.compile(
    r"\s(?:-\s+)?(?:TÜBİTAK|Sanayi İşbirliği|Horizon|Bilimsel Araştırma Projeleri|BAP\b|Kalkınma Ajansı|AB\s|"
    r"ERC\b|COST\b|Erasmus|SAN-TEZ|KOSGEB|TEYDEB)"
)
_YEAR = re.compile(r"\(\d{4}[a-z]?\)\.?\s*")


def flatten(text: str) -> str:
    """Footer'lari, markdown vurgu isaretlerini ve satir kirilmalarini temizler."""
    text = _FOOTER.sub(" ", text)
    text = _PAGE.sub(" ", text)
    text = text.replace("**", "")
    text = re.sub(r"(?<!\w)_|_(?!\w)", "", text)  # italik isaretleri (kelime icindeki _'ye dokunmaz)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)  # splitter'in bolmedigi sahte "####" basliklari
    text = " ".join(text.split())
    return re.sub(r"\s+([,.;:])", r"\1", text)


def split_numbered(text: str) -> list[str]:
    """'1. ... 2. ... 3. ...' seklindeki duz metni maddelere ayirir.

    Sadece sirali numaralar (1, 2, 3, ...) madde baslangici sayilir; boylece
    '19(10), 4695.' gibi sayilar yanlislikla bolme noktasi olmaz.
    """
    items, expected, start = [], 1, None
    for m in re.finditer(r"(?:^|(?<=\s))(\d{1,3})\.\s+", text):
        if int(m.group(1)) != expected:
            continue
        if start is not None:
            items.append(text[start : m.start()].strip())
        start, expected = m.end(), expected + 1
    if start is not None:
        items.append(text[start:].strip())
    return [i for i in items if i]


def _first_sentence(text: str) -> str:
    """Basligi, ardindan gelen dergi/kitap/kongre adindan ayirir (ilk '. ' ya da metin sonu)."""
    m = re.search(r"[.?!](?:\s|$)", text)
    title = text[: m.start()] if m else text
    return title.strip(" .")


def clean_list(text: str) -> list[str]:
    """'A · B · C' listelerini maddelere ayirir (arastirma alanlari, dersler)."""
    return [p.strip() for p in flatten(text).split("·") if p.strip()]


def clean_publications(text: str) -> list[str]:
    """Yayin ve yonetilen tez maddelerinden yalnizca basligi alir: '<adlar> (YYYY). <Baslik>. <Dergi>...'"""
    titles = []
    for item in split_numbered(flatten(text)):
        m = _YEAR.search(item)
        if not m:
            logger.debug("Yil bulunamadi, madde oldugu gibi alindi: %s", item[:80])
            titles.append(_first_sentence(item))
            continue
        titles.append(_first_sentence(item[m.end() :]))
    return [t for t in titles if t]


def clean_projects(text: str) -> list[str]:
    """Proje maddelerinden yalnizca basligi alir: '<Baslik> <Program> · Gorev: ... · Butce: ...'"""
    titles = []
    for item in split_numbered(flatten(text)):
        head = item.split("· Görev")[0]
        m = _PROGRAM.search(head)
        title = head[: m.start()] if m else head
        titles.append(title.strip(" .·-"))
    return [t for t in titles if t]


_DEGREE = re.compile(r"(Doktora|Yüksek Lisans|Lisans|Tıpta Uzmanlık|Sanatta Yeterlik)\s*,\s*")


def clean_education(text: str) -> list[str]:
    """'Doktora, <Universite>, <Alan> (YYYY) Tez: <Baslik>' -> 'Doktora - <Alan> - Tez: <Baslik>'"""
    flat = flatten(text)
    starts = list(_DEGREE.finditer(flat))
    items = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(flat)
        body = flat[m.end() : end]
        tez = None
        if "Tez:" in body:
            body, tez = body.split("Tez:", 1)
            tez = tez.strip(" .")
        body = re.sub(r"\(\d{4}\)", "", body).strip(" ,.")
        alan = body.rsplit(",", 1)[-1].strip() if "," in body else body  # universite atilir
        items.append(f"{m.group(1)} - {alan}" + (f" - Tez: {tez}" if tez else ""))
    return items


CLEANERS = {
    "arastirma": clean_list,
    "dersler": clean_list,
    "egitim": clean_education,
    "yayinlar": clean_publications,
    "yonetilen_tezler": clean_publications,
    "projeler": clean_projects,
}


def clean_section(key: str, parts: list[tuple[str | None, str]]) -> list[str]:
    """Bir bolumun tum alt basliklarini temizleyip tek madde listesi dondurur."""
    cleaner = CLEANERS[key]
    items: list[str] = []
    for _sub, text in parts:
        items.extend(cleaner(text))
    # Ayni baslik birden fazla alt bolumde gecebilir (bildiri + makale): tekrarlari at
    return list(dict.fromkeys(items))
