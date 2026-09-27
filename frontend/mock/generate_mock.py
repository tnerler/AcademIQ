"""Demo için mock API verisi üretir.

data/ klasöründeki sahte CV ve ilan PDF'lerini okuyup API sözleşmesindeki
şekillere uygun JSON dosyaları yazar:

  cvs.json      -> HocaDetay[]   (GET /api/cvs ve GET /api/cvs/{id})
  matches.json  -> {ilan_id: MatchResponse}  (POST /api/match)
  ilanlar.json  -> pasif Proje İlanları ekranı için örnek liste

Skorlar ve gerekçeler basit kelime örtüşmesiyle üretilir; gerçek hibrit
arama ve LLM çıktısını temsil etmez, sadece arayüzü beslemek içindir.

Çalıştırma (repo kökünden):
    pip install pypdf
    python frontend/mock/generate_mock.py
"""

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = Path(__file__).resolve().parent

SECTION_HEADERS = {
    "ARAŞTIRMA VE UZMANLIK ALANLARI": "arastirma",
    "EĞİTİM BİLGİLERİ": "egitim",
    "AKADEMİK UNVANLAR": None,
    "İDARİ GÖREVLER": None,
    "YAYINLAR": "yayinlar",
    "PROJELER": "projeler",
    "PATENTLER": None,
    "YÖNETİLEN TEZLER": "yonetilen_tezler",
    "VERDİĞİ DERSLER": "dersler",
    "HAKEMLİK VE EDİTÖRLÜK": None,
    "ÖDÜLLER": None,
    "BİLİMSEL KURULUŞLARA ÜYELİKLER": None,
}

BOLUM_ETIKETI = {
    "arastirma": "Araştırma alanları",
    "egitim": "Eğitim",
    "yayinlar": "Yayınlar",
    "projeler": "Projeler",
    "yonetilen_tezler": "Yönetilen tezler",
    "dersler": "Dersler",
}

STOPWORDS = {
    "için", "ile", "bir", "ve", "veya", "olan", "olarak", "bu", "da", "de", "en",
    "alanında", "amacıyla", "yaklaşımların", "geliştirilmesi", "çözümler", "çerçeve",
    "sistem", "tasarımı", "the", "and", "for", "of", "in", "a", "an", "on", "from",
    "study", "comparative", "case", "challenges", "opportunities", "turkey", "proje",
    "projenin", "amaçlanmaktadır", "hedeflenmektedir", "geliştirilecektir", "alanlarında",
    "deneyim", "deneyimi", "aranmaktadır", "yürütücüden", "beklenmektedir", "üzerinde",
    "yeni", "nesil", "yöntemleri", "yöntemlerle", "tabanlı", "destekli",
}

CITIES = ["Ankara", "İstanbul", "İzmir", "Bursa", "Konya", "Kayseri", "Antalya",
          "Eskişehir", "Trabzon", "Erzurum", "Samsun", "Adana", "Gaziantep", "Sakarya"]


