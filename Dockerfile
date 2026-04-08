# syntax=docker/dockerfile:1.7

# --- Stage 1: Build & generate ---
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies into a venv we can copy verbatim into the runtime image
COPY requirements.txt .
RUN uv venv /app/venv && \
    . /app/venv/bin/activate && \
    uv pip install -r requirements.txt --no-cache-dir

# Copy source + generator and pre-render the MCP tools file at build time.
# This bakes the live OpenAPI schema into the image so cold starts are instant.
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN . /app/venv/bin/activate && python scripts/generate_mcp_tools.py


# --- Stage 2: Runtime ---
FROM python:3.11-slim-bookworm

# curl is needed for HEALTHCHECK
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser

# Stamped at build time so /health can report exactly which build is live.
# Overridden by the GitHub Actions workflow with the SDK version tag.
ARG MCP_VERSION=dev
ENV MCP_VERSION=${MCP_VERSION}

# Copy the pre-built venv and pre-generated source from the builder stage
COPY --from=builder --chown=appuser:appuser /app/venv ./venv
COPY --from=builder --chown=appuser:appuser /app/src/ ./src/

USER appuser
ENV PATH="/home/appuser/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Honest health signal for Container Apps probes and local docker.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

LABEL org.opencontainers.image.title="financial-reports-mcp" \
      org.opencontainers.image.source="https://github.com/financial-reports/financial-reports-mcp-server" \
      org.opencontainers.image.vendor="FinancialReports" \
      org.opencontainers.image.description="Remote MCP server for the FinancialReports global filings API"

CMD ["python", "-m", "uvicorn", "src.financial_reports_mcp:app", "--host", "0.0.0.0", "--port", "8000"]
