import time

import pytest

from agent_lab.guards import Budget, BudgetExceeded, CircuitOpen, SessionStore, ToolRunner, ToolTimeout, check_claims
from agent_lab.tools import FaultInjector, ToolError


def test_budget_tool_calls_and_turns():
    b = Budget(max_tool_calls=2, max_turns=1)
    b.charge_tool(); b.charge_tool()
    with pytest.raises(BudgetExceeded, match="tool-call"):
        b.charge_tool()
    b.charge_turn()
    with pytest.raises(BudgetExceeded, match="turn"):
        b.charge_turn()


def test_budget_wall_clock():
    b = Budget(max_seconds=0.01)
    time.sleep(0.02)
    with pytest.raises(BudgetExceeded, match="wall-clock"):
        b.charge_turn()


def test_runner_retries_transient_then_succeeds():
    f = FaultInjector(fail_times={"get_price": 2})
    r = ToolRunner(f.toolset())
    assert r.call("get_price", Budget(), sku="sku-100")["price"] == 42.0
    assert [e["outcome"] for e in r.log] == ["error: get_price: transient error"] * 2 + ["ok"]


def test_runner_gives_up_after_max_attempts():
    f = FaultInjector(fail_forever={"get_price"})
    r = ToolRunner(f.toolset(), max_attempts=3)
    with pytest.raises(ToolError, match="upstream"):
        r.call("get_price", Budget(), sku="sku-100")
    assert f.calls.count("get_price") == 3


def test_runner_does_not_retry_non_retryable():
    f = FaultInjector()
    r = ToolRunner(f.toolset())
    with pytest.raises(ToolError, match="unknown sku"):
        r.call("get_price", Budget(), sku="nope")
    assert f.calls.count("get_price") == 1


def test_runner_timeout_not_retried_and_fast():
    f = FaultInjector(hang_seconds={"get_price": 2.0})
    r = ToolRunner(f.toolset(), timeout=0.05)
    t0 = time.monotonic()
    with pytest.raises(ToolTimeout):
        r.call("get_price", Budget(), sku="sku-100")
    assert time.monotonic() - t0 < 0.5
    assert f.calls.count("get_price") == 1


def test_circuit_breaker_opens():
    f = FaultInjector(fail_forever={"get_stock"})
    r = ToolRunner(f.toolset(), max_attempts=2, breaker_threshold=2)
    with pytest.raises(ToolError):
        r.call("get_stock", Budget(), sku="sku-100")
    with pytest.raises(CircuitOpen):
        r.call("get_stock", Budget(), sku="sku-100")
    assert f.calls.count("get_stock") == 2  # second call never reached the tool


def test_unknown_tool():
    with pytest.raises(ToolError, match="unknown tool"):
        ToolRunner({}).call("teleport", Budget())


def test_runner_charges_budget_per_attempt():
    f = FaultInjector(fail_times={"get_price": 2})
    b = Budget(max_tool_calls=2)
    with pytest.raises(BudgetExceeded):
        ToolRunner(f.toolset()).call("get_price", b, sku="sku-100")


def test_session_store_isolated():
    s = SessionStore()
    s.set("a", "k", 1)
    assert s.get("a", "k") == 1 and s.get("b", "k") is None
    assert s.keys("a") == ["k"] and s.keys("b") == []


@pytest.mark.parametrize("answer, evidence, nums, skus", [
    ("costs $35.00", [{"sku": "sku-300", "price": 35.0}], [], []),
    ("costs $35.00 (sku-300)", [{"sku": "sku-300", "price": 35.0}], [], []),  # sku digits are not numbers
    ("costs $36", [{"sku": "sku-300", "price": 35.0}], ["36"], []),
    ("try sku-999", [{"results": [{"sku": "sku-100"}]}], [], ["sku-999"]),
    ("12 in stock", [{"stock": 12}], [], []),
    ("no numbers here", [], [], []),
])
def test_check_claims(answer, evidence, nums, skus):
    rep = check_claims(answer, evidence)
    assert rep.unsupported_numbers == nums and rep.unsupported_skus == skus
    assert rep.ok == (not nums and not skus)
