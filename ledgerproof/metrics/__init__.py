"""Honest, false-match-aware metrics harness (Item #5).

Runs the whole loop end-to-end — deterministic Seam-A matching, the Seam-B exception agent, the
verifier and the governor — and grades it against the hidden ground truth to produce one report
card. The headline is NOT a single match rate: it is the full picture, with false-match rate as
the cardinal number. Meant to be run on a different-seed held-out set (PRD sections 5, 10).
"""

from .report import build_report, format_card

__all__ = ["build_report", "format_card"]
