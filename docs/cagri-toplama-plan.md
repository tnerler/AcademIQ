# Çağrı Toplama — Plan

TÜBİTAK'ın yayımladığı Ar-Ge proje çağrılarını düzenli olarak toplayıp tarihleriyle (açık / geçmiş)
listelemek, akademisyenlerle eşleştirmek ve "Bana Uygun" ekranını beslemek.

LinkedIn kaynak olarak **kullanılmıyor**: okuma API'si yok, kazıma kullanım şartlarına aykırı ve gönderiler
yalnızca `tubitak.gov.tr/tr/duyuru` sayfalarının kısa özetidir. Asıl kaynak doğrudan bu sayfalardır.

## Kaynak incelemesi (2026-09-28)

- `https://tubitak.gov.tr/tr/duyuru`: sunucu tarafında üretilen HTML (Drupal), JS gerekmiyor. `?page=N` ile
  sayfalanıyor, sayfa başına ~20 duyuru ve yayın tarihi var.
- Detay sayfalarında "Çağrı Takvimi" bölümünde etiketli tarihler bulunuyor (ör. SBEP: uluslararası 16 Kasım,
  ulusal 23 Kasım, e-imza 26 Kasım 2026). Ufuk Avrupa ortaklık çağrıları (SBEP, FOREST, Water4All, DUT) da burada.
- Gürültü örnekleri: "…sonuçları açıklandı", "…süresi uzatıldı/güncellendi", lise/ortaokul yarışmaları,
  ödüller, bilim fuarı, etkinlik katılım destekleri, sanayi/girişimcilik çağrıları (1501, 1707, 1832, 1711, BiGG).
- `ufukavrupa.org.tr/tr/cagrilar`: liste JS ile yükleniyor, içerik büyük ölçüde TÜBİTAK duyurularıyla örtüşüyor.
  Şimdilik kapsam dışı, mimari yeni kaynak eklemeye açık.

## Kararlar

