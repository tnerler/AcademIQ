"""YOK Akademik guncellik kontrolu: "YOK'u kontrol et" tetiklemesi ve son taramanin raporu."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import func, insert, select

from backend.api.schemas import YokTarama, YokTaramaDurumu
from backend.cagrilar.db import get_engine
from backend.config import get_settings
from backend.yok.db import yok_akademisyenler, yok_taramalari

router = APIRouter(prefix="/api/yok", tags=["YÖK Akademik"])

_TARA_LOCK_ID = 7_310_102


def _tarama(row) -> YokTarama:
    return YokTarama(**row)  # limit_ gibi fazla kolonlar yok sayilir


@router.get("/tarama", response_model=YokTaramaDurumu, summary="Süren ve son biten YÖK taraması (raporlarıyla)")
def tarama_durumu() -> YokTaramaDurumu:
    t = yok_taramalari.c
    with get_engine().connect() as conn:
        aktif = conn.execute(select(yok_taramalari).where(t.durum.in_(["bekliyor", "calisiyor"]))
                             .order_by(t.id).limit(1)).mappings().first()
        son = conn.execute(select(yok_taramalari).where(t.durum.in_(["bitti", "hata"]))
                           .order_by(t.id.desc()).limit(1)).mappings().first()
        son_tam = conn.execute(select(func.max(t.bitti)).where(t.tur == "tam", t.durum == "bitti")).scalar()
        sayi = conn.execute(select(func.count()).select_from(yok_akademisyenler).where(
            yok_akademisyenler.c.aktif, yok_akademisyenler.c.universite == get_settings().yok_universite)).scalar()
    return YokTaramaDurumu(aktif=_tarama(aktif) if aktif else None, son_biten=_tarama(son) if son else None,
                           son_tam=son_tam, akademisyen_sayisi=sayi)


@router.post("/tara", response_model=YokTarama, status_code=status.HTTP_202_ACCEPTED,
             summary="YÖK'ü şimdi tara (admin token gerekir)")
def tara(
    tur: Literal["hizli", "tam"] = Query("hizli", description="hizli: ~1 dk, sadece liste; tam: ~2 saat"),
    limit: int | None = Query(None, ge=1, description="Test için: tam taramada en fazla bu kadar hocanın detayı"),
    x_admin_token: str | None = Header(None, description="ADMIN_TOKEN (.env)"),
) -> YokTarama:
    s = get_settings()
    if not s.admin_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Elle tarama kapalı: sunucuda ADMIN_TOKEN tanımlı değil")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, s.admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Yönetici anahtarı hatalı")

    t = yok_taramalari.c
    with get_engine().begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(_TARA_LOCK_ID)))  # es zamanli iki tiklama tek istek olsun
        if conn.execute(select(t.id).where(t.durum.in_(["bekliyor", "calisiyor"]))).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Zaten bekleyen ya da devam eden bir YÖK taraması var")
        son = conn.execute(select(func.max(t.istendi)).where(t.kaynak == "elle")).scalar()
        bekleme = timedelta(minutes=s.yok_tarama_bekleme_dk)
        if son and datetime.now(timezone.utc) - son < bekleme:
            kalan = int((son + bekleme - datetime.now(timezone.utc)).total_seconds() // 60) + 1
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"YÖK'ün bot koruması için taramalar arasında {s.yok_tarama_bekleme_dk} dk "
                                f"beklenmeli. {kalan} dk sonra tekrar deneyin.")
        row = conn.execute(insert(yok_taramalari).values(tur=tur, kaynak="elle", limit_=limit)
                           .returning(*yok_taramalari.c)).mappings().one()
    return _tarama(row)
