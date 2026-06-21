# Bot image — installs philippe with the `bot` extra (aiogram + psycopg) via uv.
# psycopg[binary] ships wheels, so no libpq/build deps are needed.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer — cached until the manifest/lock/src change.
# README.md is required because pyproject sets `readme = "README.md"`.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra bot

# Forms (also bind-mounted in compose so edits don't need a rebuild).
COPY examples ./examples

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["philippe"]
CMD ["run", "--forms-dir", "examples"]
