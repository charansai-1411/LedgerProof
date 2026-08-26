"""Scenario Lab: generate a fresh dataset at a chosen difficulty and stress-test the pipeline.

Reports, over the bank credits, how many were correctly resolved, correctly rejected (opened as
unexplained), incorrectly resolved (the number that must stay zero), missed, and escalated. Runs
COLD — no pattern cache. Used by the /api/scenario endpoint and the Scenario Lab page.
"""

from __future__ import annotations

import random
import time

from ..agent.grader import grade
from ..agent.heuristic import HeuristicAgentModel
from ..engine.grader import load_ground_truth
from ..generator.config import REPO_ROOT, GeneratorConfig
from ..generator.generate import Generator
from ..generator.writers import write_dataset
from ..verifier.config import GovernorConfig
from ..verifier.models import DECISION_HUMAN
from ..verifier.pipeline import run_pipeline

BASE = REPO_ROOT / "configs" / "generator.yaml"

PRESETS = {
    "easy": dict(exc=0.03, sbm=0.12,
                 breaks={"compound_variance": 0.25, "timing_in_transit": 0.45,
                         "duplicate": 0.15, "unexplained": 0.15},
                 mess={"utr_garbled_rate": 0.15, "utr_missing_rate": 0.05,
                       "same_day_collision_rate": 0.20, "date_drift_days": [0, 1]}),
    "realistic": dict(exc=0.06, sbm=0.25,
                      breaks={"compound_variance": 0.30, "timing_in_transit": 0.40,
                              "duplicate": 0.10, "unexplained": 0.20},
                      mess={"utr_garbled_rate": 0.35, "utr_missing_rate": 0.12,
                            "same_day_collision_rate": 0.45, "date_drift_days": [0, 1, 2, 3]}),
    "adversarial": dict(exc=0.11, sbm=0.45,
                        breaks={"compound_variance": 0.42, "timing_in_transit": 0.30,
                                "duplicate": 0.10, "unexplained": 0.18},
                        mess={"utr_garbled_rate": 0.55, "utr_missing_rate": 0.20,
                              "same_day_collision_rate": 0.65, "date_drift_days": [0, 1, 2, 3, 4]}),
}


def run_scenario(difficulty: str, records: int) -> dict:
    if difficulty not in PRESETS:
        raise ValueError(f"unknown difficulty '{difficulty}'")
    d = PRESETS[difficulty]
    records = max(500, min(int(records), 40_000))

    cfg = GeneratorConfig.load(BASE, seed_override=random.randint(1, 10 ** 9),
                               run_name_override="scenario")
    cfg.n_payments = records
    cfg.exception_rate = d["exc"]
    cfg.seam_b_match_rate = d["sbm"]
    cfg.breaks = d["breaks"]
    cfg.seam_b_mess = d["mess"]
    cfg.validate()

    ds = Generator(cfg).generate()
    out = write_dataset(ds, cfg, out_root=REPO_ROOT / "data" / "scenarios")

    bench = GovernorConfig(enabled=True, min_confidence=0.95, allowlist=["bank_settlement_match"],
                           min_drift_days=0, max_drift_days=4)
    t0 = time.perf_counter()
    recs = run_pipeline(out, HeuristicAgentModel(), bench)  # cold: no cache
    seconds = time.perf_counter() - t0

    gt = load_ground_truth(out)
    b = grade([r.finding for r in recs], gt)
    matchable = b["matchable"]
    human = sum(1 for r in recs if r.governor.decision == DECISION_HUMAN)
    return {
        "difficulty": difficulty, "records": records, "credits": len(recs),
        "matchable": matchable,
        "correctly_resolved": b["correct_matches"],
        "correctly_rejected": b["unexplained"]["correctly_opened"],
        "incorrect_resolutions": b["false_matches"],   # must be 0
        "missed": matchable - b["correct_matches"],    # matchable the agent honestly left open
        "human_escalated": human,
        "false_match_rate": b["false_match_rate"],
        "seconds": round(seconds, 2),
    }
