FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY loadgen/pyproject.toml loadgen/
COPY ml/pyproject.toml ml/
# Slim: keep minimal deps for loadgen; do NOT pull lightgbm/pandas heavy if avoidable
RUN pip install --no-cache-dir httpx numpy pandas pyarrow

COPY loadgen/ loadgen/
COPY ml/ ml/
RUN pip install --no-deps -e ./ml -e ./loadgen

CMD ["python", "-m", "loadgen.runner"]
