"""Cagri vektor indeksi ("Bana Uygun": CV profili -> cagri aramasi). Id'ler cagrilar.id ile ayni."""

from __future__ import annotations

from collections.abc import Mapping

from langchain_core.documents import Document
from sqlalchemy import select

from backend.cagrilar.db import cagrilar, get_engine
from backend.vectorstore import get_cagri_store, init_cagri_table

MAX_CHARS = 6000  # embedding'e giden metin: baslik + program + ozet + sayfa metninin basi


def cagri_metni(r: Mapping) -> str:
    program = " ".join(filter(None, [r["program_kodu"], r["program_adi"]]))
    return "\n".join(filter(None, [r["baslik"], program, r["ozet"], r["metin"]]))[:MAX_CHARS]


def cagrilari_indeksle(cagri_idler: set[str]) -> None:
    if not cagri_idler:
        return
    with get_engine().connect() as conn:
        rows = conn.execute(select(cagrilar).where(cagrilar.c.id.in_(cagri_idler))).mappings().all()
    init_cagri_table()
    get_cagri_store().add_documents(
        [Document(page_content=cagri_metni(r), metadata={"hedef_kitle": r["hedef_kitle"]}) for r in rows],
        ids=[r["id"] for r in rows],
    )


def tumunu_indeksle() -> int:
    """Eksik ya da bozuk indeksi bastan kurar: uv run python -m backend.cagrilar.index"""
    with get_engine().connect() as conn:
        ids = set(conn.execute(select(cagrilar.c.id)).scalars())
    cagrilari_indeksle(ids)
    return len(ids)


if __name__ == "__main__":
    print(f"{tumunu_indeksle()} cagri indekslendi")
