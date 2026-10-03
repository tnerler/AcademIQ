"""Kayitli cagrilari guncel kurallarla (extract.py karari, tarih bayraklari, tekrar birlestirme) yeniden degerlendirir.
Siniflandirma kurallari degistiginde bir kez calistirilir; sayfalar yeniden indirilmez, saklanan metin kullanilir.

  uv run python -m backend.cagrilar.yeniden            # yalnizca rapor
  uv run python -m backend.cagrilar.yeniden --uygula   # cagri olmayanlari sil, tekrarlari birlestir, alanlari guncelle
  uv run python -m backend.cagrilar.yeniden --butce [--uygula]  # yalnizca butce / program_butcesi alanlarini yeniden cikar
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta
import logging
import sys

from sqlalchemy import delete, select, update

from backend.cagrilar.db import cagrilar, duyurular, get_engine, init_schema
from backend.cagrilar.eslesme import eslesmeyi_sil
from backend.cagrilar.extract import _basvuru_tarihi_mi, cikar
from backend.cagrilar.fetch import TEKRAR_PENCERESI_GUN, _guncellemeyi_uygula, _otomatik_eslestir, ayni_baslik
from backend.cagrilar.index import cagrilari_indeksle
from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi
from backend.cagrilar.sources.tubitak import Tubitak
from backend.vectorstore import get_cagri_store

logger = logging.getLogger("cagrilar")


def cagrilari_sil(sebepler: dict[str, str]) -> None:
    """cagri_id -> sebep. Vektorler de silinir, eslesmeler CASCADE; duyurulari cagri_degil olur ki sonraki
    taramalarda yeniden eklenmesin."""
    if not sebepler:
        return
    get_cagri_store().delete(ids=list(sebepler))
    with get_engine().begin() as conn:
        for cagri_id, sebep in sebepler.items():
            conn.execute(update(duyurular).where(duyurular.c.cagri_id == cagri_id)
                         .values(karar="cagri_degil", sebep=sebep, cagri_id=None))
        conn.execute(delete(cagrilar).where(cagrilar.c.id.in_(list(sebepler))))


def yeniden_degerlendir(uygula: bool) -> Counter:
    sayac: Counter = Counter()
    with get_engine().connect() as conn:
        rows = conn.execute(select(cagrilar).order_by(cagrilar.c.yayin_tarihi.nulls_last(), cagrilar.c.ilk_gorulme)).all()

    # 1) Karar: cagri olmayanlar
    silinecek: dict[str, str] = {}
    guncel: dict[str, dict] = {}
    onemli: set[str] = set()  # son tarihi degisen: acik/gecmis durumu degisir, eslesme yenilenir
    for r in rows:
        args = (r.metin, [(b["etiket"], b["url"]) for b in r.baglantilar], r.yayin_tarihi, r.baslik, r.kaynak)
        c = cikar(*args)
        # Silme geri alinamaz: ikinci bir bagimsiz calistirma da cagri_degil demeli (LLM karari rastgele sapabiliyor)
        if c.tur == "cagri_degil" and cikar(*args).tur == "cagri_degil":
            silinecek[r.id] = f"yeniden değerlendirme: {c.sebep}"
            print(f"SIL      [{r.kaynak}] {r.baslik[:90]}\n         {c.sebep[:160]}")
            continue
        # Kayitli tarihler aynen kalir, yalnizca basvuru bayraklari eklenir: tarihleri LLM'e bastan cikartmak
        # uzatmayla gelenleri kaybettirir ve dogru tarihleri de rastgele degistirebilir.
        llm = {(t.etiket.strip(), t.tarih): t.basvuru for t in c.tarihler}
        alanlar = {"tarihler": [{**t, "basvuru": _basvuru_tarihi_mi(t["etiket"], llm.get((t["etiket"], t["tarih"]), True))}
                                for t in r.tarihler]}
        eski_son = max((t["tarih"] for t in r.tarihler if t.get("basvuru", True)), default=None)
        yeni_son = max((t["tarih"] for t in alanlar["tarihler"] if t["basvuru"]), default=None)
        if eski_son != yeni_son:
            print(f"SON      [{r.kaynak}] {r.baslik[:90]}: {eski_son} -> {yeni_son}")
            sayac["son_tarih_degisen"] += 1
            onemli.add(r.id)
        guncel[r.id] = alanlar

    # 2) Tekrarlar: eskiye birlestir (satirlar eskiden yeniye sirali)
    kalan = [r for r in rows if r.id not in silinecek]
    birlesen: dict[str, str] = {}  # yeni -> eski
    for i, yeni in enumerate(kalan):
        for eski in kalan[:i]:
            if eski.id in birlesen or not ayni_baslik(yeni.baslik, eski.baslik):
                continue
            if yeni.yayin_tarihi and eski.yayin_tarihi and \
                    abs(yeni.yayin_tarihi - eski.yayin_tarihi) > timedelta(days=TEKRAR_PENCERESI_GUN):
                continue
            birlesen[yeni.id] = eski.id
            print(f"BIRLESTIR [{yeni.kaynak}] {yeni.baslik[:80]}\n       -> {eski.baslik[:80]}")
            break

    sayac.update(silinen=len(silinecek), birlesen=len(birlesen), incelenen=len(rows))
    if not uygula:
        return sayac

    degisen = set(guncel) - set(birlesen)
    with get_engine().begin() as conn:
        for cagri_id in degisen:
            conn.execute(update(cagrilar).where(cagrilar.c.id == cagri_id).values(**guncel[cagri_id]))
    satir = {r.id: r for r in rows}
    for yeni_id, eski_id in birlesen.items():
        y = satir[yeni_id]
        _guncellemeyi_uygula(eski_id, DuyuruOge(y.url, y.baslik, y.yayin_tarihi), DuyuruSayfasi(metin=y.metin))
        with get_engine().begin() as conn:  # duyurusu eskiye baglanir; cagrilari_sil artik ona dokunmaz
            conn.execute(update(duyurular).where(duyurular.c.cagri_id == yeni_id).values(
                karar="guncelleme", sebep="aynı çağrının tekrar duyurusu (yeniden değerlendirme)", cagri_id=eski_id))
    cagrilari_sil(silinecek | {y: "aynı çağrının tekrar duyurusu" for y in birlesen})

    hedefler = (onemli - set(birlesen)) | set(birlesen.values())
    for cagri_id in hedefler:
        eslesmeyi_sil(cagri_id)  # tarih/hedef kitle degismis olabilir
    cagrilari_indeksle(hedefler)
    _otomatik_eslestir(hedefler, sayac)
    return sayac


def butceleri_yenile(uygula: bool) -> Counter:
    """Butce alanlari (proje basina / program toplami) ayrildiginda bir kez: TUBITAK cagrilarinin sayfasi bagli
    cagri metni PDF'leriyle yeniden indirilir (butce ust siniri cogunlukla PDF'te), digerlerinde saklanan metin
    kullanilir. Diger alanlar ve metin degismez; sonraki taramada icerik hash'i degisen TUBITAK cagrilari zaten
    bastan cikarilir."""
    sayac: Counter = Counter()
    tubitak = Tubitak()
    with get_engine().connect() as conn:
        rows = conn.execute(select(cagrilar).order_by(cagrilar.c.kaynak, cagrilar.c.baslik)).all()
    for r in rows:
        try:
            if r.kaynak == tubitak.ad:
                sayfa = tubitak.detay(r.url)
                metin, linkler = sayfa.metin, sayfa.baglantilar
            else:
                metin, linkler = r.metin, [(b["etiket"], b["url"]) for b in r.baglantilar]
            c = cikar(metin, linkler, r.yayin_tarihi, r.baslik, r.kaynak)
        except Exception as exc:
            logger.warning("Butce cikarilamadi (%s): %s", r.url, exc)
            sayac["hata"] += 1
            continue
        if (c.butce, c.program_butcesi) == (r.butce, r.program_butcesi):
            continue
        sayac["degisen"] += 1
        print(f"BUTCE    [{r.kaynak}] {r.baslik[:90]}\n         proje başına: {r.butce} -> {c.butce}"
              f"\n         program:      {r.program_butcesi} -> {c.program_butcesi}")
        if uygula:
            with get_engine().begin() as conn:
                conn.execute(update(cagrilar).where(cagrilar.c.id == r.id)
                             .values(butce=c.butce, program_butcesi=c.program_butcesi))
    sayac["incelenen"] = len(rows)
    return sayac


def main() -> int:
    ap = argparse.ArgumentParser(description="Kayitli cagrilari guncel kurallarla yeniden degerlendirir.")
    ap.add_argument("--uygula", action="store_true", help="Degisiklikleri veritabanina yaz (varsayilan: yalnizca rapor)")
    ap.add_argument("--butce", action="store_true", help="Yalnizca butce alanlarini yeniden cikar")
    args = ap.parse_args()
    init_schema()
    print(dict(butceleri_yenile(args.uygula) if args.butce else yeniden_degerlendir(args.uygula)))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        force=True)  # parser.py import aninda root logger'i yapilandiriyor
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
