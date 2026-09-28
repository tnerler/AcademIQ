# AcademIQ
Proje ilanlarını akademisyen CV'leriyle anlamsal olarak eşleştirip en uygun araştırmacıları öneren RAG tabanlı sistem.

## Docker ile çalıştırma

Gereksinimler: kök dizinde `.env` (`OPENAI_API_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`)
ve `data/cvler/` altında akademisyen CV'leri (.docx ya da .pdf).

```bash
docker compose up -d --build      # postgres + backend + frontend
```

- Frontend: http://localhost:3000
- API / Swagger: http://localhost:8000/docs

### CV'ler

`data/cvler/` klasörü veritabanıyla senkronize tutulur. Klasöre CV eklendiğinde, bir CV değiştirildiğinde ya da
silindiğinde şunu çalıştırın:

```bash
docker compose --profile index run --rm indexer
docker compose restart backend    # BM25 indeksi açılışta yüklendiği için
```

- CV'ler şablondan bağımsız olarak LLM ile ortak bir şemaya çıkarılır. Araştırma alanları, özet, yayın, proje
  ve tez başlıkları aramaya girer; iletişim, eğitim, görevler, bibliyometri, dersler, ödüller gibi bilgiler
  CV detayında gösterilir.
- Yalnızca yeni ya da değişen dosyalar işlenir. Klasörde olmayan hocalar silinir (CV Yükle ile eklenenler hariç).
- Hoca kimliği dosya adından gelir: `001_Prof_Dr_Ertugrul_Akbulut_Klasik.docx` → `C001_Ertugrul_Akbulut`.
- .docx CV'lerin önizlemesi LibreOffice ile PDF'e çevrilir (`data/processed/cv_onizleme/`).
- CV'ler değiştiyse kayıtlı çağrı eşleştirmeleri yeniden hesaplanır.

Seçenekler: `--hepsi` (hepsini yeniden işle), `--dump <klasör>` (DB'ye yazmadan çıkarımı incele),
`--eslesme-atla`.

Durdurmak için `docker compose down` (veriler `academiq_pgdata` volume'ünde kalır).

### Proje çağrıları

`cagri-fetcher` servisi TÜBİTAK duyurularını her gün 07:00'de (TSİ) tarar; ilk çalıştırmada son 1 yılı toplar.
Çağrı olmayan duyurular elenir, "süresi uzatıldı" duyuruları ilgili çağrının tarihlerini günceller ve yeni
akademik çağrılar otomatik olarak eşleştirilir. Ayrıntılar: [docs/cagri-toplama-plan.md](docs/cagri-toplama-plan.md).

```bash
docker compose exec cagri-fetcher python -m backend.cagrilar.fetch             # hemen bir kez tara
docker compose exec cagri-fetcher python -m backend.cagrilar.fetch --backfill  # son 1 yılı yeniden tara
```

Arayüzdeki "Kaynakları tara" butonu için `.env`'e `ADMIN_TOKEN` ekleyin.
