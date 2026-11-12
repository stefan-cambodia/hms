# HMS API / worker image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --home /app hms
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install . && pip uninstall -y hms-backend || true
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker-entrypoint.sh /usr/local/bin/hms-entrypoint
RUN chmod +x /usr/local/bin/hms-entrypoint && mkdir -p /app/var/media && chown -R hms /app/var
USER hms
EXPOSE 8000
ENTRYPOINT ["hms-entrypoint"]
CMD ["api"]
