"""Run the dashboard:  python -m ledgerproof.api --data data/heldout [--port 8000]"""

from __future__ import annotations

import argparse

import uvicorn

from ..generator.config import REPO_ROOT
from .app import create_app


def main() -> None:
    p = argparse.ArgumentParser(prog="ledgerproof.api", description=__doc__)
    p.add_argument("--data", default=str(REPO_ROOT / "data" / "heldout"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()

    app = create_app(args.data)
    print(f"[ledgerproof] dashboard on http://{args.host}:{args.port}  (data: {args.data})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
