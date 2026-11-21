FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv
WORKDIR /app
COPY starters/python/pyproject.toml starters/python/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY starters/python/app ./app
COPY packages/contracts/schema.json /contracts/schema.json
ENV KIT_CONTRACT_SCHEMA=/contracts/schema.json PYTHONUNBUFFERED=1 KIT_CORS_ORIGINS=""
RUN useradd --uid 10001 --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
