"""Dashboard + JSON API (Item #7).

A FastAPI app that serves a single polished page over the real reconciliation pipeline: recon
summary, an exception queue where every row expands to show why the system did what it did
(diagnosis -> evidence -> verifier -> governor -> narrative -> audit), a source-of-truth lookup
(the three views of one transaction side by side), and live finance-team-owned governor controls.

Python-only — no npm/build step. Run:  python -m ledgerproof.api --data data/heldout
Optional dependency:  pip install -r requirements-api.txt
"""

from .app import create_app

__all__ = ["create_app"]
