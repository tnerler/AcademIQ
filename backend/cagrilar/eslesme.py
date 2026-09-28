"""Toplanan bir cagri icin akademisyen eslestirmesi (sonuc cagri_eslesmeleri'nde saklanir)."""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.api.schemas import MatchResponse
from backend.cagrilar.db import cagri_eslesmeleri, cagrilar, get_engine
from backend.matching.pipeline import match_text
from backend.matching.search import refresh_bm25

logger = logging.getLogger("cagrilar")


class CagriBulunamadi(LookupError):
    pass


def kayitli_eslesme(cagri_id: str) -> MatchResponse | None:
    with get_engine().connect() as conn:
        row = conn.execute(select(cagri_eslesmeleri).where(cagri_eslesmeleri.c.cagri_id == cagri_id)).first()
    if row is None:
        return None
    return MatchResponse.model_validate(row.sonuc).model_copy(update={"olusturuldu": row.olusturuldu})


async def cagri_eslestir(cagri_id: str, yenile: bool = False) -> MatchResponse:
    """Kayitli sonuc varsa onu dondurur; yoksa (ya da yenile=True) cagri metniyle eslestirip kaydeder."""
    if not yenile and (kayitli := kayitli_eslesme(cagri_id)):
        return kayitli
    with get_engine().connect() as conn:
        metin = conn.execute(select(cagrilar.c.metin).where(cagrilar.c.id == cagri_id)).scalar()
    if metin is None:
        raise CagriBulunamadi(cagri_id)

    sonuc = await match_text(metin)
    with get_engine().begin() as conn:
        stmt = insert(cagri_eslesmeleri).values(cagri_id=cagri_id, sonuc=sonuc.model_dump(mode="json"))
        row = conn.execute(
            stmt.on_conflict_do_update(index_elements=["cagri_id"],
                                       set_={"sonuc": stmt.excluded.sonuc, "olusturuldu": stmt.excluded.olusturuldu})
            .returning(cagri_eslesmeleri.c.olusturuldu)
        ).one()
    return sonuc.model_copy(update={"olusturuldu": row.olusturuldu})


def eslesmeyi_sil(cagri_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(delete(cagri_eslesmeleri).where(cagri_eslesmeleri.c.cagri_id == cagri_id))


def tum_eslesmeleri_sil() -> None:
    """Hoca havuzu degisince (CV indeksleme) kayitli sonuclarin hepsi gecersiz olur."""
    with get_engine().begin() as conn:
        conn.execute(delete(cagri_eslesmeleri))


async def acik_akademik_cagrilari_eslestir(cagri_idler: set[str] | None = None) -> tuple[int, int]:
    """Verilen (None: tum) cagrilardan akademik ve suresi gecmemis olanlar icin ilk N akademisyeni
    hesaplayip saklar. Donus: (basarili, hatali)."""
    q = select(cagrilar.c.id).where(
        cagrilar.c.hedef_kitle == "akademik",
        or_(cagrilar.c.son_tarih.is_(None), cagrilar.c.son_tarih >= func.current_date()),
    )
    if cagri_idler is not None:
        if not cagri_idler:
            return 0, 0
        q = q.where(cagrilar.c.id.in_(cagri_idler))
    with get_engine().connect() as conn:
        hedefler = conn.execute(q).scalars().all()
    if not hedefler:
        return 0, 0
    refresh_bm25()  # CV'ler baska bir surecte indekslenmis olabilir

    basarili = hatali = 0
    for cagri_id in hedefler:
        try:
            await cagri_eslestir(cagri_id, yenile=True)
            basarili += 1
        except Exception as exc:
            logger.warning("Otomatik eslestirme basarisiz (%s): %s", cagri_id, exc)
            hatali += 1
    return basarili, hatali
