"""Eslestir sayfasindaki sohbet asistani."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.api.routes_match import MAX_METIN_CHARS
from backend.api.schemas import SohbetIstegi, SohbetYaniti
from backend.sohbet.akis import yanitla

router = APIRouter(prefix="/api", tags=["Eşleştir"])


@router.post("/sohbet", response_model=SohbetYaniti,
             summary="Sohbet: ilan metni, alan araması ya da bir akademisyen hakkında soru")
async def sohbet(istek: SohbetIstegi) -> SohbetYaniti:
    mesaj = istek.mesaj.strip()
    if not mesaj:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mesaj boş olamaz")
    if len(mesaj) > MAX_METIN_CHARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Mesaj en fazla {MAX_METIN_CHARS} karakter olabilir")
    return await yanitla(mesaj, istek.gecmis)
