FROM python:3.13-slim
# Bump to python:3.14-slim when 3.14 ships (expected Oct 2025)

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Dependency layer — only rebuilds when pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "main.py"]
