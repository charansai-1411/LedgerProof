"""Settlement Q&A agent (Track-4 direction, additive).

Answers natural-language questions about a reconciliation run — match rate, MDR/GST totals, why a
credit was opened, what's in the human queue — over the SAME reconciled data and audit trail the
rest of the system produces. Two front-ends behind one query core: a deterministic keyword router
(RuleQA, no API — powers the dashboard and tests) and a Gemini function-calling agent (GeminiQA).
"""

from .service import QAContext, RuleQA

__all__ = ["QAContext", "RuleQA"]
