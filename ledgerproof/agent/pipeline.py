"""Run an AgentModel over every bank credit and collect findings."""

from __future__ import annotations

from pathlib import Path

from .loader import load_seam_b
from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox


def investigate_all(data_dir: str | Path, model: AgentModel) -> list[AgentFinding]:
    tools = SeamBToolbox(load_seam_b(data_dir))
    return [model.investigate(bid, tools) for bid in tools.all_bank_txn_ids()]
