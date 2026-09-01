"""Single- vs multi-agent architecture experiment — a real experiment, not a one-shot.

HYPOTHESIS
  H0 (null): specialized multi-agent routing gives NO meaningful improvement in hard-exception
             recall over a single investigator.
  H1 (alt) : multi-agent improves hard-case recall enough to justify its extra latency and cost.

METHOD
  Repeated over N seeds (fresh dataset each), identical tools / verifier / governor / ground truth;
  ONLY the agent architecture changes. We report the mean and standard deviation across seeds of
  match accuracy, hard-case recall, LLM calls/case and $/case, and decide H0 vs H1 on whether the
  mean multi-agent hard-recall advantage clears a meaningful threshold.

    python scripts/arch_experiment.py            # 5 seeds, n=2500
    python scripts/arch_experiment.py --seeds 8 --n 4000
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics as st
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ledgerproof.api.service import ReconService
from ledgerproof.generator.config import REPO_ROOT, GeneratorConfig
from ledgerproof.generator.generate import Generator
from ledgerproof.generator.writers import write_dataset
from ledgerproof.verifier.config import GovernorConfig

BASE = REPO_ROOT / "configs" / "generator.yaml"
DATA = REPO_ROOT / "data" / "arch"
MEANINGFUL = 0.02  # a <2pt mean hard-recall gain is not worth 3-4x the cost — we call that "no effect"


def run(seeds: int, n: int) -> dict:
    rows = []
    seed = 40_000
    t0 = time.perf_counter()
    for i in range(seeds):
        seed += 101
        cfg = GeneratorConfig.load(BASE, seed_override=seed, run_name_override=f"arch_s{i}")
        cfg.n_payments = n
        # a harder-than-realistic mix so the multi-agent has a fair chance to show an advantage
        cfg.seam_b_match_rate = 0.4
        cfg.seam_b_mess = {"utr_garbled_rate": 0.5, "utr_missing_rate": 0.18,
                           "same_day_collision_rate": 0.6, "date_drift_days": [0, 1, 2, 3, 4]}
        cfg.validate()
        out = write_dataset(Generator(cfg).generate(), cfg, out_root=DATA)
        svc = ReconService(out, GovernorConfig.load())
        a = svc.architectures()
        det, single, multi = a["systems"]
        rows.append({"seed": seed,
                     "single_acc": single["match_accuracy"], "multi_acc": multi["match_accuracy"],
                     "single_hard": single["hard_case_resolution"], "multi_hard": multi["hard_case_resolution"],
                     "single_calls": single["llm_calls_per_case"], "multi_calls": multi["llm_calls_per_case"],
                     "single_cost": single["cost_per_case_usd"], "multi_cost": multi["cost_per_case_usd"]})
        print(f"  seed {seed}: single acc {single['match_accuracy']:.3f} hard {single['hard_case_resolution']:.3f} | "
              f"multi acc {multi['match_accuracy']:.3f} hard {multi['hard_case_resolution']:.3f} | "
              f"calls {single['llm_calls_per_case']} vs {multi['llm_calls_per_case']}", flush=True)
    elapsed = round(time.perf_counter() - t0, 1)

    def ms(key):
        xs = [r[key] for r in rows]
        return {"mean": round(st.mean(xs), 4), "std": round(st.pstdev(xs), 4)}

    hard_delta = round(st.mean([r["multi_hard"] - r["single_hard"] for r in rows]), 4)
    acc_delta = round(st.mean([r["multi_acc"] - r["single_acc"] for r in rows]), 4)
    cost_ratio = round(st.mean([r["multi_cost"] / r["single_cost"] for r in rows if r["single_cost"]]), 1)
    accept_h1 = hard_delta >= MEANINGFUL
    verdict = (
        f"Across {seeds} seeds (n={n:,} each), multi-agent hard-case recall changed by a mean of "
        f"{hard_delta:+.3f} vs single-agent (accuracy {acc_delta:+.3f}), while costing ~{cost_ratio}x the "
        f"LLM calls per case. "
        + (f"H1 supported: the {hard_delta:+.3f} gain clears the {MEANINGFUL} threshold."
           if accept_h1 else
           f"We FAIL TO REJECT H0: the mean change ({hard_delta:+.3f}) is below the {MEANINGFUL} "
           f"meaningful-effect threshold, so specialization does not justify its cost on this "
           f"single-expertise-domain workload. Chosen: the single investigator.")
    )
    return {
        "hypothesis": {"H0": "multi-agent gives no meaningful hard-recall improvement over single-agent",
                       "H1": "multi-agent improves hard-case recall enough to justify latency/cost",
                       "meaningful_effect_threshold": MEANINGFUL},
        "method": {"seeds": seeds, "n_payments": n, "held_constant": ["tools", "verifier", "governor",
                   "ground_truth", "difficulty_mix"], "varied": "agent architecture only",
                   "wall_seconds": elapsed,
                   "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
                   "note": "agent = deterministic heuristic searcher (0 real LLM calls); calls/cost are the "
                           "MODELED per-case counts an LLM path would incur, not live API calls."},
        "per_seed": rows,
        "aggregate": {"single_accuracy": ms("single_acc"), "multi_accuracy": ms("multi_acc"),
                      "single_hard_recall": ms("single_hard"), "multi_hard_recall": ms("multi_hard"),
                      "mean_hard_recall_delta": hard_delta, "mean_accuracy_delta": acc_delta,
                      "mean_cost_ratio": cost_ratio},
        "decision": "H1" if accept_h1 else "fail_to_reject_H0",
        "verdict": verdict,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--n", type=int, default=2500)
    args = ap.parse_args()
    print(f"[arch] {args.seeds} seeds x n={args.n} …", flush=True)
    result = run(args.seeds, args.n)
    (REPO_ROOT / "docs" / "arch_experiment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n" + result["verdict"])
    print(f"[arch] wrote {REPO_ROOT / 'docs' / 'arch_experiment.json'}")


if __name__ == "__main__":
    main()
