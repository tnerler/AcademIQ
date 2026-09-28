"""Proje Ilanlari: otomatik toplanan cagrilar, filtreler ve "Kaynaklari tara" tetiklemesi."""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy import Select, case, func, insert, or_, select

from backend.api.schemas import CagriDetay, CagriListe, CekmeCalismasi, ProgramOzet, TaramaDurumu
from backend.cagrilar.db import cagri_eslesmeleri, cagrilar, cekme_calismalari, durum, get_engine
from backend.config import get_settings

router = APIRouter(prefix="/api/cagrilar", tags=["Proje İlanları"])

_TARA_LOCK_ID = 7_310_002
# Liste detay alanlarini da dondurur (satir acilinca ayri istek gerekmesin); sayfa metni haric
_KOLONLAR = [c for c in cagrilar.c if c.name in CagriDetay.model_fields]

# Acik cagrilar son tarihe yakin olan once, sonra tarihi belirsizler (yeni once), en sonda gecmisler (yeni once)
_SIRA = [
    case((durum == "acik", 0), (durum == "belirsiz", 1), else_=2),
    case((durum == "acik", cagrilar.c.son_tarih)),
    cagrilar.c.son_tarih.desc().nulls_last(),
    cagrilar.c.yayin_tarihi.desc().nulls_last(),
]


def _uygun_hocalar(sonuc: dict | None) -> list[str]:
    return [s["hoca"]["ad_soyad"] for s in (sonuc or {}).get("sonuclar", [])]


def _filtrele(q: Select, durum_: str | None, hedef_kitle: str | None, program: str | None, ara: str | None) -> Select:
    if durum_:
        q = q.where(durum == durum_)
    if hedef_kitle:
        q = q.where(cagrilar.c.hedef_kitle == hedef_kitle)
    if program:
        q = q.where(cagrilar.c.program_kodu == program)
    if ara and ara.strip():
        kalip = f"%{ara.strip()}%"
        q = q.where(or_(*(col.ilike(kalip) for col in (
            cagrilar.c.baslik, cagrilar.c.ozet, cagrilar.c.program_adi, cagrilar.c.program_kodu))))
    return q


@router.get("", response_model=CagriListe, summary="Toplanan proje cagrilari (filtreli, sayfali)")
def list_cagrilar(
    durum_: Literal["acik", "gecmis", "belirsiz"] | None = Query(None, alias="durum"),
    hedef_kitle: Literal["akademik", "sanayi"] | None = None,
    program: str | None = Query(None, description="Program kodu, ör. 1001"),
    q: str | None = Query(None, description="Başlık, özet ve programda arama"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CagriListe:
    base = _filtrele(select(*_KOLONLAR, durum, cagri_eslesmeleri.c.sonuc)
                     .outerjoin(cagri_eslesmeleri, cagri_eslesmeleri.c.cagri_id == cagrilar.c.id),
                     durum_, hedef_kitle, program, q)
    with get_engine().connect() as conn:
        toplam = conn.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        rows = conn.execute(base.order_by(*_SIRA).limit(limit).offset(offset)).mappings().all()
    return CagriListe(toplam=toplam, cagrilar=[
        CagriDetay(**{k: v for k, v in r.items() if k != "sonuc"}, uygun_hocalar=_uygun_hocalar(r["sonuc"]))
        for r in rows
    ])


@router.get("/programlar", response_model=list[ProgramOzet], summary="Filtre icin program kodlari")
def list_programlar() -> list[ProgramOzet]:
    q = (select(cagrilar.c.program_kodu.label("kod"), func.max(cagrilar.c.program_adi).label("ad"),
                func.count().label("sayi"))
         .where(cagrilar.c.program_kodu.is_not(None))
         .group_by(cagrilar.c.program_kodu)
         .order_by(func.count().desc(), cagrilar.c.program_kodu))
    with get_engine().connect() as conn:
        return [ProgramOzet(**r) for r in conn.execute(q).mappings()]


@router.get("/tarama", response_model=TaramaDurumu, summary="Son cagri toplama calismasinin durumu")
def tarama_durumu() -> TaramaDurumu:
    with get_engine().connect() as conn:
        son = conn.execute(select(cekme_calismalari).order_by(cekme_calismalari.c.id.desc()).limit(1)).mappings().first()
        son_basarili = conn.execute(select(func.max(cekme_calismalari.c.bitti))
                                    .where(cekme_calismalari.c.durum == "bitti")).scalar()
    return TaramaDurumu(son=CekmeCalismasi(**son) if son else None, son_basarili=son_basarili)


@router.post("/tara", response_model=CekmeCalismasi, status_code=status.HTTP_202_ACCEPTED,
             summary="Kaynaklari simdi tara (admin token gerekir)")
def tara(x_admin_token: str | None = Header(None, description="ADMIN_TOKEN (.env)")) -> CekmeCalismasi:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Elle tarama kapali: sunucuda ADMIN_TOKEN tanimli degil")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Yonetici anahtari hatali")

    with get_engine().begin() as conn:
        conn.execute(select(func.pg_advisory_xact_lock(_TARA_LOCK_ID)))  # es zamanli iki tiklama tek istek olsun
        aktif = conn.execute(select(cekme_calismalari.c.id)
                             .where(cekme_calismalari.c.durum.in_(["bekliyor", "calisiyor"]))).first()
        if aktif:
            raise HTTPException(status.HTTP_409_CONFLICT, "Zaten bekleyen ya da devam eden bir tarama var")
        row = conn.execute(insert(cekme_calismalari).values(tur="elle").returning(*cekme_calismalari.c)).mappings().one()
    return CekmeCalismasi(**row)


@router.get("/{cagri_id}", response_model=CagriDetay, summary="Cagri detayi")
def get_cagri(cagri_id: str) -> CagriDetay:
    q = (select(*_KOLONLAR, durum, cagri_eslesmeleri.c.sonuc)
         .outerjoin(cagri_eslesmeleri, cagri_eslesmeleri.c.cagri_id == cagrilar.c.id)
         .where(cagrilar.c.id == cagri_id))
    with get_engine().connect() as conn:
        r = conn.execute(q).mappings().first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Cagri bulunamadi: {cagri_id}")
    return CagriDetay(**{k: v for k, v in r.items() if k != "sonuc"}, uygun_hocalar=_uygun_hocalar(r["sonuc"]))
