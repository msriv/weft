FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY weft_core weft_core
COPY services services
COPY config config
CMD ["uv", "run", "--no-sync", "python", "-m", "services.poller.main"]
