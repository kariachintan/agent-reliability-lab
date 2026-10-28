# Agent reliability scenario report

Generated 2026-10-28 04:16 UTC on Python 3.12.3 (linux). Planner: `simulated` (scripted, not an LLM)

**7/7 scenarios met every expectation.**

| Scenario | Result | Final status | Tool calls |
|---|---|---|---|
| happy-path | PASS | `ok` | 2 |
| tool-transient-failure | PASS | `ok` | 4 |
| tool-permanent-failure | PASS | `degraded` | 4 |
| tool-timeout | PASS | `degraded` | 2 |
| unsupported-claim | PASS | `unsupported-claim` | 2 |
| budget-limit | PASS | `budget-exceeded` | 4 |
| session-isolation | PASS | `ok` | 4 |

## happy-path

Tools work; the answer should be fully evidence-backed.

Task: _What is the price of the Cedar Footrest?_

| Check | OK | Observed |
|---|---|---|
| status ok | yes | `ok` |
| answer cites price from tool | yes | `Cedar Footrest (sku-300) costs $35.00.` |
| no unsupported claims | yes | `ClaimReport(unsupported_numbers=[], unsupported_skus=[])` |

Final answer: `Cedar Footrest (sku-300) costs $35.00.`

Tool call sequence: `search_catalog, get_price`

## tool-transient-failure

get_price fails twice then succeeds; retries should recover transparently.

Task: _What is the price of the Aster Desk Lamp?_

| Check | OK | Observed |
|---|---|---|
| status ok after retries | yes | `ok` |
| get_price attempted 3 times | yes | `get_price calls=3` |
| runner log shows 2 errors then ok | yes | `[{'tool': 'search_catalog', 'attempt': 1, 'outcome': 'ok'}, {'tool': 'get_price', 'attempt': 1, 'outcome': 'error: get_price: transient error'}, {'tool': 'get_p` |

Final answer: `Aster Desk Lamp (sku-100) costs $42.00.`

Tool call sequence: `search_catalog, get_price, get_price, get_price`

## tool-permanent-failure

get_price always fails; the agent must give up honestly, not invent a price.

Task: _What is the price of the Aster Desk Lamp?_

| Check | OK | Observed |
|---|---|---|
| status degraded | yes | `degraded` |
| answer admits failure | yes | `I could not complete this: get_price: upstream unavailable. No figures are available.` |
| no price in answer | yes | `I could not complete this: get_price: upstream unavailable. No figures are available.` |
| retries capped at max_attempts | yes | `calls=3` |

Final answer: `I could not complete this: get_price: upstream unavailable. No figures are available.`

Tool call sequence: `search_catalog, get_price, get_price, get_price`

## tool-timeout

get_price hangs for 5s with a 0.2s timeout; the loop must not block and must not retry a hang.

Task: _What is the price of the Cedar Footrest?_

| Check | OK | Observed |
|---|---|---|
| status degraded | yes | `degraded` |
| timeout recorded | yes | `[{'tool': 'search_catalog', 'attempt': 1, 'outcome': 'ok'}, {'tool': 'get_price', 'attempt': 1, 'outcome': 'timeout'}]` |
| hang not retried | yes | `calls=1` |
| answer explains | yes | `I could not complete this: get_price: timed out after 0.2s. No figures are available.` |

Final answer: `I could not complete this: get_price: timed out after 0.2s. No figures are available.`

Tool call sequence: `search_catalog, get_price`

## unsupported-claim

The planner adds a stock figure it never looked up; the claim checker must withhold it.

Task: _What is the price of the Cedar Footrest?_

| Check | OK | Observed |
|---|---|---|
| status unsupported-claim | yes | `unsupported-claim` |
| fabricated number flagged | yes | `ClaimReport(unsupported_numbers=['2'], unsupported_skus=[])` |
| fabrication withheld from answer | yes | `[withheld: the draft answer contained claims not backed by tool results: ['2']] Verified facts only: search 'Cedar Footrest' -> ['sku-300']; sku-300 price $35.0` |
| verified price still delivered | yes | `[withheld: the draft answer contained claims not backed by tool results: ['2']] Verified facts only: search 'Cedar Footrest' -> ['sku-300']; sku-300 price $35.0` |

Final answer: `[withheld: the draft answer contained claims not backed by tool results: ['2']] Verified facts only: search 'Cedar Footrest' -> ['sku-300']; sku-300 price $35.00`

Tool call sequence: `search_catalog, get_price`

## budget-limit

A greedy planner never stops calling tools; the budget must stop it.

Task: _Find me a desk thing._

| Check | OK | Observed |
|---|---|---|
| status budget-exceeded | yes | `budget-exceeded` |
| stopped at 4 tool calls | yes | `calls=4` |
| answer reports partial evidence | yes | `Stopped: tool-call budget of 4 exceeded. Partial evidence: 4 tool result(s).` |

Final answer: `Stopped: tool-call budget of 4 exceeded. Partial evidence: 4 tool result(s).`

Tool call sequence: `search_catalog, search_catalog, search_catalog, search_catalog`

## session-isolation

Two sessions run back to back; the second must not see the first's memory.

Task: _What is the price of the Brook Monitor Arm?_

| Check | OK | Observed |
|---|---|---|
| second session has no leaked memory | yes | `Brook Monitor Arm (sku-200) costs $89.00.` |
| first session memory still exists | yes | `sku-200` |
| sessions are separate keys | yes | `s-2=['last_sku'] s-3=[]` |

Final answer: `Brook Monitor Arm (sku-200) costs $89.00.`

Tool call sequence: `search_catalog, get_price, search_catalog, get_price`

---

All tools, data, and faults are synthetic. A PASS means the guard behaved as designed in this harness, nothing more.
