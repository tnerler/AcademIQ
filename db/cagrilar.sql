-- Cagri toplama modulu semasi (docs/cagri-toplama-plan.md).
-- init.sql yalnizca bos volume'de calistigi icin bu dosya backend ve fetcher
-- acilisinda calistirilir (backend/cagrilar/db.py:init_schema); tum ifadeler idempotent.

-- tarihler = [{"etiket": "...", "tarih": "YYYY-MM-DD", "basvuru": true}, ...] -> en gec basvuru tarihi
-- (bos liste: NULL; "basvuru" anahtari olmayan eski kayitlar basvuru tarihi sayilir).
-- Generated kolonda kullanilabilmesi icin IMMUTABLE; tarihler her zaman ISO formatinda yazilir.
CREATE OR REPLACE FUNCTION cagri_son_tarih(tarihler JSONB) RETURNS DATE
    LANGUAGE sql IMMUTABLE AS
$$ SELECT max((e->>'tarih')::date) FROM jsonb_array_elements(tarihler) AS e
   WHERE coalesce((e->>'basvuru')::boolean, true) $$;  -- sonuc/proje baslangici gibi tarihler (basvuru=false) haric

CREATE TABLE IF NOT EXISTS cagrilar (
    id                 TEXT PRIMARY KEY,           -- doc_id(url): uuid5
    kaynak             TEXT NOT NULL,              -- 'TÜBİTAK'
    url                TEXT NOT NULL UNIQUE,       -- cagriyi ilk duyuran sayfa
    baslik             TEXT NOT NULL,
    program_kodu       TEXT,                       -- '1071', '2518', 'SBEP' ...
    program_adi        TEXT,
    hedef_kitle        TEXT NOT NULL CHECK (hedef_kitle IN ('akademik', 'sanayi')),
    ozet               TEXT,
    tarihler           JSONB NOT NULL DEFAULT '[]',
    son_tarih          DATE GENERATED ALWAYS AS (cagri_son_tarih(tarihler)) STORED,
    butce              TEXT,                       -- proje basina destek ust siniri
    program_butcesi    TEXT,                       -- programin toplam butcesi
    sure               TEXT,
    basvuru_kosullari  TEXT[] NOT NULL DEFAULT '{}',
    baglantilar        JSONB NOT NULL DEFAULT '[]',  -- [{"etiket": "...", "url": "..."}]
    metin              TEXT NOT NULL,              -- temizlenmis sayfa metni
    icerik_hash        TEXT NOT NULL,
    guncelleme_urller  TEXT[] NOT NULL DEFAULT '{}',  -- "suresi uzatildi" gibi sonraki duyurular
    yayin_tarihi       DATE,
    ilk_gorulme        TIMESTAMPTZ NOT NULL DEFAULT now(),
    son_kontrol        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS cagrilar_son_tarih_idx ON cagrilar (son_tarih);
ALTER TABLE cagrilar ADD COLUMN IF NOT EXISTS program_butcesi TEXT;

-- Cekilen her duyuru (cagri olsun olmasin): tekrar kontrolu ve filtre hatalarini incelemek icin
CREATE TABLE IF NOT EXISTS duyurular (
    url            TEXT PRIMARY KEY,
    kaynak         TEXT NOT NULL,
    baslik         TEXT NOT NULL,
    yayin_tarihi   DATE,
    ilk_gorulme    TIMESTAMPTZ NOT NULL DEFAULT now(),
    karar          TEXT NOT NULL
                   CHECK (karar IN ('kara_liste', 'cagri_degil', 'cagri', 'guncelleme', 'hata')),
    sebep          TEXT,                           -- eslesen kara liste kalibi, LLM gerekcesi ya da hata
    cagri_id       TEXT REFERENCES cagrilar (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cekme_calismalari (
    id       SERIAL PRIMARY KEY,
    tur      TEXT NOT NULL CHECK (tur IN ('zamanli', 'elle', 'backfill')),
    durum    TEXT NOT NULL DEFAULT 'bekliyor'
             CHECK (durum IN ('bekliyor', 'calisiyor', 'bitti', 'hata')),
    istendi  TIMESTAMPTZ NOT NULL DEFAULT now(),
    basladi  TIMESTAMPTZ,
    bitti    TIMESTAMPTZ,
    sayilar  JSONB,                                -- {taranan, kara_liste, cagri_degil, yeni, guncellenen, degisen}
    hata     TEXT
);

-- Cagri icin saklanan eslestirme sonucu (otomatik ya da "Eslestir" ile); MatchResponse JSON
CREATE TABLE IF NOT EXISTS cagri_eslesmeleri (
    cagri_id     TEXT PRIMARY KEY REFERENCES cagrilar (id) ON DELETE CASCADE,
    sonuc        JSONB NOT NULL,
    olusturuldu  TIMESTAMPTZ NOT NULL DEFAULT now()
);
