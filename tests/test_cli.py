import importlib
import json
import sys
from pathlib import Path

import pytest

import tiny_skill_agent


def test_main_validate_skills_outputs_json(monkeypatch, capsys, valid_skill_dir):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tiny_skill_agent.py", "--skills", str(valid_skill_dir), "--validate-skills"],
    )

    tiny_skill_agent.main()
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["reports"][0]["name"] == "valid-skill"


def test_main_validate_skills_reports_yaml_errors(monkeypatch, capsys, colon_skill_dir):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tiny_skill_agent.py", "--skills", str(colon_skill_dir), "--validate-skills"],
    )

    with pytest.raises(SystemExit) as excinfo:
        tiny_skill_agent.main()

    payload = json.loads(capsys.readouterr().out)

    assert excinfo.value.code == 1
    assert payload["ok"] is False
    assert payload["reports"][0]["errors"][0]["code"] == "yaml-unparseable"


def test_main_validate_skills_returns_exit_code_1_for_invalid(monkeypatch, capsys, missing_description_skill_dir):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tiny_skill_agent.py", "--skills", str(missing_description_skill_dir), "--validate-skills"],
    )

    with pytest.raises(SystemExit) as excinfo:
        tiny_skill_agent.main()

    payload = json.loads(capsys.readouterr().out)

    assert excinfo.value.code == 1
    assert payload["ok"] is False
    assert payload["reports"][0]["errors"][0]["code"] == "description-missing"


def test_main_requires_task_without_show_catalog_or_validate(monkeypatch, valid_skill_dir):
    monkeypatch.setattr(
        sys,
        "argv",
        ["tiny_skill_agent.py", "--skills", str(valid_skill_dir)],
    )

    with pytest.raises(SystemExit, match="task is required unless --show-catalog or --validate-skills is used."):
        tiny_skill_agent.main()


def test_main_builds_telemetry_with_file_and_endpoint(monkeypatch, capsys, valid_skill_dir, workspace_dir):
    cli_module = importlib.import_module("tiny_skill_agent.cli")
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["openai_kwargs"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent_kwargs"] = kwargs

        def run(self, task):
            captured["task"] = task
            return {"ok": True}

    def fake_builder(file_path=None, otlp_endpoint=None):
        captured["telemetry"] = {
            "file_path": file_path,
            "otlp_endpoint": otlp_endpoint,
        }
        return "telemetry-emitter"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tiny_skill_agent.py",
            "do it",
            "--skills",
            str(valid_skill_dir),
            "--workspace",
            str(workspace_dir),
            "--openai-telemetry-file",
            "logs/openai-otel.jsonl",
            "--otel-endpoint",
            "http://127.0.0.1:4318/v1/traces",
        ],
    )
    monkeypatch.setattr(cli_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(cli_module, "SkillAgent", FakeAgent)
    monkeypatch.setattr(
        cli_module,
        "build_openai_telemetry_emitter",
        fake_builder,
    )

    tiny_skill_agent.main()
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert captured["telemetry"]["file_path"] == Path("logs/openai-otel.jsonl")
    assert (
        captured["telemetry"]["otlp_endpoint"]
        == "http://127.0.0.1:4318/v1/traces"
    )
    assert captured["agent_kwargs"]["openai_telemetry"] == "telemetry-emitter"
    assert captured["task"] == "do it"