def tr_lower(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def tokens(text):
    words = re.findall(r"[a-zçğıöşüâîû]+", tr_lower(text))
    return {w[:5] for w in words if len(w) > 2 and w not in STOPWORDS}


def pdf_text(path):
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [
        ln for ln in text.splitlines()
        if not ln.startswith("DEMO VERİSİ") and not re.fullmatch(r"\s*Sayfa \d+\s*", ln)
    ]
    return "\n".join(lines)


def numbered_items(block):
    """'1. ...' ile başlayan satırlardan maddeleri çıkarır (sarılmış satırları birleştirir)."""
    items = re.split(r"\n\s*\d{1,2}\.\s", "\n" + block)
    return [re.sub(r"\s+", " ", it).strip() for it in items[1:] if it.strip()]


def split_sections(text):
    sections, current = {}, None
    for line in text.splitlines():
        key = line.strip()
        if key in SECTION_HEADERS:
            current = key
            sections[current] = []
        elif current:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def parse_cv(path):
    text = pdf_text(path)
    sec = split_sections(text)
    cv = {"yayinlar": [], "projeler": [], "yonetilen_tezler": [], "dersler": [], "egitim": []}

    for item in numbered_items(sec.get("YAYINLAR", "")):
        m = re.search(r"\(\d{4}\)\.\s+(.+?)\.\s", item + " ")
        if m:
            cv["yayinlar"].append(m.group(1).strip())

    for item in numbered_items(sec.get("PROJELER", "")):
        # Başlık, program adından önceki kısımdır: program adı "TÜBİTAK", "Bilimsel", "Sanayi" ... ile başlar.
        m = re.match(r"(.+?)\s+(TÜBİTAK|Bilimsel Araştırma|Sanayi|Horizon|Kalkınma|AB |Avrupa|SSB|Savunma)", item)
        cv["projeler"].append((m.group(1) if m else item.split(" · ")[0]).strip())

    for item in numbered_items(sec.get("YÖNETİLEN TEZLER", "")):
        m = re.search(r"\(\d{4}\)\.\s+(.+?)\.?$", item)
        if m:
            cv["yonetilen_tezler"].append(m.group(1).replace(" Yüksek Lisans", "").strip().rstrip("."))

    dersler = re.sub(r"\s+", " ", sec.get("VERDİĞİ DERSLER", "")).strip()
    cv["dersler"] = [d.strip() for d in dersler.split("·") if d.strip()]

    for m in re.finditer(r"Tez:\s*(.+)", sec.get("EĞİTİM BİLGİLERİ", "")):
        cv["egitim"].append(m.group(1).strip())

    return cv


METHOD_PATTERNS = [
    r"^(.+?):\s+(.+?) bir çerçeve$",
    r"^(.+?) alanında (.+?) çözümler$",
    r"^(.+?) için (.+?) yaklaşımların geliştirilmesi$",
    r"^(.+?) amacıyla (.+?) bir sistem tasarımı$",
]


def build_profile(hoca, cv):
    topics, methods = Counter(), Counter()
    for title in cv["projeler"] + cv["yonetilen_tezler"] + cv["egitim"]:
        for pat in METHOD_PATTERNS:
            m = re.match(pat, title)
            if m:
                topics[m.group(1)] += 1
                methods[m.group(2)] += 1
                break
    yontemler = [m for m, _ in methods.most_common(5)]
    anahtar = [t for t, _ in topics.most_common(5)]
    ad_soyad = f"{hoca['ad']} {hoca['soyad']}"
    ozet = (
        f"{hoca['bolum']} alanında çalışan {hoca['unvan']} {ad_soyad}; "
        f"{', '.join(hoca['uzmanlik'][:3])} konularına odaklanıyor. "
    )
    if yontemler:
        ozet += f"Çalışmalarında ağırlıklı olarak {', '.join(yontemler[:3])} yöntemlerini kullanıyor. "
    ozet += (
        f"CV'sinde {len(cv['yayinlar'])} yayın, {len(cv['projeler'])} proje ve "
        f"{len(cv['yonetilen_tezler'])} yönetilen tez bulunuyor."
    )
    return {
        "arastirma_alanlari": hoca["uzmanlik"],
        "yontemler": yontemler,
        "anahtar_kelimeler": anahtar,
        "ozet_metni": ozet,
    }


def clean_aciklama(text):
    """Manifest açıklamasındaki test notlarını (kontrol örneği vb.) ayıklar."""
    sentences = re.split(r"(?<=\.)\s+", text)
    skip = ("kontrol örneği", "benzerlik skoru", "uygun aday bulunduğundan", "hoca havuzunda")
    return " ".join(s for s in sentences if not any(k in s for k in skip))


def parse_ilan_meta(text, fmt):
    flat = re.sub(r"\s+", " ", text)
    meta = {"son_basvuru": None, "butce": None, "sure": None, "yer": None, "basvuru_kosullari": []}

    m = re.search(r"(\d{1,3}(?:\.\d{3})+)\s*TL", flat)
    if m:
        meta["butce"] = f"{m.group(1)} TL"
    m = re.search(r"(\d+)\s*ay\b", flat)
    if m:
        meta["sure"] = f"{m.group(1)} ay"

    if fmt == "duz_metin":
        m = re.search(r"Proje (\S+) ilinde", flat)
        if m:
            meta["yer"] = m.group(1)
        block = re.search(r"Başvuru Koşulları(.+?)\s4\.", flat)
        if block:
            meta["basvuru_kosullari"] = [
                k.strip() for k in block.group(1).split("•") if k.strip()
            ]
    else:
        after = flat[m.end():] if m else flat
        for city in CITIES:
            if city in after.split("Adres")[0]:
                meta["yer"] = city
                break
        block = re.search(r"(En az .+?)\s\*Başvuru", flat)
        if block:
            parts = re.split(r"(?<=[a-zçğıöşü]{3})\.\s+", block.group(1))
            meta["basvuru_kosullari"] = [p.strip().rstrip(".") + "." for p in parts if p.strip()]
    return meta


def score_hoca(ilan, hoca, cv, query):
    gerekli = ilan["gerekli_uzmanlik"]
    uz_lower = {tr_lower(u) for u in hoca["uzmanlik"]}
    exact = [g for g in gerekli if tr_lower(g) in uz_lower]
    uz_tokens = tokens(" ".join(hoca["uzmanlik"]))
    partial = [g for g in gerekli if g not in exact and tokens(g) & uz_tokens]

    scored = []
    for bolum in ("yayinlar", "projeler", "yonetilen_tezler", "dersler", "egitim"):
        for item in cv[bolum]:
            t = tokens(item)
            hit = t & query
            if hit:
                scored.append((len(hit) / math.sqrt(len(t) or 1), bolum, item))
    scored.sort(reverse=True)
    item_score = sum(s for s, _, _ in scored[:10])

    raw = 3.0 * len(exact) + 1.0 * len(partial) + 0.6 * item_score
    return raw, exact, partial, scored


def build_kanitlar(exact, partial, scored, best_item):
    kanitlar = []
    if exact or partial:
        kanitlar.append({
            "bolum": "arastirma",
            "bolum_etiketi": BOLUM_ETIKETI["arastirma"],
            "maddeler": exact + partial,
            "skor": round(min(99.0, 70 + 8 * len(exact) + 3 * len(partial)), 1),
        })
    by_bolum = {}
    for s, bolum, item in scored:
        by_bolum.setdefault(bolum, []).append((s, item))
    for bolum, items in by_bolum.items():
        top = items[:3]
        kanitlar.append({
            "bolum": bolum,
            "bolum_etiketi": BOLUM_ETIKETI[bolum],
            "maddeler": [it for _, it in top],
            "skor": round(min(98.0, 35 + 60 * top[0][0] / best_item), 1),
        })
    kanitlar.sort(key=lambda k: k["skor"], reverse=True)
    return kanitlar[:4]


def build_gerekce(hoca, ad_soyad, exact, partial, gerekli, kanitlar):
    unvan = hoca["unvan"]
    n = {k["bolum"]: len(k["maddeler"]) for k in kanitlar}
    parts = []
    if exact:
        parts.append(
            f"{unvan} {ad_soyad}, {', '.join(exact[:3])} alanlarındaki uzmanlığıyla "
            f"ilanın aradığı yetkinliklerle doğrudan örtüşüyor."
        )
    elif partial:
        parts.append(
            f"{unvan} {ad_soyad}, {', '.join(partial[:2])} konularına yakın alanlarda "
            f"çalışıyor; ilanla dolaylı bir örtüşme var."
        )
    else:
        parts.append(
            f"{unvan} {ad_soyad} için doğrudan eşleşen bir uzmanlık alanı bulunmuyor; "
            f"CV'deki bazı çalışmalar ilanın konusuyla kısmen ilişkili."
        )
    ev = []
    if n.get("projeler"):
        ev.append(f"{n['projeler']} proje")
    if n.get("yayinlar"):
        ev.append(f"{n['yayinlar']} yayın")
    if n.get("yonetilen_tezler"):
        ev.append(f"{n['yonetilen_tezler']} yönetilen tez")
    if ev:
        parts.append(f"CV'sinde ilanla ilişkili {' ve '.join(ev)} bulunuyor.")
    missing = [g for g in gerekli if g not in exact and g not in partial]
    if missing and (exact or partial):
        parts.append(f"{missing[0]} konusunda doğrudan bir çalışması görünmüyor.")
    return " ".join(parts)


def main():
    hocalar = json.loads((DATA / "fake_akademik_cvler" / "hocalar_manifest.json").read_text(encoding="utf-8"))
    with open(DATA / "ilanlar_manifest.csv", encoding="utf-8-sig", newline="") as f:
        ilanlar = list(csv.DictReader(f))

    cvs, parsed = [], {}
    for h in sorted(hocalar, key=lambda x: x["id"]):
        cv = parse_cv(DATA / "fake_akademik_cvler" / h["dosya"])
        hid = Path(h["dosya"]).stem
        parsed[hid] = (h, cv)
        cvs.append({
            "id": hid,
            "unvan": h["unvan"],
            "ad_soyad": f"{h['ad']} {tr_upper(h['soyad'])}",
            "universite": h["universite"],
            "fakulte": h["fakulte"],
            "bolum": h["bolum"],
            "ana_alan": h["ana_alan"] or None,
            "arastirma_alanlari": h["uzmanlik"],
            "email": h["email"],
            "profil": build_profile(h, cv),
            "pdf_url": f"/api/cvs/{hid}/pdf",
        })
    ozet_keys = ("id", "unvan", "ad_soyad", "universite", "fakulte", "bolum", "ana_alan", "arastirma_alanlari")
    ozet_by_id = {c["id"]: {k: c[k] for k in ozet_keys} for c in cvs}

    matches, ilan_list = {}, []
    for il in ilanlar:
        il["gerekli_uzmanlik"] = [g.strip() for g in il["gerekli_uzmanlik"].split(";") if g.strip()]
        aciklama = clean_aciklama(il["aciklama"])
        text = pdf_text(DATA / il["dosya"])
        meta = parse_ilan_meta(text, il["format"])
        y, mo, d = il["tarih"].split("-")
        meta["son_basvuru"] = f"{d}.{mo}.{y}"

        query = tokens(" ".join(il["gerekli_uzmanlik"]) + " " + il["baslik"] + " " + aciklama)
        rows = []
        for hid, (h, cv) in parsed.items():
            raw, exact, partial, scored = score_hoca(il, h, cv, query)
            rows.append((raw, hid, exact, partial, scored))
        rows.sort(key=lambda r: r[0], reverse=True)
        top = rows[:5]
        best = top[0][0] or 1
        best_item = max((r[4][0][0] for r in top if r[4]), default=1)

        sonuclar = []
        for i, (raw, hid, exact, partial, scored) in enumerate(top, start=1):
            h, _ = parsed[hid]
            kanitlar = build_kanitlar(exact, partial, scored, best_item)
            sonuclar.append({
                "sira": i,
                "hoca": ozet_by_id[hid],
                "skor": round(100 * raw / best, 1),
                "gerekce": build_gerekce(h, ozet_by_id[hid]["ad_soyad"], exact, partial,
                                         il["gerekli_uzmanlik"], kanitlar),
                "kanitlar": kanitlar,
            })

        matches[il["id"]] = {
            "ilan": {
                "baslik": il["baslik"],
                "kurum": il["kurum"],
                "konu": f"{il['alan']}: {il['baslik']}",
                "amac_kapsam": aciklama,
                "aranan_uzmanliklar": il["gerekli_uzmanlik"],
                "anahtar_kelimeler": il["gerekli_uzmanlik"] + [il["alan"]],
                "sorgu_metni": f"{', '.join(il['gerekli_uzmanlik'])} alanlarında uzman akademisyen. {aciklama}",
                "meta": meta,
            },
            "sonuclar": sonuclar,
        }

        kurum = il["kurum"]
        ilan_list.append({
            "id": il["id"],
            "baslik": il["baslik"],
            "kurum": kurum.split(" - ")[0],
            "program": kurum,
            "alan": il["alan"],
            "gerekli_uzmanlik": il["gerekli_uzmanlik"],
            "son_basvuru": il["tarih"],
            "kaynak": "TÜBİTAK" if kurum.startswith("TÜBİTAK") else
                      ("Elle yüklendi" if il["format"] == "duz_metin" else "Diğer site"),
            "dosya": Path(il["dosya"]).name,
        })

    def dump(name, obj):
        (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    dump("cvs.json", cvs)
    dump("matches.json", matches)
    dump("ilanlar.json", ilan_list)

    print(f"{len(cvs)} CV, {len(matches)} eşleştirme, {len(ilan_list)} ilan yazıldı.")
    for iid, mr in matches.items():
        names = ", ".join(f"{s['hoca']['ad_soyad']}({s['skor']:.0f})" for s in mr["sonuclar"])
        print(f"  {iid}: {names}")


if __name__ == "__main__":
    main()
