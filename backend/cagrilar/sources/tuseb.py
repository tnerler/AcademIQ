"""proje-destek.tuseb.gov.tr/tr/haberler (sunucu tarafinda HTML) ayristiricisi.

Cagri ayrintilari (tarihler, butce, alanlar) cogunlukla haberde degil, bagli "cagri metni" PDF'inde;
files.tuseb.gov.tr'deki PDF'lerin metni habere eklenir. Sunucu ara sertifikayi gondermiyor (bkz. ek_sertifika).

Bazi kartlarin haber sayfasi yok, dogrudan TBYS'ye (Angular uygulamasi) gidiyor ve bircok kart ayni TBYS adresini
paylasiyor (ör. asi cagrilari). Bunlarin kimligi liste adresi + basliktan uretilen parca (#bcg-asisinin-...),
metni karttaki ozettir.
"""

from __future__ import annotations

from datetime import date
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak, baglantilar, duz_metin, pdf_ekle, tr_tarih
from backend.matching.ilan_extract import fold

logger = logging.getLogger("cagrilar")

BASE_URL = "https://proje-destek.tuseb.gov.tr"
LIST_URL = f"{BASE_URL}/tr/haberler"

MAX_PDF = 2  # habere eklenen en fazla PDF (cagri metni + varsa ikinci dokuman)
MAX_KART_ARAMA = 15  # haber sayfasi olmayan kart yeniden kontrol edilirken en fazla bu kadar liste sayfasi
_URL_TARIHI = re.compile(r"-(\d{4})(\d{2})(\d{2})/?$")


class Tuseb(Kaynak):
    ad = "TÜSEB"
    ek_sertifika = "certum_dv_tls_g2_r39.pem"

    def __init__(self) -> None:
        super().__init__()
        self._kartlar: dict[str, DuyuruSayfasi] = {}  # haber sayfasi olmayan kartlar: kimlik -> kart ozeti

    def liste(self, sayfa: int) -> list[DuyuruOge]:
        url = LIST_URL if sayfa == 0 else f"{LIST_URL}/p/{sayfa + 1}"
        soup = BeautifulSoup(self.get(url), "html.parser")
        ogeler = []
        for kart in soup.select(".card"):
            link = kart.select_one(".detail-button a[href]")
            baslik = kart.select_one(".card-body h5")
            if not link or not baslik:
                continue
            href = urljoin(BASE_URL, link["href"])
            baslik_metni = " ".join(baslik.get_text().split())
            tarih = kart.select_one(".card-date")
            yayin_tarihi = _url_tarihi(href) or (tr_tarih(tarih.get_text()) if tarih else None)
            if "/haberler/" not in urlparse(href).path:
                ozet = kart.select_one(".card-body p")
                ozet_metni = " ".join(ozet.get_text().split()) if ozet else ""
                href = f"{LIST_URL}#{_parca(baslik_metni)}"
                self._kartlar[href] = DuyuruSayfasi(
                    metin="\n".join(dict.fromkeys(filter(None, [baslik_metni, ozet_metni]))),  # ozet = baslik olabiliyor
                    baglantilar=[("TÜSEB Bilgi Yönetim Sistemi (TBYS)", link["href"])])
            ogeler.append(DuyuruOge(url=href, baslik=baslik_metni, yayin_tarihi=yayin_tarihi))
        return ogeler

    def detay(self, url: str) -> DuyuruSayfasi:
        if url.startswith(f"{LIST_URL}#"):
            return self._kart(url)
        soup = BeautifulSoup(self.get(url), "html.parser")
        icerik = soup.select_one("#content-body-right")
        if icerik is None:
            raise ValueError(f"Haber icerigi bulunamadi: {url}")
        for el in icerik.select("script, style, img, noscript"):
            el.decompose()

        linkler = baglantilar(icerik, url)  # haberlerin bir kismi www.tuseb.gov.tr'de (ayni duzen)
        metin = duz_metin(icerik)
        metin = pdf_ekle(self, metin, [href for _, href in linkler if _tuseb_pdf(href)][:MAX_PDF])
        return DuyuruSayfasi(metin=metin, baglantilar=linkler)

    def _kart(self, url: str) -> DuyuruSayfasi:
        """Haber sayfasi olmayan kartin ozeti; bu surecte liste gezilmediyse (aktif cagri kontrolu) aranir."""
        for sayfa in range(MAX_KART_ARAMA):
            if url in self._kartlar or not self.liste(sayfa):
                break
        if url not in self._kartlar:
            raise ValueError(f"TUSEB karti listede bulunamadi: {url}")
        return self._kartlar[url]


def _parca(baslik: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(baslik))[:120].strip("-")


def _tuseb_pdf(href: str) -> bool:
    u = urlparse(href)
    return u.netloc.endswith("tuseb.gov.tr") and u.path.lower().endswith(".pdf")


def _url_tarihi(href: str) -> date | None:
    """Haber adresinin sonundaki yayin tarihi: ...-yayimlandi-20260819"""
    if m := _URL_TARIHI.search(href):
        try:
            return date(*map(int, m.groups()))
        except ValueError:
            return None
    return None
