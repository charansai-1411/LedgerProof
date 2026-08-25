"""Build the end-to-end reconciliation report card."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..agent.grader import grade as grade_seam_b
from ..agent.model import AgentModel
from ..engine.grader import grade as grade_seam_a
from ..engine.grader import load_ground_truth
from ..engine.loader import load_sources
from ..engine.seam_a import SeamAEngine
from ..generator.config import FeeConfig
from ..verifier.config import GovernorConfig
from ..verifier.models import DECISION_AUTO, DECISION_HUMAN
from ..verifier.pipeline import run_pipeline


def build_report(data_dir: str | Path, model: AgentModel, gov_cfg: GovernorConfig) -> dict:
    data_dir = Path(data_dir)
    gt = load_ground_truth(data_dir)
    fees = FeeConfig.load()

    t0 = time.perf_counter()

    # --- Seam A: deterministic settlement-report <-> ledger ---
    sources = load_sources(data_dir)
    recon = SeamAEngine(fees).reconcile(sources)
    a = grade_seam_a(recon, gt)

    # --- Seam B: agent -> verifier -> governor ---
    records = run_pipeline(data_dir, model, gov_cfg)
    b = grade_seam_b([r.finding for r in records], gt)

    elapsed = time.perf_counter() - t0

    # governance outcomes
    autos = [r for r in records if r.governor.decision == DECISION_AUTO]
    humans = [r for r in records if r.governor.decision == DECISION_HUMAN]
    gt_credits = gt["bank_credits"]
    wrong_autos = [
        r for r in autos
        if r.finding.matched_settlement_id != gt_credits[r.finding.bank_txn_id]["true_settlement_id"]
    ]

    # human-queue precision: of items sent to a human, how many genuinely needed one
    # (unexplained credits, or matchable ones the agent could not confidently resolve) vs items
    # that were cleanly resolvable but held (e.g. because auto-resolve is off).
    def genuinely_human(r) -> bool:
        info = gt_credits[r.finding.bank_txn_id]
        if info["break_type"] == "unexplained":
            return True
        return not r.verification.verified  # matchable but unproven -> genuinely needs a human
    genuine = [r for r in humans if genuinely_human(r)]

    # cardinal metric: everything the system ASSERTED/acted on that was wrong
    acted_matches = a["matched"] + len(autos)
    acted_false = len(a["false_matches"]) + len(wrong_autos)
    combined_false_rate = round(acted_false / acted_matches, 6) if acted_matches else 0.0

    # coverage: every item not auto-resolved carries a reason
    seam_a_reasons = all(e.category and e.detail for e in recon.exceptions)
    seam_b_reasons = all((r.governor.reason and (r.finding.narrative or r.finding.matched_settlement_id))
                         for r in humans)

    records_processed = recon.total_payments + len(records)

    return {
        "dataset": data_dir.name,
        "seed": gt.get("seed"),
        "policy": {
            "auto_resolve_enabled": gov_cfg.enabled,
            "min_confidence": gov_cfg.min_confidence,
            "allowlist": list(gov_cfg.allowlist),
        },
        "cardinal": {
            "combined_false_match_rate": combined_false_rate,
            "acted_matches": acted_matches,
            "acted_false_matches": acted_false,
        },
        "seam_a_payments": {
            "total": recon.total_payments,
            "matched": a["matched"],
            "match_rate": a["match_rate"],
            "false_match_rate": a["false_match_rate"],
            "exceptions": a["exceptions"],
            "partial_payment_recall": a["partial_payment"]["recall"],
            "timing_recall": a["timing_in_transit"]["recall"],
            "duplicates_detected": a["duplicates_detected"],
        },
        "seam_b_credits": {
            "total": b["credits_total"],
            "matchable": b["matchable"],
            "correct_matches": b["correct_matches"],
            "false_match_rate": b["false_match_rate"],
            "matchable_recall": b["matchable_recall"],
            "hero": b["hero"],
            "unexplained_correctly_opened": b["unexplained"]["correctly_opened"],
        },
        "governance": {
            "verified": sum(1 for r in records if r.verification.verified),
            "auto_resolved": len(autos),
            "wrong_auto_resolutions": len(wrong_autos),
            "human_review": len(humans),
            "auto_resolve_rate": round(len(autos) / len(records), 4) if records else 0.0,
            "human_queue_precision": round(len(genuine) / len(humans), 4) if humans else 1.0,
        },
        "coverage": {
            "every_unresolved_item_has_a_reason": bool(seam_a_reasons and seam_b_reasons),
        },
        "throughput": {
            "records_processed": records_processed,
            "seconds": round(elapsed, 3),
            "records_per_second": round(records_processed / elapsed, 1) if elapsed else 0.0,
        },
    }


def format_card(card: dict) -> str:
    a, b, g, c = card["seam_a_payments"], card["seam_b_credits"], card["governance"], card["cardinal"]
    lines = [
        f"RECONCILIATION REPORT CARD  —  dataset '{card['dataset']}' (seed {card['seed']})",
        f"  policy: auto_resolve={card['policy']['auto_resolve_enabled']} "
        f"min_confidence={card['policy']['min_confidence']} allowlist={card['policy']['allowlist']}",
        "",
        f"  CARDINAL  combined false-match rate : {c['combined_false_match_rate']}  "
        f"({c['acted_false_matches']} wrong of {c['acted_matches']} asserted)  "
        f"{'PASS (zero)' if c['combined_false_match_rate'] == 0.0 else 'FAIL'}",
        "",
        f"  Seam A (payments)  {a['matched']}/{a['total']} matched  "
        f"({a['match_rate']:.1%})   false-match {a['false_match_rate']}   exceptions {a['exceptions']}",
        f"      partial-payment recall {a['partial_payment_recall']:.0%} · "
        f"timing recall {a['timing_recall']:.0%} · "
        f"dupes {a['duplicates_detected']['detected']}/{a['duplicates_detected']['true']}",
        f"  Seam B (bank credits)  {b['correct_matches']}/{b['matchable']} matched  "
        f"(hero {b['hero']['correct']}/{b['hero']['total']})   false-match {b['false_match_rate']}   "
        f"unexplained opened {b['unexplained_correctly_opened']}",
        "",
        f"  Governance  verified {g['verified']} · auto-resolved {g['auto_resolved']} "
        f"(wrong {g['wrong_auto_resolutions']}) · human queue {g['human_review']} "
        f"(precision {g['human_queue_precision']:.0%})",
        f"  Coverage  every unresolved item has a reason: "
        f"{card['coverage']['every_unresolved_item_has_a_reason']}",
        f"  Throughput  {card['throughput']['records_per_second']:.0f} records/s "
        f"({card['throughput']['records_processed']} in {card['throughput']['seconds']}s)",
    ]
    return "\n".join(lines)
