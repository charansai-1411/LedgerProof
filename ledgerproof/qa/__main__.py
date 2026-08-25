"""CLI:  python -m ledgerproof.qa --data data/heldout "what is my total MDR this cycle?"

With no question, drops into a small REPL. Default model is the deterministic rule router (no API);
--model gemini uses the Gemini function-calling agent.
"""

from __future__ import annotations

import argparse
import sys

from ..generator.config import REPO_ROOT
from .service import QAContext, RuleQA


def main() -> None:
    # answers contain ₹/≥; make stdout UTF-8 so they print on a Windows (cp1252) console
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="ledgerproof.qa", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "heldout"))
    p.add_argument("--model", default="rule", choices=["rule", "gemini"])
    p.add_argument("question", nargs="*", help="the question (omit for a REPL)")
    args = p.parse_args()

    ctx = QAContext(args.data)
    if args.model == "gemini":
        from .gemini_qa import GeminiQA
        qa = GeminiQA(ctx)
    else:
        qa = RuleQA(ctx)

    def answer(q: str) -> None:
        print("Q:", q)
        print("A:", qa.ask(q)["answer"], "\n")

    if args.question:
        answer(" ".join(args.question))
        return
    print(f"[qa] {args.data} — model={args.model}. Ask a question (blank to quit).")
    try:
        while True:
            q = input("> ").strip()
            if not q:
                break
            answer(q)
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
