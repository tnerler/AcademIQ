"""
Cagri toplama tablolari (SQLAlchemy Core).

Sema db/cagrilar.sql'de; buradaki Table tanimlari yalnizca sorgu yazmak icindir ve
SQL dosyasiyla ayni tutulmalidir. Vektor tablolarindaki PGEngine kendi event loop'unda
async calistigi icin burada ayni baglanti adresiyle ayri bir sync engine kullanilir.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import (ARRAY, Column, Date, DateTime, Engine, Integer, MetaData, Table, Text, case,
                        create_engine, func, text)
from sqlalchemy.dialects.postgresql import JSONB

from backend.config import PROJECT_ROOT, get_settings

SCHEMA_SQL = PROJECT_ROOT / "db" / "cagrilar.sql"
_SCHEMA_LOCK_ID = 7_310_001  # backend ve fetcher ayni anda acilirsa sema tek seferde uygulansin

metadata = MetaData()

cagrilar = Table(
    "cagrilar", metadata,
    Column("id", Text, primary_key=True),
    Column("kaynak", Text, nullable=False),
    Column("url", Text, nullable=False, unique=True),
    Column("baslik", Text, nullable=False),
    Column("program_kodu", Text),
    Column("program_adi", Text),
    Column("hedef_kitle", Text, nullable=False),
    Column("ozet", Text),
    Column("tarihler", JSONB, nullable=False),
    Column("son_tarih", Date),  # generated: cagri_son_tarih(tarihler), yazilmaz
    Column("butce", Text),
    Column("sure", Text),
    Column("basvuru_kosullari", ARRAY(Text), nullable=False),
    Column("baglantilar", JSONB, nullable=False),
    Column("metin", Text, nullable=False),
    Column("icerik_hash", Text, nullable=False),
    Column("guncelleme_urller", ARRAY(Text), nullable=False),
    Column("yayin_tarihi", Date),
    Column("ilk_gorulme", DateTime(timezone=True), nullable=False),
    Column("son_kontrol", DateTime(timezone=True)),
)

duyurular = Table(
    "duyurular", metadata,
    Column("url", Text, primary_key=True),
    Column("kaynak", Text, nullable=False),
    Column("baslik", Text, nullable=False),
    Column("yayin_tarihi", Date),
    Column("ilk_gorulme", DateTime(timezone=True), nullable=False),
    Column("karar", Text, nullable=False),
    Column("sebep", Text),
    Column("cagri_id", Text),
)

cekme_calismalari = Table(
    "cekme_calismalari", metadata,
    Column("id", Integer, primary_key=True),
    Column("tur", Text, nullable=False),
    Column("durum", Text, nullable=False),
    Column("istendi", DateTime(timezone=True), nullable=False),
    Column("basladi", DateTime(timezone=True)),
    Column("bitti", DateTime(timezone=True)),
    Column("sayilar", JSONB),
    Column("hata", Text),
)

cagri_eslesmeleri = Table(
    "cagri_eslesmeleri", metadata,
    Column("cagri_id", Text, primary_key=True),
    Column("sonuc", JSONB, nullable=False),
    Column("olusturuldu", DateTime(timezone=True), nullable=False),
)

# Durum yazilmaz, sorgu aninda hesaplanir: tum tarihler gecince 'gecmis', tarih yoksa 'belirsiz'
durum = case(
    (cagrilar.c.son_tarih.is_(None), "belirsiz"),
    (cagrilar.c.son_tarih >= func.current_date(), "acik"),
    else_="gecmis",
).label("durum")


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def init_schema() -> None:
    """db/cagrilar.sql'i uygular (idempotent)."""
    with get_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _SCHEMA_LOCK_ID})
        conn.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
