"""Yuklenen dosyalarin ortak dogrulamasi: ilan (PDF), CV (PDF ya da .docx)."""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

MAX_PDF_BYTES = 20 * 1024 * 1024


async def read_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Yalnizca PDF dosyasi yuklenebilir")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "PDF en fazla 20 MB olabilir")
    return data


async def read_cv_file(file: UploadFile) -> tuple[bytes, str]:
    """CV: PDF ya da Word (.docx). Donus: (icerik, uzanti)."""
    data = await file.read()
    if data.startswith(b"%PDF"):
        uzanti = ".pdf"
    elif data.startswith(b"PK") and (file.filename or "").lower().endswith(".docx"):
        uzanti = ".docx"
    else:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Yalnizca PDF ya da Word (.docx) CV yuklenebilir")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Dosya en fazla 20 MB olabilir")
    return data, uzanti
