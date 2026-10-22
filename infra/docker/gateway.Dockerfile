FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx pydantic pydantic-settings
COPY backend/ backend/
COPY gateway/ gateway/
EXPOSE 8001
CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8001"]
