# syntax=docker/dockerfile:1
FROM python:3.12-slim
# Tesseract for scanned PDFs (fetcher.ocr_page)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Shared download cache, one build at a time (sharing=locked): later builds reuse the first one's
# downloads instead of racing it for uv's cache locks. Retries reuse whatever already arrived.
ENV UV_HTTP_TIMEOUT=300 UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked uv sync --frozen --no-dev --no-install-project
COPY weft_core weft_core
COPY services services
COPY config config
CMD ["uv", "run", "--no-sync", "python", "-m", "services.crawler.main"]
