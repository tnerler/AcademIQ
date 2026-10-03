"""Cagri kaynagi arayuzu: yeni bir site eklemek icin bu sinifi uygulayan bir modul yazmak yeterli."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
import logging
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import certifi
import httpx
import pymupdf
import trafilatura

from backend.matching.ilan_extract import fold

logger = logging.getLogger("cagrilar")

SERTIFIKALAR = Path(__file__).parent / "certs"


@dataclass
class DuyuruOge:
    """Liste sayfasindaki bir duyuru."""
    url: str
    baslik: str
    yayin_tarihi: date | None


@dataclass
class DuyuruSayfasi:
    """Detay sayfasinin temizlenmis metni ve icindeki baglantilar."""
    metin: str
    baglantilar: list[tuple[str, str]] = field(default_factory=list)  # (etiket, url)


class Kaynak(ABC):
    ad: str
    istek_araligi: float = 1.0  # siteyi yormamak icin iki istek arasi bekleme (sn)
    # Liste yeniden eskiye sirali mi? Degilse artimli taramada ilk bilinen duyuruda durulmaz,
    # tum liste gezilip bilinenler atlanir (sayfa sayisi az olan kaynaklar icin).
    sirali: bool = True
    # Sunucu ara sertifikayi gondermiyorsa (tarayicilar AIA ile tamamlar, Python tamamlamaz)
    # certs/ altindaki ara sertifika guvenilenlere eklenir. verify=False'tan farkli olarak zincir
    # yine kok sertifikaya kadar dogrulanir.
    ek_sertifika: str | None = None

    def __init__(self) -> None:
        verify: ssl.SSLContext | bool = True
        if self.ek_sertifika:
            verify = ssl.create_default_context(cafile=certifi.where())
            verify.load_verify_locations(SERTIFIKALAR / self.ek_sertifika)
        self._client = httpx.Client(
            timeout=30, follow_redirects=True, verify=verify,
            headers={"User-Agent": "AcademIQ/0.1 (akademik proje cagrisi takibi)"},
        )
        self._son_istek = 0.0

    def get(self, url: str, params: dict | None = None) -> str:
        return self.istek(url, params).text

    def istek(self, url: str, params: dict | None = None) -> httpx.Response:
        for deneme in range(3):
            bekle = self._son_istek + self.istek_araligi - time.monotonic()
            if bekle > 0:
                time.sleep(bekle)
            try:
                res = self._client.get(url, params=params)
                self._son_istek = time.monotonic()
                res.raise_for_status()
                return res
            except httpx.HTTPError as exc:
                self._son_istek = time.monotonic()
                if deneme == 2 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500):
                    raise
                logger.warning("Istek basarisiz, tekrar denenecek (%s): %s", url, exc)
                time.sleep(5 * (deneme + 1))
        raise AssertionError("unreachable")

    @abstractmethod
    def liste(self, sayfa: int) -> list[DuyuruOge]:
        """0'dan baslayan liste sayfasi; yeniden eskiye siralidir. Bos liste: sayfalar bitti."""

    @abstractmethod
    def detay(self, url: str) -> DuyuruSayfasi:
        ...


# --- Ortak ayristirma yardimcilari -------------------------------------------------

_BLOK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "table", "ul", "ol"}


def duz_metin(root) -> str:
    """Blok elemanlarini satir, satir ici elemanlari (a, strong ...) ayni satirda birakan duz metin.
    ('Detayli bilgi icin lutfen <a>tiklayiniz</a>.' tek satir kalir.)"""
    for el in root.find_all(_BLOK):
        el.insert_before("\n")
        el.insert_after("\n")
    lines = (" ".join(line.split()) for line in root.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def baglantilar(root, base_url: str) -> list[tuple[str, str]]:
    """root icindeki http(s) baglantilari (etiket, url); ayni url bir kez."""
    out: dict[str, str] = {}
    for a in root.select("a[href]"):
        href = urljoin(base_url, a["href"].strip())
        if urlparse(href).scheme in ("http", "https") and href not in out:
            out[href] = " ".join(a.get_text().split()).strip("[]() ") or href
    return [(etiket, href) for href, etiket in out.items()]


def pdf_metni(data: bytes) -> str:
    """PDF metni; satir sonlarinda bolunmus cumleler birlestirilir, bos satirlar paragraf ayiracidir."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
    paragraflar = re.split(r"\n\s*\n", text)
    return "\n".join(p for p in (" ".join(p.split()) for p in paragraflar) if p)


def pdf_ekle(kaynak: Kaynak, metin: str, hrefler: list[str], max_karakter: int | None = None) -> str:
    """Bagli PDF'lerin metnini '## Ek: <dosya>' basligiyla duyuru metninin sonuna ekler; okunamayan PDF atlanir."""
    for href in hrefler:
        try:
            ek = pdf_metni(kaynak.istek(href).content)
        except Exception as exc:  # PDF okunamazsa duyuru metniyle devam
            logger.warning("%s PDF okunamadi (%s): %s", kaynak.ad, href, exc)
            continue
        metin += f"\n\n## Ek: {href.rsplit('/', 1)[-1]}\n{ek[:max_karakter]}"
    return metin


_AYLAR = {ay: i for i, ay in enumerate(
    ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"], 1)}


def tr_tarih(text: str) -> date | None:
    """'19 Agustos 2026', 'Agustos 19, 2026', '24 Temmuz, 2026' gibi Turkce ay adli tarihler."""
    kelimeler = re.findall(r"[a-z]+|\d+", fold(text))
    ay = next((_AYLAR[k] for k in kelimeler if k in _AYLAR), None)
    sayilar = [int(k) for k in kelimeler if k.isdigit()]
    yil = next((s for s in sayilar if s > 1900), None)
    gun = next((s for s in sayilar if 1 <= s <= 31), None)
    try:
        return date(yil, ay, gun) if ay and yil and gun else None
    except ValueError:
        return None


MIN_ANA_METIN = 100  # bundan kisa "ana metin" (ör. bos kabuk sayfada kalan menu yazisi) duyuru degildir

# Ana metin disinda kalan site iskeleti; baglanti toplarken atlanir
_ISKELET = "nav, header, footer, aside, script, style, noscript, form, [role=navigation], [class*=menu], [id*=menu]"


def ana_metin(html: str, url: str) -> DuyuruSayfasi:
    """Yapisini bilmedigimiz sayfalar (ör. kalkinma ajanslarinin kendi siteleri) icin: metin trafilatura ile
    ana icerikten; baglantilar iskelet (menu, header, footer) disinda kalan ve etiketi metinde gecenlerden."""
    metin = trafilatura.extract(html, url=url, include_tables=True, favor_recall=True) or ""
    metin = "\n".join(line for line in (" ".join(line.split()) for line in metin.splitlines()) if line)
    if len(metin) < MIN_ANA_METIN:
        raise ValueError(f"Sayfada ana metin bulunamadi: {url}")

    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select(_ISKELET):
        el.decompose()
    duz = " ".join(metin.split()).casefold()
    secili = [(etiket, href) for etiket, href in baglantilar(soup.body or soup, url)
              if etiket.casefold() in duz and not href.startswith(url.split("?")[0] + "#")]
    return DuyuruSayfasi(metin=metin, baglantilar=secili)
