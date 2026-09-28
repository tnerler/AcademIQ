"""
Cagri toplama calistirmasi: yeni duyurular -> kara liste -> LLM karari/cikarimi -> cagrilar,
ardindan aktif cagrilarin sayfalari yeniden kontrol edilir; yeni/degisen cagrilar indekslenir ve
akademik olanlar otomatik eslestirilir.

  - Ilk calistirma (duyurular bos) ya da --backfill: son `cagri_backfill_gun` gunun tum duyurulari.
  - Sonraki calistirmalar: liste sayfalari bilinen bir duyuruya gelene kadar gezilir.
  - Duyurular eskiden yeniye islenir: yarida kalan bir calistirmadan sonra atlanan duyuru olmaz.
  - 'hata' karari verilen duyurular her calistirmada yeniden denenir.

Kullanim (zamanli calistirma icin bkz. backend/cagrilar/worker.py):
  uv run python -m backend.cagrilar.fetch              # simdi bir kez calistir
  uv run python -m backend.cagrilar.fetch --backfill   # son 1 yili yeniden tara (bilinenler atlanir)
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import logging
import re
import sys

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.cagrilar.db import cagrilar, cekme_calismalari, duyurular, get_engine, init_schema
from backend.cagrilar.eslesme import acik_akademik_cagrilari_eslestir, eslesmeyi_sil
from backend.cagrilar.extract import CagriCikarim, cikar, tarihleri_birlestir
from backend.cagrilar.filters import kara_liste
from backend.cagrilar.index import cagrilari_indeksle
from backend.cagrilar.sources.base import DuyuruOge, DuyuruSayfasi, Kaynak
from backend.cagrilar.sources.tubitak import Tubitak
from backend.config import get_settings
from backend.matching.ilan_extract import fold
from backend.vectorstore import doc_id

logger = logging.getLogger("cagrilar")

# Worker ayni surecte her gun calisir: LLM/embedding istemcilerinin async baglantilari ilk loop'a
# baglandigi icin her calistirmada yeni loop (asyncio.run) acmak yerine tek kalici loop kullanilir.
_LOOP = asyncio.new_event_loop()

MAX_ARTAN_SAYFA = 30  # bilinen duyuru hic bulunamazsa (ör. uzun sure calismadiysa) en fazla bu kadar sayfa


def kaynaklar() -> list[Kaynak]:
    return [Tubitak()]


# --- Calistirma kaydi ----------------------------------------------------------

def istek_olustur(tur: str) -> int:
    with get_engine().begin() as conn:
        return conn.execute(insert(cekme_calismalari).values(tur=tur).returning(cekme_calismalari.c.id)).scalar_one()


def calistir(calisma_id: int, backfill: bool = False) -> Counter:
    """cekme_calismalari satirini calistirir; sonucu (sayilar/hata) ayni satira yazar."""
    with get_engine().begin() as conn:
        conn.execute(update(cekme_calismalari).where(cekme_calismalari.c.id == calisma_id)
                     .values(durum="calisiyor", basladi=func.now()))
    sayac: Counter = Counter()
    try:
        for kaynak in kaynaklar():
            _kaynak_calistir(kaynak, backfill, sayac)
    except Exception as exc:
        logger.exception("Cekme calismasi basarisiz")
        _bitir(calisma_id, "hata", sayac, f"{type(exc).__name__}: {exc}")
        raise
    _bitir(calisma_id, "bitti", sayac, None)
    logger.info("Calisma %d bitti: %s", calisma_id, dict(sayac))
    return sayac


def _bitir(calisma_id: int, durum: str, sayac: Counter, hata: str | None) -> None:
    with get_engine().begin() as conn:
        conn.execute(update(cekme_calismalari).where(cekme_calismalari.c.id == calisma_id)
                     .values(durum=durum, bitti=func.now(), sayilar=dict(sayac), hata=hata))


# --- Akis ------------------------------------------------------------------------

def _kaynak_calistir(kaynak: Kaynak, backfill: bool, sayac: Counter) -> None:
    with get_engine().connect() as conn:
        bilinen = set(conn.execute(select(duyurular.c.url)
                                   .where(duyurular.c.kaynak == kaynak.ad, duyurular.c.karar != "hata")).scalars())
        hatali = [DuyuruOge(r.url, r.baslik, r.yayin_tarihi) for r in conn.execute(
            select(duyurular).where(duyurular.c.kaynak == kaynak.ad, duyurular.c.karar == "hata"))]
    backfill = backfill or not bilinen
    if backfill:
        sayac["backfill"] = 1

    yeni = _yeni_duyurular(kaynak, bilinen, backfill)
    sayac["taranan"] += len(yeni)
    islenen: set[str] = set()      # bu calistirmada olusturulan/guncellenen cagri id'leri
    eslestirilecek: set[str] = set()
    for oge in list(reversed(yeni)) + hatali:  # eskiden yeniye; en son onceki hatalar
        cagri_id, yeni_mi = _isle(kaynak, oge, sayac)
        if cagri_id:
            islenen.add(cagri_id)
            if yeni_mi:
                eslestirilecek.add(cagri_id)

    degisen = _aktifleri_kontrol_et(kaynak, islenen, sayac)
    for cagri_id in degisen:
        eslesmeyi_sil(cagri_id)  # eski metinle hesaplanmis sonuc gecersiz
    cagrilari_indeksle(islenen | degisen)
    _otomatik_eslestir(eslestirilecek | degisen, sayac)


def _yeni_duyurular(kaynak: Kaynak, bilinen: set[str], backfill: bool) -> list[DuyuruOge]:
    """Liste sayfalarindan islenmemis duyurular (yeniden eskiye)."""
    sinir = date.today() - timedelta(days=get_settings().cagri_backfill_gun)
    yeni: list[DuyuruOge] = []
    sayfa = 0
    while True:
        ogeler = kaynak.liste(sayfa)
        if not ogeler:
            return yeni
        for oge in ogeler:
            if backfill:
                if oge.yayin_tarihi and oge.yayin_tarihi < sinir:
                    return yeni
                if oge.url not in bilinen and oge.url not in {o.url for o in yeni}:
                    yeni.append(oge)
            elif oge.url in bilinen:
                return yeni
            else:
                yeni.append(oge)
        sayfa += 1
        if not backfill and sayfa >= MAX_ARTAN_SAYFA:
            logger.warning("%s: %d sayfada bilinen duyuru bulunamadi, durduruluyor", kaynak.ad, sayfa)
            return yeni


def _isle(kaynak: Kaynak, oge: DuyuruOge, sayac: Counter) -> tuple[str | None, bool]:
    """Tek duyuru. Donus: (olusturulan/guncellenen cagri id'si, yeni cagri mi)."""
    if kalip := kara_liste(oge.baslik):
        sayac["kara_liste"] += 1
        _duyuru_yaz(kaynak, oge, "kara_liste", f"başlık kalıbı: {kalip}")
        return None, False
    try:
        sayfa = kaynak.detay(oge.url)
        c = cikar(sayfa.metin, sayfa.baglantilar, oge.yayin_tarihi, oge.baslik)
    except Exception as exc:  # tek duyurunun hatasi calismayi durdurmasin; sonraki calismada tekrar denenir
        logger.warning("Duyuru islenemedi (%s): %s", oge.url, exc)
        sayac["hata"] += 1
        _duyuru_yaz(kaynak, oge, "hata", f"{type(exc).__name__}: {exc}"[:500])
        return None, False

    if c.tur == "cagri_degil":
        sayac["cagri_degil"] += 1
        _duyuru_yaz(kaynak, oge, "cagri_degil", c.sebep)
        return None, False

    if c.tur == "guncelleme" and (hedef := _guncellenen_cagri(c, oge)):
        _guncellemeyi_uygula(hedef, oge, sayfa)
        sayac["guncellenen"] += 1
        _duyuru_yaz(kaynak, oge, "guncelleme", c.sebep, hedef)
        logger.info("GUNCELLEME %s -> %s", oge.baslik[:80], hedef)
        return hedef, False

    cagri_id = _cagri_yaz(kaynak, oge, sayfa, c)
    sayac["yeni"] += 1
    _duyuru_yaz(kaynak, oge, "cagri", c.sebep, cagri_id)
    logger.info("CAGRI %s", oge.baslik[:80])
    return cagri_id, True


def _duyuru_yaz(kaynak: Kaynak, oge: DuyuruOge, karar: str, sebep: str | None, cagri_id: str | None = None) -> None:
    stmt = pg_insert(duyurular).values(url=oge.url, kaynak=kaynak.ad, baslik=oge.baslik,
                                       yayin_tarihi=oge.yayin_tarihi, karar=karar, sebep=sebep, cagri_id=cagri_id)
    with get_engine().begin() as conn:
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["url"], set_={"karar": karar, "sebep": sebep, "cagri_id": cagri_id}))


