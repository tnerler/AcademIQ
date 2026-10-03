"""
YOK Akademik (akademik.yok.gov.tr) uzerinden bir universitenin akademisyenlerini ceker.

Site bir WAF arkasinda: tarayici User-Agent'i + Referer + oturum cerezi olmadan istekler 418 ile
engelleniyor. Sayfalama linkleri oturuma bagli token icerdiginden URL uretilemez, linkler sirayla
takip edilir. Istekler arasi bekleme WAF'a takilmamak icin kasitli olarak uzun tutuldu.

Kullanim:
  uv run python -m backend.yok.scrape --liste     # sadece akademisyen listesini tara
  uv run python -m backend.yok.scrape             # liste + profil + sekmeler (yarida kalirsa devam eder)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
import httpx

logger = logging.getLogger("yok")

BASE = "https://akademik.yok.gov.tr"
ANA_SAYFA = f"{BASE}/AkademikArama/view/searchResultviewListAuthorAndUniversities.jsp"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
BEKLEME = (2.5, 4.0)  # saniye, istekler arasi rastgele

VARSAYILAN_UNIVERSITE = "PİRİ REİS ÜNİVERSİTESİ"
VARSAYILAN_CIKTI = Path("data/yok/pirireis_akademisyenler.json")


class Engellendi(RuntimeError):
    pass


class YokIstemci:
    def __init__(self) -> None:
        self.http = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"},
            follow_redirects=True,
            timeout=30,
        )
        self.referer = ANA_SAYFA
        self._son = 0.0

    def get(self, url: str) -> BeautifulSoup:
        bekle = random.uniform(*BEKLEME) - (time.monotonic() - self._son)
        if bekle > 0:
            time.sleep(bekle)
        r = self.http.get(urljoin(BASE, url), headers={"Referer": self.referer})
        self._son = time.monotonic()
        if r.status_code in (403, 418) or "Has Been Blocked" in r.text:
            raise Engellendi(f"WAF engeli ({r.status_code}): {url}")
        r.raise_for_status()
        self.referer = str(r.url)
        return BeautifulSoup(r.text, "html.parser")


def _metin(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


# --- Liste ----------------------------------------------------------------------

def universite_linki(soup: BeautifulSoup, universite: str) -> str:
    for a in soup.select('a[href*="AkademisyenArama?birim="]'):
        if universite in _metin(a):
            return a["href"]
    raise LookupError(f"Universite bulunamadi: {universite}")


def satir_ayristir(tr: Tag) -> dict:
    td = tr.find_all("td")[2]
    h6 = td.find_all("h6")
    birim = [p.strip() for p in _metin(h6[1]).split("/") if p.strip()] if len(h6) > 1 else []
    temel = td.select_one("span.label-success")
    bilim = td.select_one("span.label-primary")
    kelimeler = [
        _metin(a) for sp in td.find_all("span", recursive=False)
        if not sp.get("class") for a in sp.find_all("a")
    ]
    orcid = td.select_one("a.popoverData[data-content^='ORCID']")
    mail = tr.select_one('a[href^="mailto:"]')
    profil = td.select_one("h4 a")["href"]
    return {
        "author_id": parse_qs(urlparse(profil).query)["authorId"][0],
        "arastirmaci_id": tr["id"].removeprefix("authorInfo_"),
        "ad_soyad": _metin(td.find("h4")),
        "unvan": _metin(h6[0]) if h6 else "",
        "universite": birim[0] if birim else "",
        "fakulte": birim[1] if len(birim) > 1 else "",
        "bolum": birim[2] if len(birim) > 2 else "",
        "anabilim_dali_program": birim[3] if len(birim) > 3 else "",
        "temel_alan": _metin(temel),
        "bilim_alani": _metin(bilim),
        "anahtar_kelimeler": kelimeler,
        "eposta": mail["href"].removeprefix("mailto:") if mail else "",
        "orcid": orcid["data-content"].removeprefix("ORCID:") if orcid else "",
        "profil_url": urljoin(BASE, f"/AkademikArama/AkademisyenGorevOgrenimBilgileri?islem=direct&authorId="
                              + parse_qs(urlparse(profil).query)["authorId"][0]),
    }


def sonraki_sayfa(soup: BeautifulSoup) -> str | None:
    aktif = soup.select_one("ul.pagination li.active")
    sonraki = aktif.find_next_sibling("li") if aktif else None
    a = sonraki.find("a") if sonraki else None
    return a["href"] if a else None


def liste_tara(ist: YokIstemci, universite: str) -> tuple[int, list[dict]]:
    soup = ist.get(universite_linki(ist.get(ANA_SAYFA), universite))
    m = re.search(r"Arama sonucu:\s*(\d+)\s*sonuç", soup.get_text(" "))
    beklenen = int(m.group(1)) if m else -1
    kisiler: dict[str, dict] = {}
    sayfa = 1
    while True:
        satirlar = soup.select('tr[id^="authorInfo_"]')
        for tr in satirlar:
            k = satir_ayristir(tr)
            kisiler.setdefault(k["author_id"], k)
        logger.info("sayfa %d: %d satir (toplam %d/%d)", sayfa, len(satirlar), len(kisiler), beklenen)
        url = sonraki_sayfa(soup)
        if not url or not satirlar:
            break
        soup = ist.get(url)
        sayfa += 1
    return beklenen, list(kisiler.values())


# --- Profil ve sekmeler ------------------------------------------------------------

# Profil sayfasindaki menu id'leri -> ciktidaki alan adi. Sayfa basliklarina guvenilmez (ör. makale
# sayfasinin basligi "BILDIRILER" gorunuyor), menu id'leri sabit.
SEKMELER = {
    "booksMenu": "kitaplar",
    "articleMenu": "makaleler",
    "proceedingMenu": "bildiriler",
    "projectMenu": "projeler",
    "lessonMenu": "dersler",
    "thesisMenu": "yonetilen_tezler",
    "patentMenu": "patentler",
}


def _alan(metin: str, etiket: str) -> str:
    m = re.search(rf"{etiket}\s*:\s*(.*?)\s*(?:,\s*[A-ZÇĞİÖŞÜ][\wçğıöşü ]*:|,?\s*$)", metin)
    return m.group(1).strip(" ,") if m else ""


def _paneller(soup: BeautifulSoup) -> list[tuple[str, list[list[Tag]]]]:
    """Ders/tez sayfalarindaki akordiyon: (duzey, tablo satirlarinin hucreleri)."""
    return [
        (_metin(p.select_one(".panel-title")), [tr.find_all("td") for tr in p.select("tbody tr")])
        for p in soup.select("#accordion > .panel")
    ]


def profil_ayristir(soup: BeautifulSoup) -> dict:
    listeler = soup.select("ul.timeline")
    gorevler, ogrenim = [], []
    for ul in listeler:
        baslik = _metin(ul.select_one("li.time-label span.bg-default"))
        yil = ""
        for li in ul.find_all("li", recursive=False):
            if "time-label" in (li.get("class") or []):
                if not li.select_one(".bg-default"):
                    yil = _metin(li)
                continue
            item = li.select_one(".timeline-item")
            if not item:
                continue
            ortak = {"yil": yil, "kurum": _metin(item.find("h4")), "birim": _metin(item.find("h5"))}
            derece = _metin(li.select_one(".timeline-footer"))
            if baslik.startswith("Akademik"):
                gorevler.append({"unvan": derece, **ortak})
            elif baslik.startswith("Öğrenim"):
                tez = _metin(item.find("h6")).removeprefix("Tez adı:").strip()
                ogrenim.append({"derece": derece, **ortak, "tez_adi": tez})
    return {"akademik_gorevler": gorevler, "ogrenim": ogrenim}


def yayinlar_ayristir(soup: BeautifulSoup) -> list[dict]:
    """Makaleler ve bildiriler: 'Tumu' sekmesindeki tablo."""
    sonuc = []
    for tr in soup.select("#all tbody tr"):
        td = tr.find_all("td")[1]
        baslik = _metin(td.select_one("span.baslika"))
        etiket_p = td.find("p", recursive=False) and td.find_all("p", recursive=False)[-1]
        etiketler = [_metin(s) for s in etiket_p.select("span.label")] if etiket_p else []
        doi = etiket_p.find("a", href=True) if etiket_p else None
        yazarlar = [_metin(a) for a in td.select("a.popoverData")]
        # Makale: "..., Yayın Yeri:Dergi , 2020 <etiketler>"; bildiri: "(11.11.2020 ) , Yayın Yeri:Kongre"
        govde = _metin(td).removesuffix(_metin(etiket_p) if etiket_p else "").strip()
        m = re.search(r"Yayın Yeri\s*:\s*(.*?)(?:\s*,\s*(\d{4}))?$", govde)
        tarih = re.search(r"\((\d{2}\.\d{2}\.(\d{4}))", govde)
        sonuc.append({
            "baslik": baslik.strip(" ,"),
            "yil": (m and m.group(2)) or (tarih.group(2) if tarih else ""),
            "tarih": tarih.group(1) if tarih else "",
            "yayin_yeri": m.group(1).strip() if m else "",
            "etiketler": etiketler,
            "yazarlar": yazarlar,
            "doi": doi["href"] if doi else "",
        })
    return sonuc


def kitaplar_ayristir(soup: BeautifulSoup) -> list[dict]:
    sonuc = []
    for blok in soup.select("div.projects div.row > div[class*='col-lg-11']"):
        p = blok.find_all("p")
        detay = _metin(p[0]) if p else ""
        etiketler = [_metin(s) for s in p[1].select("span.label")] if len(p) > 1 else []
        yil = next((e for e in etiketler if re.fullmatch(r"\d{4}", e)), "")
        # "Bölüm Adı:<ad>, SOYAD AD, ..." -> bolum adi ilk "virgul + BUYUK HARFLI kelime"de biter
        bolum = re.search(r"Bölüm Adı\s*:\s*(.*?),\s*[A-ZÇĞİÖŞÜ]{2,}\b", detay)
        sonuc.append({
            "baslik": re.sub(r"^\d+\.\s*", "", _metin(blok.find("strong"))),
            "bolum_adi": bolum.group(1).strip() if bolum else "",
            "yil": yil,
            "yayin_yeri": _alan(detay, "Yayın Yeri"),
            "tur": [e for e in etiketler if e != yil],
            "detay": detay,
        })
    return sonuc


def projeler_ayristir(soup: BeautifulSoup, author_id: str) -> list[dict]:
    sonuc = []
    for proj in soup.select("div.projects div.projectmain"):
        kap = proj.parent
        rol = ""
        for a in proj.select("a.popoverData"):
            if author_id in a.get("href", ""):
                m = re.search(r"Projedeki Görev:\s*</b>\s*([^<]*)", a.get("data-content", ""))
                rol = m.group(1).strip() if m else ""
        tip = proj.select_one(".projectType")
        tip_metin = _metin(tip)
        etiketler = [_metin(s) for s in tip.select("span.label") if _metin(s)] if tip else []
        tarih = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})?", tip_metin)
        butce = re.search(r"\d{2}\.\d{2}\.\d{4}\s*,\s*([\d.,]+\s*[A-ZÇĞİÖŞÜ ]+)$", tip_metin)
        ozet = kap.select_one(".collapse p")
        sonuc.append({
            "baslik": _metin(proj.select_one("span.baslika")),
            "tur": etiketler[0] if etiketler else "",
            "durum": etiketler[1] if len(etiketler) > 1 else "",
            "baslangic": tarih.group(1) if tarih else "",
            "bitis": (tarih.group(2) or "") if tarih else "",
            "butce": butce.group(1).strip() if butce else "",
            "rol": rol,
            "ekip": [_metin(a) for a in proj.select("a.popoverData")],
            "proje_konusu": _metin(ozet),
        })
    return sonuc


def dersler_ayristir(soup: BeautifulSoup) -> list[dict]:
    """Ayni ders her donem tekrar listelenir; (duzey, ders adi) basina tekillestirilir."""
    dersler: dict[tuple[str, str], dict] = {}
    for duzey, satirlar in _paneller(soup):
        for td in satirlar:
            if len(td) < 4:
                continue
            donem, ad, dil = _metin(td[0]), _metin(td[1]), _metin(td[2])
            d = dersler.setdefault((duzey, ad.casefold()), {"ders_adi": ad, "duzey": duzey, "dil": dil, "donemler": []})
            if donem not in d["donemler"]:
                d["donemler"].append(donem)
    return list(dersler.values())


def tezler_ayristir(soup: BeautifulSoup) -> list[dict]:
    sonuc = []
    for duzey, satirlar in _paneller(soup):
        for td in satirlar:
            if len(td) < 4:
                continue
            link = td[2].find("a", href=True)
            sonuc.append({
                "tez_adi": _metin(td[2]),
                "duzey": duzey,
                "yil": _metin(td[0]),
                "hazirlayan": _metin(td[1]),
                "universite": _metin(td[3]),
                "url": link["href"] if link else "",
            })
    return sonuc


def patentler_ayristir(soup: BeautifulSoup) -> list[dict]:
    sonuc = []
    for proj in soup.select("div.projects div.projectmain"):
        baslik = _metin(proj.select_one(".projectTitle"))
        no = re.search(r"\s(\d{4}/\d+)$", baslik)
        yazar = _metin(proj.select_one(".projectAuthor"))
        ozet = proj.parent.select_one(".collapse p")
        sonuc.append({
            "baslik": baslik[: no.start()].strip() if no else baslik,
            "basvuru_no": no.group(1) if no else "",
            "basvuru_sahipleri": _alan(yazar.split("Patent Buluş")[0], "Patent Başvuru Sahipleri"),
            "bulus_sahipleri": _alan(yazar, "Patent Buluş Sahipleri"),
            "etiketler": [_metin(s) for s in proj.select(".projectType span.label")],
            "ozet": _metin(ozet),
        })
    return sonuc


def _kisi_sayfasi_mi(soup: BeautifulSoup, ad: str) -> bool:
    # Ilk h4 kisi basligi: profilde "AD SOYAD <birim>", sekmelerde "UNVAN AD SOYAD"
    return ad in _metin(soup.find("h4"))


def detay_cek(ist: YokIstemci, kisi: dict) -> dict:
    profil = ist.get(kisi["profil_url"])
    if not _kisi_sayfasi_mi(profil, kisi["ad_soyad"]):
        raise RuntimeError(f"profil sayfasi baska kisiye ait: {kisi['ad_soyad']}")
    detay = profil_ayristir(profil)
    for menu_id, alan in SEKMELER.items():
        a = profil.select_one(f"li#{menu_id} a[href]")
        if not a:
            detay[alan] = []
            continue
        s = ist.get(a["href"])
        if not _kisi_sayfasi_mi(s, kisi["ad_soyad"]):
            raise RuntimeError(f"{alan} sayfasi baska kisiye ait: {kisi['ad_soyad']}")
        if alan in ("makaleler", "bildiriler"):
            detay[alan] = yayinlar_ayristir(s)
        elif alan == "kitaplar":
            detay[alan] = kitaplar_ayristir(s)
        elif alan == "projeler":
            detay[alan] = projeler_ayristir(s, kisi["author_id"])
        elif alan == "dersler":
            detay[alan] = dersler_ayristir(s)
        elif alan == "yonetilen_tezler":
            detay[alan] = tezler_ayristir(s)
        elif alan == "patentler":
            detay[alan] = patentler_ayristir(s)
    return detay


def detay_cek_tekrarli(ist: YokIstemci, kisi: dict, deneme_sayisi: int = 3) -> dict:
    """WAF engelinde 5 dk, diger hatalarda 30 sn bekleyip oturumu tazeleyerek yeniden dener."""
    for deneme in range(1, deneme_sayisi + 1):
        try:
            return detay_cek(ist, kisi)
        except (Engellendi, httpx.HTTPError, RuntimeError) as e:
            logger.warning("%s: %s (deneme %d/%d)", kisi["ad_soyad"], e, deneme, deneme_sayisi)
            if deneme == deneme_sayisi:
                raise
            time.sleep(300 if isinstance(e, Engellendi) else 30)
            ist.get(ANA_SAYFA)
    raise AssertionError("ulasilamaz")


def detaylari_cek(ist: YokIstemci, kisiler: list[dict], ilerleme: Path, kayit) -> None:
    """Her kisinin detayi ilerleme dosyasina (jsonl) yazilir; yeniden calistirinca bitenler atlanir.
    `kayit(tamamlananlar)` her kisiden sonra cagrilir, JSON kisi kisi buyur."""
    biten: dict[str, dict] = {}
    if ilerleme.exists():
        for satir in ilerleme.read_text(encoding="utf-8").splitlines():
            if satir.strip():
                d = json.loads(satir)
                biten[d["author_id"]] = d["detay"]
    for k in kisiler:
        if k["author_id"] in biten:
            k.update(biten[k["author_id"]])
    tamam = [k for k in kisiler if k["author_id"] in biten]
    kalan = [k for k in kisiler if k["author_id"] not in biten]
    logger.info("detay: %d hazir, %d kalan", len(tamam), len(kalan))
    kayit(tamam)

    with ilerleme.open("a", encoding="utf-8") as f:
        for i, k in enumerate(kalan, 1):
            detay = detay_cek_tekrarli(ist, k)
            k.update(detay)
            tamam.append(k)
            f.write(json.dumps({"author_id": k["author_id"], "detay": detay}, ensure_ascii=False) + "\n")
            f.flush()
            logger.info(
                "[%d/%d] %s: %s", i, len(kalan), k["ad_soyad"],
                ", ".join(f"{alan}={len(detay[alan])}" for alan in SEKMELER.values()),
            )
            kayit(tamam)


def kaydet(yol: Path, universite: str, beklenen: int, kisiler: list[dict]) -> None:
    """Gecici dosyaya yazip yerine tasir: okuyan hic yarim JSON gormez."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    veri = {
        "kaynak": "akademik.yok.gov.tr",
        "universite": universite,
        "cekilme_zamani": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sitede_gorunen_toplam": beklenen,
        "akademisyen_sayisi": len(kisiler),
        "akademisyenler": kisiler,
    }
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(yol)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universite", default=VARSAYILAN_UNIVERSITE)
    ap.add_argument("--cikti", type=Path, default=VARSAYILAN_CIKTI)
    ap.add_argument("--liste", action="store_true", help="sadece akademisyen listesini tara")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    logging.getLogger("httpx").setLevel(logging.WARNING)

    ist = YokIstemci()
    beklenen, kisiler = liste_tara(ist, args.universite)
    if args.liste:
        kaydet(args.cikti, args.universite, beklenen, kisiler)
        logger.info("%d akademisyen -> %s", len(kisiler), args.cikti)
        return

    # JSON'da yalnizca detayi tamamlanan akademisyenler bulunur, her kisiden sonra guncellenir
    ilerleme = args.cikti.with_suffix(".ilerleme.jsonl")
    detaylari_cek(ist, kisiler, ilerleme, lambda tamam: kaydet(args.cikti, args.universite, beklenen, tamam))
    logger.info("tamamlandi: %d akademisyen -> %s", len(kisiler), args.cikti)


if __name__ == "__main__":
    main()
