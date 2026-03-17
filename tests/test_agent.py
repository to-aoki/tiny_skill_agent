from pathlib import Path

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

    def _json_chat(self, system: str, user: str) -> dict:
        return self._actions.pop(0)

    def _plain_chat(self, system: str, user: str) -> str:
        return "finalized"


def build_skill_state(skill):
    skill_files = {skill.name: tiny_skill_agent.list_skill_files(skill)}
    skill_hints = {
        skill.name: tiny_skill_agent.extract_referenced_skill_files(skill.body, skill_files[skill.name]),
    }
    loaded_resources = {skill.name: {}}
    return skill_files, skill_hints, loaded_resources


def test_run_skill_session_reads_resource_then_respond(valid_skill, workspace_dir):
    agent = StubAgent([
        {
            "action": "read_resource",
            "skill": "valid-skill",
            "path": "references/guide.md",
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
    skill_files, skill_hints, loaded_resources = build_skill_state(valid_skill)

    final_text, resource_reads, script_runs, session_steps = agent._run_skill_session(
        "summarize",
        [valid_skill],
        tiny_skill_agent.build_workspace_snapshot(workspace_dir),
        skill_files,
        skill_hints,
        loaded_resources,
    )

    assert final_text == "done"
    assert script_runs == []
    assert resource_reads[0]["path"] == "references/guide.md"
    assert "Formatting guidance for tests." in loaded_resources["valid-skill"]["references/guide.md"]
    assert any(step["tool"] == "read_resource" for step in session_steps if step["type"] == "tool_result")


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
    skill_files, skill_hints, loaded_resources = build_skill_state(valid_skill)

    final_text, resource_reads, script_runs, session_steps = agent._run_skill_session(
        "summarize",
        [valid_skill],
        tiny_skill_agent.build_workspace_snapshot(workspace_dir),
        skill_files,
        skill_hints,
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs[0]["returncode"] == 0
    assert '"label": "agent-test"' in script_runs[0]["stdout"]
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
    skill_files, skill_hints, loaded_resources = build_skill_state(valid_skill)

    final_text, resource_reads, script_runs, _ = agent._run_skill_session(
        "summarize",
        [valid_skill],
        tiny_skill_agent.build_workspace_snapshot(workspace_dir),
        skill_files,
        skill_hints,
        loaded_resources,
    )

    assert final_text == "done"
    assert resource_reads == []
    assert script_runs[0]["returncode"] is None
    assert "Only Python scripts under scripts/" in script_runs[0]["error"]
