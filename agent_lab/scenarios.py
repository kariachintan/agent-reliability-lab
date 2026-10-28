"""Evaluation scenarios: a fault setup, a task, and explicit expectations.

Each scenario builds its own Agent so runs are isolated. `expect` returns a
list of (check name, passed, observed) so the report shows evidence, not just
a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .agent import Agent, AgentResult
from .guards import Budget, SessionStore, ToolRunner
from .model import Model, SimulatedModel
from .tools import FaultInjector

Check = tuple[str, bool, str]


@dataclass
class ScenarioResult:
    name: str
    description: str
    passed: bool
    checks: list[Check]
    result: AgentResult
    tool_calls: list[str]
    task: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    build: Callable[[Model], tuple[Agent, FaultInjector]]
    task: str
    expect: Callable[[AgentResult, FaultInjector, Agent], list[Check]]
    sessions: tuple[str, ...] = ("s-1",)
    model_factory: Callable[[], Model] = SimulatedModel

    def run(self, model: Model | None = None) -> ScenarioResult:
        model = model or self.model_factory()
        agent, faults = self.build(model)
        result = None
        for sid in self.sessions:
            result = agent.run(self.task, sid)
        assert result is not None
        checks = self.expect(result, faults, agent)
        return ScenarioResult(self.name, self.description, all(c[1] for c in checks), checks, result, list(faults.calls), self.task)


def _agent(model: Model, faults: FaultInjector, budget: Callable[[], Budget] = Budget, timeout: float = 0.5) -> Agent:
    return Agent(model=model, runner=ToolRunner(faults.toolset(), timeout=timeout), sessions=SessionStore(), budget_factory=budget)


# ---- scenarios -----------------------------------------------------------

def _happy(model):
    f = FaultInjector()
    return _agent(model, f), f


def _transient(model):
    f = FaultInjector(fail_times={"get_price": 2})
    return _agent(model, f), f


def _permanent(model):
    f = FaultInjector(fail_forever={"get_price"})
    return _agent(model, f), f


def _hang(model):
    f = FaultInjector(hang_seconds={"get_price": 5.0})
    return _agent(model, f, timeout=0.2), f


def _budget(model):
    f = FaultInjector()
    return _agent(model, f, budget=lambda: Budget(max_tool_calls=4, max_turns=10)), f


def _isolation(model):
    f = FaultInjector()
    return _agent(model, f), f


def _fabricate(model):
    f = FaultInjector()
    return _agent(model, f), f


SCENARIOS: list[Scenario] = [
    Scenario(
        "happy-path", "Tools work; the answer should be fully evidence-backed.",
        _happy, "What is the price of the Cedar Footrest?",
        lambda r, f, a: [
            ("status ok", r.status == "ok", r.status),
            ("answer cites price from tool", "$35.00" in r.answer, r.answer),
            ("no unsupported claims", r.claims is not None and r.claims.ok, str(r.claims)),
        ],
    ),
    Scenario(
        "tool-transient-failure", "get_price fails twice then succeeds; retries should recover transparently.",
        _transient, "What is the price of the Aster Desk Lamp?",
        lambda r, f, a: [
            ("status ok after retries", r.status == "ok", r.status),
            ("get_price attempted 3 times", f.calls.count("get_price") == 3, f"get_price calls={f.calls.count('get_price')}"),
            ("runner log shows 2 errors then ok", [e["outcome"] for e in r.tool_log if e["tool"] == "get_price"][-1] == "ok", str(r.tool_log)),
        ],
    ),
    Scenario(
        "tool-permanent-failure", "get_price always fails; the agent must give up honestly, not invent a price.",
        _permanent, "What is the price of the Aster Desk Lamp?",
        lambda r, f, a: [
            ("status degraded", r.status == "degraded", r.status),
            ("answer admits failure", "could not" in r.answer.lower(), r.answer),
            ("no price in answer", "$" not in r.answer, r.answer),
            ("retries capped at max_attempts", f.calls.count("get_price") == a.runner.max_attempts, f"calls={f.calls.count('get_price')}"),
        ],
    ),
    Scenario(
        "tool-timeout", "get_price hangs for 5s with a 0.2s timeout; the loop must not block and must not retry a hang.",
        _hang, "What is the price of the Cedar Footrest?",
        lambda r, f, a: [
            ("status degraded", r.status == "degraded", r.status),
            ("timeout recorded", any(e["outcome"] == "timeout" for e in r.tool_log), str(r.tool_log)),
            ("hang not retried", f.calls.count("get_price") == 1, f"calls={f.calls.count('get_price')}"),
            ("answer explains", "timed out" in r.answer, r.answer),
        ],
    ),
    Scenario(
        "unsupported-claim", "The planner adds a stock figure it never looked up; the claim checker must withhold it.",
        _fabricate, "What is the price of the Cedar Footrest?",
        lambda r, f, a: [
            ("status unsupported-claim", r.status == "unsupported-claim", r.status),
            ("fabricated number flagged", r.claims is not None and "2" in r.claims.unsupported_numbers, str(r.claims)),
            ("fabrication withheld from answer", "order soon" not in r.answer, r.answer),
            ("verified price still delivered", "$35.00" in r.answer, r.answer),
        ],
        model_factory=lambda: SimulatedModel(fabricate=True),
    ),
    Scenario(
        "budget-limit", "A greedy planner never stops calling tools; the budget must stop it.",
        _budget, "Find me a desk thing.",
        lambda r, f, a: [
            ("status budget-exceeded", r.status == "budget-exceeded", r.status),
            ("stopped at 4 tool calls", len(f.calls) == 4, f"calls={len(f.calls)}"),
            ("answer reports partial evidence", "Partial evidence: 4" in r.answer, r.answer),
        ],
        model_factory=lambda: SimulatedModel(greedy=True),
    ),
    Scenario(
        "session-isolation", "Two sessions run back to back; the second must not see the first's memory.",
        _isolation, "What is the price of the Brook Monitor Arm?",
        lambda r, f, a: [
            ("second session has no leaked memory", "Earlier in this session" not in r.answer, r.answer),
            ("first session memory still exists", a.sessions.get("s-1", "last_sku") == "sku-200", str(a.sessions.get("s-1", "last_sku"))),
            ("sessions are separate keys", a.sessions.keys("s-2") == ["last_sku"] and a.sessions.keys("s-3") == [], f"s-2={a.sessions.keys('s-2')} s-3={a.sessions.keys('s-3')}"),
        ],
        sessions=("s-1", "s-2"),
    ),
]


def by_name(name: str) -> Scenario:
    for s in SCENARIOS:
        if s.name == name:
            return s
    raise KeyError(name)
