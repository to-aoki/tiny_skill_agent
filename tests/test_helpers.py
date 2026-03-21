import json

import pytest

import tiny_skill_agent


def test_find_skill_files_matches_partial_path(valid_skill):
    result = tiny_skill_agent.find_skill_files(valid_skill, "guide.md")

    assert result["scope"] == "skill"
    assert result["matchCount"] == 1
    assert result["matches"][0]["path"] == "references/guide.md"
    assert result["matches"][0]["kind"] == "references"


def test_read_skill_resource_reads_utf8_text(valid_skill):
    resource = tiny_skill_agent.read_skill_resource(valid_skill, "references/guide.md")

    assert resource["path"] == "references/guide.md"
    assert resource["kind"] == "references"
    assert "Formatting guidance for tests." in resource["content"]


def test_read_skill_resource_resolves_partial_path_via_search(valid_skill):
    resource = tiny_skill_agent.read_skill_resource(valid_skill, "guide.md")

    assert resource["path"] == "references/guide.md"
    assert resource["resolvedBySearch"] is True


def test_read_skill_resource_blocks_path_escape(valid_skill):
    with pytest.raises(SystemExit, match="outside the skill root"):
        tiny_skill_agent.read_skill_resource(valid_skill, "../README.md")


def test_read_workspace_file_reads_utf8_text(workspace_dir):
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "notes.txt", "hello\nworld\n")

    resource = tiny_skill_agent.read_workspace_file(workspace_dir, "notes.txt")

    assert resource["path"] == "notes.txt"
    assert resource["size_bytes"] > 0
    assert resource["content"] == "hello\nworld\n"


def test_read_workspace_file_resolves_partial_path_via_search(valid_skill, workspace_dir):
    (workspace_dir / "src").mkdir()
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "src" / "main.py", "print('x')\n")

    resource = tiny_skill_agent.read_workspace_file(workspace_dir, "main.py", selected_skill=valid_skill)

    assert resource["path"] == "src/main.py"
    assert resource["resolvedBySearch"] is True


def test_read_workspace_file_blocks_path_escape(workspace_dir):
    with pytest.raises(SystemExit, match="outside the workspace"):
        tiny_skill_agent.read_workspace_file(workspace_dir, "../README.md")


def test_list_workspace_directory_lists_on_demand(workspace_dir):
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "root.txt", "ok\n")
    (workspace_dir / "src").mkdir()
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "src" / "main.py", "print('x')\n")

    result = tiny_skill_agent.list_workspace_directory(workspace_dir, ".", recursive=True, max_depth=2, max_entries=10)

    assert result["path"] == "."
    assert "root.txt" in result["entries"]
    assert "src/" in result["entries"]
    assert "src/main.py" in result["entries"]


def test_build_task_context_input_does_not_embed_workspace_snapshot(workspace_dir):
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "secret.py", "print('secret')\n")

    context = tiny_skill_agent.build_task_context_input("describe")

    assert str(workspace_dir) not in context
    assert "secret.py" not in context
    assert "available skill metadata only" in context
    assert "not preloaded" in context


def test_build_skill_adherence_block_uses_name_and_description_only(valid_skill):
    block = tiny_skill_agent.build_skill_adherence_block([valid_skill])

    assert valid_skill.name in block
    assert valid_skill.description in block
    assert str(valid_skill.root / "SKILL.md") not in block
    assert "references/guide.md" not in block


def test_parse_json_from_text_prefers_final_json_over_fenced_examples():
    text = """Thinking Process:
```json
{
  "skills": ["draft-skill"],
  "reason": "draft"
}
```

Schema example:
```json
{
  "skills": ["skill-name-1"],
  "reason": "brief explanation"
}
```
</think>

{
  "skills": ["repo-map"],
  "reason": "final"
}
"""

    parsed = tiny_skill_agent.parse_json_from_text(text)

    assert parsed == {
        "skills": ["repo-map"],
        "reason": "final",
    }


def test_parse_json_from_text_reads_single_fenced_json_block():
    text = """Here is the result:

```json
{
  "skills": ["repo-map"],
  "reason": "final"
}
```
"""

    parsed = tiny_skill_agent.parse_json_from_text(text)

    assert parsed == {
        "skills": ["repo-map"],
        "reason": "final",
    }


