# One image for all Python services (data prep, training, simulators, ingestion,
# KPI engine, anomaly detection, AI advisor). Each container runs a different module.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY pipeline ./pipeline
COPY simulators ./simulators
COPY services ./services
COPY knowledge_base ./knowledge_base

# data/, models/ and reports/ are mounted as volumes so results survive restarts
# and are visible on the host.
CMD ["python", "-c", "print('Set a command for this container in docker-compose.yml')"]
