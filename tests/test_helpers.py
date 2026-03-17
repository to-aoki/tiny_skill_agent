import json

import pytest

import tiny_skill_agent


def test_list_skill_files_and_extract_references(valid_skill):
    files = tiny_skill_agent.list_skill_files(valid_skill)
    references = tiny_skill_agent.extract_referenced_skill_files(valid_skill.body, files)

    assert files == [
        "references/guide.md",
        "scripts/echo_workspace.py",
        "scripts/not_python.sh",
    ]
    assert references == [
        "references/guide.md",
        "scripts/echo_workspace.py",
    ]


def test_read_skill_resource_reads_utf8_text(valid_skill):
    resource = tiny_skill_agent.read_skill_resource(valid_skill, "references/guide.md")

    assert resource["path"] == "references/guide.md"
    assert resource["kind"] == "references"
    assert "Formatting guidance for tests." in resource["content"]


def test_read_skill_resource_blocks_path_escape(valid_skill):
    with pytest.raises(SystemExit, match="outside the skill root"):
        tiny_skill_agent.read_skill_resource(valid_skill, "../README.md")


def test_run_skill_script_executes_python_script(valid_skill, workspace_dir):
    result = tiny_skill_agent.run_skill_script(
        valid_skill,
        "scripts/echo_workspace.py",
        ["--label", "from-test"],
        workspace_dir,
    )
    payload = json.loads(result["stdout"])

    assert result["returncode"] == 0
    assert payload["label"] == "from-test"
    assert payload["workspace"] == str(workspace_dir.resolve())


def test_run_skill_script_rejects_non_python_script(valid_skill, workspace_dir):
    with pytest.raises(SystemExit, match="Only Python scripts under scripts/ can be executed"):
        tiny_skill_agent.run_skill_script(valid_skill, "scripts/not_python.sh", [], workspace_dir)


def test_normalize_script_request_strips_python_prefix(valid_skill):
    script, args = tiny_skill_agent.normalize_script_request(
        valid_skill,
        "python scripts/echo_workspace.py --label sample",
        [],
    )

    assert script == "scripts/echo_workspace.py"
    assert args == ["--label", "sample"]


def test_is_script_path_only_allows_python_under_scripts():
    assert tiny_skill_agent.is_script_path("scripts/example.py") is True
    assert tiny_skill_agent.is_script_path("scripts/example.sh") is False
    assert tiny_skill_agent.is_script_path("assets/example.py") is False


def test_build_workspace_snapshot_skips_common_cache_dirs(workspace_dir):
    (workspace_dir / "visible.txt").write_text("ok", encoding="utf-8")
    (workspace_dir / "__pycache__").mkdir()
    (workspace_dir / "__pycache__" / "ignored.pyc").write_text("x", encoding="utf-8")

    snapshot = tiny_skill_agent.build_workspace_snapshot(workspace_dir)

    assert "visible.txt" in snapshot["sample_paths"]
    assert not any("__pycache__" in item for item in snapshot["sample_paths"])
