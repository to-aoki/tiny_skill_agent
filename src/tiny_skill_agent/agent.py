"""スキル選択とアクション実行を行うエージェント本体。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from .action import (
    create_file,
    extract_action_args,
    extract_action_bool_field,
    extract_action_directory_path,
    extract_action_file_path,
    extract_action_int_field,
    extract_action_scope,
    extract_action_text_alias,
    extract_action_text_field,
    insert_edit_into_file,
    read_file_for_action,
    replace_string_in_file,
    run_skill_script,
)
from .prompt import (
    SYSTEM_ACTOR_PROMPT,
    SYSTEM_FINALIZER_PROMPT,
    SYSTEM_SELECTOR_PROMPT,
)
from .skills import (
    Skill,
    SkillRegistry,
    build_selection_input,
    build_task_context_input,
    ensure_skill_allows_action,
    ensure_skill_allows_workspace_path,
    find_explicit_skill_mentions,
    list_allowed_actions_for_skill,
    normalize_selected_skill_names,
    resolve_action_skill,
)
from .telemetry import OpenAITelemetryEmitter, build_openai_telemetry_emitter
from .utils import (
    extract_response_text,
    parse_json_from_text,
    strip_thinking,
    truncate_text,
)
from .workspace import (
    infer_run_script_path,
    list_workspace_directory,
    looks_like_python_invocation,
    normalize_workspace_path,
)

OPENAI_RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
OPENAI_MAX_RETRIES = 2


@dataclass(slots=True)
class SkillSessionState:
    """1 回のスキル実行セッションで蓄積する状態。"""

    loaded_resources: dict[str, dict[str, str]]
    resource_reads: list[dict[str, Any]] = field(default_factory=list)
    script_runs: list[dict[str, Any]] = field(default_factory=list)
    workspace_reads: list[dict[str, Any]] = field(default_factory=list)
    workspace_writes: list[dict[str, Any]] = field(default_factory=list)
    session_steps: list[dict[str, Any]] = field(default_factory=list)
    loaded_workspace_files: dict[str, str] = field(default_factory=dict)
    listed_workspace_directories: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )


class SkillAgent:
    """選択したスキルを使ってタスクを段階的に処理する。"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        registry: SkillRegistry,
        workspace: Path,
        allow_scripts: bool = False,
        max_skill_turns: int = 8,
        openai_log_file: Path | None = None,
        openai_telemetry: OpenAITelemetryEmitter | None = None,
    ) -> None:
        """エージェント実行に必要な依存関係と設定を保持する。"""
        self.client = client
        self.model = model
        self.registry = registry
        self.workspace = workspace.resolve()
        self.allow_scripts = allow_scripts
        self.max_skill_turns = max(1, max_skill_turns)
        self._selected_skill_names: list[str] = []
        self.openai_telemetry = openai_telemetry
        if self.openai_telemetry is None and openai_log_file is not None:
            self.openai_telemetry = build_openai_telemetry_emitter(
                openai_log_file.resolve()
            )

    def run(self, task: str) -> dict[str, Any]:
        """タスクに対してスキル選択から最終応答生成まで実行する。"""
        self._selected_skill_names = []
        available_skills = sorted(
            self.registry.skills.values(),
            key=lambda item: item.name,
        )
        explicitly_requested = find_explicit_skill_mentions(task, available_skills)
        auto_selectable_skills = [
            skill
            for skill in available_skills
            if not bool(skill.frontmatter.get("disable-model-invocation"))
        ]
        selected_skills: list[Skill] = []
        for skill in explicitly_requested:
            if skill not in selected_skills:
                selected_skills.append(skill)

        if selected_skills:
            selection = {
                "skills": [skill.name for skill in selected_skills],
                "reason": "Activated explicitly requested skills without model selection.",
            }
        elif not auto_selectable_skills:
            selection = {
                "skills": [],
                "reason": "No auto-selectable skills are available.",
            }
        else:
            selector_input = build_selection_input(task, auto_selectable_skills)
            selection = self._json_chat(SYSTEM_SELECTOR_PROMPT, selector_input)
            for name in normalize_selected_skill_names(selection):
                skill = self.registry.get(name)
                if skill is not None and skill not in selected_skills:
                    selected_skills.append(skill)
        self._selected_skill_names = [skill.name for skill in selected_skills]

        if not selected_skills:
            final_text = self._plain_chat(
                "You are a concise coding assistant. "
                "No specialized skill has been activated.",
                build_task_context_input(task),
            )
            return {
                "selection": selection,
                "selected_skill": None,
                "selected_skills": [],
                "loaded_resources": [],
                "resource_reads": [],
                "workspace_reads": [],
                "workspace_writes": [],
                "script_run": None,
                "script_runs": [],
                "session_steps": [],
                "final": final_text,
            }

        loaded_resources = {skill.name: {} for skill in selected_skills}
        (
            final_text,
            resource_reads,
            script_runs,
            session_steps,
            workspace_reads,
            workspace_writes,
        ) = self._run_skill_session(task, selected_skills, loaded_resources)
        script_run = script_runs[-1] if script_runs else None
        return {
            "selection": selection,
            "selected_skill": (
                selected_skills[0].name if len(selected_skills) == 1 else None
            ),
            "selected_skills": [skill.name for skill in selected_skills],
            "loaded_resources": [
                {"skill": skill_name, "path": path}
                for skill_name, resources in loaded_resources.items()
                for path in resources
            ],
            "resource_reads": resource_reads,
            "workspace_reads": workspace_reads,
            "workspace_writes": workspace_writes,
            "script_run": script_run,
            "script_runs": script_runs,
            "session_steps": session_steps,
            "final": final_text,
        }

    def _plain_chat(self, system: str, user: str) -> str:
        """OpenAI 互換 API を呼び出してプレーンテキスト応答を得る。"""
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        for attempt in range(1, OPENAI_MAX_RETRIES + 2):
            started_at = time.perf_counter()
            try:
                response = self.client.chat.completions.create(**request_payload)
            except Exception as exc:
                retryable = isinstance(exc, OPENAI_RETRYABLE_ERRORS)
                self._emit_openai_telemetry(
                    request=request_payload,
                    attempt=attempt,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    error=exc,
                    retryable=retryable,
                )
                if not retryable:
                    raise
                if attempt > OPENAI_MAX_RETRIES:
                    hint = (
                        "Check OPENAI_BASE_URL or ensure the server is running."
                        if isinstance(exc, (APIConnectionError, APITimeoutError))
                        else "Check the server logs for the backend root cause."
                    )
                    raise SystemExit(
                        f"OpenAI request failed after {attempt} attempts: "
                        f"{type(exc).__name__}: {exc}. {hint}"
                    ) from exc
                time.sleep(0.5 * attempt)
                continue

            self._emit_openai_telemetry(
                request=request_payload,
                attempt=attempt,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                response=response,
            )
            break

        text = extract_response_text(response)
        cleaned = strip_thinking(text)
        if cleaned:
            return cleaned
        if text:
            return text
        if hasattr(response, "model_dump"):
            dumped_text = json.dumps(
                response.model_dump(),
                ensure_ascii=False,
                indent=2,
            )
            raise SystemExit(
                "Could not extract assistant text from model response:\n"
                f"{truncate_text(dumped_text, 4000)}"
            )
        raise SystemExit(
            f"Could not extract assistant text from model response: {response!r}"
        )

    def _emit_openai_telemetry(
        self,
        *,
        request: dict[str, Any],
        attempt: int,
        duration_ms: float,
        response: Any | None = None,
        error: Exception | None = None,
        retryable: bool | None = None,
    ) -> None:
        """OpenAI API 呼び出しを OpenTelemetry emitter へ流す。"""
        if self.openai_telemetry is None:
            return
        try:
            self.openai_telemetry.emit_chat_completion(
                request=request,
                attempt=attempt,
                duration_ms=duration_ms,
                selected_skills=self._selected_skill_names,
                response=response,
                error=error,
                retryable=retryable,
            )
        except Exception as exc:
            print(
                f"Warning: could not emit OpenAI telemetry: {exc}",
                file=sys.stderr,
            )

    def _json_chat(self, system: str, user: str) -> dict[str, Any]:
        """モデル応答を JSON オブジェクトとして取得する。"""
        text = self._plain_chat(system, user).strip()
        parsed = parse_json_from_text(text)
        if not isinstance(parsed, dict):
            raise SystemExit(f"Model did not return a JSON object:\n{text}")
        return parsed

    def _build_actor_payload(
        self,
        task: str,
        turn: int,
        skills: list[Skill],
        state: SkillSessionState,
    ) -> dict[str, Any]:
        """各ターンのアクターモデルへ渡す状態を構築する。"""
        return {
            "task": task,
            "turn": turn,
            "remaining_turns_after_this": self.max_skill_turns - turn,
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "frontmatter": skill.frontmatter,
                    "instructions": skill.body,
                    "allowed_actions": list_allowed_actions_for_skill(
                        skill,
                        self.allow_scripts,
                    ),
                    "loaded_resources": [
                        {"path": path, "content": content}
                        for path, content in state.loaded_resources.get(
                            skill.name,
                            {},
                        ).items()
                    ],
                }
                for skill in skills
            ],
            "listed_workspace_directories": list(
                state.listed_workspace_directories.values()
            ),
            "loaded_workspace_files": [
                {"path": path, "content": content}
                for path, content in state.loaded_workspace_files.items()
            ],
            "session_history": state.session_steps,
            "tool_policy": {
                "list_directory": (
                    "List one workspace directory. Set skill and optional "
                    "directoryPath, recursive, maxDepth, maxEntries."
                ),
                "read_file": (
                    "Read one file. Use scope=skill for bundled skill files. "
                    "Partial paths and filenames are auto-resolved when they "
                    "match exactly one file. Use line bounds when needed."
                ),
                "create_file": (
                    "Create one workspace text file. Set skill, filePath, "
                    "content. Fails if the file exists."
                ),
                "replace_string_in_file": (
                    "Exact text replace in one workspace file. Set skill, "
                    "filePath, stringToReplace, replacementString, optional "
                    "replaceAll."
                ),
                "insert_edit_into_file": (
                    "Insert after a line or replace a line range in one "
                    "workspace file. Set skill, filePath, newText, and line "
                    "indexes."
                ),
                "run_script": (
                    "Run one bundled Python script under scripts/. Set skill "
                    "and path. Partial script paths are auto-resolved when "
                    "they match exactly one script."
                    if self.allow_scripts
                    else "Skill scripts are disabled. Read files or respond."
                ),
                "skill_requirement": "Set skill on every tool action.",
            },
        }

    def _append_session_step(
        self,
        state: SkillSessionState,
        turn: int,
        step_type: str,
        data: dict[str, Any],
        tool: str | None = None,
        status: str | None = None,
    ) -> None:
        """セッション履歴へ 1 ステップ分の記録を追加する。"""
        step = {"turn": turn, "type": step_type, "data": data}
        if tool is not None:
            step["tool"] = tool
        if status is not None:
            step["status"] = status
        state.session_steps.append(step)

    def _append_tool_result(
        self,
        state: SkillSessionState,
        turn: int,
        tool_name: str,
        result: dict[str, Any],
    ) -> None:
        """ツール実行結果を履歴形式へ正規化して追加する。"""
        status = (
            "ok"
            if (
                result.get("returncode") == 0
                if tool_name == "run_script"
                else not result.get("error")
            )
            else "error"
        )
        self._append_session_step(
            state,
            turn,
            "tool_result",
            result,
            tool=tool_name,
            status=status,
        )

    def _build_action_error(
        self,
        action: dict[str, Any],
        error: str,
        *,
        path: str = "",
        include_file_path: bool = False,
        include_content: bool = False,
    ) -> dict[str, Any]:
        """アクション失敗時の共通エラーペイロードを組み立てる。"""
        resolved_path = (
            path
            or extract_action_file_path(action)
            or extract_action_directory_path(action)
        )
        result = {
            "skill": str(action.get("skill") or ""),
            "returncode": None,
            "error": error,
        }
        if resolved_path:
            result["path"] = resolved_path
        if include_file_path and resolved_path:
            result["filePath"] = resolved_path
        if include_content:
            result["content"] = ""
        return result

    def _build_script_error(
        self,
        action: dict[str, Any],
        error: str,
        args: list[str],
    ) -> dict[str, Any]:
        """スクリプト実行失敗時の結果形式を組み立てる。"""
        result = self._build_action_error(
            action,
            error,
            path=extract_action_file_path(action),
        )
        result.update({"args": args, "stdout": "", "stderr": error})
        return result

    def _handle_list_directory(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """ディレクトリ一覧取得アクションを処理する。"""
        directory_path = extract_action_directory_path(action)
        try:
            skill = resolve_action_skill(
                skills,
                str(action.get("skill") or ""),
                directory_path,
            )
            ensure_skill_allows_action(skill, "list_directory", self.allow_scripts)
            normalized_directory, _ = normalize_workspace_path(
                self.workspace,
                directory_path,
                kind="directory",
                default=".",
            )
            ensure_skill_allows_workspace_path(skill, normalized_directory)
            result = list_workspace_directory(
                self.workspace,
                normalized_directory,
                recursive=extract_action_bool_field(action, ("recursive",)),
                max_depth=extract_action_int_field(action, "maxDepth"),
                max_entries=extract_action_int_field(action, "maxEntries"),
            )
            result["skill"] = skill.name
            state.listed_workspace_directories[result["path"]] = result
        except SystemExit as exc:
            result = self._build_action_error(action, str(exc), path=directory_path)
        return "list_directory", result

    def _handle_read_file(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """ファイル読み込みアクションを処理する。"""
        action_path = extract_action_file_path(action)
        file_scope = extract_action_scope(action)
        try:
            skill = resolve_action_skill(
                skills,
                str(action.get("skill") or ""),
                action_path,
            )
            ensure_skill_allows_action(skill, "read_file", self.allow_scripts)
            result = read_file_for_action(
                self.workspace,
                skill,
                action_path,
                action_scope=file_scope,
                start_line=extract_action_int_field(
                    action,
                    "startLineNumberBaseZero",
                ),
                end_line=extract_action_int_field(
                    action,
                    "endLineNumberBaseZero",
                ),
            )
            result["skill"] = skill.name
            if result["scope"] == "skill":
                state.loaded_resources.setdefault(skill.name, {})[result["path"]] = (
                    result["content"]
                )
                state.resource_reads.append(result)
            else:
                state.loaded_workspace_files[result["path"]] = result["content"]
                state.workspace_reads.append(result)
        except SystemExit as exc:
            result = self._build_action_error(
                action,
                str(exc),
                path=action_path,
                include_file_path=True,
                include_content=True,
            )
            target = (
                state.resource_reads if file_scope == "skill" else state.workspace_reads
            )
            target.append(result)
        return "read_file", result

    def _handle_workspace_write(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        tool_name: str,
        writer: Callable[[str, dict[str, Any]], dict[str, Any]],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """workspace への書き込み系アクションを共通処理する。"""
        action_path = extract_action_file_path(action)
        try:
            skill = resolve_action_skill(
                skills,
                str(action.get("skill") or ""),
                action_path,
            )
            ensure_skill_allows_action(skill, tool_name, self.allow_scripts)
            normalized_path, _ = normalize_workspace_path(self.workspace, action_path)
            ensure_skill_allows_workspace_path(skill, normalized_path)
            result = writer(normalized_path, action)
            result["skill"] = skill.name
            state.loaded_workspace_files[result["path"]] = result["content"]
        except SystemExit as exc:
            result = self._build_action_error(
                action,
                str(exc),
                path=action_path,
                include_file_path=True,
                include_content=True,
            )
        state.workspace_writes.append(result)
        return tool_name, result

    def _handle_create_file(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """ファイル作成アクションを処理する。"""
        return self._handle_workspace_write(
            action,
            skills,
            "create_file",
            lambda normalized_path, current_action: create_file(
                self.workspace,
                normalized_path,
                extract_action_text_field(current_action, "content"),
            ),
            state,
        )

    def _handle_replace_string_in_file(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """文字列置換アクションを処理する。"""
        return self._handle_workspace_write(
            action,
            skills,
            "replace_string_in_file",
            lambda normalized_path, current_action: replace_string_in_file(
                self.workspace,
                normalized_path,
                extract_action_text_alias(
                    current_action,
                    ("stringToReplace", "oldText", "old_text", "old_text_to_replace"),
                ),
                extract_action_text_alias(
                    current_action,
                    (
                        "replacementString",
                        "newText",
                        "new_text",
                        "replacement_text",
                    ),
                ),
                replace_all=extract_action_bool_field(
                    current_action,
                    ("replaceAll", "replace_all"),
                ),
            ),
            state,
        )

    def _handle_insert_edit_into_file(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """行挿入・行置換アクションを処理する。"""
        return self._handle_workspace_write(
            action,
            skills,
            "insert_edit_into_file",
            lambda normalized_path, current_action: insert_edit_into_file(
                self.workspace,
                normalized_path,
                extract_action_text_alias(current_action, ("newText", "code", "content")),
                start_line=extract_action_int_field(
                    current_action,
                    "startLineNumberBaseZero",
                ),
                end_line=extract_action_int_field(
                    current_action,
                    "endLineNumberBaseZero",
                ),
                insert_after_line=extract_action_int_field(
                    current_action,
                    "insertAfterLineNumberBaseZero",
                ),
            ),
            state,
        )

    def _handle_run_script(
        self,
        action: dict[str, Any],
        skills: list[Skill],
        state: SkillSessionState,
    ) -> tuple[str, dict[str, Any]]:
        """スキル付属スクリプトの実行アクションを処理する。"""
        script_args = extract_action_args(action)
        if not self.allow_scripts:
            result = {"error": "Bundled skill scripts are disabled by the host runner."}
            state.script_runs.append(result)
            return "run_script", result
        try:
            action_path = extract_action_file_path(action)
            script_resolution_path = action_path
            if not script_resolution_path and script_args:
                offset = 1 if looks_like_python_invocation(script_args[0]) else 0
                if len(script_args) > offset:
                    script_resolution_path = script_args[offset]
            skill = resolve_action_skill(
                skills,
                str(action.get("skill") or ""),
                script_resolution_path,
            )
            ensure_skill_allows_action(skill, "run_script", self.allow_scripts)
            resolved_script_path, script_args = infer_run_script_path(
                skill,
                action_path,
                script_args,
            )
            result = run_skill_script(
                skill,
                resolved_script_path,
                script_args,
                self.workspace,
            )
            result["skill"] = skill.name
        except SystemExit as exc:
            result = self._build_script_error(action, str(exc), script_args)
        state.script_runs.append(result)
        return "run_script", result

    def _run_skill_session(
        self,
        task: str,
        skills: list[Skill],
        loaded_resources: dict[str, dict[str, str]],
    ) -> tuple[
        str,
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """スキル実行ループを回して最終応答を得る。"""
        state = SkillSessionState(loaded_resources=loaded_resources)
        handlers: dict[
            str,
            Callable[
                [dict[str, Any], list[Skill], SkillSessionState],
                tuple[str, dict[str, Any]],
            ],
        ] = {
            "list_directory": self._handle_list_directory,
            "read_file": self._handle_read_file,
            "create_file": self._handle_create_file,
            "replace_string_in_file": self._handle_replace_string_in_file,
            "insert_edit_into_file": self._handle_insert_edit_into_file,
            "run_script": self._handle_run_script,
        }

        for turn in range(1, self.max_skill_turns + 1):
            action = self._json_chat(
                SYSTEM_ACTOR_PROMPT,
                json.dumps(
                    self._build_actor_payload(task, turn, skills, state),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self._append_session_step(state, turn, "assistant_action", action)
            action_name = str(action.get("action") or "").strip()
            if action_name == "respond":
                return (
                    str(action.get("message") or ""),
                    state.resource_reads,
                    state.script_runs,
                    state.session_steps,
                    state.workspace_reads,
                    state.workspace_writes,
                )
            handler = handlers.get(action_name)
            if handler is None:
                self._append_tool_result(
                    state,
                    turn,
                    "tool_dispatch",
                    {"error": f"Unknown action: {action_name or '(missing)'}"},
                )
                continue
            tool_name, result = handler(action, skills, state)
            self._append_tool_result(state, turn, tool_name, result)

        final_payload = {
            "task": task,
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.body,
                }
                for skill in skills
            ],
            "listed_workspace_directories": [
                {"path": path, "entries": item.get("entries", [])}
                for path, item in state.listed_workspace_directories.items()
            ],
            "loaded_resources": [
                {"skill": skill_name, "path": path}
                for skill_name, resources in state.loaded_resources.items()
                for path in resources
            ],
            "loaded_workspace_files": [
                {"path": path} for path in state.loaded_workspace_files
            ],
            "session_history": state.session_steps,
            "limit_reached": True,
            "max_skill_turns": self.max_skill_turns,
        }
        final_text = self._plain_chat(
            SYSTEM_FINALIZER_PROMPT,
            json.dumps(final_payload, ensure_ascii=False, indent=2),
        )
        return (
            final_text,
            state.resource_reads,
            state.script_runs,
            state.session_steps,
            state.workspace_reads,
            state.workspace_writes,
        )
