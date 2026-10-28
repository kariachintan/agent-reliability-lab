import json

import pytest

from agent_lab.agent import Agent
from agent_lab.guards import Budget, SessionStore, ToolRunner
from agent_lab.model import AnthropicModel, FinalAnswer, ModelError, SimulatedModel, ToolCall, _subject
from agent_lab.scenarios import SCENARIOS, by_name
from agent_lab.tools import FaultInjector


@pytest.mark.parametrize("name", [s.name for s in SCENARIOS])
def test_every_scenario_meets_expectations(name):
    res = by_name(name).run()
    assert res.passed, [c for c in res.checks if not c[1]]


def test_by_name_unknown():
    with pytest.raises(KeyError):
        by_name("nope")


def test_subject_extraction():
    assert _subject("What is the price of the Cedar Footrest?") == "Cedar Footrest"
    assert _subject("Find me a desk thing.") == "Find me a desk thing."


def test_simulated_model_empty_search_answers():
    m = SimulatedModel()
    a = m.next_action("price of Zebra", [{"tool": "search_catalog", "args": {}, "result": {"query": "Zebra", "results": []}}], {})
    assert isinstance(a, FinalAnswer) and "No catalog items" in a.text


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        outer = self

        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                reply = outer.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply

                class B:
                    text = reply

                class R:
                    content = [B()]

                return R()

        self.messages = messages


def _agent(model):
    f = FaultInjector()
    return Agent(model, ToolRunner(f.toolset()), SessionStore(), Budget)


def test_anthropic_model_parses_actions():
    m = AnthropicModel(client=FakeClient(['{"tool": "get_price", "args": {"sku": "sku-100"}}', '```json\n{"answer": "sku-100 costs $42.00"}\n```']), model="fake")
    a = m.next_action("t", [], {})
    assert isinstance(a, ToolCall) and a.name == "get_price"
    b = m.next_action("t", [], {})
    assert isinstance(b, FinalAnswer)


def test_real_model_answer_is_still_claim_checked():
    m = AnthropicModel(client=FakeClient(['{"answer": "It costs $999 and ships in 3 days."}']), model="fake")
    res = _agent(m).run("price?", "s")
    assert res.status == "unsupported-claim" and "999" in str(res.claims.unsupported_numbers)


def test_model_errors_are_reported_not_raised():
    m = AnthropicModel(client=FakeClient(["this is not json"]), model="fake")
    res = _agent(m).run("price?", "s")
    assert res.status == "model-error" and "non-JSON" in res.answer
    m2 = AnthropicModel(client=FakeClient([RuntimeError("rate limited")]), model="fake")
    assert "rate limited" in _agent(m2).run("price?", "s").answer
    m3 = AnthropicModel(client=FakeClient(['{"nonsense": 1}']), model="fake")
    assert _agent(m3).run("price?", "s").status == "model-error"


def test_anthropic_model_requires_config(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ModelError):
        AnthropicModel()
