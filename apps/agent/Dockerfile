# syntax=docker/dockerfile:1.9
#
# Bedrock AgentCore Runtime expects ARM64; do not build with --platform
# linux/amd64 or the runtime rejects the image. The starter-toolkit's
# `agentcore launch` invokes CodeBuild with the correct arch automatically;
# this Dockerfile exists for local iteration and for the CDK-managed path.

FROM --platform=linux/arm64 python:3.13-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM --platform=linux/arm64 python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=deps --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

USER app

# AgentCore Runtime contract: serve /invocations and /ping on :8080.
EXPOSE 8080

CMD ["python", "-m", "agent"]
