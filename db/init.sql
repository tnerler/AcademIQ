-- Bu dosya, Postgres container'i ilk defa (bos bir data volume ile) ayaga
-- kalktiginda docker-entrypoint-initdb.d mekanizmasi tarafindan otomatik
-- calistirilir. Volume zaten varsa tekrar calismaz.

CREATE EXTENSION IF NOT EXISTS vector;

-- Pasif modul (Proje Ilanlari / Ilan Ekle): bu asamada yazilmiyor.
CREATE TABLE IF NOT EXISTS is_ilanlari (
    id               TEXT PRIMARY KEY,
    baslik           TEXT NOT NULL,
    kurum            TEXT,
    alan             TEXT NOT NULL,
    gerekli_uzmanlik TEXT[] NOT NULL,
    aciklama         TEXT NOT NULL,
    kaynak_url       TEXT,
    tarih            DATE
);

-- Vektor tablolari burada elle olusturulmuyor: langchain_postgres PGEngine,
-- indeksleme sirasinda (backend/indexing/index_cvs.py) su tablolari yonetir:
--   cv_chunks        : CV parcalari + embedding (hoca_id, bolum, sira metadata kolonlari)
--   hoca_profilleri  : akademisyen kimligi + LLM profil ozeti + embedding
