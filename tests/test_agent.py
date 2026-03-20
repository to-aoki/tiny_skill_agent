from pathlib import Path
import json

import tiny_skill_agent.agent as agent_module
import tiny_skill_agent


class StubAgent(tiny_skill_agent.SkillAgent):
    def __init__(self, actions, workspace: Path, allow_scripts: bool = False):
        self.client = None
        self.model = "stub-model"
        self.registry = None
        self.workspace = workspace.resolve()
        self.allow_scripts = allow_scripts
        self.max_skill_turns = 4
        self._actions = list(actions)
        self.json_users = []
        self.plain_users = []

    def _json_chat(self, system: str, user: str) -> dict:
        self.json_users.append(user)
        return self._actions.pop(0)

    def _plain_chat(self, system: str, user: str) -> str:
        self.plain_users.append(user)
        return "finalized"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class FakeCompletions:
    def __init__(self, response=None, error=None, outcomes=None):
        self.response = response
        self.error = error
        self.outcomes = list(outcomes or [])
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self.error is not None:
            raise self.error
        return self.response


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


class FakeRegistry:
    def __init__(self, skills):
        self.skills = {skill.name: skill for skill in skills}

    def get(self, name):
        return self.skills.get(name)


def build_loaded_resources(skill):
    return {skill.name: {}}


def test_plain_chat_writes_openai_jsonl_log(workspace_dir):
    log_file = workspace_dir / "logs" / "openai.jsonl"
    response_payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 123,
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "logged answer"},
                "finish_reason": "stop",
            }
        ],
    }
    completions = FakeCompletions(response=FakeResponse(response_payload))
    agent = tiny_skill_agent.SkillAgent(
        client=FakeClient(completions),
        model="stub-model",
        registry=None,
        workspace=workspace_dir,
        openai_log_file=log_file,
    )

    text = agent._plain_chat("system prompt", "user prompt")

    assert text == "logged answer"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["api"] == "chat.completions"
    assert payload["request"]["model"] == "stub-model"
    assert payload["request"]["messages"][0]["role"] == "system"
    assert payload["response"]["id"] == "chatcmpl-test"


def test_plain_chat_logs_openai_error(workspace_dir):
    log_file = workspace_dir / "logs" / "openai-errors.jsonl"
    completions = FakeCompletions(error=RuntimeError("boom"))
    agent = tiny_skill_agent.SkillAgent(
        client=FakeClient(completions),
        model="stub-model",
        registry=None,
        workspace=workspace_dir,
        openai_log_file=log_file,
    )

    try:
        agent._plain_chat("system prompt", "user prompt")
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("RuntimeError was not raised")

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["api"] == "chat.completions"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "boom"


def test_plain_chat_retries_retryable_openai_errors(monkeypatch, workspace_dir):
    log_file = workspace_dir / "logs" / "openai-retry.jsonl"
    response_payload = {
        "id": "chatcmpl-retry",
        "object": "chat.completion",
        "created": 123,
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "retried answer"},
                "finish_reason": "stop",
            }
        ],
    }
    completions = FakeCompletions(outcomes=[RuntimeError("temporary"), FakeResponse(response_payload)])
    agent = tiny_skill_agent.SkillAgent(
        client=FakeClient(completions),
        model="stub-model",
        registry=None,
        workspace=workspace_dir,
        openai_log_file=log_file,
    )
    monkeypatch.setattr(agent_module, "OPENAI_RETRYABLE_ERRORS", (RuntimeError,))
    monkeypatch.setattr(agent_module.time, "sleep", lambda _: None)

    text = agent._plain_chat("system prompt", "user prompt")

    assert text == "retried answer"
    assert len(completions.calls) == 2
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["attempt"] == 1
    assert first["retryable"] is True
    assert first["error"]["message"] == "temporary"
    assert second["attempt"] == 2
    assert second["response"]["id"] == "chatcmpl-retry"


