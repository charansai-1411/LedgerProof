"""The pattern cache, its precise key, and the resolver that consults it."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.heuristic import HeuristicAgentModel
from ..agent.model import AgentFinding, AgentModel
from ..agent.tools import SeamBToolbox

# The cache holds ONLY the Seam-B break category — a precise key, never fuzzy.
BREAK_TYPE = "bank_settlement_match"


def probe(bank_txn_id: str, tools: SeamBToolbox, merchant_id: str = "mrc_demo") -> tuple:
    """A precise, deterministic pattern key computed from the credit alone — no agent call.

    The key is (merchant, break_type, utr_class): the resolution difficulty *shape*. It is cheap
    (a UTR-index lookup) and precise: it groups credits that resolve by the same strategy, and never
    merges structurally different ones.
    """
    bc = tools.get_bank_credit(bank_txn_id)
    if bc.utr and tools.find_settlement_by_utr(bc.utr) is not None:
        utr_class = "clean_unique_utr"
    elif not bc.utr:
        utr_class = "missing_utr"
    else:
        utr_class = "unmatched_utr"  # garbled or shared — must be resolved by search
    return (merchant_id, BREAK_TYPE, utr_class)


@dataclass
class CacheEntry:
    strategy: str          # the validated resolution strategy (agent's match_basis)
    seed_bank_txn_id: str  # the first credit that taught this pattern
    hits: int = 0


@dataclass
class PatternCache:
    entries: dict = field(default_factory=dict)

    def get(self, sig: tuple) -> CacheEntry | None:
        return self.entries.get(sig)

    def store(self, sig: tuple, strategy: str, seed_bank_txn_id: str) -> None:
        if sig not in self.entries:
            self.entries[sig] = CacheEntry(strategy=strategy, seed_bank_txn_id=seed_bank_txn_id)

    def record_hit(self, sig: tuple) -> None:
        if sig in self.entries:
            self.entries[sig].hits += 1

    def summary(self) -> dict:
        return {
            "patterns_learned": len(self.entries),
            "patterns": {
                "|".join(sig): {"strategy": e.strategy, "hits": e.hits, "seed": e.seed_bank_txn_id}
                for sig, e in self.entries.items()
            },
        }


class CachedResolver:
    """Wraps an expensive investigator (the `inner` AgentModel — e.g. Gemini) with the cache.

    On a cache hit, resolution is done by a deterministic strategy re-application (no inner call).
    On a miss, the inner agent investigates; the pattern is learned only AFTER the verifier confirms
    the finding (see `learn`). Every finding — hit or miss — is still verified downstream.
    """

    def __init__(self, inner: AgentModel, cache: PatternCache | None = None,
                 merchant_id: str = "mrc_demo") -> None:
        self.inner = inner
        self.cache = cache or PatternCache()
        self.strategy = HeuristicAgentModel()  # the deterministic strategy library
        self.merchant_id = merchant_id
        self.agent_invocations = 0
        self.cache_hits = 0

    def resolve(self, bank_txn_id: str, tools: SeamBToolbox) -> tuple[AgentFinding, str]:
        sig = probe(bank_txn_id, tools, self.merchant_id)
        if self.cache.get(sig) is not None:
            self.cache.record_hit(sig)
            self.cache_hits += 1
            # re-apply the validated strategy deterministically — NO inner (LLM) call
            return self.strategy.investigate(bank_txn_id, tools), "cache"
        self.agent_invocations += 1
        return self.inner.investigate(bank_txn_id, tools), "agent"

    def learn(self, finding: AgentFinding, tools: SeamBToolbox, verified: bool) -> None:
        """Cache a pattern ONLY after the verifier has confirmed a real match (guardrail 1)."""
        if verified and finding.matched_settlement_id is not None:
            sig = probe(finding.bank_txn_id, tools, self.merchant_id)
            self.cache.store(sig, "|".join(finding.match_basis) or "search", finding.bank_txn_id)
