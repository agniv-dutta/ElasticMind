FROM python:3.11-slim

# Keep slim: target_app must not have LightGBM/pandas/heavy deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY target_app/pyproject.toml target_app/
RUN pip install fastapi "uvicorn[standard]" httpx

COPY target_app/ target_app/
RUN pip install --no-deps -e ./target_app

EXPOSE 8001
CMD ["uvicorn", "target_app.app:app", "--host", "0.0.0.0", "--port", "8001"]
