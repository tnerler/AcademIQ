# AcademIQ
Proje ilanlarını akademisyen CV'leriyle anlamsal olarak eşleştirip en uygun araştırmacıları öneren RAG tabanlı sistem.

## Docker ile çalıştırma

Gereksinimler: kök dizinde `.env` (`OPENAI_API_KEY`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`)
ve `data/raw/` altında CV ile ilan PDF'leri.

```bash
docker compose up -d --build      # postgres + backend + frontend
```

- Frontend: http://localhost:3000
- API / Swagger: http://localhost:8000/docs

Boş bir veritabanında CV'leri bir kez indekslemek için:

```bash
docker compose --profile index run --rm indexer
docker compose restart backend    # BM25 indeksi açılışta yüklendiği için
```

Durdurmak için `docker compose down` (veriler `academiq_pgdata` volume'ünde kalır).
