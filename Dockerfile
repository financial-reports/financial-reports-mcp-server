FROM python:3.11-slim as builder
RUN pip install uv
WORKDIR /app
COPY requirements.txt .
RUN uv venv /app/venv
RUN . /app/venv/bin/activate && uv pip install -r requirements.txt --no-cache-dir

FROM python:3.11-slim-bookworm
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser
COPY --from=builder --chown=appuser:appuser /app/venv ./venv
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser entrypoint.sh .
RUN chmod +x entrypoint.sh
USER appuser
ENV PATH="/home/appuser/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=stdio
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-m", "src.financial_reports_mcp"]