| Konu | Karar |
|---|---|
| Kaynak | Yalnızca TÜBİTAK duyuruları (kaynak arayüzü çoklu kaynağa açık) |
| Çağrı türü | Ar-Ge proje çağrıları; sanayi çağrıları dahil ama `hedef_kitle = sanayi` etiketiyle |
| İçerik | Yalnızca detay sayfası metni (ekli PDF'ler indirilmez) |
| Tablo | Yeni `cagrilar` tablosu; `is_ilanlari` elle eklenen ilanlara kalır |
| Tarih modeli | Etiketli tarih listesi (`tarihler` JSONB) |
| Aktif kuralı | Tüm tarihler geçince "geçmiş"; tarih yoksa "tarih belirsiz" olarak kaydedilir ve gösterilir |
| İlk çalıştırma | Son 1 yıl |
| Düzenli çalıştırma | Liste sayfaları taranır, bilinen bir URL'ye gelince durulur |
| Ham veri | Temizlenmiş metin DB'de saklanır (yeniden işlemek için) |
| Filtre | Başlık kara listesi → kalanlar için LLM (`is_cagri` + alan çıkarımı tek çağrıda) |
| Çıkarılan alanlar | Program kodu/adı, konu-amaç özeti, bütçe/süre/koşullar, bağlantılar, tarihler, hedef kitle |
| Eşleştirme alanları | Çekerken değil, eşleştirme anında üretilir (mevcut `extract_ilan`) |
| Uzatma/güncelleme duyuruları | İlgili mevcut çağrıyı günceller; eşleşme bulunmazsa yeni çağrı |
| Görülen duyurular | Ayrı `duyurular` tablosu (karar + sebep ile) |
| Sayfa değişiklikleri | Aktif çağrılar her çalıştırmada yeniden indirilir; hash değişirse yeniden çıkarılır |
| Zamanlama | Ayrı compose servisi (`cagri-fetcher`), günde 1 kez |
| Elle tetikleme | API + "Kaynakları tara" butonu; DB'ye istek satırı, fetcher alır; admin token ile korunur |
| Takip | `cekme_calismalari` tablosu + log; arayüzde "son güncelleme" |
| Liste filtreleri | Durum, hedef kitle, program, metin arama |
| Satırdaki "Eşleştir" | Eşleştir sayfasına götürür; `POST /api/match` `cagri_id` kabul eder (metin DB'den, 3000 karakter sınırı yok) |
| Otomatik eşleştirme | Yeni akademik çağrı → ilk 5 hoca saklanır, İlanlar listesinde görünür |
| Bana Uygun | CV → çağrı: çağrı embedding'leri + CV profil özeti ile hibrit arama, ilk N için LLM gerekçe/eksik |
| CV saklama | Kullanıcı seçer (varsayılan geçici; "CV'mi kaydet" → hoca havuzuna indekslenir) |
| CV Yükle sayfası | Aynı tek-CV indeksleme koduyla açılır |
| Şema uygulama | `db/cagrilar.sql`, backend ve fetcher açılışında idempotent (`init_schema`, advisory lock) |
| DB erişimi | SQLAlchemy Core, ayrı sync engine (PGEngine'in async havuzu kendi event loop'unda çalışıyor) |
| Çağrı kimliği | URL'den uuid5 (`doc_id`), Faz 7'deki çağrı embedding'i de aynı id'yi kullanır |
| `son_tarih` | `tarihler`'den generated kolon (`cagri_son_tarih` IMMUTABLE fonksiyonu) |

## Veri modeli

Şema: `db/cagrilar.sql` (`cagrilar`, `duyurular`, `cekme_calismalari`); sorgu tanımları ve `durum` ifadesi:
`backend/cagrilar/db.py`; API modelleri: `CagriOzet`, `CagriDetay` (`backend/api/schemas.py`).

- `durum` yazılmaz, sorguda hesaplanır: `son_tarih` yok → `belirsiz`, `son_tarih >= current_date` → `acik`, değilse `gecmis`.
- Faz 7'de eklenecek: `cagri_eslesmeleri (cagri_id TEXT PK → cagrilar, sonuc JSONB, olusturuldu)` ve
  langchain_postgres çağrı vektör tablosu.

## Modül yapısı

```
backend/cagrilar/
  sources/base.py      # Kaynak arayüzü (liste + detay), istek aralığı, tekrar deneme
  sources/tubitak.py   # tubitak.gov.tr/tr/duyuru ayrıştırıcı
  filters.py           # başlık kara listesi
  extract.py           # LLM: karar (cagri / guncelleme / cagri_degil) + alanlar; uzatmalarda tarih birleştirme
  fetch.py             # tek çalıştırma: python -m backend.cagrilar.fetch [--backfill]
  worker.py            # compose servisi (cagri-fetcher): günlük zamanlayıcı + bekleyen istekler
  index.py             # çağrı vektör indeksi (cagri_vektorleri)
  eslesme.py           # çağrı → akademisyen eşleştirmesi, sonuç cagri_eslesmeleri'nde saklanır
  bana_uygun.py        # CV profili → açık akademik çağrılar (hibrit arama + LLM neden/eksik)
backend/indexing/upload.py      # tek CV analiz + indeksleme (CV Yükle, "CV'mi kaydet")
backend/api/routes_cagrilar.py  # /api/cagrilar ...
```

## Fazlar

### Faz 1 ✅ — Veri modeli
- `duyurular`, `cagrilar`, `cekme_calismalari` tabloları ve durum hesaplaması.
- Pydantic modelleri: `CagriTarihi`, `Baglanti`, `CagriOzet`, `CagriDetay`.
- **Bitti sayılır:** tablolar mevcut bir DB'ye de uygulanabiliyor; durum sorgusu örnek verilerle doğru.

### Faz 2 ✅ — Çekme (TÜBİTAK)
- Liste sayfası ayrıştırıcı (URL, başlık, yayın tarihi) ve `?page=N` gezinme.
- Detay sayfası: ana içerik alanından temiz metin + dış bağlantılar (paylaş butonları hariç).
- Backfill (son 1 yıl) ve artan mod (bilinen URL'de dur). İstekler arasında gecikme, User-Agent, timeout/tekrar.
- **Bitti sayılır:** backfill çalışınca son 1 yılın tüm duyuruları `duyurular`'a düşüyor; ikinci çalıştırma ilk sayfada duruyor.

### Faz 3 ✅ — Filtreleme ve çıkarım
- Başlık kara listesi (sonuçlar açıklandı, yarışma, ödül, bilim fuarı, …) → `karar = kara_liste`.
- LLM çıkarımı: `is_cagri`, `guncelleme_mi` (+ hangi program/yıl/dönem), `hedef_kitle`, program, özet,
  etiketli tarihler (ISO), bütçe/süre/koşullar, bağlantılar. Tarihler ve metasal alanlar metinde
  doğrulanır (`ground_ilan` mantığı).
- SBEP gibi 20-30 gerçek duyuruyla küçük bir değerlendirme seti (doğru karar + doğru tarihler).
- **Bitti sayılır:** değerlendirme setinde karar ve tarih doğruluğu kabul edilebilir düzeyde.

### Faz 4 ✅ — Tekrar kontrolü ve güncellemeler
- URL ile tekrar kontrolü; aktif çağrılarda yeniden indirme + `icerik_hash` karşılaştırması, değişende yeniden çıkarım.
- Uzatma/güncelleme duyurusu → program kodu + yıl/dönem ile mevcut çağrı bulunur, `tarihler` güncellenir,
  URL `guncelleme_urller`'e eklenir; bulunamazsa yeni çağrı.
- **Bitti sayılır:** "1711 … süresi güncellendi" gibi bir duyuru mevcut 1711 çağrısının tarihini değiştiriyor.

### Faz 5 ✅ — Zamanlama
- `cagri-fetcher` compose servisi: günde 1 zamanlı çalıştırma + `cekme_calismalari`'nda `bekliyor` satırlarını yoklama.
- Aynı anda tek çalıştırma; her çalıştırmanın sayıları ve hatası kaydedilir.
- **Bitti sayılır:** `docker compose up` sonrası günlük çalıştırma ve elle istek fetcher tarafından işleniyor.

### Faz 6 ✅ — API ve arayüz
- `GET /api/cagrilar` (durum, hedef_kitle, program, q filtreleri; son_tarih'e göre sıralı), `GET /api/cagrilar/{id}`.
- `POST /api/cagrilar/tara` (admin token) → istek satırı; `GET /api/cagrilar/tarama` → son çalıştırma durumu.
- `POST /api/match` `cagri_id` parametresi.
- `ilanlar.js`: gerçek API, filtreler, etiketli tarihler, "tarih belirsiz", "Kaynakları tara" butonu,
  "son güncelleme" bilgisi; "Eşleştir" → Eşleştir sayfası `cagri_id` ile.
- **Bitti sayılır:** liste gerçek verilerle filtrelenebiliyor, buton taramayı tetikliyor, Eşleştir çağrı metniyle çalışıyor.

### Faz 7 ✅ — Otomasyon ve Bana Uygun
- **Otomatik eşleştirme:** yeni akademik çağrı kaydedilince eşleştirme çalışır, `cagri_eslesmeleri`'ne yazılır;
  İlanlar listesinde "Uygun hocalar" rozeti, Eşleştir saklanan sonucu anında gösterir.
- **Yaklaşan son tarih:** listede 7 günden az kalanlar vurgulanır.
- **Çağrı indeksi:** akademik çağrılar için embedding (langchain_postgres) + BM25.
- **Tek CV indeksleme:** `index_cvs` akışından tek PDF için fonksiyon; indeksleme sonrası BM25 yeniden yüklenir.
- **CV Yükle** sayfası (şu an 501) bu fonksiyonla açılır.
- **Bana Uygun:** CV yükle → profil özeti → açık çağrılarda hibrit arama → ilk N için LLM gerekçe/eksik.
  "CV'mi kaydet" işaretliyse CV hoca havuzuna indekslenir, değilse saklanmaz.
- **Bitti sayılır:** yüklenen bir CV için açık ve uygun çağrılar gerekçeleriyle listeleniyor.

## Uygulamada seçilen varsayılanlar (değiştirilebilir)

| Konu | Varsayılan | Nerede |
|---|---|---|
| Kara liste | 252 gerçek başlıktan çıkarılan kalıplar | `backend/cagrilar/filters.py` |
| Günlük çalışma | 07:00 TSİ | `CAGRI_CEKME_SAATI` |
| Admin token | `.env`'de `ADMIN_TOKEN`; arayüzde "Kaynakları tara" formuna girilir, tarayıcıda hatırlanır | `ilanlar.js` |
| Bana Uygun | ilk 5 çağrı (`RESULT_COUNT`), skor eşiği yok, yalnızca akademik çağrılar | `bana_uygun.py` |
| Tarihi belirsiz çağrılar | 90 gün boyunca her gün yeniden kontrol | `CAGRI_BELIRSIZ_KONTROL_GUN` |
| Uzatma eşleştirmesi | başlık örtüşmesi ≥ 0.7, ya da aynı program kodu + ≥ 0.5 | `fetch.py:_guncellenen_cagri` |
| Otomatik eşleştirme | yalnızca yeni/değişen, akademik ve süresi geçmemiş çağrılar | `CAGRI_OTOMATIK_ESLESTIRME` |