def _hash(metin: str) -> str:
    return hashlib.sha256(metin.encode()).hexdigest()


def _alanlar(c: CagriCikarim, sayfa: DuyuruSayfasi) -> dict:
    """Cikarimdan cagrilar tablosuna yazilan alanlar (kimlik ve tarihce alanlari haric)."""
    return {
        "program_kodu": c.program_kodu, "program_adi": c.program_adi, "hedef_kitle": c.hedef_kitle,
        "ozet": c.ozet, "tarihler": [t.model_dump() for t in c.tarihler], "butce": c.butce, "sure": c.sure,
        "basvuru_kosullari": c.basvuru_kosullari, "baglantilar": [b.model_dump() for b in c.baglantilar],
        "metin": sayfa.metin, "icerik_hash": _hash(sayfa.metin), "son_kontrol": func.now(),
    }


def _cagri_yaz(kaynak: Kaynak, oge: DuyuruOge, sayfa: DuyuruSayfasi, c: CagriCikarim) -> str:
    cagri_id = doc_id(oge.url)
    alanlar = _alanlar(c, sayfa)
    stmt = pg_insert(cagrilar).values(id=cagri_id, kaynak=kaynak.ad, url=oge.url, baslik=oge.baslik,
                                      yayin_tarihi=oge.yayin_tarihi, **alanlar)
    with get_engine().begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=alanlar))
    return cagri_id


