FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=parsifal.settings.production \
    PARSIFAL_DATA_DIR=/data \
    PARSIFAL_STATIC_ROOT=/app/staticfiles \
    DEBUG=False \
    ALLOWED_HOSTS=* \
    PORT=8000

WORKDIR /app

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/production.txt

COPY . .

# Static files are collected into the image (served by WhiteNoise); the data directory is a volume.
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/app/bin/entrypoint.sh"]
CMD ["serve"]
