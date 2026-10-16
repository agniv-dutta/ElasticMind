"""Load a trained model from S3 (or fall back to a local path)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

from ml.models.base import Predictor
from ml.models.registry import load_predictor


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"malformed s3 uri: {uri}")
    return bucket, key


def load_model_from_s3(
    uri: str,
    local_dir: str | Path = "ml/models/artifacts",
    region: str | None = None,
    s3_client: Any | None = None,
    local_fallback: str | Path | None = None,
) -> Predictor:
    """Download ``s3://bucket/key`` and load it with the model registry.

    Falls back to a local model if the S3 download fails (e.g. offline dev).
    """
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    if uri:
        try:
            bucket, key = _parse_s3_uri(uri)
            client = s3_client or (boto3.client("s3", region_name=region) if boto3 else None)
            if client is None:
                raise ImportError("boto3 unavailable")
            dest = local_dir / Path(key).name
            client.download_file(bucket, key, str(dest))
            meta_key = f"{key.rsplit('.', 1)[0]}.meta.json"
            try:
                client.download_file(bucket, meta_key, str(dest.with_suffix(".meta.json")))
            except Exception:
                pass
            return load_predictor(dest)
        except Exception:
            pass

    if local_fallback is not None and Path(local_fallback).exists():
        return load_predictor(local_fallback)
    raise FileNotFoundError(f"could not load model from {uri!r} or local fallback")
