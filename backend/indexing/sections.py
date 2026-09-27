"""
CV Markdown'ini standart bolumlere ayirir ve baslik blogundan kimlik bilgilerini cikarir.

pymupdf4llm ciktisinda:
  - "# <Unvan Ad SOYAD>" ilk satirdir, altindaki paragraf universite/fakulte/bolum/e-posta icerir.
  - "## BOLUM ADI" standart bolumlerdir.
  - "### ..." alt basliklardir (Yayinlar A/B/C/D, Tezler Doktora/Yuksek Lisans). Ancak bazen
    sayfa kirilmasi yuzunden bir basligin devami ("### tasarımı") yanlislikla baslik olur;
    bilinmeyen alt basliklar icerige geri katilir.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from langchain_text_splitters import MarkdownHeaderTextSplitter

# Normalize edilmis "##" basligi -> standart bolum anahtari
SECTION_MAP = {
    "arastirma ve uzmanlik alanlari": "arastirma",
    "egitim bilgileri": "egitim",
    "akademik unvanlar": "unvanlar",
    "idari gorevler": "idari",
    "yayinlar": "yayinlar",
    "projeler": "projeler",
    "patentler": "patentler",
    "yonetilen tezler": "yonetilen_tezler",
    "verdigi dersler": "dersler",
    "hakemlik ve editorluk": "hakemlik",
    "oduller": "oduller",
    "bilimsel kuruluslara uyelikler": "uyelikler",
}

# Aramaya dahil edilen bolumler (sirasi chunk sirasini belirler)
SEARCHABLE_SECTIONS = ["arastirma", "egitim", "yayinlar", "projeler", "yonetilen_tezler", "dersler"]

SECTION_LABELS = {
    "arastirma": "Araştırma ve Uzmanlık Alanları",
    "egitim": "Eğitim",
    "yayinlar": "Yayınlar",
    "projeler": "Projeler",
    "yonetilen_tezler": "Yönetilen Tezler",
    "dersler": "Verdiği Dersler",
}

# Alt basliklar: yayin turleri "A." - "D." ile baslar, tez seviyeleri sabittir.
_KNOWN_SUBHEADING = re.compile(r"^([A-Z]\.\s|doktora$|yuksek lisans$)", re.IGNORECASE)

_UNVANLAR = [
    "Prof. Dr.", "Doç. Dr.", "Dr. Öğr. Üyesi", "Öğr. Gör. Dr.", "Öğr. Gör.",
    "Arş. Gör. Dr.", "Arş. Gör.", "Dr.",
]


def normalize(text: str) -> str:
    """Turkce karakterleri ASCII'ye indirger ve kucuk harfe cevirir (baslik eslemesi icin)."""
    text = text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.replace("*", "")).strip()


@dataclass
class Header:
    unvan: str | None
    ad_soyad: str
    universite: str | None = None
    fakulte: str | None = None
    bolum: str | None = None
    email: str | None = None


@dataclass
class ParsedCV:
    header: Header
    # bolum anahtari -> [(alt baslik veya None, ham metin)]
    sections: dict[str, list[tuple[str | None, str]]] = field(default_factory=dict)


def _parse_header(title_line: str, body: str) -> Header:
    name = title_line.lstrip("#").replace("*", "").strip()
    unvan = next((u for u in _UNVANLAR if name.startswith(u + " ")), None)
    ad_soyad = name[len(unvan):].strip() if unvan else name

    header = Header(unvan=unvan, ad_soyad=ad_soyad)
    flat = " ".join(body.replace("*", "").split())
    if m := re.search(r"E-posta:\s*(\S+@\S+?)(?:\s|·|$)", flat):
        header.email = m.group(1)
    affiliation = flat.split("E-posta:")[0]
    parts = [p.strip() for p in affiliation.split("·") if p.strip()]
    header.universite, header.fakulte, header.bolum = (parts + [None, None, None])[:3]
    return header


_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "ad"), ("##", "bolum"), ("###", "alt")],
    strip_headers=True,
)


def split_sections(markdown: str) -> ParsedCV:
    docs = _HEADER_SPLITTER.split_text(markdown)

    # Baslik blogu: "# <Unvan Ad>" altinda, ilk "##" oncesindeki paragraf
    head = next(d for d in docs if "ad" in d.metadata)
    header = _parse_header(head.metadata["ad"], head.page_content if "bolum" not in head.metadata else "")

    cv = ParsedCV(header=header)
    for doc in docs:
        if "bolum" not in doc.metadata:
            continue
        key = SECTION_MAP.get(normalize(doc.metadata["bolum"]), "diger")
        sub = doc.metadata.get("alt")
        parts = cv.sections.setdefault(key, [])
        if sub and not _KNOWN_SUBHEADING.match(normalize(sub)) and not _KNOWN_SUBHEADING.match(sub) and parts:
            # Sayfa kirilmasindan dogan sahte "###" basligi: onceki parcanin devami
            prev_sub, prev_text = parts[-1]
            parts[-1] = (prev_sub, f"{prev_text} {sub}\n{doc.page_content}")
        else:
            parts.append((sub, doc.page_content))
    return cv
