import io
import json

from agent_lab.cli import EXIT_FAILED, EXIT_OK, EXIT_PROVIDER, EXIT_USAGE, main


def run(*argv):
    out = io.StringIO()
    return main(list(argv), out=out), out.getvalue()


def test_list():
    code, text = run("list")
    assert code == EXIT_OK and "tool-timeout" in text


def test_run_all_text_and_report(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LAB_MODEL_PROVIDER", "simulated")
    report = tmp_path / "r.md"
    code, text = run("run", "--report", str(report), "--strict")
    assert code == EXIT_OK and "7/7 scenarios passed" in text
    md = report.read_text()
    assert "| happy-path | PASS |" in md and "scripted, not an LLM" in md


def test_run_subset_json(monkeypatch):
    monkeypatch.setenv("AGENT_LAB_MODEL_PROVIDER", "simulated")
    code, text = run("run", "--scenario", "budget-limit", "--json")
    data = json.loads(text)
    assert code == EXIT_OK and data["results"][0]["status"] == "budget-exceeded"


def test_unknown_scenario(monkeypatch):
    monkeypatch.setenv("AGENT_LAB_MODEL_PROVIDER", "simulated")
    assert run("run", "--scenario", "nope")[0] == EXIT_USAGE


def test_bad_provider(monkeypatch):
    monkeypatch.setenv("AGENT_LAB_MODEL_PROVIDER", "oracle")
    assert run("run")[0] == EXIT_PROVIDER


def test_strict_fails_when_scenario_fails(monkeypatch):
    import agent_lab.cli as cli
    from agent_lab.scenarios import Scenario, by_name

    broken = by_name("happy-path")
    fake = Scenario(broken.name, broken.description, broken.build, broken.task, lambda r, f, a: [("always", False, "x")])
    monkeypatch.setattr(cli, "SCENARIOS", [fake])
    monkeypatch.setattr(cli, "by_name", lambda n: fake)
    monkeypatch.setenv("AGENT_LAB_MODEL_PROVIDER", "simulated")
    code, text = run("run", "--strict")
    assert code == EXIT_FAILED and "x always" in text
