"""Synthetic tools plus fault injection.

Tools are plain callables returning JSON-serialisable dicts. FaultInjector
wraps them so scenarios can make a tool fail N times, hang, or fail forever,
without the agent loop knowing anything about the scenario.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

CATALOG = {
    "sku-100": {"name": "Aster Desk Lamp", "price": 42.0, "stock": 12},
    "sku-200": {"name": "Brook Monitor Arm", "price": 89.0, "stock": 0},
    "sku-300": {"name": "Cedar Footrest", "price": 35.0, "stock": 4},
}


class ToolError(RuntimeError):
    """A tool failed. `retryable` tells the runner whether retrying makes sense."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


def search_catalog(query: str) -> dict[str, Any]:
    q = query.lower()
    hits = [{"sku": k, **v} for k, v in CATALOG.items() if q in v["name"].lower() or q in k]
    return {"query": query, "results": hits}


def get_stock(sku: str) -> dict[str, Any]:
    if sku not in CATALOG:
        raise ToolError(f"unknown sku {sku}", retryable=False)
    return {"sku": sku, "stock": CATALOG[sku]["stock"]}


def get_price(sku: str) -> dict[str, Any]:
    if sku not in CATALOG:
        raise ToolError(f"unknown sku {sku}", retryable=False)
    return {"sku": sku, "price": CATALOG[sku]["price"]}


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "search_catalog": search_catalog,
    "get_stock": get_stock,
    "get_price": get_price,
}


@dataclass
class FaultInjector:
    """Scenario-controlled misbehaviour for named tools."""

    fail_times: dict[str, int] = field(default_factory=dict)   # tool -> remaining transient failures
    fail_forever: set[str] = field(default_factory=set)
    hang_seconds: dict[str, float] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def wrap(self, name: str, fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        def wrapped(**kwargs):
            self.calls.append(name)
            if name in self.fail_forever:
                raise ToolError(f"{name}: upstream unavailable", retryable=True)
            if self.fail_times.get(name, 0) > 0:
                self.fail_times[name] -= 1
                raise ToolError(f"{name}: transient error", retryable=True)
            if name in self.hang_seconds:
                time.sleep(self.hang_seconds[name])
            return fn(**kwargs)

        return wrapped

    def toolset(self) -> dict[str, Callable[..., dict[str, Any]]]:
        return {name: self.wrap(name, fn) for name, fn in TOOLS.items()}
