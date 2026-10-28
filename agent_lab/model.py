"""Planning models.

The agent loop asks a model for the next action given the task and history.

* SimulatedModel - a scripted policy. Deterministic and offline. Flags let
  scenarios make it misbehave on purpose (fabricate a fact, loop forever) so
  the guards have something to catch. Clearly labelled; it is not an LLM.
* AnthropicModel - optional. Asks a real model for a JSON action. Same guards
  apply; nothing it says is trusted until the ClaimChecker has seen it.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class FinalAnswer:
    text: str


Action = ToolCall | FinalAnswer


class ModelError(RuntimeError):
    pass


class Model(Protocol):
    name: str

    def next_action(self, task: str, history: list[dict[str, Any]], memory: dict[str, Any]) -> Action: ...


@dataclass
class SimulatedModel:
    name: str = "simulated"
    fabricate: bool = False     # add a stock claim without checking stock
    greedy: bool = False        # never stop calling tools
    calls_made: int = field(default=0)

    def next_action(self, task: str, history: list[dict[str, Any]], memory: dict[str, Any]) -> Action:
        self.calls_made += 1
        last = history[-1] if history else None
        if self.greedy:
            return ToolCall("search_catalog", {"query": "desk"})
        if last and last.get("error"):
            # Honest degradation: say what could not be done rather than guess.
            return FinalAnswer(f"I could not complete this: {last['error']}. No figures are available.")
        if not history:
            return ToolCall("search_catalog", {"query": _subject(task)})
        if last and last["tool"] == "search_catalog":
            hits = last["result"]["results"]
            if not hits:
                return FinalAnswer(f"No catalog items match '{last['result']['query']}'.")
            return ToolCall("get_price", {"sku": hits[0]["sku"]})
        if last and last["tool"] == "get_price":
            name = next(h["result"]["results"][0]["name"] for h in history if h.get("tool") == "search_catalog")
            text = f"{name} ({last['result']['sku']}) costs ${last['result']['price']:.2f}."
            if memory.get("last_sku"):
                text += f" Earlier in this session you looked at {memory['last_sku']}."
            if self.fabricate:
                text += " Only 2 left in stock, so order soon."
            return FinalAnswer(text)
        return FinalAnswer("Done.")


def _subject(task: str) -> str:
    m = re.search(r"(?:price of|cost of|about|for)\s+(?:the\s+)?([a-z ]+?)(?:\?|$)", task, re.IGNORECASE)
    return (m.group(1) if m else task).strip()


SYSTEM = (
    "You are a catalog assistant with tools: search_catalog(query), get_price(sku), get_stock(sku). "
    "Reply with exactly one JSON object and nothing else: "
    '{"tool": "<name>", "args": {...}} to call a tool, or {"answer": "<text>"} to finish. '
    "Only state numbers and SKUs that appeared in tool results."
)


class AnthropicModel:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None, client=None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("AGENT_LAB_MODEL")
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ModelError("ANTHROPIC_API_KEY is not set")
        if not self.model:
            raise ModelError("AGENT_LAB_MODEL is not set")
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ModelError("install the optional extra: pip install -e '.[llm]'") from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def next_action(self, task: str, history: list[dict[str, Any]], memory: dict[str, Any]) -> Action:
        content = json.dumps({"task": task, "history": history, "session_memory": memory})
        try:
            resp = self._client.messages.create(model=self.model, max_tokens=300, system=SYSTEM,
                                                messages=[{"role": "user", "content": content}])
        except Exception as exc:
            raise ModelError(f"model call failed: {exc}") from exc
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        try:
            data = json.loads(text.strip("`").removeprefix("json").strip())
        except json.JSONDecodeError as exc:
            raise ModelError(f"model returned non-JSON action: {text[:80]!r}") from exc
        if "answer" in data:
            return FinalAnswer(str(data["answer"]))
        if "tool" in data:
            return ToolCall(str(data["tool"]), dict(data.get("args") or {}))
        raise ModelError(f"model returned an action with neither tool nor answer: {data}")


def model_from_env() -> Model:
    kind = os.environ.get("AGENT_LAB_MODEL_PROVIDER", "simulated").lower()
    if kind == "simulated":
        return SimulatedModel()
    if kind == "anthropic":
        return AnthropicModel()
    raise ModelError(f"unknown provider {kind!r} (use 'simulated' or 'anthropic')")
