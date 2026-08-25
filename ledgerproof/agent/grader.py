"""Grade Seam-B findings against the hidden ground truth.

Cardinal metric again: FALSE-MATCH RATE — a credit the agent matched to the WRONG settlement.
Also reports accuracy on the hard 'hero' subset (bank_settlement_match) separately, because the
clean credits are easy and would otherwise mask the number that actually matters.
"""

from __future__ import annotations

from .model import AgentFinding


def grade(findings: list[AgentFinding], ground_truth: dict) -> dict:
    gt = ground_truth["bank_credits"]

    def bucket(break_type: str) -> set[str]:
        return {bid for bid, v in gt.items() if v["break_type"] == break_type}

    clean, hero, unexplained = bucket("clean"), bucket("bank_settlement_match"), bucket("unexplained")
    matchable = clean | hero

    correct = wrong = 0
    hero_correct = 0
    unexplained_correctly_open = 0
    matchable_left_open = 0
    proposed = 0

    for f in findings:
        true = gt[f.bank_txn_id]["true_settlement_id"]
        if f.matched_settlement_id is None:
            if f.bank_txn_id in unexplained:
                unexplained_correctly_open += 1
            elif f.bank_txn_id in matchable:
                matchable_left_open += 1  # missed, but NOT a false match (honest miss)
            continue
        proposed += 1
        if f.matched_settlement_id == true:
            correct += 1
            if f.bank_txn_id in hero:
                hero_correct += 1
        else:
            wrong += 1  # false match — the cardinal sin

    return {
        "credits_total": len(findings),
        "matchable": len(matchable),
        "correct_matches": correct,
        "false_matches": wrong,
        "false_match_rate": round(wrong / proposed, 6) if proposed else 0.0,
        "matchable_recall": round(correct / len(matchable), 4) if matchable else 1.0,
        "matchable_left_open": matchable_left_open,
        "hero": {
            "total": len(hero),
            "correct": hero_correct,
            "recall": round(hero_correct / len(hero), 4) if hero else 1.0,
        },
        "unexplained": {
            "total": len(unexplained),
            "correctly_opened": unexplained_correctly_open,
        },
    }
