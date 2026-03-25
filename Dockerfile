# ── Builder stage: compile Python dependencies ───────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Build-time headers needed by cairosvg (Cairo/Pango/GDK) and cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Download Playwright Chromium browser to a fixed, non-home path
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium


# ── Final stage: lean runtime image ──────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Copy compiled Python packages and CLI tools from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy Playwright Chromium browser from builder
COPY --from=builder /ms-playwright /ms-playwright

# Install runtime system libraries (no build tools here)
#   cairosvg   → libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libffi8
#   opencv     → libglib2.0-0 libgl1
#   fonts      → fonts-dejavu-core  (DejaVu paths hardcoded in utils.py / smartpost.py / campaign.py)
#               fonts-liberation   (Liberation paths hardcoded in smartpost.py / campaign.py)
#   playwright → Chromium OS-level deps installed via playwright install-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libffi8 \
    libglib2.0-0 \
    libgl1 \
    fonts-dejavu-core \
    fonts-liberation \
    && playwright install-deps chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY . .

# Create non-privileged user, fix ownership, and make browser binaries executable
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/generated_images \
    && chown -R appuser /app \
    && chmod -R 755 /ms-playwright

USER appuser

EXPOSE 8055

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8055", "--workers", "4"]
