FROM python:3.15-rc-alpine

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir .

ENV ANNOTATOR_IMAGES=/app/images
ENV ANNOTATOR_DB=/data/annotations.sqlite3
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["flask", "--app", "app.app:create_app", "run", "--host=0.0.0.0", "--port=5000"]
