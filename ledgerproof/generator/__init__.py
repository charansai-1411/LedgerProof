"""Synthetic settlement-data generator.

Produces three source files shaped like their real Razorpay counterparts plus a hidden
ground-truth key. Forward generation (truth first, then injected mess); integer paise
everywhere; seeded and reproducible. See docs/GENERATOR_SPEC.md.
"""

from .generate import Generator, GeneratedDataset, run

__all__ = ["Generator", "GeneratedDataset", "run"]
