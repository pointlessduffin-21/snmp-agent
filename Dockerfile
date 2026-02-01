# Multi-stage build for SNMP Agent Monitor
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies including headers for netifaces compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (SNMP tools, network utilities for hostname resolution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    snmp \
    libsnmp-base \
    iputils-ping \
    net-tools \
    curl \
    samba-common-bin \
    dnsutils \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY start_web.py .
COPY requirements.txt .

# Create volume mount points
VOLUME ["/app/config", "/app/data"]

# Expose ports
EXPOSE 8000 1883 9001

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/stats || exit 1

# Run the application
CMD ["python", "start_web.py", "--port", "8000"]
