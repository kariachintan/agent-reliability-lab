"""The agent loop: model proposes, guards dispose."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .guards import Budget, BudgetExceeded, ClaimReport, SessionStore, ToolRunner, check_claims
from .model import FinalAnswer, Model, ModelError, ToolCall
from .tools import ToolError


@dataclass
class AgentResult:
    status: str                       # "ok" | "degraded" | "budget-exceeded" | "unsupported-claim" | "model-error"
    answer: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    claims: ClaimReport | None = None
    tool_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Agent:
    model: Model
    runner: ToolRunner
    sessions: SessionStore
    budget_factory: Any = Budget

    def run(self, task: str, session_id: str) -> AgentResult:
        budget = self.budget_factory()
        history: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        memory = {k: self.sessions.get(session_id, k) for k in self.sessions.keys(session_id)}
        try:
            while True:
                budget.charge_turn()
                try:
                    action = self.model.next_action(task, history, memory)
                except ModelError as exc:
                    return AgentResult("model-error", f"The planner failed: {exc}", history, evidence, tool_log=self.runner.log)
                if isinstance(action, FinalAnswer):
                    return self._finish(action.text, history, evidence, session_id)
                assert isinstance(action, ToolCall)
                try:
                    result = self.runner.call(action.name, budget, **action.args)
                    history.append({"tool": action.name, "args": action.args, "result": result})
                    evidence.append(result)
                    if action.name == "get_price":
                        self.sessions.set(session_id, "last_sku", result["sku"])
                except ToolError as exc:
                    history.append({"tool": action.name, "args": action.args, "error": str(exc)})
        except BudgetExceeded as exc:
            return AgentResult("budget-exceeded", f"Stopped: {exc}. Partial evidence: {len(evidence)} tool result(s).",
                               history, evidence, tool_log=self.runner.log)

    def _finish(self, text: str, history, evidence, session_id) -> AgentResult:
        claims = check_claims(text, evidence)
        degraded = any("error" in h for h in history)
        if not claims.ok:
            flagged = claims.unsupported_numbers + claims.unsupported_skus
            text = (f"[withheld: the draft answer contained claims not backed by tool results: {flagged}] "
                    f"Verified facts only: {_verified_summary(evidence)}")
            return AgentResult("unsupported-claim", text, history, evidence, claims, self.runner.log)
        return AgentResult("degraded" if degraded else "ok", text, history, evidence, claims, self.runner.log)


def _verified_summary(evidence: list[dict[str, Any]]) -> str:
    parts = []
    for ev in evidence:
        if "price" in ev:
            parts.append(f"{ev['sku']} price ${ev['price']:.2f}")
        elif "stock" in ev:
            parts.append(f"{ev['sku']} stock {ev['stock']}")
        elif "results" in ev:
            parts.append(f"search '{ev['query']}' -> {[r['sku'] for r in ev['results']]}")
    return "; ".join(parts) or "none"
