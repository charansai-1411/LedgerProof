"""CLI entry point: python -m ledgerproof.generator --config configs/generator.yaml

Reproducible and config-first. Override the seed / run name to produce a held-out set:
    python -m ledgerproof.generator --config configs/generator.yaml --seed 99 --run-name heldout
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import REPO_ROOT
from .generate import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="ledgerproof.generator", description=__doc__)
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "configs" / "generator.yaml"),
        help="path to the generator config YAML",
    )
    parser.add_argument("--seed", type=int, default=None, help="override the config seed")
    parser.add_argument("--run-name", default=None, help="override the config run_name")
    parser.add_argument("--out", default=None, help="output root (default: <repo>/data)")
    args = parser.parse_args()

    out_dir = run(args.config, seed_override=args.seed, run_name_override=args.run_name, out_root=args.out)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    print(f"[ledgerproof] generated -> {out_dir}")
    print(f"  seed={manifest['seed']}  run={manifest['run_name']}")
    print(f"  counts: {manifest['counts']}")
    print(f"  exceptions: {manifest['exception_counts']}")


if __name__ == "__main__":
    main()
