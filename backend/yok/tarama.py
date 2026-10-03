"""
YOK taramasi: universite listesini (ve tam taramada her hocanin profil + sekmelerini) yeniden ceker,
son bilinen durumla (yok_akademisyenler) karsilastirir, farki yok_taramalari.rapor'a yazar ve
son bilinen durumu gunceller.

  hizli (~1 dk): liste taranir -> eklenen/ayrilan hocalar, unvan/bolum/anahtar kelime degisiklikleri.
                 Yeni eklenen hocalarin profil ve sekmeleri de hemen cekilir (kisi basi ~30 sn).
  tam (~2 saat): hizli + tum aktif hocalarin profil ve sekmeleri -> eklenen/silinen yayin, ders, proje ...

Ilerleme ve rapor her hocadan sonra yazilir; UI tarama bitmeden kismi raporu gorebilir.

  uv run python -m backend.yok.tarama --tur hizli
  uv run python -m backend.yok.tarama --tur tam --limit 3     # test: sadece ilk 3 hocanin detayi
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.cagrilar.db import get_engine
from backend.config import get_settings
from backend.yok.db import init_schema, yok_akademisyenler, yok_taramalari
from backend.yok.fark import Rapor, detay_farki, kisi_ozeti, liste_farki
from backend.yok.scrape import YokIstemci, detay_cek_tekrarli, liste_tara

logger = logging.getLogger("yok")

MIN_LISTE_ORANI = 0.9  # liste bundan az geldiyse (site hatasi / yarim sayfa) herkes "ayrildi" sayilmasin


def _guncelle(tarama_id: int, **degerler) -> None:
    with get_engine().begin() as conn:
        conn.execute(update(yok_taramalari).where(yok_taramalari.c.id == tarama_id).values(**degerler))


def _kaydet(tarama_id: int, rapor: Rapor, **ilerleme) -> None:
    _guncelle(tarama_id, ilerleme=ilerleme, rapor=rapor.json(), ozet=rapor.ozet())


def _son_bilinen(universite: str) -> dict[str, dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(select(yok_akademisyenler.c.author_id, yok_akademisyenler.c.veri,
                                   yok_akademisyenler.c.detay_var)
                            .where(yok_akademisyenler.c.universite == universite, yok_akademisyenler.c.aktif))
        return {r.author_id: {**r.veri, "_detay_var": r.detay_var} for r in rows}


def _liste_uygula(universite: str, liste: list[dict], ayrilan: list[dict], eski: dict[str, dict]) -> None:
    """Listede gorunenlerin liste alanlarini yazar (detay korunur), ayrilanlari pasif yapar."""
    satirlar = []
    for k in liste:
        onceki = {a: v for a, v in eski.get(k["author_id"], {}).items() if a != "_detay_var"}
        satirlar.append({"author_id": k["author_id"], "universite": universite, "veri": {**onceki, **k},
                         "detay_var": eski.get(k["author_id"], {}).get("_detay_var", False), "aktif": True})
    q = pg_insert(yok_akademisyenler).values(satirlar)
    # Daha once ayrilmis biri geri donduyse eski detayi durur, veri liste alanlariyla guncellenir
    q = q.on_conflict_do_update(index_elements=["author_id"], set_={
        "veri": yok_akademisyenler.c.veri.op("||")(q.excluded.veri), "universite": q.excluded.universite,
        "aktif": True, "son_gorulme": func.now(),
    })
    with get_engine().begin() as conn:
        conn.execute(q)
        if ayrilan:
            conn.execute(update(yok_akademisyenler)
                         .where(yok_akademisyenler.c.author_id.in_([k["author_id"] for k in ayrilan]))
                         .values(aktif=False))


def _detay_yaz(kisi: dict, detay: dict) -> None:
    with get_engine().begin() as conn:
        conn.execute(update(yok_akademisyenler).where(yok_akademisyenler.c.author_id == kisi["author_id"])
                     .values(veri={**kisi, **detay}, detay_var=True, detay_zamani=func.now()))


def tara(tarama_id: int, tur: str, limit: int | None = None) -> Rapor:
    universite = get_settings().yok_universite
    rapor = Rapor()
    ist = YokIstemci()

    _kaydet(tarama_id, rapor, asama="liste", yapilan=0, toplam=None)
    beklenen, liste = liste_tara(ist, universite)
    eski = _son_bilinen(universite)
    if not liste or (beklenen > 0 and len(liste) < beklenen * MIN_LISTE_ORANI) \
            or (eski and len(liste) < len(eski) * MIN_LISTE_ORANI / 2):
        raise RuntimeError(f"Liste eksik geldi ({len(liste)} hoca, sitede {beklenen}, onceki {len(eski)}); "
                           "son bilinen durum degistirilmedi")

    eklenen, ayrilan, degisen = liste_farki(eski, liste)
    _liste_uygula(universite, liste, ayrilan, eski)
    rapor.eklenen = [kisi_ozeti(k) for k in eklenen]
    rapor.ayrilan = [kisi_ozeti(k) for k in ayrilan]
    for k in liste:
        rapor.degisen_ekle(k, alanlar=degisen.get(k["author_id"]))
    logger.info("liste: %d hoca, %d eklenen, %d ayrilan, %d alan degisikligi",
                len(liste), len(eklenen), len(ayrilan), len(degisen))

    # Detay: yeni gelenler (ve daha once detayi hic cekilmemisler) her zaman; tam taramada herkes
    detaysiz = [k for k in liste if not eski.get(k["author_id"], {}).get("_detay_var")]
    if tur == "tam":
        digerleri = [k for k in liste if eski.get(k["author_id"], {}).get("_detay_var")]
        hedef = detaysiz + (digerleri[:limit] if limit else digerleri)
    else:
        hedef = detaysiz
    _kaydet(tarama_id, rapor, asama="detay", yapilan=0, toplam=len(hedef))

    for i, k in enumerate(hedef, 1):
        detay = detay_cek_tekrarli(ist, k)
        onceki = eski.get(k["author_id"])
        if onceki and onceki["_detay_var"]:
            rapor.degisen_ekle(k, bolumler=detay_farki(onceki, detay))
        _detay_yaz(k, detay)
        _kaydet(tarama_id, rapor, asama="detay", yapilan=i, toplam=len(hedef))
        logger.info("[%d/%d] %s", i, len(hedef), k["ad_soyad"])
    return rapor


def calistir(tarama_id: int) -> None:
    """'calisiyor' durumundaki taramayi yurutur; sonucu (ya da hatayi) kaydeder."""
    with get_engine().connect() as conn:
        t = conn.execute(select(yok_taramalari).where(yok_taramalari.c.id == tarama_id)).mappings().one()
    try:
        rapor = tara(tarama_id, t["tur"], t["limit_"])
    except Exception as e:
        logger.exception("YOK taramasi %d hata", tarama_id)
        _guncelle(tarama_id, durum="hata", bitti=func.now(), hata=str(e)[:500])
        raise
    _guncelle(tarama_id, durum="bitti", bitti=func.now(), rapor=rapor.json(), ozet=rapor.ozet())
    logger.info("YOK taramasi %d bitti: %s", tarama_id, rapor.ozet())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tur", choices=["hizli", "tam"], default="hizli")
    ap.add_argument("--limit", type=int, help="tam taramada en fazla bu kadar hocanin detayi (test)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_schema()
    with get_engine().begin() as conn:
        tarama_id = conn.execute(insert(yok_taramalari).values(
            tur=args.tur, kaynak="elle", durum="calisiyor", basladi=func.now(), limit_=args.limit,
        ).returning(yok_taramalari.c.id)).scalar_one()
    calistir(tarama_id)


if __name__ == "__main__":
    main()
