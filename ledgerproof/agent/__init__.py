"""Exception agent — Seam B: bank-credit <-> settlement matching (the hero task).

A lumped bank credit must be matched to the right settlement batch when the UTR is a
strong-but-insufficient signal (garbled / missing / shared), the value date drifts across the
T+2+NEFT window, and same-day settlements collide. Finding the right settlement is search;
the deterministic verifier (Item #4) confirms one proposed match. The model sits behind the
`AgentModel` interface so it is swappable (heuristic baseline <-> Gemini on Vertex).
"""

from .model import AgentFinding, AgentModel
from .tools import SeamBToolbox
from .heuristic import HeuristicAgentModel

__all__ = ["AgentFinding", "AgentModel", "SeamBToolbox", "HeuristicAgentModel"]
