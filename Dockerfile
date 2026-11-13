# Build with a fixed Python minor version and reproducible dependency ranges.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/promoeditor

# DejaVu is used by Pillow for legible Cyrillic promotional layouts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 promo \
    && useradd --uid 10001 --gid promo --home-dir /srv/promoeditor --no-create-home --shell /usr/sbin/nologin promo

COPY --chown=promo:promo app/ ./app/
RUN mkdir -p /srv/promoeditor/instance/jobs \
    && chown -R promo:promo /srv/promoeditor/instance

USER promo
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=8s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=5).read()" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "8", "--timeout-keep-alive", "10"]
