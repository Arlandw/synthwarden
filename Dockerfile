# SynthWarden Dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production image
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 synthwarden

# Copy dependencies from builder
COPY --from=builder /root/.local /home/synthwarden/.local

# Copy application (including templates and static files)
COPY --chown=synthwarden:synthwarden src/ ./src/

# Create data directory
RUN mkdir -p /app/data && chown synthwarden:synthwarden /app/data

# Switch to non-root user
USER synthwarden

# Set Python path
ENV PATH=/home/synthwarden/.local/bin:$PATH
ENV PYTHONPATH=/app/src

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "synthwarden.main:app", "--host", "0.0.0.0", "--port", "8000"]
