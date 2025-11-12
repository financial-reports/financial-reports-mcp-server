# --- Builder Stage ---
# Use the official Python image. Using 'uv' for speed.
FROM python:3.11-slim as builder

# Install uv, our package manager
RUN pip install uv

# Create and set the working directory
WORKDIR /app

# Copy only the dependency file
COPY requirements.txt .

# Install dependencies into a virtual environment
RUN uv venv /app/venv
RUN . /app/venv/bin/activate && uv pip install -r requirements.txt --no-cache-dir

# --- Final Stage ---
# Use a slim, non-root image for security
FROM python:3.11-slim-bookworm

# Set up a non-root user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser
USER appuser

# Copy the virtual environment from the builder
COPY --from=builder --chown=appuser:appuser /app/venv ./venv

# Copy the application source code
COPY --chown=appuser:appuser src/ ./src/

# Set environment variables
ENV PATH="/home/appuser/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Expose the MCP_TRANSPORT env var
# We will set this to 'stdio' in the 'docker run' command
ENV MCP_TRANSPORT=stdio

# The command to run the MCP server
CMD ["python", "-m", "src.financial_reports_mcp"]