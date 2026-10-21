FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y libgomp1 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY ml/pyproject.toml ml/
COPY backend/pyproject.toml backend/
COPY loadgen/pyproject.toml loadgen/
COPY target_app/pyproject.toml target_app/

RUN pip install fastapi "uvicorn[standard]" pydantic pydantic-settings sqlalchemy httpx pyyaml \
    numpy pandas pyarrow scikit-learn lightgbm statsmodels joblib matplotlib boto3

COPY ml/ ml/
COPY backend/ backend/
COPY experiments/ experiments/

RUN pip install -e ./ml -e ./backend

RUN mkdir -p /data
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
