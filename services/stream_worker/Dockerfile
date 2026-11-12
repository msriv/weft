# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# the `ml` group holds the real small models (BGE-M3, GlotLID, spaCy); WEFT_NLP=real turns them on
# Shared download cache, one build at a time (sharing=locked): later builds reuse the first one's
# downloads instead of racing it for uv's cache locks. Retries reuse whatever already arrived.
ENV UV_HTTP_TIMEOUT=300 UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked uv sync --frozen --no-dev --group ml --no-install-project
RUN uv pip install "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
RUN uv run --no-sync python -c "from huggingface_hub import hf_hub_download as d; d('cis-lmu/glotlid','model.bin',local_dir='/models/glotlid')" \
 && uv run --no-sync python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3')"
ENV GLOTLID_MODEL=/models/glotlid/model.bin
COPY weft_core weft_core
COPY services services
COPY config config
ENV WEFT_NLP=real
CMD ["uv", "run", "--no-sync", "uvicorn", "services.stream_worker.app:app", "--host", "0.0.0.0", "--port", "8080"]
