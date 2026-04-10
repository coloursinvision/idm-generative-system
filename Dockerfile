# =============================================================================
# IDM Generative System — Production Dockerfile
# Target: Digital Ocean App Platform (or any OCI-compliant runtime)
# Entrypoint: FastAPI + uvicorn
# =============================================================================
# Build: docker build -t idm-api:latest .
# Run:   docker run -p 8000:8000 --env-file .env idm-api:latest
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Builder
# Install Python deps into a virtual-env so we can COPY only the venv later.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Prevent .pyc files and enable unbuffered stdout (crash-safe logging).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System deps for building native extensions (numba/llvmlite, numpy, scipy).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

# Create venv — isolates deps from system Python.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install deps first (cache layer — only rebuilds when deps change).
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir ".[dev]"

# ---------------------------------------------------------------------------
# Stage 2 — Runtime
# Slim image with only the venv + application code.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Runtime-only system libraries (no compilers).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user — DO NOT run as root in production.
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Numba: disable JIT cache writes (read-only filesystem).
    NUMBA_DISABLE_JIT_CACHE=1 \
    # Uvicorn config via env (overridable at runtime).
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=2 \
    UVICORN_LOG_LEVEL=info

# Copy venv from builder.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy application code — order matters for cache efficiency.
COPY engine/ ./engine/
COPY api/ ./api/
COPY knowledge/ ./knowledge/
COPY pyproject.toml README.md ./

# Pre-compile Numba kernels during build (avoids cold-start latency).
# If this fails, the container still starts — JIT compiles on first call.
RUN python -c "\
from engine.effects.reverb import _comb_filter_kernel, _allpass_kernel; \
from engine.effects.delay import _delay_line_kernel; \
from engine.effects.compressor import _smooth_envelope_single, _smooth_envelope_auto; \
print('Numba kernels pre-compiled.')" 2>/dev/null || echo "Numba pre-compilation skipped."

# Switch to unprivileged user.
USER appuser

EXPOSE 8000

# Health check — matches /health endpoint in api/main.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production entrypoint: uvicorn with configurable workers.
# DO App Platform sets PORT env var — uvicorn reads UVICORN_PORT.
CMD ["python", "-m", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
