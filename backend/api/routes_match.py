"""Eslestir modulu (aktif) ve Proje Ilanlari / Ilan Ekle (pasif, 501)."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from backend.api.schemas import MatchResponse
from backend.matching.pipeline import match, match_text

MAX_PDF_BYTES = 20 * 1024 * 1024
MIN_METIN_CHARS = 100
MAX_METIN_CHARS = 3000

router = APIRouter(prefix="/api", tags=["Eşleştir"])


@router.post("/match", response_model=MatchResponse, summary="Proje ilanina (PDF ya da metin) en uygun akademisyenler")
async def match_ilan(
    file: UploadFile | None = File(None, description="Proje ilani (PDF)"),
    metin: str | None = Form(None, description="Proje ilani duz metin (PDF yerine)"),
) -> MatchResponse:
    if file is not None:
        data = await file.read()
        if not data.startswith(b"%PDF"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Yalnizca PDF dosyasi yuklenebilir")
        if len(data) > MAX_PDF_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "PDF en fazla 20 MB olabilir")
        return await match(data)

    metin = (metin or "").strip()
    if not metin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bir PDF dosyasi ya da ilan metni gonderin")
    if not MIN_METIN_CHARS <= len(metin) <= MAX_METIN_CHARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Ilan metni {MIN_METIN_CHARS}-{MAX_METIN_CHARS} karakter arasinda olmali")
    return await match_text(metin)


@router.get("/ilanlar", status_code=status.HTTP_501_NOT_IMPLEMENTED, tags=["Proje İlanları"],
            summary="Proje ilanlari listesi (pasif modul)")
def list_ilanlar() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Proje ilanlari bu asamada devre disi")


@router.post("/ilanlar", status_code=status.HTTP_501_NOT_IMPLEMENTED, tags=["Proje İlanları"],
             summary="Ilan ekle (pasif modul)")
def add_ilan() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Ilan ekleme bu asamada devre disi")
