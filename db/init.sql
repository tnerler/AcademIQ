-- Bu dosya, Postgres container'i ilk defa (bos bir data volume ile) ayaga
-- kalktiginda docker-entrypoint-initdb.d mekanizmasi tarafindan otomatik
-- calistirilir. Volume zaten varsa tekrar calismaz.

CREATE EXTENSION IF NOT EXISTS vector;

-- Faz 1 semasi: hoca (akademisyen) kayitlari.
CREATE TABLE IF NOT EXISTS hocalar (
    id           TEXT PRIMARY KEY,
    unvan        TEXT NOT NULL,
    ad           TEXT NOT NULL,
    soyad        TEXT NOT NULL,
    universite   TEXT NOT NULL,
    fakulte      TEXT NOT NULL,
    bolum        TEXT NOT NULL,
    ana_alan     TEXT NOT NULL,
    ikincil_alan TEXT,
    uzmanlik     TEXT[] NOT NULL,
    email        TEXT NOT NULL,
    kaynak_pdf   TEXT
);

-- Faz 1 semasi: is ilani / proje cagrisi kayitlari.
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

-- Embedding tablolari burada elle olusturulmuyor: Faz 4/5'te kullanilacak
-- langchain_postgres'in PGVector vectorstore'u, "cv_embeddings" ve
-- "ilan_embeddings" koleksiyonlarini ilk yazma isleminde kendi yonetimindeki
-- tablolarla (vector kolonu dahil) otomatik olusturuyor.
