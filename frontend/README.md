# AcademIQ Frontend

Build adımı olmayan, saf HTML/CSS/JS arayüz. `index.html` tek sayfa, ekranlar arası
geçiş hash ile yapılıyor (`#/cvler`, `#/eslestir` ...).

## Çalıştırma

Repo kökünden:

```bash
python frontend/dev_server.py
```

Ardından http://localhost:3000 adresini açın. Backend CORS ayarında 3000 portu izinli.

`dev_server.py`, `python -m http.server`'dan tek farkla ayrılıyor: mock modda CV PDF
önizlemesi için `data/fake_akademik_cvler/` klasörünü `/mock-pdf/` altında servis ediyor.

## Mock / gerçek API

- Varsayılan olarak **mock veri** kullanılır (`js/config.js` → `USE_MOCK_DEFAULT`).
- Gerçek backend'e geçmek için sol alttaki **Mock veri** rozetine tıklayın ya da
  `http://localhost:3000/?mock=0` adresini açın. Seçim tarayıcıda saklanır. `?mock=1` ile geri dönülür.
- Backend adresi: `js/config.js` → `API_URL` (varsayılan `http://localhost:8000`).

Mock modda Eşleştir ekranında `data/duz_metin/` ya da `data/tablo_formatli/` klasöründen
bir ilan PDF'i seçin; ilan dosya adındaki `I0xx` numarasından tanınır. "Metin yapıştır"
sekmesinde ise metin, kelime örtüşmesine göre en yakın örnek ilanla eşlenir.
Hata ekranını denemek için adında `hata` geçen bir PDF yükleyin ya da metne "hata" yazın.

## Yapı

```
frontend/
  index.html            sidebar ve içerik alanı
  css/styles.css        tasarım token'ları ve tüm bileşen stilleri
  js/
    config.js           API adresi, mock anahtarı, timeout'lar
    api.js              tüm backend çağrıları (sözleşmeyle birebir) ve mock karşılıkları
    ui.js               ortak yardımcılar: ikonlar, biçimlendirme, modal, toast
    app.js              hash yönlendirici
    pages/
      home.js           Ana Sayfa
      cvler.js          CV'ler: liste, filtreler, detay, PDF önizleme      (aktif)
      eslestir.js       Eşleştir: PDF / metin, sonuçlar, kanıtlar, CSV     (aktif)
      cv-yukle.js       CV Yükle                                           (önizleme)
      ilanlar.js        Proje İlanları                                     (önizleme)
      ilan-ekle.js      İlan Ekle                                          (önizleme)
      bana-uygun.js     Bana Uygun İlanlar                                 (önizleme)
  mock/
    cvs.json            HocaDetay[]
    matches.json        { ilan_id: MatchResponse }
    ilanlar.json        önizleme ekranları için örnek ilan listesi
    generate_mock.py    yukarıdaki dosyaları data/ altındaki PDF'lerden üretir
  TUANA_SORULAR.md      backend'e iletilecek açık sorular
```

## Kullanılan endpoint'ler

| Metot | Yol | Ekran |
|---|---|---|
| GET | `/api/cvs` | CV'ler listesi, Ana Sayfa sayacı, Eşleştir "N CV tarandı" |
| GET | `/api/cvs/{id}` | CV'ler detay paneli |
| GET | `/api/cvs/{id}/pdf` | PDF önizleme (iframe) |
| POST | `/api/match` | Eşleştir (multipart: PDF için `file`, metin için `metin`*) |

\* Metin alanının adı backend'le netleşecek, bkz. `TUANA_SORULAR.md`.

Pasif modüller (`POST /api/cvs`, `GET/POST /api/ilanlar`) çağrılmıyor.

## Mock veriyi yeniden üretmek

`data/` klasörü git'e dahil değil, bu yüzden üretilen JSON'lar `frontend/mock/` altında commit'leniyor.

```bash
pip install pypdf
python frontend/mock/generate_mock.py
```
