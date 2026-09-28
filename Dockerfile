# AcademIQ backend (FastAPI). docker compose ile calistirilir, bkz. docker-compose.yml
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# .docx CV'lerin PDF onizlemesi icin LibreOffice; Calibri/Cambria/Arial/Times icin metrik uyumlu fontlar
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Bagimliliklar ayri katmanda: kod degisince yeniden kurulmaz
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY backend ./backend
COPY db ./db

EXPOSE 8000
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
