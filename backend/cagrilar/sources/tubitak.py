"""tubitak.gov.tr/tr/duyuru (Drupal, sunucu tarafinda HTML) ayristiricisi.

Proje butcesi ust siniri, uygunluk kosullari gibi ayrintilar cogunlukla duyuruda degil, bagli cagri metni /
ulusal basvuru kurallari PDF'inde; bu PDF'lerin metni duyuruya eklenir (bkz. cagri_pdfleri)."""

from __future__ import annotations

from datetime import date, datetime
import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak, baglantilar, duz_metin, pdf_ekle
from backend.matching.ilan_extract import fold

BASE_URL = "https://tubitak.gov.tr"
LIST_URL = f"{BASE_URL}/tr/duyuru"

# Detay sayfasinda metne ve baglantilara alinmayan kisimlar
_GURULTU = [".social-sharing-buttons", ".file-size", ".file-link", "script", "style", "img", "noscript"]

MAX_PDF = 2  # duyuruya eklenen en fazla cagri dokumani
MAX_PDF_KARAKTER = 20000  # tek PDF'ten alinan metin (cikarim tum metnin ilk extract.MAX_CHARS karakterini okur)
# Cagri metni / ulusal basvuru kurallari; basvuru rehberi, e-imza yardimi, konu basliklari listesi gibi genel
# dokumanlar degil
_CAGRI_PDF = re.compile(r"cagri|call|duyuru|kural|surec|basvuru.?dok|announcement")
_GENEL_PDF = re.compile(r"kilavuz|rehber|yardim|konu.?baslik|yatirim.?plan|guideline|form\b|sablon|template")


class Tubitak(Kaynak):
    ad = "TÜBİTAK"

    def liste(self, sayfa: int) -> list[DuyuruOge]:
        soup = BeautifulSoup(self.get(LIST_URL, params={"page": sayfa}), "html.parser")
        ogeler = []
        for row in soup.select(".views-row"):
            link = row.select_one(".views-field-title a")
            if not link or not link.get("href"):
                continue
            time_tag = row.select_one("time[datetime]")
            ogeler.append(DuyuruOge(
                url=urljoin(BASE_URL, link["href"]),
                baslik=" ".join(link.get_text().split()),
                yayin_tarihi=_parse_date(time_tag["datetime"]) if time_tag else None,
            ))
        return ogeler

    def detay(self, url: str) -> DuyuruSayfasi:
        soup = BeautifulSoup(self.get(url), "html.parser")
        article = soup.select_one("#block-feza-gursey-content article") or soup.select_one("article")
        if article is None:
            raise ValueError(f"Duyuru icerigi bulunamadi: {url}")
        for sel in _GURULTU:
            for el in article.select(sel):
                el.decompose()

        linkler = baglantilar(article, BASE_URL)
        baslik = soup.select_one("h1")
        metin = duz_metin(article)
        if baslik:
            metin = f"# {' '.join(baslik.get_text().split())}\n\n{metin}"
        metin = pdf_ekle(self, metin, cagri_pdfleri(linkler), MAX_PDF_KARAKTER)
        return DuyuruSayfasi(metin=metin, baglantilar=linkler)


def cagri_pdfleri(linkler: list[tuple[str, str]]) -> list[str]:
    """tubitak.gov.tr'deki cagri dokumani PDF'leri; ulusal (Turkce) dokumanlar uluslararasi cagri metninden once."""
    secili = []
    for etiket, href in linkler:
        u = urlparse(href)
        ad = fold(f"{etiket} {unquote(u.path.rsplit('/', 1)[-1])}")
        if (u.netloc.endswith("tubitak.gov.tr") and u.path.lower().endswith(".pdf")
                and _CAGRI_PDF.search(ad) and not _GENEL_PDF.search(ad)):
            secili.append((("uluslararasi" in ad or "call" in ad) and "ulusal " not in ad, href))
    return [href for _, href in sorted(secili, key=lambda x: x[0])][:MAX_PDF]


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
