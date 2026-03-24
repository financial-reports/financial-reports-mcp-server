# --- Stage 1: Build & Generate ---
FROM python:3.11-slim as builder
RUN pip install uv
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN uv venv /app/venv
RUN . /app/venv/bin/activate && uv pip install -r requirements.txt --no-cache-dir

# Copy source code and generator
COPY src/ ./src/
COPY scripts/ ./scripts/

# Generate the MCP tools NOW, during the cloud build! 
RUN . /app/venv/bin/activate && python scripts/generate_mcp_tools.py

# --- Stage 2: Production ---
FROM python:3.11-slim-bookworm
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser

# Copy the environment and pre-generated code
COPY --from=builder --chown=appuser:appuser /app/venv ./venv
COPY --from=builder --chown=appuser:appuser /app/src/ ./src/

USER appuser
ENV PATH="/home/appuser/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Boot instantly. No entrypoint script needed!
CMD ["python", "-m", "uvicorn", "src.financial_reports_mcp:app", "--host", "0.0.0.0", "--port", "8000"]