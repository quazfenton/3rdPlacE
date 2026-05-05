# Third Place Platform - Production Dockerfile
# Multi-stage build for smaller production image

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
# Stage 2: Production
# =============================================================================
FROM python:3.11-slim as production

# Create non-root user for security
RUN groupadd -r thirdplace && useradd -r -g thirdplace thirdplace

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /root/.local /home/thirdplace/.local

# Copy application code
COPY --chown=thirdplace:thirdplace . .

# Create directories for data and logs
RUN mkdir -p /data /logs && chown -R thirdplace:thirdplace /data /logs

# Set environment variables
ENV PATH=/home/thirdplace/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    DATABASE_URL=sqlite:////data/thirdplace.db \
    LOG_FILE=/logs/app.log \
    LOG_LEVEL=INFO

# Switch to non-root user
USER thirdplace

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
