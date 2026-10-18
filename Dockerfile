FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANNOTATOR_IMAGES=/app/images \
    ANNOTATOR_DB=/data/annotations.sqlite3

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir . \
    && addgroup --system --gid 10001 annotator \
    && adduser --system --uid 10001 --ingroup annotator --no-create-home annotator

USER 10001:10001

EXPOSE 5000

CMD ["gunicorn", "--workers", "2", "--threads", "2", "--graceful-timeout", "30", "--bind", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "app.app:create_app()"]
