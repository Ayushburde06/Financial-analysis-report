# Playwright Python image already includes Chromium at a matching version.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    ENVIRONMENT=production \
    MAX_LIVE_PDF_PAGES=70 \
    PREFER_LOCAL_PDF_TEXT=0 \
    PER_PAGE_OCR=0 \
    LLM_MAX_ATTEMPTS=2 \
    PDF_RENDER_SETTLE_MS=500 \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/uploads /app/outputs /app/tmp /tmp/matplotlib

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
