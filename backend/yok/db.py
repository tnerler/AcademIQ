"""
YOK Akademik tablolari (SQLAlchemy Core). Sema db/yok.sql'de; Table tanimlari onunla ayni tutulmalidir.
Engine cagri modulununkiyle ortaktir (ayni veritabani).

Ilk kurulumda son bilinen durum, scraper'in urettigi JSON'dan yuklenir:
  uv run python -m backend.yok.db --ice-aktar data/yok/pirireis_akademisyenler.json
(yok-worker tablo bossa ve dosya varsa bunu kendisi yapar.)
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, Table, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert

from backend.cagrilar.db import get_engine
from backend.config import PROJECT_ROOT
from backend.yok.scrape import SEKMELER

logger = logging.getLogger("yok")

SCHEMA_SQL = PROJECT_ROOT / "db" / "yok.sql"
_SCHEMA_LOCK_ID = 7_310_101

metadata = MetaData()

yok_akademisyenler = Table(
    "yok_akademisyenler", metadata,
    Column("author_id", Text, primary_key=True),
    Column("universite", Text, nullable=False),
    Column("veri", JSONB, nullable=False),
    Column("detay_var", Boolean, nullable=False),
    Column("aktif", Boolean, nullable=False),
    Column("ilk_gorulme", DateTime(timezone=True), nullable=False),
    Column("son_gorulme", DateTime(timezone=True), nullable=False),
    Column("detay_zamani", DateTime(timezone=True)),
)

yok_taramalari = Table(
    "yok_taramalari", metadata,
    Column("id", Integer, primary_key=True),
    Column("tur", Text, nullable=False),
    Column("kaynak", Text, nullable=False),
    Column("durum", Text, nullable=False),
    Column("limit_", Integer),
    Column("istendi", DateTime(timezone=True), nullable=False),
    Column("basladi", DateTime(timezone=True)),
    Column("bitti", DateTime(timezone=True)),
    Column("ilerleme", JSONB),
    Column("ozet", JSONB),
    Column("rapor", JSONB),
    Column("hata", Text),
)


def init_schema() -> None:
    """db/yok.sql'i uygular (idempotent)."""
    with get_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _SCHEMA_LOCK_ID})
        conn.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))


def detay_var_mi(kisi: dict) -> bool:
    return all(alan in kisi for alan in SEKMELER.values())


def ice_aktar(yol: Path) -> int:
    """Scraper JSON'unu son bilinen durum olarak yazar (var olan hocalarin verisi degistirilir)."""
    veri = json.loads(yol.read_text(encoding="utf-8"))
    cekilme = datetime.fromisoformat(veri["cekilme_zamani"])
    satirlar = [
        {"author_id": k["author_id"], "universite": veri["universite"], "veri": k, "detay_var": detay_var_mi(k),
         "aktif": True, "detay_zamani": cekilme if detay_var_mi(k) else None}
        for k in veri["akademisyenler"]
    ]
    if not satirlar:
        return 0
    q = pg_insert(yok_akademisyenler).values(satirlar)
    q = q.on_conflict_do_update(index_elements=["author_id"], set_={
        "veri": q.excluded.veri, "detay_var": q.excluded.detay_var, "aktif": True,
        "son_gorulme": func.now(), "detay_zamani": q.excluded.detay_zamani,
    })
    with get_engine().begin() as conn:
        conn.execute(q)
    return len(satirlar)


def bos_mu() -> bool:
    with get_engine().connect() as conn:
        return not conn.execute(select(func.count()).select_from(yok_akademisyenler)).scalar()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ice-aktar", type=Path, required=True, help="scraper JSON dosyasi")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    init_schema()
    logger.info("%d akademisyen ice aktarildi", ice_aktar(args.ice_aktar))


if __name__ == "__main__":
    main()
