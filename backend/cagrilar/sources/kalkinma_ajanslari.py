"""ka.gov.tr duyurulari: 26 kalkinma ajansinin duyurularini toplayan JSON API.

Liste api.ka.gov.tr'den gelir; her duyurunun detayi ilgili ajansin kendi sitesinde (api.ka.gov.tr/redirect/...
oraya yonlendirir). Ajans siteleri farkli oldugu icin detay metni genel ana metin cikariciyla alinir.
Duyurunun kimligi (url) yonlendirme adresidir: liste bunu verir ve ajans sitesi adres degistirse de sabit kalir.
"""

from __future__ import annotations

from datetime import date

from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak, ana_metin

LIST_URL = "https://api.ka.gov.tr/api/announcements"


class KalkinmaAjanslari(Kaynak):
    ad = "Kalkınma Ajansları"

    def liste(self, sayfa: int) -> list[DuyuruOge]:
        veri = self.istek(LIST_URL, params={"page": sayfa + 1}).json()  # API sayfalari 1'den baslar
        if not veri.get("state", veri.get("status")):
            raise ValueError(f"ka.gov.tr API hatasi: {veri}")
        return [DuyuruOge(url=d["redirect_url"], baslik=" ".join(d["name"].split()),
                          yayin_tarihi=_tarih(d.get("date_to_show") or d.get("publish_start_date")))
                for d in veri["data"]]

    def detay(self, url: str) -> DuyuruSayfasi:
        res = self.istek(url)
        return ana_metin(res.text, str(res.url))


def _tarih(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
