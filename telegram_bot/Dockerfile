# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="Base Volume Bump Bot"
LABEL org.opencontainers.image.description="Telegram bot for bumping Base-chain token volume"

# Non-root user for security
RUN addgroup --system botgroup && adduser --system --ingroup botgroup botuser

WORKDIR /app

# Install Python packages from builder
COPY --from=builder /install /usr/local

# Copy source files
COPY config.py wallet.py storage.py transactions.py bot.py ./

# Persistent data directory (mount a volume here in production)
RUN mkdir -p /app/data && chown botuser:botgroup /app/data

USER botuser

ENV DATABASE_PATH=/app/data/bot_data.db \
    PYTHONUNBUFFERED=1

VOLUME ["/app/data"]

CMD ["python", "bot.py"]
