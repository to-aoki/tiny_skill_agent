import json
import sys

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
