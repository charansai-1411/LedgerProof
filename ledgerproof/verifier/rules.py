"""Rule Inspector (critique 18) — make the policy behind a decision inspectable.

Every rule has a stable id, a plain description, its current value, and where the value comes from.
`rules_for_decision` returns exactly the rules that fired for one credit, so "why did we (not)
resolve this?" answers with concrete rule ids, not hand-waving — reinforcing that the judgment is
policy, not model opinion.
"""

from __future__ import annotations

from ..generator.config import FeeConfig
from ..verifier.config import GovernorConfig


def rule_catalog(gov: GovernorConfig, fees: FeeConfig) -> list[dict]:
    return [
        {"id": "R-021", "rule": "settlement_window",
         "value": f"T+{gov.min_drift_days}..T+{gov.max_drift_days} days",
         "source": "configs/governor.yaml → verifier"},
        {"id": "R-044", "rule": "mdr_fee", "value": "configured per-instrument rate",
         "source": "configs/fees.yaml → methods",
         "detail": {m: f"{c['mdr_bps']}bps+₹{c['flat_paise']/100:g}" for m, c in fees.methods.items()}},
        {"id": "R-052", "rule": "gst_on_mdr", "value": f"{fees.gst_rate_bps/100:g}% of MDR",
         "source": "configs/fees.yaml → gst_rate_bps"},
        {"id": "R-058", "rule": "tds_194o", "value": f"{fees.tds_rate_bps/100:g}% of gross",
         "source": "configs/fees.yaml → tds_rate_bps"},
        {"id": "R-063", "rule": "rolling_reserve",
         "value": f"{fees.reserve_rate_bps/100:g}% on {','.join(fees.reserve_applies_to)}",
         "source": "configs/fees.yaml → reserve"},
        {"id": "R-071", "rule": "auto_resolve_threshold", "value": f"confidence ≥ {gov.min_confidence}",
         "source": "configs/governor.yaml → auto_resolve.min_confidence"},
        {"id": "R-072", "rule": "auto_resolve_allowlist", "value": ", ".join(gov.allowlist) or "(empty)",
         "source": "configs/governor.yaml → auto_resolve.allowlist"},
        {"id": "R-080", "rule": "false_match_is_cardinal",
         "value": "never force a match; open when unproven", "source": "design invariant"},
    ]


def rules_for_decision(record, gov: GovernorConfig, fees: FeeConfig) -> list[dict]:
    """The subset of rules that actually governed THIS credit's decision."""
    cat = {r["id"]: r for r in rule_catalog(gov, fees)}
    fired: list[str] = ["R-080"]  # always in force
    f = record.finding
    if f.matched_settlement_id:
        # the verifier re-derives net from the deduction rules, inside the date window
        fired += ["R-044", "R-052", "R-058", "R-063", "R-021"]
        if "date_window" in f.match_basis:
            fired.append("R-021")
    if record.governor.decision == "auto_resolved":
        fired += ["R-071", "R-072"]
    elif f.matched_settlement_id and f.break_type not in gov.allowlist:
        fired.append("R-072")   # held: category not on allowlist
    elif f.matched_settlement_id and f.confidence < gov.min_confidence:
        fired.append("R-071")   # held: below threshold
    seen: dict[str, dict] = {}
    for rid in fired:
        seen[rid] = cat[rid]
    return list(seen.values())
