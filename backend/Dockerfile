# HMS API / worker image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XDG_CACHE_HOME=/app/var/cache
# Pango + HarfBuzz for PDF documents; Noto fonts cover Latin, Cyrillic,
# Khmer (fonts-noto-core) and Simplified Chinese (fonts-noto-cjk).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fontconfig fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f
RUN useradd --system --uid 10001 --home /app hms
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install . && pip uninstall -y hms-backend || true
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker-entrypoint.sh /usr/local/bin/hms-entrypoint
RUN chmod +x /usr/local/bin/hms-entrypoint && mkdir -p /app/var/media /app/var/cache && chown -R hms /app/var
USER hms
EXPOSE 8000
ENTRYPOINT ["hms-entrypoint"]
CMD ["api"]