def test_plain_chat_exits_cleanly_after_retryable_openai_failures(monkeypatch, workspace_dir):
    log_file = workspace_dir / "logs" / "openai-retry-exhausted.jsonl"
    completions = FakeCompletions(error=RuntimeError("still down"))
    agent = tiny_skill_agent.SkillAgent(
        client=FakeClient(completions),
        model="stub-model",
        registry=None,
        workspace=workspace_dir,
        openai_log_file=log_file,
    )
    monkeypatch.setattr(agent_module, "OPENAI_RETRYABLE_ERRORS", (RuntimeError,))
    monkeypatch.setattr(agent_module, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(agent_module.time, "sleep", lambda _: None)

    try:
        agent._plain_chat("system prompt", "user prompt")
    except SystemExit as exc:
        assert "OpenAI request failed after 2 attempts" in str(exc)
        assert "still down" in str(exc)
    else:
        raise AssertionError("SystemExit was not raised")

    assert len(completions.calls) == 2
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    assert second["attempt"] == 2
    assert second["retryable"] is True


def test_run_skips_selector_when_skill_is_explicitly_requested(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "respond",
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    agent.registry = FakeRegistry([valid_skill])

    result = agent.run("Use `valid-skill` to summarize the guide.")

    assert result["final"] == "done"
    assert result["selected_skills"] == ["valid-skill"]
    assert result["selection"]["skills"] == ["valid-skill"]
    assert "without model selection" in result["selection"]["reason"]
    assert len(agent.json_users) == 1


def test_run_skill_session_reads_resource_then_respond(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "read_file",
            "skill": "valid-skill",
            "scope": "skill",
            "filePath": "guide.md",
            "args": [],
            "message": "",
            "reason": "Need the guide.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert script_runs == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert resource_reads[0]["path"] == "references/guide.md"
    assert resource_reads[0]["resolvedBySearch"] is True
    assert "Formatting guidance for tests." in loaded_resources["valid-skill"]["references/guide.md"]
    assert any(step["tool"] == "read_file" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_reads_workspace_file_then_respond(valid_skill, workspace_dir):
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "app.py", "print('hi')\n")
    agent = StubAgent([
        {
            "action": "read_file",
            "skill": "valid-skill",
            "scope": "workspace",
            "filePath": "app.py",
            "args": [],
            "message": "",
            "reason": "Need the local file contents.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs == []
    assert workspace_writes == []
    assert workspace_reads[0]["path"] == "app.py"
    assert "print('hi')" in workspace_reads[0]["content"]
    assert any(step["tool"] == "read_file" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_lists_directory_then_respond(valid_skill, workspace_dir):
    (workspace_dir / "src").mkdir()
    tiny_skill_agent.write_utf8_text_file(workspace_dir / "src" / "main.py", "print('hi')\n")
    agent = StubAgent([
        {
            "action": "list_directory",
            "skill": "valid-skill",
            "directoryPath": ".",
            "recursive": True,
            "maxDepth": 2,
            "maxEntries": 20,
            "args": [],
            "message": "",
            "reason": "Need to discover files first.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs == []
    assert workspace_reads == []
    assert workspace_writes == []
    listing_step = next(step for step in session_steps if step["type"] == "tool_result" and step["tool"] == "list_directory")
    assert "src/main.py" in listing_step["data"]["entries"]


def test_run_skill_session_writes_workspace_file_then_respond(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "create_file",
            "skill": "valid-skill",
            "filePath": "notes/todo.txt",
            "content": "line 1\nline 2\n",
            "args": [],
            "message": "",
            "reason": "Need to create the file.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs == []
    assert workspace_reads == []
    assert workspace_writes[0]["path"] == "notes/todo.txt"
    assert tiny_skill_agent.read_utf8_text_file(workspace_dir / "notes" / "todo.txt") == "line 1\nline 2\n"
    assert any(step["tool"] == "create_file" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_ignores_allowed_tools_for_workspace_write(valid_skill, workspace_dir):
    valid_skill.frontmatter["allowed-tools"] = ["read"]
    agent = StubAgent([
        {
            "action": "create_file",
            "skill": "valid-skill",
            "filePath": "blocked.txt",
            "content": "blocked\n",
            "args": [],
            "message": "",
            "reason": "This should fail.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, _, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs == []
    assert workspace_reads == []
    assert workspace_writes[0]["path"] == "blocked.txt"
    assert workspace_writes[0]["created"] is True
    assert (workspace_dir / "blocked.txt").read_text(encoding="utf-8") == "blocked\n"


def test_run_skill_session_runs_script_then_respond(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "run_script",
            "skill": "valid-skill",
            "path": "scripts/echo_workspace.py",
            "args": ["--label", "agent-test"],
            "message": "",
            "reason": "Need script output.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir, allow_scripts=True)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert script_runs[0]["returncode"] == 0
    assert '"label": "agent-test"' in script_runs[0]["stdout"]
    assert any(step["tool"] == "run_script" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_infers_single_available_script(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "run_script",
            "skill": "valid-skill",
            "args": ["--label", "implicit-script"],
            "message": "",
            "reason": "Need script output.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir, allow_scripts=True)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert script_runs[0]["returncode"] == 0
    assert script_runs[0]["path"] == "scripts/echo_workspace.py"
    assert '"label": "implicit-script"' in script_runs[0]["stdout"]
    assert any(step["tool"] == "run_script" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_extracts_script_path_from_args(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "run_script",
            "skill": "valid-skill",
            "args": ["scripts/echo_workspace.py", "--label", "path-in-args"],
            "message": "",
            "reason": "Need script output.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir, allow_scripts=True)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert script_runs[0]["returncode"] == 0
    assert script_runs[0]["path"] == "scripts/echo_workspace.py"
    assert '"label": "path-in-args"' in script_runs[0]["stdout"]
    assert any(step["tool"] == "run_script" for step in session_steps if step["type"] == "tool_result")


def test_run_skill_session_rejects_non_python_script_request(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "run_script",
            "skill": "valid-skill",
            "path": "scripts/not_python.sh",
            "args": [],
            "message": "",
            "reason": "This should fail.",
        },
        {
            "action": "respond",
            "skill": "",
            "path": "",
            "args": [],
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir, allow_scripts=True)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, _, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert script_runs[0]["returncode"] is None
    assert "Only Python scripts under scripts/" in script_runs[0]["error"]


def test_run_skill_session_initial_payload_omits_workspace_root(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "respond",
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, _, _, _, _, _ = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    payload = json.loads(agent.json_users[0])

    assert final_text == "done"
    assert "workspace" not in payload
    assert str(workspace_dir) not in agent.json_users[0]
    assert "available_files" not in payload["skills"][0]
    assert "suggested_files" not in payload["skills"][0]
    assert "available_scripts" not in payload["skills"][0]
    assert "find_file" not in payload["tool_policy"]
    assert "find_file" not in payload["skills"][0]["allowed_actions"]


def test_run_skill_session_records_unknown_action_dispatch(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "unsupported_action",
            "skill": "valid-skill",
            "message": "",
            "reason": "This should be rejected by dispatch.",
        },
        {
            "action": "respond",
            "message": "done",
            "reason": "Finished.",
        },
    ], workspace=workspace_dir)
    loaded_resources = build_loaded_resources(valid_skill)

    final_text, resource_reads, script_runs, session_steps, workspace_reads, workspace_writes = agent._run_skill_session(
        "summarize",
        [valid_skill],
        loaded_resources,
    )

    dispatch_step = next(step for step in session_steps if step["type"] == "tool_result" and step["tool"] == "tool_dispatch")

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs == []
    assert workspace_reads == []
    assert workspace_writes == []
    assert dispatch_step["status"] == "error"
    assert "Unknown action: unsupported_action" in dispatch_step["data"]["error"]

