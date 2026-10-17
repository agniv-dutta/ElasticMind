"""Audit logging of scaling actions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class AuditEntry:
    timestamp: str
    desired: int
    current: int
    action: str
    reason: str


class AuditLog:
    def __init__(self, path: str | Path = "backend/data/audit.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, desired: int, current: int, action: str, reason: str) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            desired=desired,
            current=current,
            action=action,
            reason=reason,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def read(self, limit: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out