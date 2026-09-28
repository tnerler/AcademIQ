"""CV'ler modulu: kayitli akademisyen listesi, detay, PDF onizleme ve CV yukleme."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.api.schemas import CVCikarim, HocaDetay, HocaOzet, ProfilOzeti
from backend.api.uploads import read_cv_file
from backend.config import PROJECT_ROOT
from backend.indexing.upload import CVOkunamadi, analiz_et, kaydet
from backend.matching.pipeline import hoca_ozet
from backend.vectorstore import doc_id, get_profile_store

router = APIRouter(prefix="/api/cvs", tags=["CV'ler"])


def _get_meta(hoca_id: str) -> dict:
    result = get_profile_store().get_by_ids([doc_id(hoca_id)])
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Akademisyen bulunamadi: {hoca_id}")
    return result[0].metadata


@router.get("", response_model=list[HocaOzet], summary="Kayitli akademisyenlerin listesi")
def list_cvs() -> list[HocaOzet]:
    data = get_profile_store().get(include=["metadatas"])
    return sorted((hoca_ozet(m) for m in data["metadatas"]), key=lambda h: h.id)


@router.get("/{hoca_id}", response_model=HocaDetay, summary="Akademisyen detayi ve profil ozeti")
def get_cv(hoca_id: str) -> HocaDetay:
    meta = _get_meta(hoca_id)
    return HocaDetay(
        **hoca_ozet(meta).model_dump(),
        email=meta.get("email"),
        profil=ProfilOzeti(**meta["profil"]) if meta.get("profil") else None,
        cv=CVCikarim(**meta["cv"]) if meta.get("cv") else None,
        pdf_url=f"/api/cvs/{hoca_id}/pdf" if _onizleme(meta) else None,
    )


def _onizleme(meta: dict) -> str | None:
    """CV onizleme PDF'i: .docx CV'ler icin uretilen PDF, PDF CV'lerde kaynagin kendisi."""
    if meta.get("onizleme_pdf"):
        return meta["onizleme_pdf"]
    kaynak = meta.get("kaynak_pdf", "")
    return kaynak if kaynak.lower().endswith(".pdf") else None


@router.get("/{hoca_id}/pdf", response_class=FileResponse, summary="CV PDF onizleme (inline)")
def get_cv_pdf(hoca_id: str) -> FileResponse:
    onizleme = _onizleme(_get_meta(hoca_id))
    path = (PROJECT_ROOT / onizleme).resolve() if onizleme else None
    if not path or not path.is_file() or not path.is_relative_to(PROJECT_ROOT):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV onizlemesi bulunamadi")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


@router.post("", response_model=HocaDetay, status_code=status.HTTP_201_CREATED,
             summary="CV yukle (PDF / .docx): indeksleyip hoca havuzuna ekler (ayni e-posta varsa gunceller)")
async def upload_cv(file: UploadFile = File(..., description="Akademisyen CV'si (PDF ya da .docx)")) -> HocaDetay:
    data, uzanti = await read_cv_file(file)
    try:
        a = await asyncio.to_thread(analiz_et, data, uzanti)
        hoca_id = await asyncio.to_thread(kaydet, a)
    except CVOkunamadi as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return get_cv(hoca_id)
