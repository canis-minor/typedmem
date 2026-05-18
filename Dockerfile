# TypedMemory HTTP server container.
#
# Build:    docker build -t typedmem .
# Run:      docker run -p 8080:8080 -v /var/lib/typedmem:/data typedmem \
#             serve --store /data/agent.db
# Cloud Run: see docs/server.md for the GCS-FUSE-mounted deploy pattern.

FROM python:3.12-slim AS base

# Run as non-root for defense-in-depth.
RUN useradd --create-home --shell /bin/sh app

WORKDIR /app

# Install only what we ship. Builds are reproducible from pyproject.toml.
COPY pyproject.toml README.md ./
COPY typedmem/ ./typedmem/

# [gcp] pulls in google-auth for Cloud Run identity-token validation.
# Local-only deployments could install '[server]' alone; the [gcp] extra
# is a superset and is the documented default.
RUN pip install --no-cache-dir '.[gcp]' \
 && rm -rf /root/.cache/pip

USER app

# Cloud Run sets $PORT; default 8080 for plain `docker run`.
ENV PORT=8080
# Default store path; override by mounting a volume at /data or by setting
# TYPEDMEM_DB at run time. The CLI reads TYPEDMEM_DB to pick the store, so
# `typedmem serve` works without further flags inside the container.
ENV TYPEDMEM_DB=/data/agent.db
EXPOSE 8080

# Reasonable default; override with `docker run ... typedmem <subcommand>`
# or via Cloud Run --args=. Note: --store / --workspace / --profile are
# *global* flags and must come BEFORE the subcommand name when overriding
# at the command line (or use TYPEDMEM_DB env var instead).
ENTRYPOINT ["typedmem"]
CMD ["serve"]
