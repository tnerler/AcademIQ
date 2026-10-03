-- YOK Akademik modulu semasi (backend/yok). Backend ve yok-worker acilisinda calistirilir
-- (backend/yok/db.py:init_schema); tum ifadeler idempotent.

-- Son bilinen durum: her akademisyenin YOK'ten cekilen verisi. Taramalar bununla karsilastirilir.
CREATE TABLE IF NOT EXISTS yok_akademisyenler (
    author_id      TEXT PRIMARY KEY,               -- YOK authorId
    universite     TEXT NOT NULL,
    veri           JSONB NOT NULL,                 -- liste satiri + (varsa) profil ve sekmeler
    detay_var      BOOLEAN NOT NULL DEFAULT false, -- profil/sekmeler cekildi mi (yeni eklenenlerde bir sure false)
    aktif          BOOLEAN NOT NULL DEFAULT true,  -- universite listesinden cikanlar false (veri silinmez)
    ilk_gorulme    TIMESTAMPTZ NOT NULL DEFAULT now(),
    son_gorulme    TIMESTAMPTZ NOT NULL DEFAULT now(),
    detay_zamani   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS yok_akademisyenler_uni_idx ON yok_akademisyenler (universite) WHERE aktif;

-- "YOK'u kontrol et" ve haftalik tam tarama istekleri; yok-worker 'bekliyor' olanlari sirayla calistirir
CREATE TABLE IF NOT EXISTS yok_taramalari (
    id        SERIAL PRIMARY KEY,
    tur       TEXT NOT NULL CHECK (tur IN ('hizli', 'tam')),   -- hizli: sadece liste; tam: + profil ve sekmeler
    kaynak    TEXT NOT NULL CHECK (kaynak IN ('elle', 'zamanli')),
    durum     TEXT NOT NULL DEFAULT 'bekliyor'
              CHECK (durum IN ('bekliyor', 'calisiyor', 'bitti', 'hata')),
    limit_    INTEGER,                              -- test icin: tam taramada en fazla bu kadar hoca
    istendi   TIMESTAMPTZ NOT NULL DEFAULT now(),
    basladi   TIMESTAMPTZ,
    bitti     TIMESTAMPTZ,
    ilerleme  JSONB,                                -- {asama, yapilan, toplam}
    ozet      JSONB,                                -- {eklenen, ayrilan, degisen}
    rapor     JSONB,                                -- backend/yok/fark.py rapor sekli
    hata      TEXT
);
