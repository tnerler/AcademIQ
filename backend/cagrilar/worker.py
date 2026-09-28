"""
Cagri toplama servisi (docker compose: cagri-fetcher). Her dakika:
  - "Kaynaklari tara" ile eklenen bekleyen istek varsa calistirir,
  - bugun (Turkiye saati) cagri_cekme_saati gectiyse ve bugun zamanli calisma yapilmadiysa bir tane ekler.
Tek surec calistigi icin istekler sirayla islenir; istek alma SKIP LOCKED ile yine de guvenlidir.

  uv run python -m backend.cagrilar.worker
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time

from sqlalchemy import func, select, text, update

from backend.cagrilar.db import cekme_calismalari, get_engine, init_schema
from backend.cagrilar.fetch import calistir
from backend.config import get_settings

logger = logging.getLogger("cagrilar")

TR = timezone(timedelta(hours=3))  # Turkiye 2016'dan beri yaz saati uygulamiyor
YOKLAMA_SN = 60


def _zamanli_gerekli_mi() -> bool:
    simdi = datetime.now(TR)
    if simdi.hour < get_settings().cagri_cekme_saati:
        return False
    bugun = simdi.replace(hour=0, minute=0, second=0, microsecond=0)
    with get_engine().connect() as conn:
        return not conn.execute(select(func.count()).select_from(cekme_calismalari).where(
            cekme_calismalari.c.tur.in_(["zamanli", "backfill"]),
            cekme_calismalari.c.istendi >= bugun,
        )).scalar()


def _istek_al() -> tuple[int, str] | None:
    """En eski bekleyen istegi 'calisiyor' yapip dondurur."""
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            UPDATE cekme_calismalari SET durum = 'calisiyor', basladi = now()
            WHERE id = (SELECT id FROM cekme_calismalari WHERE durum = 'bekliyor'
                        ORDER BY istendi LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING id, tur""")).first()
    return (row.id, row.tur) if row else None


def main() -> None:
    init_schema()
    with get_engine().begin() as conn:  # onceki surec calisirken durduysa
        n = conn.execute(update(cekme_calismalari).where(cekme_calismalari.c.durum == "calisiyor")
                         .values(durum="hata", bitti=func.now(), hata="Servis yeniden basladi, calisma yarida kaldi")
                         ).rowcount
    if n:
        logger.warning("%d yarida kalmis calisma 'hata' olarak isaretlendi", n)
    logger.info("Cagri toplama servisi basladi (her gun %02d:00 TSI)", get_settings().cagri_cekme_saati)

    while True:
        try:
            if _zamanli_gerekli_mi():
                with get_engine().begin() as conn:
                    conn.execute(cekme_calismalari.insert().values(tur="zamanli"))
            while istek := _istek_al():
                calisma_id, tur = istek
                logger.info("Calisma %d basliyor (%s)", calisma_id, tur)
                try:
                    calistir(calisma_id, backfill=tur == "backfill")
                except Exception:
                    pass  # calistir hatayi kaydedip logladi; servis ayakta kalir
        except Exception:
            logger.exception("Servis dongusunde hata")  # ör. DB gecici olarak erisilemez
        time.sleep(YOKLAMA_SN)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        force=True)  # parser.py import aninda root logger'i yapilandiriyor
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
