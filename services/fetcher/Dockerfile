FROM python:3.12-slim
# Tesseract for scanned PDFs (fetcher.ocr_page)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY weft_core weft_core
COPY services services
COPY config config
CMD ["uv", "run", "--no-sync", "uvicorn", "services.fetcher.app:app", "--host", "0.0.0.0", "--port", "8080"]
