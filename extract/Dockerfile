# Tier-1 container worker: PyMuPDF routing, pdftotext, pandoc.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils pandoc \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 extract
WORKDIR /app
COPY pyproject.toml ./
COPY extract_worker ./extract_worker
RUN pip install --no-cache-dir .
USER extract
ENTRYPOINT ["extract-worker", "--role", "container"]
