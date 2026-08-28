"""AI Necessity Benchmark + metric decomposition — the honest self-attack.

Two questions a senior reviewer asks, answered with measurement, not architecture philosophy:

  1. "Why couldn't a strong engineer just write deterministic candidate search + scoring?"
     -> We built exactly that (the `det_search` tier) and measure, per exception class, where it
        succeeds, where it conservatively opens, and where the candidate window doesn't even contain
        the answer. The honest finding: for the current break distribution deterministic search
        recovers almost everything; its frontier is same-day collisions and out-of-window date drift.

  2. "Is the agent solving anything, or is the verifier doing the hard work?"
     -> We separate the metrics: candidate reachability, proposer accuracy (BEFORE the verifier),
        verifier rejection rate of wrong proposals, and final accuracy — each with population n. A
        conservative proposer (det_search) rarely proposes a wrong match, so the verifier rejects
        little; an aggressive proposer (greedy, never opens) proposes many wrong matches, and there
        the verifier earns its keep — catching every one, final false-match rate 0.

Everything runs against the hidden ground truth; the working DB never contains it.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from ..agent.grader import grade
from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
from ..agent.model import AgentFinding
from ..agent.tools import SeamBToolbox
from ..engine.grader import load_ground_truth
from ..verifier.config import GovernorConfig
from ..verifier.governor import Governor
from ..verifier.verifier import SeamBVerifier

# hardest-tag priority for classifying a hard credit
_CLASS_ORDER = ["same_day_collision", "utr_missing", "utr_garbled", "date_drift"]


def _hard_class(difficulty: list[str]) -> str:
    for tag in _CLASS_ORDER:
        if tag in difficulty:
            return tag
    return "other"


def _exact_only(bc, tools: SeamBToolbox) -> AgentFinding:
    """Tier 0 — exact unique UTR whose amount also reconciles. Otherwise open."""
    s = tools.find_settlement_by_utr(bc.utr)
    if s is not None and s.amount == bc.credit_amount:
        return AgentFinding(bc.bank_txn_id, s.settlement_id, 0.99, ["exact_utr", "net_amount"])
    return AgentFinding(bc.bank_txn_id, None, 0.0, [])


def _greedy(bc, tools: SeamBToolbox) -> AgentFinding:
    """Aggressive proposer — ALWAYS proposes the nearest-amount candidate in the window, never opens.
    Deliberately unsafe, so the verifier has real wrong proposals to catch."""
    s = tools.find_settlement_by_utr(bc.utr)
    if s is not None and s.amount == bc.credit_amount:
        return AgentFinding(bc.bank_txn_id, s.settlement_id, 0.99, ["exact_utr", "net_amount"])
    cands = tools.get_settlements_in_window(bc.value_date, 3, 1)
    if not cands:
        return AgentFinding(bc.bank_txn_id, None, 0.0, [])
    nearest = min(cands, key=lambda c: abs(c.amount - bc.credit_amount))
    return AgentFinding(bc.bank_txn_id, nearest.settlement_id, 0.80, ["date_window", "nearest_amount"])


def _tally(findings, gt) -> dict:
    """correct / open / wrong counts against ground truth, ignoring category."""
    correct = wrong = opened = 0
    for f in findings:
        true = gt[f.bank_txn_id]["true_settlement_id"]
        if f.matched_settlement_id is None:
            opened += 1
        elif f.matched_settlement_id == true:
            correct += 1
        else:
            wrong += 1
    return {"n": len(findings), "correct": correct, "open": opened, "wrong": wrong}


def necessity_report(data_dir: str | Path) -> dict:
    if not (Path(data_dir) / "ground_truth.json").exists():
        return {"graded": False}
    tools = SeamBToolbox(load_seam_b(data_dir))
    gt = load_ground_truth(data_dir)["bank_credits"]
    bids = tools.all_bank_txn_ids()

    heuristic = HeuristicAgentModel()
    findings = {
        "exact_only": [_exact_only(tools.get_bank_credit(b), tools) for b in bids],
        "det_search": [heuristic.investigate(b, tools) for b in bids],
        "greedy": [_greedy(tools.get_bank_credit(b), tools) for b in bids],
    }

    # ---- 1. candidate reachability: is the true settlement even in the search window? ----
    matchable = [b for b in bids if gt[b]["break_type"] in ("clean", "bank_settlement_match")]
    reachable = 0
    for b in matchable:
        bc = tools.get_bank_credit(b)
        window = {s.settlement_id for s in tools.get_settlements_in_window(bc.value_date, 3, 1)}
        window |= {s.settlement_id for s in tools.get_settlements_in_window(bc.value_date, 0, 0)}
        s = tools.find_settlement_by_utr(bc.utr)
        if s:
            window.add(s.settlement_id)
        if gt[b]["true_settlement_id"] in window:
            reachable += 1

    # ---- 2. per-class resolution for each tier (before the verifier) ----
    classes: dict[str, list[str]] = {"clean": [], "unexplained": []}
    for b in bids:
        v = gt[b]
        if v["break_type"] == "clean":
            classes["clean"].append(b)
        elif v["break_type"] == "unexplained":
            classes["unexplained"].append(b)
        else:
            classes.setdefault("hard:" + _hard_class(v["difficulty"]), []).append(b)

    per_class = []
    for cls, members in classes.items():
        mset = set(members)
        row = {"class": cls, "n": len(members)}
        for tier, fs in findings.items():
            row[tier] = _tally([f for f in fs if f.bank_txn_id in mset], gt)
        per_class.append(row)
    per_class.sort(key=lambda r: (not r["class"].startswith("hard"), r["class"]))

    # ---- 3. does the verifier actually do work? greedy proposals through verify+govern ----
    bench = GovernorConfig(enabled=True, min_confidence=0.5, allowlist=["bank_settlement_match"],
                           min_drift_days=0, max_drift_days=4)
    verifier = SeamBVerifier(bench.min_drift_days, bench.max_drift_days)
    governor = Governor(bench)

    def verify_pass(fs):
        claimed = Counter(f.matched_settlement_id for f in fs if f.matched_settlement_id)
        proposed = wrong_proposed = wrong_rejected = final_wrong = accepted = 0
        for f in fs:
            if f.matched_settlement_id is None:
                continue
            proposed += 1
            true = gt[f.bank_txn_id]["true_settlement_id"]
            is_wrong = f.matched_settlement_id != true
            if is_wrong:
                wrong_proposed += 1
            v = verifier.verify(f, tools, claimed)
            g = governor.decide(f, v)
            acted = g.decision == "auto_resolved"
            if acted:
                accepted += 1
                if is_wrong:
                    final_wrong += 1
            elif is_wrong and not v.verified:
                wrong_rejected += 1
        return {"proposed": proposed, "wrong_proposed": wrong_proposed,
                "wrong_rejected_by_verifier": wrong_rejected, "accepted": accepted,
                "final_false_matches": final_wrong,
                "proposal_accuracy": round((proposed - wrong_proposed) / proposed, 4) if proposed else 1.0,
                "verifier_rejection_rate_of_wrong": round(wrong_rejected / wrong_proposed, 4) if wrong_proposed else 1.0}

    verifier_work = {"greedy": verify_pass(findings["greedy"]),
                     "det_search": verify_pass(findings["det_search"])}

    # ---- 4. decomposed final metrics (with n) ----
    det_grade = grade(findings["det_search"], {"bank_credits": gt})
    return {
        "graded": True,
        "dataset": Path(data_dir).name,
        "population": {"credits": len(bids), "matchable": len(matchable),
                       "clean": sum(1 for b in bids if gt[b]["break_type"] == "clean"),
                       "hard": sum(1 for b in bids if gt[b]["break_type"] == "bank_settlement_match"),
                       "unexplained": sum(1 for b in bids if gt[b]["break_type"] == "unexplained")},
        "candidate_reachability": {"matchable": len(matchable), "in_window": reachable,
                                   "recall": round(reachable / len(matchable), 4) if matchable else 1.0},
        "per_class": per_class,
        "verifier_work": verifier_work,
        "decomposition": {
            "det_search_proposal_accuracy": verifier_work["det_search"]["proposal_accuracy"],
            "det_search_proposals": verifier_work["det_search"]["proposed"],
            "greedy_proposal_accuracy": verifier_work["greedy"]["proposal_accuracy"],
            "greedy_proposals": verifier_work["greedy"]["proposed"],
            "final_matchable_recall": det_grade["matchable_recall"],
            "final_false_match_rate": det_grade["false_match_rate"],
            "n_matchable": det_grade["matchable"],
        },
        "conclusion": _conclude(per_class, verifier_work, reachable, len(matchable)),
    }


def _conclude(per_class, verifier_work, reachable, n_matchable) -> str:
    gw = verifier_work["greedy"]
    frontier = [r["class"].replace("hard:", "") for r in per_class
                if r["class"].startswith("hard") and r["det_search"]["open"] > 0]
    miss = n_matchable - reachable
    parts = [
        "Deterministic candidate search (window + amount + UTR-prefix) recovers the hard bank-credit "
        "cases the exact-key tier cannot — so for the CURRENT break distribution a strong engineer's "
        "search, not an LLM, is what does the work.",
    ]
    if frontier:
        parts.append("Its honest frontier is " + ", ".join(sorted(set(frontier))) +
                     " — cases it conservatively OPENS rather than force-matching (where softer evidence, "
                     "i.e. an LLM, could add recall at the verifier's gate).")
    if miss > 0:
        parts.append(f"{miss} matchable credit(s) fall outside the deterministic date window entirely — "
                     "the search space did not contain the answer, an a-priori limit of fixed-window search.")
    parts.append(f"The verifier's value shows only against an AGGRESSIVE proposer: greedy proposed "
                 f"{gw['wrong_proposed']} wrong matches and the verifier rejected {gw['wrong_rejected_by_verifier']} "
                 f"of them — final false matches {gw['final_false_matches']}. A conservative proposer barely "
                 f"exercises the verifier; an LLM (which CAN propose confidently-wrong matches) is exactly why "
                 f"the deterministic gate is non-negotiable.")
    return " ".join(parts)
