# syntax=docker/dockerfile:1
FROM python:3.15-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# the `ml` group holds the real small models (BGE-M3, GlotLID, spaCy); WEFT_NLP=real turns them on
# Shared download cache, one build at a time (sharing=locked): later builds reuse the first one's
# downloads instead of racing it for uv's cache locks. Retries reuse whatever already arrived.
ENV UV_HTTP_TIMEOUT=300 UV_LINK_MODE=copy
# models are baked into the image here, readable by the non-root user below
ENV HF_HOME=/opt/hf
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked uv sync --frozen --no-dev --group ml --no-install-project
RUN echo "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl --hash=sha256:1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85" > /tmp/spacy.txt \
 && uv pip install --require-hashes -r /tmp/spacy.txt
RUN uv run --no-sync python -c "from huggingface_hub import hf_hub_download as d; d('cis-lmu/glotlid','model.bin',local_dir='/models/glotlid')" \
 && uv run --no-sync python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3')"
ENV GLOTLID_MODEL=/models/glotlid/model.bin
COPY weft_core weft_core
COPY services services
COPY config config
ENV WEFT_NLP=real
RUN useradd --system --uid 10001 --no-create-home app && mkdir -p /models && chown -R app /opt/hf /models
ENV UV_CACHE_DIR=/tmp/uv-cache
USER app
CMD ["uv", "run", "--no-sync", "uvicorn", "services.stream_worker.app:app", "--host", "0.0.0.0", "--port", "8080"]
