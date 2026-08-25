"""Load the governor / verifier policy from configs/governor.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..generator.config import REPO_ROOT

DEFAULT_GOVERNOR = REPO_ROOT / "configs" / "governor.yaml"


@dataclass
class GovernorConfig:
    enabled: bool
    min_confidence: float
    allowlist: list[str]
    min_drift_days: int
    max_drift_days: int

    @classmethod
    def load(cls, path: Path | str = DEFAULT_GOVERNOR) -> "GovernorConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        ar = raw["auto_resolve"]
        v = raw.get("verifier", {})
        return cls(
            enabled=bool(ar["enabled"]),
            min_confidence=float(ar["min_confidence"]),
            allowlist=list(ar["allowlist"]),
            min_drift_days=int(v.get("min_drift_days", 0)),
            max_drift_days=int(v.get("max_drift_days", 4)),
        )
