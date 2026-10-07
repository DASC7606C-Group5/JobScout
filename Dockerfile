FROM oven/bun:1.4.2 AS web-build
WORKDIR /build
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
RUN bun node_modules/vite/bin/vite.js build && bun run typecheck

FROM ghcr.io/astral-sh/uv:0.12.19 AS uv
FROM python:3.14-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 FRONTEND_DIRECTORY=/app/web/dist
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY README.md ./
RUN uv sync --locked --no-dev && useradd --uid 10001 --create-home jobscout && mkdir -p /data && chown jobscout:jobscout /data
COPY --from=web-build /build/dist ./web/dist
USER jobscout
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
CMD ["/app/.venv/bin/uvicorn", "jobscout.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
