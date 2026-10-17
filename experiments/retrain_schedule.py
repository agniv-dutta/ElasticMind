"""Scheduled retraining with versioned models (simulated)."""
from __future__ import annotations

import json
from pathlib import Path


class ModelVersionStore:
    def __init__(self, root: str | Path = "ml/models/versions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta = self.root / "versions.json"

    def _read(self) -> dict:
        if not self.meta.exists():
            return {}
        return json.loads(self.meta.read_text())

    def promote_if_better(self, new_mape: float, current_mape: float | None = None) -> bool:
        if current_mape is None:
            versions = self._read()
            current_mape = versions.get("promoted", {}).get("mape")
        return current_mape is None or float(new_mape) < float(current_mape)

    def register(self, version: str, mape: float, promote: bool = False) -> None:
        data = self._read()
        data[version] = {"mape": mape}
        if promote:
            data["promoted"] = {"version": version, "mape": mape}
        self.meta.write_text(json.dumps(data, indent=2))