"""Cagri kaynagi arayuzu: yeni bir site eklemek icin bu sinifi uygulayan bir modul yazmak yeterli."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
import logging
import time

import httpx

logger = logging.getLogger("cagrilar")


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

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=30, follow_redirects=True,
            headers={"User-Agent": "AcademIQ/0.1 (akademik proje cagrisi takibi)"},
        )
        self._son_istek = 0.0

    def get(self, url: str, params: dict | None = None) -> str:
        for deneme in range(3):
            bekle = self._son_istek + self.istek_araligi - time.monotonic()
            if bekle > 0:
                time.sleep(bekle)
            try:
                res = self._client.get(url, params=params)
                self._son_istek = time.monotonic()
                res.raise_for_status()
                return res.text
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
