"""
YOK tarama servisi (docker compose: yok-worker). Birkac saniyede bir:
  - "YOK'u kontrol et" ile eklenen bekleyen tarama varsa calistirir,
  - haftalik tam tarama zamani geldiyse (yok_tam_tarama_gunu/saati, Turkiye saati) bir tane ekler.
Her taramadan sonra (ve acilista) degisen hocalar eslestirme havuzuna indekslenir (backend/yok/index.py).
Cagri servisinden ayri: tam tarama ~2 saat surer, cagri toplamayi bekletmemeli.
Butona basinca hizli tarama hemen baslasin diye yoklama araligi kisa (sorgu ucuz).

  uv run python -m backend.yok.worker
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time

from sqlalchemy import func, select, text, update

from backend.cagrilar.db import get_engine
from backend.config import get_settings
from backend.yok.db import bos_mu, ice_aktar, init_schema, yok_taramalari
from backend.yok.tarama import calistir

logger = logging.getLogger("yok")

TR = timezone(timedelta(hours=3))
YOKLAMA_SN = 5


def _zamanli_gerekli_mi() -> bool:
    s = get_settings()
    simdi = datetime.now(TR)
    if simdi.weekday() != s.yok_tam_tarama_gunu or simdi.hour < s.yok_tam_tarama_saati:
        return False
    bugun = simdi.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_engine().connect() as conn:
        return not conn.execute(select(func.count()).select_from(yok_taramalari).where(
            yok_taramalari.c.kaynak == "zamanli", yok_taramalari.c.istendi >= bugun,
        )).scalar()


def _istek_al() -> int | None:
    """En eski bekleyen taramayi 'calisiyor' yapip id'sini dondurur."""
    with get_engine().begin() as conn:
        return conn.execute(text("""
            UPDATE yok_taramalari SET durum = 'calisiyor', basladi = now()
            WHERE id = (SELECT id FROM yok_taramalari WHERE durum = 'bekliyor'
                        ORDER BY istendi LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING id""")).scalar()


def indeksle() -> None:
    """Degisen YOK hocalarini havuza yazar; bir sey degistiyse kayitli cagri eslestirmelerini yeniler."""
    from backend.indexing.index_cvs import eslesmeleri_yenile
    from backend.yok.index import senkronize

    try:
        sayac = senkronize()
        logger.info("YOK indeks: %s", sayac)
        if sayac["islenen"] or sayac["silinen"]:
            eslesmeleri_yenile()
    except Exception:
        logger.exception("YOK indeksleme hatasi")  # bir sonraki taramada yeniden denenir


def main() -> None:
    init_schema()
    ilk = get_settings().yok_ilk_veri
    if bos_mu() and ilk.exists():
        logger.info("Son bilinen durum bos: %s ice aktariliyor", ilk)
        logger.info("%d akademisyen ice aktarildi", ice_aktar(ilk))

    with get_engine().begin() as conn:  # onceki surec calisirken durduysa
        n = conn.execute(update(yok_taramalari).where(yok_taramalari.c.durum == "calisiyor")
                         .values(durum="hata", bitti=func.now(),
                                 hata="Servis yeniden basladi, tarama yarida kaldi (o ana kadarki degisiklikler kaydedildi)")
                         ).rowcount
    if n:
        logger.warning("%d yarida kalmis tarama 'hata' olarak isaretlendi", n)
    s = get_settings()
    logger.info("YOK tarama servisi basladi (tam tarama: haftanin %d. gunu %02d:00 TSI)",
                s.yok_tam_tarama_gunu, s.yok_tam_tarama_saati)
    indeksle()  # ilk kurulumda (ya da servis kapaliyken degisen veri varsa) havuzu gunceller

    while True:
        try:
            if _zamanli_gerekli_mi():
                with get_engine().begin() as conn:
                    conn.execute(yok_taramalari.insert().values(tur="tam", kaynak="zamanli"))
            while (tarama_id := _istek_al()) is not None:
                logger.info("YOK taramasi %d basliyor", tarama_id)
                try:
                    calistir(tarama_id)
                except Exception:
                    pass  # calistir hatayi kaydedip logladi; servis ayakta kalir
                indeksle()  # yarida kalan taramada da o ana kadarki degisiklikler kaydedildi
        except Exception:
            logger.exception("Servis dongusunde hata")
        time.sleep(YOKLAMA_SN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
