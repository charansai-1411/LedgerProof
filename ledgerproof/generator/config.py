"""Config loading for the generator. Reads configs/generator.yaml and configs/fees.yaml.

The fee config is shared with the deterministic engine — fees are policy, not hardcode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEES = REPO_ROOT / "configs" / "fees.yaml"


@dataclass
class FeeConfig:
    gst_rate_bps: int
    methods: dict[str, dict[str, int]]
    reserve_rate_bps: int
    reserve_applies_to: list[str]

    @classmethod
    def load(cls, path: Path | str = DEFAULT_FEES) -> "FeeConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            gst_rate_bps=int(raw["gst_rate_bps"]),
            methods={m: {k: int(v) for k, v in cfg.items()} for m, cfg in raw["methods"].items()},
            reserve_rate_bps=int(raw["reserve"]["rate_bps"]),
            reserve_applies_to=list(raw["reserve"]["applies_to"]),
        )


@dataclass
class GeneratorConfig:
    seed: int
    run_name: str
    merchant_id: str
    n_payments: int
    n_cycles: int
    settlement_delay_days: int
    base_date: str
    method_mix: dict[str, float]
    refund_rate: float
    exception_rate: float
    breaks: dict[str, float]
    seam_b_match_rate: float
    seam_b_mess: dict[str, Any]
    fees: FeeConfig = field(default_factory=FeeConfig.load)

    @classmethod
    def load(
        cls,
        path: Path | str,
        seed_override: int | None = None,
        run_name_override: str | None = None,
        fees_path: Path | str = DEFAULT_FEES,
    ) -> "GeneratorConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        cfg = cls(
            seed=int(raw["seed"]),
            run_name=str(raw["run_name"]),
            merchant_id=str(raw["merchant_id"]),
            n_payments=int(raw["n_payments"]),
            n_cycles=int(raw["n_cycles"]),
            settlement_delay_days=int(raw["settlement_delay_days"]),
            base_date=str(raw["base_date"]),
            method_mix={k: float(v) for k, v in raw["method_mix"].items()},
            refund_rate=float(raw["refund_rate"]),
            exception_rate=float(raw["exception_rate"]),
            breaks={k: float(v) for k, v in raw["breaks"].items()},
            seam_b_match_rate=float(raw["seam_b_match_rate"]),
            seam_b_mess=dict(raw["seam_b_mess"]),
            fees=FeeConfig.load(fees_path),
        )
        if seed_override is not None:
            cfg.seed = seed_override
        if run_name_override is not None:
            cfg.run_name = run_name_override
        cfg.validate()
        return cfg

    def validate(self) -> None:
        mix_sum = sum(self.method_mix.values())
        if abs(mix_sum - 1.0) > 1e-6:
            raise ValueError(f"method_mix must sum to 1.0, got {mix_sum}")
        if not (0.0 <= self.exception_rate < 1.0):
            raise ValueError(f"exception_rate must be in [0, 1), got {self.exception_rate}")
        for m in self.method_mix:
            if m not in self.fees.methods:
                raise ValueError(f"method '{m}' in method_mix has no entry in fees.yaml")
