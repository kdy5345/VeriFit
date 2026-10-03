FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 verifit \
    && mkdir -p /app/data \
    && chown verifit:verifit /app/data
COPY backend/scripts ./scripts
COPY backend/run.py ./
USER verifit
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
# SQLite checkpoints and per-thread locks use a single API worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir '.[dev]'
COPY backend/tests ./tests
USER verifit
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
