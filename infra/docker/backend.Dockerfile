FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY ml/pyproject.toml ml/
COPY backend/pyproject.toml backend/
COPY loadgen/pyproject.toml loadgen/
COPY target_app/pyproject.toml target_app/

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic pydantic-settings sqlalchemy httpx pyyaml boto3 \
    "numpy>=1.26" "pandas>=2.1" "pyarrow>=15.0" "scikit-learn>=1.4" "lightgbm>=4.3" "statsmodels>=0.14" "joblib>=1.3" "matplotlib>=3.8"

COPY ml/ ml/
COPY backend/ backend/
COPY experiments/ experiments/
COPY loadgen/ loadgen/
COPY target_app/ target_app/

RUN pip install --no-cache-dir -e ./ml -e ./backend

RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
