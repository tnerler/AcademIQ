"""ab.gov.tr (Disisleri Bakanligi AB Baskanligi) duyurulari: tek sayfalik, sunucu tarafinda HTML liste.

Liste elle siralaniyor (2025 tarihli duyurular 2026 tarihlilerin arasinda) ve tek sayfa; bu yuzden sirali=False:
her calistirmada tum liste gezilir, bilinenler atlanir. "Guncel Hibeler" sayfasi hibeler.ab.gov.tr iframe'i,
o alan adi artik cozulmuyor.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak, baglantilar, duz_metin, tr_tarih

BASE_URL = "https://www.ab.gov.tr/"
LIST_URL = urljoin(BASE_URL, "duyurular_42.html")


class AbBaskanligi(Kaynak):
    ad = "AB Başkanlığı"
    sirali = False

    def liste(self, sayfa: int) -> list[DuyuruOge]:
        if sayfa > 0:
            return []
        soup = BeautifulSoup(self.get(LIST_URL), "html.parser")
        ogeler = []
        for entry in soup.select("article.newslist"):
            link = entry.select_one(".entry-title a[href]")
            if not link:
                continue
            tarih = entry.select_one(".entry-meta")
            ogeler.append(DuyuruOge(
                url=urljoin(BASE_URL, link["href"]),
                baslik=" ".join(link.get_text().split()),
                yayin_tarihi=tr_tarih(tarih.get_text()) if tarih else None,
            ))
        return ogeler

    def detay(self, url: str) -> DuyuruSayfasi:
        soup = BeautifulSoup(self.get(url), "html.parser")
        icerik = soup.select_one("#printBody")
        if icerik is None:
            raise ValueError(f"Duyuru icerigi bulunamadi: {url}")
        for el in icerik.select("script, style, img, noscript"):
            el.decompose()
        linkler = baglantilar(icerik, url)
        baslik = soup.select_one("h1:not(.navb)")  # h1.navb: "MEDYA / Duyurular / ..." yol satiri
        metin = duz_metin(icerik)
        if baslik:
            metin = f"# {' '.join(baslik.get_text().split())}\n\n{metin}"
        return DuyuruSayfasi(metin=metin, baglantilar=linkler)
