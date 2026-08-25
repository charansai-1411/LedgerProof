"""Orchestrate agent -> verifier -> governor over every Seam-B credit."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..agent.loader import load_seam_b
from ..agent.model import AgentModel
from ..agent.tools import SeamBToolbox
from .config import GovernorConfig
from .governor import Governor
from .models import DecisionRecord
from .verifier import SeamBVerifier


def run_pipeline(data_dir: str | Path, model: AgentModel, cfg: GovernorConfig) -> list[DecisionRecord]:
    tools = SeamBToolbox(load_seam_b(data_dir))
    findings = [model.investigate(bid, tools) for bid in tools.all_bank_txn_ids()]

    # how many findings claim each settlement — used by the verifier's conflict check
    claimed = Counter(f.matched_settlement_id for f in findings if f.matched_settlement_id)

    verifier = SeamBVerifier(cfg.min_drift_days, cfg.max_drift_days)
    governor = Governor(cfg)

    records: list[DecisionRecord] = []
    for f in findings:
        v = verifier.verify(f, tools, claimed)
        g = governor.decide(f, v)
        records.append(DecisionRecord(finding=f, verification=v, governor=g))
    return records