def test_write_workspace_file_creates_parent_dirs(workspace_dir):
    result = tiny_skill_agent.write_workspace_file(workspace_dir, "nested/output.txt", "created\n")

    assert result["path"] == "nested/output.txt"
    assert result["created"] is True
    assert tiny_skill_agent.read_utf8_text_file(workspace_dir / "nested" / "output.txt") == "created\n"


def test_edit_workspace_file_replaces_exact_text(workspace_dir):
    target = workspace_dir / "sample.txt"
    tiny_skill_agent.write_utf8_text_file(target, "alpha\nbeta\n")

    result = tiny_skill_agent.edit_workspace_file(workspace_dir, "sample.txt", "beta", "gamma")

    assert result["path"] == "sample.txt"
    assert result["replacements"] == 1
    assert tiny_skill_agent.read_utf8_text_file(target) == "alpha\ngamma\n"


def test_create_file_uses_copilot_style_identifier(workspace_dir):
    result = tiny_skill_agent.create_file(workspace_dir, "copilot/new.txt", "created\n")

    assert result["path"] == "copilot/new.txt"
    assert result["created"] is True
    assert tiny_skill_agent.read_utf8_text_file(workspace_dir / "copilot" / "new.txt") == "created\n"


def test_replace_string_in_file_uses_copilot_style_identifier(workspace_dir):
    target = workspace_dir / "copilot.txt"
    tiny_skill_agent.write_utf8_text_file(target, "before\nafter\n")

    result = tiny_skill_agent.replace_string_in_file(workspace_dir, "copilot.txt", "after", "done")

    assert result["path"] == "copilot.txt"
    assert result["replacements"] == 1
    assert tiny_skill_agent.read_utf8_text_file(target) == "before\ndone\n"


def test_insert_edit_into_file_replaces_line_range(workspace_dir):
    target = workspace_dir / "range.txt"
    tiny_skill_agent.write_utf8_text_file(target, "a\nb\nc\n")

    result = tiny_skill_agent.insert_edit_into_file(workspace_dir, "range.txt", "x\ny\n", start_line=1, end_line=1)

    assert result["path"] == "range.txt"
    assert tiny_skill_agent.read_utf8_text_file(target) == "a\nx\ny\nc\n"


def test_edit_workspace_file_rejects_ambiguous_match_without_replace_all(workspace_dir):
    target = workspace_dir / "repeat.txt"
    tiny_skill_agent.write_utf8_text_file(target, "dup\ndup\n")

    with pytest.raises(SystemExit, match="matched 2 times"):
        tiny_skill_agent.edit_workspace_file(workspace_dir, "repeat.txt", "dup", "once")


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


def test_run_skill_script_resolves_partial_path_via_search(valid_skill, workspace_dir):
    result = tiny_skill_agent.run_skill_script(
        valid_skill,
        "echo_workspace.py",
        ["--label", "search"],
        workspace_dir,
    )
    payload = json.loads(result["stdout"])

    assert result["path"] == "scripts/echo_workspace.py"
    assert result["resolvedBySearch"] is True
    assert payload["label"] == "search"


def test_run_skill_script_decodes_utf8_output(valid_skill, workspace_dir):
    result = tiny_skill_agent.run_skill_script(
        valid_skill,
        "scripts/echo_workspace.py",
        ["--label", "変換🙂"],
        workspace_dir,
    )
    payload = json.loads(result["stdout"])

    assert result["returncode"] == 0
    assert payload["label"] == "変換🙂"


def test_run_skill_script_uses_uv_for_pep_723_script(valid_skill, workspace_dir):
    result = tiny_skill_agent.run_skill_script(
        valid_skill,
        "scripts/pep723_echo.py",
        ["--label", "inline"],
        workspace_dir,
    )
    payload = json.loads(result["stdout"])

    assert result["returncode"] == 0
    assert result["cmd"][:2] == ["uv", "run"] or result["cmd"][:2][1:] == ["run"]
    assert payload["workspace"] == str(workspace_dir.resolve())
    assert "--label" in payload["args"]
    assert "inline" in payload["args"]


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
