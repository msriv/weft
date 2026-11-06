FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group ml --no-install-project
RUN uv pip install "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
RUN uv run --no-sync python -c "from huggingface_hub import hf_hub_download as d; d('cis-lmu/glotlid','model.bin',local_dir='/models/glotlid')" \
 && uv run --no-sync python -c "from sentence_transformers import SentenceTransformer as S; S('BAAI/bge-m3')"
ENV GLOTLID_MODEL=/models/glotlid/model.bin WEFT_NLP=real
COPY weft_core weft_core
COPY services services
COPY pipeline pipeline
COPY config config
COPY evals evals
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "pipeline.run"]
