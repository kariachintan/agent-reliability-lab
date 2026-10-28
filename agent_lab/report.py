"""Markdown + JSON report of scenario runs."""
from __future__ import annotations

import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from .scenarios import ScenarioResult


def to_markdown(results: list[ScenarioResult], model_name: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(r.passed for r in results)
    lines = [
        "# Agent reliability scenario report",
        "",
        f"Generated {now} on Python {platform.python_version()} ({sys.platform}). Planner: `{model_name}`"
        + (" (scripted, not an LLM)" if model_name == "simulated" else ""),
        "",
        f"**{passed}/{len(results)} scenarios met every expectation.**",
        "",
        "| Scenario | Result | Final status | Tool calls |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | `{r.result.status}` | {len(r.tool_calls)} |")
    for r in results:
        lines += ["", f"## {r.name}", "", r.description, "", f"Task: _{r.result.steps and 'see steps' or ''}_".replace("Task: __", "").strip()]
        lines += ["", "| Check | OK | Observed |", "|---|---|---|"]
        for name, ok, observed in r.checks:
            lines.append(f"| {name} | {'yes' if ok else 'NO'} | `{observed[:160].replace('|', '/')}` |")
        lines += ["", f"Final answer: `{r.result.answer[:300]}`", "", f"Tool call sequence: `{', '.join(r.tool_calls) or '(none)'}`"]
    lines += ["", "---", "", "All tools, data, and faults are synthetic. A PASS means the guard behaved as designed in this harness, nothing more."]
    return "\n".join(lines) + "\n"


def to_json(results: list[ScenarioResult], model_name: str) -> str:
    payload = {
        "planner": model_name,
        "results": [
            {
                "name": r.name, "passed": r.passed,
                "checks": [{"name": n, "ok": ok, "observed": o} for n, ok, o in r.checks],
                "status": r.result.status, "answer": r.result.answer, "tool_calls": r.tool_calls,
                "claims": asdict(r.result.claims) if r.result.claims else None,
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2)
