"""Human-investigation benchmark — the agent's honest value proposition.

The agent does NOT beat deterministic search at matching (see necessity.py: its marginal accuracy is
zero on realistic data). Its value is that it turns a human's job on each exception from *searching*
candidate settlements into *auditing* one pre-searched, pre-verified finding. This benchmark measures
that, and is scrupulous about what is MEASURED vs MODELED:

  MEASURED (counted from the data, no assumptions):
    - records a human must inspect UNASSISTED: the candidate settlements in the plausible date window
      they must open and compare to find — or refute — a match.
    - records inspected ASSISTED: 1 — the human audits the agent's single finding (its re-derived net
      for a proposed match, or its "searched N, none reconcile" summary for an opened credit). The
      agent already inspected the candidates.
    - evidence items the agent pre-assembles per case.
    - final correctness / false-match / unresolved rate on the assisted path.

  MODELED (a transparent arithmetic model over the MEASURED counts, constants stated and tunable):
    - minutes-to-resolution = fixed_overhead + records_inspected * seconds_per_record. This is NOT a
      human-subjects study; it is records-inspected scaled by a stated per-record cost, so the ratio
      is the honest headline and the minutes are illustrative.

Accuracy is deliberately held at PARITY: a careful human reaches the same answer unassisted — the
agent's contribution is effort, not accuracy. So false matches stay 0 and the unresolved set (true
orphans) is identical either way; only the work to get there changes.
"""

from __future__ import annotations

from pathlib import Path

from ..agent.grader import grade
from ..agent.heuristic import HeuristicAgentModel
from ..agent.loader import load_seam_b
from ..agent.tools import SeamBToolbox
from ..engine.grader import load_ground_truth

# --- modeled time constants (stated so a reviewer can change them) ---
SEC_PER_RECORD = 25     # open a settlement's report rows and compare amounts
FIXED_UNASSISTED = 60   # pull the credit + write the resolution note, from scratch
FIXED_ASSISTED = 40     # read the agent's finding + confirm the verifier's re-derivation
SEC_PER_EVIDENCE = 8    # skim one pre-assembled evidence item


def human_investigation_report(data_dir: str | Path) -> dict:
    if not (Path(data_dir) / "ground_truth.json").exists():
        return {"graded": False}
    tools = SeamBToolbox(load_seam_b(data_dir))
    gt = load_ground_truth(data_dir)["bank_credits"]
    model = HeuristicAgentModel()

    unassisted_records = []
    assisted_records = []
    evidence_items = []
    findings = []
    for b in tools.all_bank_txn_ids():
        bc = tools.get_bank_credit(b)
        s = tools.find_settlement_by_utr(bc.utr)
        if s is not None and s.amount == bc.credit_amount:
            continue  # clean-UTR: trivial, never reaches a human — excluded from the queue
        f = model.investigate(b, tools)
        findings.append(f)
        window = tools.get_settlements_in_window(bc.value_date, 3, 1)
        unassisted_records.append(max(1, len(window)))   # human searches the date-narrowed candidates
        assisted_records.append(1)                       # human audits the ONE finding
        evidence_items.append(len(f.evidence))

    n = len(findings)
    if n == 0:
        return {"graded": True, "investigated": 0}

    def mean(xs):
        return round(sum(xs) / len(xs), 2)

    tot_un, tot_as = sum(unassisted_records), sum(assisted_records)
    un_min = mean([(FIXED_UNASSISTED + r * SEC_PER_RECORD) / 60 for r in unassisted_records])
    as_min = mean([(FIXED_ASSISTED + 1 * SEC_PER_RECORD + e * SEC_PER_EVIDENCE) / 60
                   for e in evidence_items])

    # accuracy parity: measured on the assisted path; human-alone assumed equal (documented)
    b = grade(findings, {"bank_credits": gt})
    orphans = sum(1 for v in gt.values() if v["break_type"] == "unexplained")

    return {
        "graded": True,
        "dataset": Path(data_dir).name,
        "investigated": n,
        "measured": {
            "records_inspected_per_case": {"unassisted": mean(unassisted_records),
                                           "assisted": mean(assisted_records)},
            "records_inspected_total": {"unassisted": tot_un, "assisted": tot_as},
            "record_reduction_factor": round(tot_un / tot_as, 1) if tot_as else 0,
            "evidence_items_preassembled_per_case": mean(evidence_items),
            "correct_resolutions": b["correct_matches"],   # matches the agent got right (assisted)
            "false_matches": b["false_matches"],           # the cardinal metric — parity at 0
            "unresolved_true_orphans": orphans,            # identical either way (correctly open)
        },
        "modeled_time": {
            "assumptions": {"seconds_per_record_inspected": SEC_PER_RECORD,
                            "fixed_overhead_unassisted_s": FIXED_UNASSISTED,
                            "fixed_overhead_assisted_s": FIXED_ASSISTED,
                            "seconds_per_evidence_item": SEC_PER_EVIDENCE},
            "minutes_per_case": {"unassisted": un_min, "assisted": as_min},
            "speedup": round(un_min / as_min, 1) if as_min else 0,
            "disclaimer": "Modeled from MEASURED record counts under the stated per-record cost — not "
                          "a human-subjects study. The record-reduction factor is the measured headline; "
                          "the minutes are an illustration and move with the assumptions.",
        },
        "conclusion": (
            f"On the {n} exceptions that reach a human, the agent turns searching into auditing: a "
            f"human inspects {mean(unassisted_records)} candidate settlements per case unassisted vs "
            f"{mean(assisted_records)} assisted — a measured {round(tot_un / tot_as, 1)}x reduction in "
            f"records inspected — at accuracy parity (false matches {b['false_matches']}, the same "
            f"{orphans} true orphans left open either way). The agent's value is effort, not accuracy."
        ),
    }
