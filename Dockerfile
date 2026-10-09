# LedgerOps Copilot API -- containerized for deployment.
#
# This packages the FastAPI dashboard/API (app/api/main.py). It does NOT run
# the reconciliation/fraud pipeline scripts automatically -- those generate
# data/*.json, which this container reads. Either bake pre-generated sample
# data into the image (as this Dockerfile does, for demo purposes) or mount
# a volume with real data for production use -- see docker-compose.yml.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (separate layer so `docker build` doesn't
# re-install on every code change, only when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY docs/ ./docs/

# Generate demo data at build time so the image is runnable standalone --
# in a real deployment, data/ would instead be a mounted volume populated
# by a scheduled job (see docs/case-study.md "what I'd do with more time"
# section for the intended production data-refresh design).
RUN python scripts/generate_sample_data.py \
    && python scripts/run_reconciliation.py \
    && python scripts/run_fraud_detection.py

EXPOSE 8000

# Basic container-level health check, backed by the app's own /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]