"""
YOK taramasi ile son bilinen durum arasindaki fark. Saf fonksiyonlar (ag/DB yok), testleri tests/test_yok_fark.py.

Rapor sekli (yok_taramalari.rapor):
  {
    "eklenen": [{author_id, ad_soyad, unvan, bolum}],        # listeye yeni giren hocalar
    "ayrilan": [{author_id, ad_soyad, unvan, bolum}],        # listeden cikan hocalar
    "degisen": [{author_id, ad_soyad, unvan,
                 "alanlar": [{alan, eski, yeni}],             # unvan, bolum, anahtar kelimeler ...
                 "bolumler": {"makaleler": {"eklenen": [...], "silinen": [...]}, ...}}],
  }
"""

from __future__ import annotations

from collections import Counter
import re
import unicodedata

# Liste satirinda gorunen (hizli taramada da karsilastirilabilen) alanlar
LISTE_ALANLARI = [
    "ad_soyad", "unvan", "fakulte", "bolum", "anabilim_dali_program",
    "temel_alan", "bilim_alani", "anahtar_kelimeler", "eposta", "orcid",
]


def _norm(metin: str) -> str:
    metin = metin.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    metin = unicodedata.normalize("NFKD", metin).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", metin).strip()


def _kitap(k: dict) -> str:
    return f"{k['bolum_adi']} ({k['baslik']})" if k.get("bolum_adi") else k["baslik"]


# Bolum -> kalemin gosterim metni. Karsilastirma anahtari bu metnin normallestirilmis hali:
# baslikta yalnizca buyuk/kucuk harf ya da noktalama degisirse fark sayilmaz.
KALEMLER = {
    "makaleler": lambda y: y["baslik"],
    "bildiriler": lambda y: y["baslik"],
    "kitaplar": _kitap,
    "projeler": lambda y: y["baslik"],
    "dersler": lambda d: f"{d['ders_adi']} ({d['duzey']})" if d.get("duzey") else d["ders_adi"],
    "yonetilen_tezler": lambda t: t["tez_adi"],
    "patentler": lambda p: p["baslik"],
    "akademik_gorevler": lambda g: " · ".join(x for x in (g.get("yil"), g.get("unvan"), g.get("kurum")) if x),
    "ogrenim": lambda o: " · ".join(x for x in (o.get("derece"), o.get("kurum")) if x),
}


def kisi_ozeti(k: dict) -> dict:
    return {"author_id": k["author_id"], "ad_soyad": k["ad_soyad"], "unvan": k.get("unvan", ""),
            "bolum": k.get("bolum", "")}


def _karsilastirilabilir(deger):
    return sorted(_norm(x) for x in deger) if isinstance(deger, list) else _norm(str(deger or ""))


def alan_farki(eski: dict, yeni: dict) -> list[dict]:
    return [
        {"alan": a, "eski": eski.get(a), "yeni": yeni.get(a)}
        for a in LISTE_ALANLARI
        if _karsilastirilabilir(eski.get(a)) != _karsilastirilabilir(yeni.get(a))
    ]


def bolum_farki(eski: list[dict], yeni: list[dict], goster) -> dict | None:
    """Kalem bazinda fark (ayni baslik birden cok kez gecebilir: coklu kume olarak karsilastirilir)."""
    def say(kalemler):
        sayac, metin = Counter(), {}
        for k in kalemler:
            anahtar = _norm(goster(k))
            sayac[anahtar] += 1
            metin.setdefault(anahtar, goster(k))
        return sayac, metin

    (es, em), (ys, ym) = say(eski), say(yeni)
    eklenen = [ym[a] for a, n in (ys - es).items() for _ in range(n)]
    silinen = [em[a] for a, n in (es - ys).items() for _ in range(n)]
    return {"eklenen": eklenen, "silinen": silinen} if eklenen or silinen else None


def detay_farki(eski: dict, yeni: dict) -> dict[str, dict]:
    """Profil ve sekmelerdeki eklenen/silinen kalemler; degismeyen bolumler dahil edilmez."""
    sonuc = {}
    for bolum, goster in KALEMLER.items():
        f = bolum_farki(eski.get(bolum) or [], yeni.get(bolum) or [], goster)
        if f:
            sonuc[bolum] = f
    return sonuc


def liste_farki(eski: dict[str, dict], yeni: list[dict]) -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    """(eklenen kisiler, ayrilan kisiler, {author_id: alan farklari}) -- eski: author_id -> son bilinen veri."""
    yeni_idler = {k["author_id"] for k in yeni}
    eklenen = [k for k in yeni if k["author_id"] not in eski]
    ayrilan = [k for aid, k in eski.items() if aid not in yeni_idler]
    degisen = {}
    for k in yeni:
        if k["author_id"] in eski:
            f = alan_farki(eski[k["author_id"]], k)
            if f:
                degisen[k["author_id"]] = f
    return eklenen, ayrilan, degisen


class Rapor:
    """Tarama boyunca biriken fark; her hocadan sonra DB'ye yazilabilsin diye artimli."""

    def __init__(self) -> None:
        self.eklenen: list[dict] = []
        self.ayrilan: list[dict] = []
        self._degisen: dict[str, dict] = {}

    def degisen_ekle(self, kisi: dict, alanlar: list[dict] | None = None, bolumler: dict | None = None) -> None:
        if not alanlar and not bolumler:
            return
        d = self._degisen.setdefault(kisi["author_id"], {**kisi_ozeti(kisi), "alanlar": [], "bolumler": {}})
        d["alanlar"].extend(alanlar or [])
        d["bolumler"].update(bolumler or {})

    def json(self) -> dict:
        return {"eklenen": self.eklenen, "ayrilan": self.ayrilan, "degisen": list(self._degisen.values())}

    def ozet(self) -> dict:
        return {"eklenen": len(self.eklenen), "ayrilan": len(self.ayrilan), "degisen": len(self._degisen)}
