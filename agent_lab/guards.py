"""Reliability primitives the agent loop composes.

* ToolRunner  - retries with backoff for retryable errors, hard timeouts via a
                worker thread, and per-tool circuit breaker.
* Budget      - caps tool calls, model turns, and wall-clock; raises when
                exceeded so the loop stops instead of spiralling.
* SessionStore- per-session memory with no cross-session reads.
* ClaimChecker- compares numbers and SKUs in the final answer against the
                evidence the tools actually returned.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .tools import ToolError


class BudgetExceeded(RuntimeError):
    pass


class ToolTimeout(ToolError):
    def __init__(self, name: str, seconds: float):
        super().__init__(f"{name}: timed out after {seconds}s", retryable=False)


class CircuitOpen(ToolError):
    def __init__(self, name: str):
        super().__init__(f"{name}: circuit open, not calling", retryable=False)


@dataclass
class Budget:
    max_tool_calls: int = 6
    max_turns: int = 6
    max_seconds: float = 10.0
    tool_calls: int = 0
    turns: int = 0
    started: float = field(default_factory=time.monotonic)

    def charge_tool(self):
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool-call budget of {self.max_tool_calls} exceeded")
        self._check_time()

    def charge_turn(self):
        self.turns += 1
        if self.turns > self.max_turns:
            raise BudgetExceeded(f"turn budget of {self.max_turns} exceeded")
        self._check_time()

    def _check_time(self):
        if time.monotonic() - self.started > self.max_seconds:
            raise BudgetExceeded(f"wall-clock budget of {self.max_seconds}s exceeded")


@dataclass
class ToolRunner:
    tools: dict[str, Callable[..., dict[str, Any]]]
    max_attempts: int = 3
    backoff: float = 0.01          # tiny so demos are fast; real systems use 100s of ms
    timeout: float = 0.5
    breaker_threshold: int = 2     # consecutive failures before the circuit opens
    failures: dict[str, int] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    def call(self, name: str, budget: Budget, **kwargs) -> dict[str, Any]:
        if name not in self.tools:
            raise ToolError(f"unknown tool {name}", retryable=False)
        if self.failures.get(name, 0) >= self.breaker_threshold:
            self.log.append({"tool": name, "outcome": "circuit-open"})
            raise CircuitOpen(name)
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            budget.charge_tool()
            try:
                result = _run_with_timeout(self.tools[name], kwargs, self.timeout)
                self.failures[name] = 0
                self.log.append({"tool": name, "attempt": attempt, "outcome": "ok"})
                return result
            except TimeoutError:
                self.failures[name] = self.failures.get(name, 0) + 1
                self.log.append({"tool": name, "attempt": attempt, "outcome": "timeout"})
                raise ToolTimeout(name, self.timeout)  # do not retry a hang; the worker may still be running
            except ToolError as exc:
                last = exc
                self.failures[name] = self.failures.get(name, 0) + 1
                self.log.append({"tool": name, "attempt": attempt, "outcome": f"error: {exc}"})
                if not exc.retryable or attempt == self.max_attempts:
                    break
                time.sleep(self.backoff * attempt)
        assert last is not None
        raise last


def _run_with_timeout(fn: Callable[..., Any], kwargs: dict[str, Any], seconds: float) -> Any:
    """Run fn in a daemon thread and give up after `seconds`.

    Python cannot kill a thread, so a timed-out worker keeps running until it
    finishes on its own. Using a *daemon* thread means it at least cannot hold
    the process open at exit. (The first version used ThreadPoolExecutor, whose
    non-daemon workers made a 5-second hang delay interpreter shutdown by 5s.)
    Real systems need cancellation at the I/O layer, e.g. request timeouts.
    """
    box: dict[str, Any] = {}

    def target():
        try:
            box["result"] = fn(**kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised in caller
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError
    if "error" in box:
        raise box["error"]
    return box["result"]


class SessionStore:
    """Memory keyed by session id. There is deliberately no 'list all' API."""

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str, key: str, default=None):
        with self._lock:
            return self._data.get(session_id, {}).get(key, default)

    def set(self, session_id: str, key: str, value: Any):
        with self._lock:
            self._data.setdefault(session_id, {})[key] = value

    def keys(self, session_id: str) -> list[str]:
        with self._lock:
            return sorted(self._data.get(session_id, {}))


NUMBER_RE = re.compile(r"(?<![\w.-])\$?(\d+(?:\.\d+)?)(?![\w.])")  # "-" excluded so sku-300 is not the number 300
SKU_RE = re.compile(r"\bsku-\d+\b", re.IGNORECASE)


@dataclass
class ClaimReport:
    unsupported_numbers: list[str]
    unsupported_skus: list[str]

    @property
    def ok(self) -> bool:
        return not self.unsupported_numbers and not self.unsupported_skus


def _flatten(obj: Any) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flatten(v))
    else:
        out.append(str(obj))
    return out


def check_claims(answer: str, evidence: list[dict[str, Any]]) -> ClaimReport:
    """Every number and SKU in the answer must appear in tool evidence."""
    tokens = set()
    for ev in evidence:
        for t in _flatten(ev):
            tokens.add(t.lower())
            m = NUMBER_RE.fullmatch(t)
            if m:
                tokens.add(_norm(m.group(1)))
    nums = [n for n in NUMBER_RE.findall(answer) if _norm(n) not in tokens]
    skus = [s for s in SKU_RE.findall(answer) if s.lower() not in tokens]
    return ClaimReport(sorted(set(nums)), sorted(set(s.lower() for s in skus)))


def _norm(n: str) -> str:
    return str(float(n)) if "." in n else str(float(int(n)))
