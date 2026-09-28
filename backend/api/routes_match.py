"""Eslestir modulu (ilan PDF'i, metin ya da toplanan bir cagri), Bana Uygun ve Ilan Ekle (pasif, 501)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from backend.api.schemas import BanaUygunResponse, MatchResponse, ProfilOzeti
from backend.api.uploads import read_cv_file, read_pdf
from backend.cagrilar.bana_uygun import bana_uygun
from backend.cagrilar.eslesme import CagriBulunamadi, cagri_eslestir
from backend.indexing.upload import CVOkunamadi, analiz_et, kaydet
from backend.matching.pipeline import match, match_text

MAX_METIN_CHARS = 3000

router = APIRouter(prefix="/api", tags=["Eşleştir"])


@router.post("/match", response_model=MatchResponse,
             summary="Proje ilanina (PDF, metin ya da toplanan cagri) en uygun akademisyenler")
async def match_ilan(
    file: UploadFile | None = File(None, description="Proje ilani (PDF)"),
    metin: str | None = Form(None, description="Proje ilani duz metin (PDF yerine)"),
    cagri_id: str | None = Form(None, description="Toplanan cagri; metin DB'den alinir, sonuc saklanir"),
    yenile: bool = Form(False, description="cagri_id ile: kayitli sonucu kullanmadan yeniden hesapla"),
) -> MatchResponse:
    if file is not None:
        return await match(await read_pdf(file))

    if cagri_id:
        try:
            return await cagri_eslestir(cagri_id, yenile=yenile)
        except CagriBulunamadi:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cagri bulunamadi: {cagri_id}") from None

    metin = (metin or "").strip()
    if not metin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bir PDF dosyasi ya da ilan metni gonderin")
    if len(metin) > MAX_METIN_CHARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Ilan metni en fazla {MAX_METIN_CHARS} karakter olabilir")
    return await match_text(metin)


@router.post("/bana-uygun", response_model=BanaUygunResponse, tags=["Bana Uygun"],
             summary="CV'ye (PDF / .docx) en uygun acik proje cagrilari")
async def bana_uygun_cagrilar(
    file: UploadFile = File(..., description="Akademisyen CV'si (PDF ya da .docx)"),
    kaydet_: bool = Form(False, alias="kaydet", description="CV'yi hoca havuzuna da kaydet"),
    sadece_acik: bool = Form(True, description="Yalnizca basvurusu acik (ya da tarihi belirsiz) cagrilar"),
) -> BanaUygunResponse:
    data, uzanti = await read_cv_file(file)
    try:
        a = await asyncio.to_thread(analiz_et, data, uzanti)
        hoca_id = await asyncio.to_thread(kaydet, a) if kaydet_ else None
    except CVOkunamadi as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return BanaUygunResponse(
        ad_soyad=a.cv.cikarim.kimlik.ad_soyad or None,
        profil=ProfilOzeti(**a.cv.profile.model_dump()),
        hoca_id=hoca_id,
        sonuclar=await bana_uygun(a.cv.profile, sadece_acik=sadece_acik),
    )


@router.post("/ilanlar", status_code=status.HTTP_501_NOT_IMPLEMENTED, tags=["Proje İlanları"],
             summary="Ilan ekle (pasif modul)")
def add_ilan() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Ilan ekleme bu asamada devre disi")
