FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY loadgen/pyproject.toml loadgen/
RUN pip install httpx numpy pandas pyarrow pyyaml

COPY loadgen/ loadgen/
RUN pip install -e ./loadgen

CMD ["python", "-m", "loadgen.runner"]
