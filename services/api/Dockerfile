# syntax=docker/dockerfile:1
FROM python:3.15-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Shared download cache, one build at a time (sharing=locked): later builds reuse the first one's
# downloads instead of racing it for uv's cache locks. Retries reuse whatever already arrived.
ENV UV_HTTP_TIMEOUT=300 UV_LINK_MODE=copy
# models are baked into the image here, readable by the non-root user below
ENV HF_HOME=/opt/hf
# the `ml` group brings BGE-M3: Ask must embed questions with the embedder the pipeline used for claims
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked uv sync --frozen --no-dev --group ml --no-install-project
RUN uv run --no-sync python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3')"
ENV WEFT_NLP=real
COPY weft_core weft_core
COPY pipeline pipeline
COPY services services
COPY config config
RUN useradd --system --uid 10001 --no-create-home app && mkdir -p /models && chown -R app /opt/hf /models
ENV UV_CACHE_DIR=/tmp/uv-cache
USER app
CMD ["uv", "run", "--no-sync", "uvicorn", "--factory", "services.api.app:app_from_env", "--host", "0.0.0.0", "--port", "8080"]