# --- Uzatma / guncelleme duyurulari ----------------------------------------------

# Baslik eslestirmesinde anlam tasimayan kelimeler (5 harflik kokler)
_BOS = {"cagri", "basvu", "sures", "uzati", "gunce", "takvi", "acild", "acili", "basla", "progr", "yili",
        "donem", "tubit", "kapsa", "ilisk", "bilgi", "belli", "oldu", "yayin", "deste"}


def _tokenler(baslik: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", fold(baslik))} - _BOS


def _guncellenen_cagri(c: CagriCikarim, oge: DuyuruOge) -> str | None:
    """Guncelleme duyurusunun ait oldugu kayitli cagri: ayni program kodu ve/veya baslik benzerligi.
    Bulunamazsa None (duyuru yeni cagri olarak kaydedilir)."""
    q = select(cagrilar.c.id, cagrilar.c.baslik, cagrilar.c.program_kodu).where(cagrilar.c.url != oge.url)
    if oge.yayin_tarihi:
        q = q.where(or_(cagrilar.c.yayin_tarihi.is_(None), cagrilar.c.yayin_tarihi <= oge.yayin_tarihi))
    with get_engine().connect() as conn:
        adaylar = conn.execute(q.order_by(cagrilar.c.yayin_tarihi.desc().nulls_last())).all()

    # Esikler 2025-09 / 2026-09 duyurularina gore: dogru eslesmelerde ortaklik >= 0.75; yanlis adaylar
    # yalnizca yil/donem sayilarini paylasip 0.5'te kaliyor. Ayni program kodu tek basina yetmez
    # (1001-UDAP uzatmasi, 1001 2. donem cagrisina baglanmamali).
    hedef = _tokenler(oge.baslik)
    kod = (c.program_kodu or "").strip().casefold()
    en_iyi, en_iyi_skor = None, 0.0
    for a in adaylar:
        tokenler = _tokenler(a.baslik)
        ortak = len(hedef & tokenler) / max(len(tokenler), 1)
        ayni_kod = bool(kod) and (a.program_kodu or "").strip().casefold() == kod
        if ortak < 0.7 and not (ayni_kod and ortak >= 0.5):
            continue
        skor = ortak + (0.5 if ayni_kod else 0.0)
        if skor > en_iyi_skor:  # esitlikte daha yeni olan (siralama) kalir
            en_iyi, en_iyi_skor = a.id, skor
    return en_iyi


def _guncellemeyi_uygula(cagri_id: str, oge: DuyuruOge, sayfa: DuyuruSayfasi) -> None:
    with get_engine().connect() as conn:
        mevcut = conn.execute(select(cagrilar.c.tarihler).where(cagrilar.c.id == cagri_id)).scalar_one()
    tarihler = tarihleri_birlestir(mevcut, sayfa.metin, oge.yayin_tarihi)
    with get_engine().begin() as conn:
        conn.execute(update(cagrilar).where(cagrilar.c.id == cagri_id).values(
            tarihler=tarihler,
            guncelleme_urller=func.array_append(cagrilar.c.guncelleme_urller, oge.url),
        ))


# --- Aktif cagrilarin yeniden kontrolu -------------------------------------------

def _aktifleri_kontrol_et(kaynak: Kaynak, atla: set[str], sayac: Counter) -> set[str]:
    """Acik (ve yakin zamanda eklenmis tarihi belirsiz) cagrilarin sayfasini yeniden indirir;
    metin degistiyse yeniden cikarir. Donus: icerigi degisen cagri id'leri."""
    s = get_settings()
    belirsiz_sinir = datetime.now(timezone.utc) - timedelta(days=s.cagri_belirsiz_kontrol_gun)
    with get_engine().connect() as conn:
        aktif = conn.execute(select(cagrilar).where(
            cagrilar.c.kaynak == kaynak.ad,
            or_(cagrilar.c.son_tarih >= func.current_date(),
                (cagrilar.c.son_tarih.is_(None)) & (cagrilar.c.ilk_gorulme >= belirsiz_sinir)),
        )).all()

    degisen: set[str] = set()
    for row in aktif:
        if row.id in atla:
            continue
        try:
            sayfa = kaynak.detay(row.url)
            if _hash(sayfa.metin) == row.icerik_hash:
                with get_engine().begin() as conn:
                    conn.execute(update(cagrilar).where(cagrilar.c.id == row.id).values(son_kontrol=func.now()))
                continue
            c = cikar(sayfa.metin, sayfa.baglantilar, row.yayin_tarihi, row.baslik)
            alanlar = _alanlar(c, sayfa)
            if row.guncelleme_urller:  # uzatma duyurulariyla gelen tarihler kaybolmasin
                alanlar["tarihler"] = tarihleri_birlestir(row.tarihler, sayfa.metin, row.yayin_tarihi)
            with get_engine().begin() as conn:
                conn.execute(update(cagrilar).where(cagrilar.c.id == row.id).values(**alanlar))
        except Exception as exc:
            logger.warning("Cagri yeniden kontrol edilemedi (%s): %s", row.url, exc)
            sayac["kontrol_hatasi"] += 1
            continue
        degisen.add(row.id)
        sayac["degisen"] += 1
        logger.info("DEGISTI %s", row.baslik[:80])
    return degisen


# --- Otomatik eslestirme ------------------------------------------------------------

def _otomatik_eslestir(cagri_idler: set[str], sayac: Counter) -> None:
    """Yeni ya da degisen, akademik ve suresi gecmemis cagrilar icin ilk N akademisyeni hesaplayip saklar."""
    if not cagri_idler or not get_settings().cagri_otomatik_eslestirme:
        return
    basarili, hatali = _LOOP.run_until_complete(acik_akademik_cagrilari_eslestir(cagri_idler))
    sayac["eslestirilen"] += basarili
    sayac["eslestirme_hatasi"] += hatali


def main() -> int:
    ap = argparse.ArgumentParser(description="Proje cagrilarini toplar.")
    ap.add_argument("--backfill", action="store_true", help="Son cagri_backfill_gun gunu yeniden tara")
    args = ap.parse_args()
    init_schema()
    calistir(istek_olustur("backfill" if args.backfill else "elle"), backfill=args.backfill)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        force=True)  # parser.py import aninda root logger'i yapilandiriyor
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(main())
