# Containerfile for the AgentAlloy service.
# Compatible with Podman (project preference) and Docker (works as Dockerfile via --file Containerfile).
#
# Build:  podman build -t agentalloy -f Containerfile .
# Run:    via compose.yaml (recommended) or `podman run --rm -p 47950:47950 -v ./data:/app/data agentalloy`

FROM python:3.12-slim AS base

# Install uv (Astral) and minimal runtime deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv is the project's package manager (matches host conventions)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer-cache friendliness
COPY pyproject.toml uv.lock ./

# Install third-party deps without trying to build the project itself
# (needs README.md, src/, etc. — added in the next layer). The `s3` extra
# pulls in boto3 for the corpus-bootstrap S3 snapshot cache.
RUN uv sync --frozen --no-dev --no-install-project --extra s3

# Copy the project source + README (used by hatchling for metadata), then
# install the project itself. The shipped skill corpus lives INSIDE the package
# at src/agentalloy/_packs/ (hatchling bundles it), so no separate corpus COPY
# is needed here.
COPY README.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev --extra s3

# The /app/data directory is the default location for the runtime DBs (see the
# ENV below); it is bind-mounted at runtime (compose.yaml) or overridden by
# LADYBUG_DB_PATH / DUCKDB_PATH in prod (-> /corpus). Create it empty rather
# than COPY-ing a host `data/` dir — that dir is gitignored and absent from a
# clean checkout, so a `COPY data/` broke every clean-context (CI) build.
RUN mkdir -p ./data

ENV LADYBUG_DB_PATH=/app/data/ladybug \
    DUCKDB_PATH=/app/data/skills.duck \
    LOG_LEVEL=INFO

EXPOSE 47950

# Note: HEALTHCHECK is intentionally defined in compose.yaml rather than here.
# Podman's default OCI image format does not honor inline HEALTHCHECK directives;
# the compose-level healthcheck works on both Podman and Docker.

CMD ["uv", "run", "uvicorn", "agentalloy.app:app", "--host", "0.0.0.0", "--port", "47950"]
