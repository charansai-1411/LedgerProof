"""Resolved-pattern cache (Item #6, stretch) — a performance/consistency layer on the core loop.

When the agent resolves a Seam-B credit and the verifier confirms it, the resolution STRATEGY is
cached against a precise pattern key. A later credit matching that pattern is resolved by
re-applying the cached strategy deterministically — WITHOUT another agent (LLM) investigation.

The one non-negotiable rule: the cache PROPOSES, the verifier STILL re-derives against the specific
record. Memory is a fast-path hypothesis generator, never an authority — so a mis-cached pattern is
caught at verify time, and a wrong resolution can never silently propagate. The cache also stays out
of the measurement path: the metrics harness (Item #5) runs cache-free, so held-out numbers are cold.

See docs/PRD.md section 8b.
"""

from .pattern_cache import CachedResolver, PatternCache, probe

__all__ = ["CachedResolver", "PatternCache", "probe"]
