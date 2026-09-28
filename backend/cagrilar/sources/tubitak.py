"""tubitak.gov.tr/tr/duyuru (Drupal, sunucu tarafinda HTML) ayristiricisi."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak

BASE_URL = "https://tubitak.gov.tr"
LIST_URL = f"{BASE_URL}/tr/duyuru"

# Detay sayfasinda metne ve baglantilara alinmayan kisimlar
_GURULTU = [".social-sharing-buttons", ".file-size", ".file-link", "script", "style", "img", "noscript"]
_BLOK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "table", "ul", "ol"}


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

        baglantilar: dict[str, str] = {}
        for a in article.select("a[href]"):
            href = urljoin(BASE_URL, a["href"])
            if urlparse(href).scheme in ("http", "https") and href not in baglantilar:
                baglantilar[href] = " ".join(a.get_text().split()) or href

        baslik = soup.select_one("h1")
        metin = _text(article)
        if baslik:
            metin = f"# {' '.join(baslik.get_text().split())}\n\n{metin}"
        return DuyuruSayfasi(metin=metin, baglantilar=[(etiket, href) for href, etiket in baglantilar.items()])


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _text(root) -> str:
    """Blok elemanlarini satir, satir ici elemanlari (a, strong ...) ayni satirda birakan duz metin.
    ('Detayli bilgi icin lutfen <a>tiklayiniz</a>.' tek satir kalir.)"""
    for el in root.find_all(_BLOK):
        el.insert_before("\n")
        el.insert_after("\n")
    lines = (" ".join(line.split()) for line in root.get_text().splitlines())
    return "\n".join(line for line in lines if line)
