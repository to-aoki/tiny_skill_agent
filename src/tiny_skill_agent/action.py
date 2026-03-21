"""ACTION 関連の定義と高水準アクション処理。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ActionCatalog:
    """サポートするアクション名を管理する。"""

    NAMES = (
        "list_directory",
        "read_file",
        "create_file",
        "replace_string_in_file",
        "insert_edit_into_file",
        "run_script",
    )

    WORKSPACE_NAMES = {
        "list_directory",
        "create_file",
        "replace_string_in_file",
        "insert_edit_into_file",
    }


class ActionPayload:
    """アクション辞書の入力値を解釈する。"""

    @staticmethod
    def extract_args(action: dict[str, Any]) -> list[str]:
        """アクション辞書から引数配列を取り出す。"""
        raw_args = action.get("args")
        if raw_args is None or raw_args == "":
            return []
        if isinstance(raw_args, list):
            return [str(item) for item in raw_args]
        return [str(raw_args)]

    @staticmethod
    def extract_file_path(action: dict[str, Any]) -> str:
        """アクション辞書からファイルパス候補を抽出する。"""
        file_path = action.get("filePath")
        if isinstance(file_path, str) and file_path.strip():
            return file_path
        path = action.get("path")
        if isinstance(path, str) and path.strip():
            return path
        script = action.get("script")
        if isinstance(script, str):
            return script
        return ""

    @staticmethod
    def extract_directory_path(action: dict[str, Any]) -> str:
        """アクション辞書からディレクトリパス候補を抽出する。"""
        directory_path = action.get("directoryPath")
        if isinstance(directory_path, str) and directory_path.strip():
            return directory_path
        file_path = action.get("path")
        if isinstance(file_path, str):
            return file_path
        return ""

    @staticmethod
    def extract_scope(action: dict[str, Any]) -> str:
        """アクション辞書から読み込みスコープ指定を抽出する。"""
        value = action.get("scope")
        if not isinstance(value, str):
            return ""
        normalized = value.strip().lower()
        return normalized if normalized in {"workspace", "skill"} else ""

    @staticmethod
    def extract_text_field(action: dict[str, Any], field_name: str) -> str:
        """アクション辞書から文字列フィールドを安全に取得する。"""
        action_name = str(action.get("action") or "tool action")
        if field_name not in action:
            raise SystemExit(f"Model requested {action_name} without {field_name}")
        value = action.get(field_name)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    @classmethod
    def extract_text_alias(
        cls,
        action: dict[str, Any],
        field_names: tuple[str, ...],
    ) -> str:
        """複数候補名から最初に見つかった文字列フィールドを返す。"""
        for field_name in field_names:
            if field_name in action:
                return cls.extract_text_field(action, field_name)
        joined = ", ".join(field_names)
        action_name = str(action.get("action") or "tool action")
        raise SystemExit(f"Model requested {action_name} without any of: {joined}")

    @staticmethod
    def extract_int_field(
        action: dict[str, Any],
        field_name: str,
    ) -> int | None:
        """アクション辞書から整数フィールドを取得する。"""
        value = action.get(field_name)
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            action_name = str(action.get("action") or "tool action")
            raise SystemExit(
                f"Model requested {action_name} with non-integer {field_name}"
            )
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            action_name = str(action.get("action") or "tool action")
            raise SystemExit(
                f"Model requested {action_name} with invalid {field_name}: {value!r}"
            ) from exc

    @staticmethod
    def extract_bool_field(
        action: dict[str, Any],
        field_names: tuple[str, ...],
    ) -> bool:
        """複数候補名から真偽値フィールドを解釈する。"""
        for field_name in field_names:
            value = action.get(field_name)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() == "true"
        return False


class ActionOperations:
    """高水準の ACTION 処理を提供する。"""

    @staticmethod
    def script_uses_inline_metadata(script_path: Path) -> bool:
        """PEP 723 の inline metadata を持つスクリプトか判定する。"""
        try:
            with script_path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index > 40:
                        break
                    if line.strip() == "# /// script":
                        return True
        except UnicodeDecodeError:
            return False
        return False

    @staticmethod
    def read_file_for_action(
        workspace: Path,
        selected_skill: Any,
        file_path: str,
        action_scope: str = "",
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """アクション指定に応じて skill または workspace を読む。"""
        from .skills import ensure_skill_allows_workspace_path
        from .skill_files import read_skill_resource
        from .workspace import (
            normalize_workspace_path,
            read_workspace_file,
        )

        scope = action_scope or ""
        if scope == "skill":
            return read_skill_resource(
                selected_skill,
                file_path,
                start_line=start_line,
                end_line=end_line,
                allow_search=True,
            )
        if scope == "workspace":
            return read_workspace_file(
                workspace,
                file_path,
                selected_skill=selected_skill,
                start_line=start_line,
                end_line=end_line,
                allow_search=True,
            )
        try:
            normalized, _ = normalize_workspace_path(workspace, file_path)
            ensure_skill_allows_workspace_path(selected_skill, normalized)
            return read_workspace_file(
                workspace,
                normalized,
                selected_skill=selected_skill,
                start_line=start_line,
                end_line=end_line,
                allow_search=False,
            )
        except SystemExit as workspace_exc:
            try:
                return read_skill_resource(
                    selected_skill,
                    file_path,
                    start_line=start_line,
                    end_line=end_line,
                    allow_search=True,
                )
            except SystemExit:
                raise workspace_exc

    @staticmethod
    def create_file(
        workspace: Path,
        rel_path: str,
        content: str,
        max_chars_per_file: int = 16000,
    ) -> dict[str, Any]:
        """workspace に新しいテキストファイルを作成する。"""
        from .workspace import (
            normalize_workspace_path,
            workspace_file_result,
            write_utf8_text_file,
        )

        normalized, path = normalize_workspace_path(workspace, rel_path)
        if path.exists():
            raise SystemExit(
                f"Refusing to create a file that already exists: {normalized}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_utf8_text_file(path, content)
        return workspace_file_result(
            path,
            normalized,
            content,
            max_chars_per_file,
            created=True,
        )

    @staticmethod
    def replace_string_in_file(
        workspace: Path,
        rel_path: str,
        string_to_replace: str,
        replacement_string: str,
        replace_all: bool = False,
        max_chars_per_file: int = 16000,
    ) -> dict[str, Any]:
        """workspace ファイル内の文字列を置換する。"""
        from .workspace import (
            read_existing_workspace_text,
            workspace_file_result,
            write_utf8_text_file,
        )

        if not string_to_replace:
            raise SystemExit(
                "Model requested replace_string_in_file without stringToReplace"
            )
        normalized, path, text = read_existing_workspace_text(workspace, rel_path)
        match_count = text.count(string_to_replace)
        if match_count == 0:
            raise SystemExit(f"Could not find old_text in workspace file: {normalized}")
        if match_count > 1 and not replace_all:
            raise SystemExit(
                f"old_text matched {match_count} times in workspace file: {normalized}. "
                "Use replace_all=true or provide a more specific snippet."
            )
        updated = text.replace(
            string_to_replace,
            replacement_string,
            -1 if replace_all else 1,
        )
        write_utf8_text_file(path, updated)
        return workspace_file_result(
            path,
            normalized,
            updated,
            max_chars_per_file,
            created=False,
            replacements=match_count if replace_all else 1,
        )

    @staticmethod
    def insert_edit_into_file(
        workspace: Path,
        rel_path: str,
        new_text: str,
        start_line: int | None = None,
        end_line: int | None = None,
        insert_after_line: int | None = None,
        max_chars_per_file: int = 16000,
    ) -> dict[str, Any]:
        """workspace ファイルへ行挿入または行範囲置換を行う。"""
        from .workspace import (
            read_existing_workspace_text,
            workspace_file_result,
            write_utf8_text_file,
        )

        normalized, path, text = read_existing_workspace_text(workspace, rel_path)
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        if insert_after_line is not None and (
            start_line is not None or end_line is not None
        ):
            raise SystemExit(
                "Use either insertAfterLineNumberBaseZero or a start/end line range "
                "for insert_edit_into_file, not both."
            )

        if insert_after_line is not None:
            if insert_after_line < -1 or insert_after_line >= total_lines:
                raise SystemExit(
                    f"insertAfterLineNumberBaseZero is out of range for workspace "
                    f"file: {normalized}"
                )
            insert_at = insert_after_line + 1
            updated_lines = lines[:insert_at] + [new_text] + lines[insert_at:]
        else:
            if start_line is None or end_line is None:
                raise SystemExit(
                    "Model requested insert_edit_into_file without line coordinates"
                )
            if start_line < 0 or end_line < start_line:
                raise SystemExit(
                    "Invalid start/end line range for insert_edit_into_file"
                )
            if start_line > total_lines or end_line >= total_lines:
                raise SystemExit(
                    "startLineNumberBaseZero/endLineNumberBaseZero is out of range "
                    f"for workspace file: {normalized}"
                )
            updated_lines = lines[:start_line] + [new_text] + lines[end_line + 1 :]

        updated = "".join(updated_lines)
        write_utf8_text_file(path, updated)
        return workspace_file_result(
            path,
            normalized,
            updated,
            max_chars_per_file,
            created=False,
            startLineNumberBaseZero=start_line,
            endLineNumberBaseZero=end_line,
            insertAfterLineNumberBaseZero=insert_after_line,
        )

    @staticmethod
    def run_skill_script(
        selected_skill: Any,
        rel_script: str,
        args: list[str],
        workspace: Path,
        timeout_sec: int = 30,
    ) -> dict[str, Any]:
        """スキル同梱の Python スクリプトを実行する。"""
        import os
        import subprocess
        import shutil
        import sys

        from .skill_files import resolve_skill_file_request
        from .utils import truncate_text
        from .workspace import normalize_script_request

        rel_script, args = normalize_script_request(selected_skill, rel_script, args)
        rel_script, script_path, resolved_by_search = resolve_skill_file_request(
            selected_skill,
            rel_script,
            allow_search=True,
            kind="scripts",
        )
        uses_inline_metadata = ActionOperations.script_uses_inline_metadata(script_path)
        if uses_inline_metadata:
            uv_path = shutil.which("uv")
            if not uv_path:
                raise SystemExit(
                    "The script uses PEP 723 inline metadata, but 'uv' is not installed."
                )
            cmd = [uv_path, "run", str(script_path), "--workspace", str(workspace), *args]
        else:
            cmd = [sys.executable, str(script_path), "--workspace", str(workspace), *args]
        completed = subprocess.run(
            cmd,
            cwd=str(workspace),
            env={**os.environ, "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return {
            "cmd": cmd,
            "path": rel_script,
            "resolvedBySearch": resolved_by_search,
            "returncode": completed.returncode,
            "stdout": truncate_text(completed.stdout, 12000),
            "stderr": truncate_text(completed.stderr, 8000),
        }


ACTION_NAMES = ActionCatalog.NAMES
WORKSPACE_ACTION_NAMES = ActionCatalog.WORKSPACE_NAMES

extract_action_args = ActionPayload.extract_args
extract_action_file_path = ActionPayload.extract_file_path
extract_action_directory_path = ActionPayload.extract_directory_path
extract_action_scope = ActionPayload.extract_scope
extract_action_text_field = ActionPayload.extract_text_field
extract_action_text_alias = ActionPayload.extract_text_alias
extract_action_int_field = ActionPayload.extract_int_field
extract_action_bool_field = ActionPayload.extract_bool_field

read_file_for_action = ActionOperations.read_file_for_action
create_file = ActionOperations.create_file
replace_string_in_file = ActionOperations.replace_string_in_file
insert_edit_into_file = ActionOperations.insert_edit_into_file
run_skill_script = ActionOperations.run_skill_script
script_uses_inline_metadata = ActionOperations.script_uses_inline_metadata
