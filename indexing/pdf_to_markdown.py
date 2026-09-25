"""CV PDF'lerini, front-matter (yapılandırılmış alanlar) + bölüm başlıklı
gövde metninden oluşan .md dosyalarına dönüştürür.

Çıktı: data/cv_markdown/<dosya_adi>.md
"""

import json
import re
from pathlib import Path

import pdfplumber
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CV_DIR = BASE_DIR / "data" / "fake_akademik_cvler"
MANIFEST_PATH = CV_DIR / "hocalar_manifest.json"
OUTPUT_DIR = BASE_DIR / "data" / "cv_markdown"

# CV'lerin PDF şablonundaki sabit bölüm başlıkları, görünüm sırasıyla.
SECTION_TITLES = {
    "ARAŞTIRMA VE UZMANLIK ALANLARI": "Araştırma ve Uzmanlık Alanları",
    "EĞİTİM BİLGİLERİ": "Eğitim Bilgileri",
    "AKADEMİK UNVANLAR": "Akademik Unvanlar",
    "İDARİ GÖREVLER": "İdari Görevler",
    "YAYINLAR": "Yayınlar",
    "PROJELER": "Projeler",
    "YÖNETİLEN TEZLER": "Yönetilen Tezler",
    "VERDİĞİ DERSLER": "Verdiği Dersler",
    "HAKEMLİK VE EDİTÖRLÜK": "Hakemlik ve Editörlük",
    "ÖDÜLLER": "Ödüller",
    "BİLİMSEL KURULUŞLARA ÜYELİKLER": "Bilimsel Kuruluşlara Üyelikler",
}
HEADER_KEY = "_header"

# Her sayfanın altında tekrar eden demo uyarısı, ör: "DEMO VERİSİ – ... Sayfa 2"
FOOTER_RE = re.compile(r"^DEMO VERİSİ.*Sayfa \d+$")


def extract_raw_text(pdf_path: Path) -> str:
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                if FOOTER_RE.match(line.strip()):
                    continue
                lines.append(line)
    return "\n".join(lines)


def split_sections(raw_text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {HEADER_KEY: []}
    current = HEADER_KEY
    for line in raw_text.split("\n"):
        stripped = line.strip()
        if stripped in SECTION_TITLES:
            current = stripped
            sections[current] = []
            continue
        sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def build_body(sections: dict[str, str]) -> str:
    parts = []
    header_block = sections.get(HEADER_KEY, "").strip()
    if header_block:
        parts.append(f"## Genel Bilgiler\n\n{header_block}")
    for raw_title, pretty_title in SECTION_TITLES.items():
        content = sections.get(raw_title, "").strip()
        if not content:
            continue
        parts.append(f"## {pretty_title}\n\n{content}")
    return "\n\n".join(parts)


def build_frontmatter(hoca: dict) -> str:
    data = {
        "id": hoca["id"],
        "unvan": hoca["unvan"],
        "ad": hoca["ad"],
        "soyad": hoca["soyad"],
        "universite": hoca["universite"],
        "fakulte": hoca["fakulte"],
        "bolum": hoca["bolum"],
        "ana_alan": hoca["ana_alan"],
        "ikincil_alan": hoca["ikincil_alan"],
        "uzmanlik": hoca["uzmanlik"],
        "email": hoca["email"],
        "kaynak_pdf": hoca["dosya"],
    }
    return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def convert_one(hoca: dict) -> Path:
    pdf_path = CV_DIR / hoca["dosya"]
    raw_text = extract_raw_text(pdf_path)
    sections = split_sections(raw_text)
    body = build_body(sections)
    frontmatter = build_frontmatter(hoca)

    md_content = f"---\n{frontmatter}---\n\n{body}\n"
    out_path = OUTPUT_DIR / f"{pdf_path.stem}.md"
    out_path.write_text(md_content, encoding="utf-8")
    return out_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for hoca in manifest:
        out_path = convert_one(hoca)
        print(f"yazildi: {out_path.relative_to(BASE_DIR)}")

    print(f"\nToplam {len(manifest)} CV, {OUTPUT_DIR.relative_to(BASE_DIR)} altina yazildi.")


if __name__ == "__main__":
    main()
