"""CV'ler modulu (aktif): kayitli akademisyen listesi, detay ve PDF onizleme.
CV Yukle (pasif): bu asamada tum CV'ler arka planda indekslendigi icin 501 doner."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from backend.api.schemas import HocaDetay, HocaOzet, ProfilOzeti
from backend.config import PROJECT_ROOT
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
        pdf_url=f"/api/cvs/{hoca_id}/pdf",
    )


@router.get("/{hoca_id}/pdf", response_class=FileResponse, summary="CV PDF onizleme (inline)")
def get_cv_pdf(hoca_id: str) -> FileResponse:
    path = (PROJECT_ROOT / _get_meta(hoca_id)["kaynak_pdf"]).resolve()
    if not path.is_file() or not path.is_relative_to(PROJECT_ROOT):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF dosyasi bulunamadi")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED, summary="CV Yukle (pasif modul)")
def upload_cv() -> None:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "CV yukleme bu asamada devre disi")
