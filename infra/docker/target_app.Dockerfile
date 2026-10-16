FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY target_app/pyproject.toml target_app/
RUN pip install fastapi "uvicorn[standard]" httpx

COPY target_app/ target_app/
RUN pip install -e ./target_app

EXPOSE 8001
CMD ["uvicorn", "target_app.app:app", "--host", "0.0.0.0", "--port", "8001"]
