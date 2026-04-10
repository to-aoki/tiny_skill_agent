"""ファイル探索、読み書き、スクリプト実行などのアクション処理。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Iterable

from .image_inputs import load_input_image
from .skills import (
    Skill,
    ensure_skill_allows_workspace_path,
    skill_allows_workspace_path,
)
from .utils import truncate_text


def iter_searchable_files(
    root: Path,
    relative_to: Path,
    include_skill_md: bool = False,
) -> Iterable[tuple[str, Path]]:
    """検索対象にできるファイルを相対パス付きで列挙する。"""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(relative_to)
        if should_skip(rel.parts) or path.suffix.lower() == ".pyc":
            continue
        if not include_skill_md and rel.name == "SKILL.md":
            continue
        yield str(rel).replace("\\", "/"), path


def normalize_search_limit(
    max_entries: int | None,
    default: int = 20,
    maximum: int = 100,
) -> int:
    """検索件数上限を安全な範囲へ丸める。"""
    return default if max_entries is None else max(1, min(max_entries, maximum))


def score_path_match(candidate: str, query: str) -> tuple[int, int, str] | None:
    """検索クエリに対するパス候補の一致度を評価する。"""
    normalized_query = normalize_hint_path(query).lower()
    if not normalized_query:
        return None
    candidate_normalized = candidate.replace("\\", "/")
    candidate_lower = candidate_normalized.lower()
    query_name = Path(normalized_query).name
    candidate_name = Path(candidate_lower).name

    if candidate_lower == normalized_query:
        return (0, len(candidate_normalized), candidate_lower)
    if candidate_name == query_name:
        return (1, len(candidate_normalized), candidate_lower)
    if candidate_lower.endswith(f"/{normalized_query}") or candidate_lower.endswith(
        normalized_query
    ):
        return (2, len(candidate_normalized), candidate_lower)
    if query_name and candidate_name.startswith(query_name):
        return (3, len(candidate_normalized), candidate_lower)
    if query_name and query_name in candidate_name:
        return (4, len(candidate_normalized), candidate_lower)
    if normalized_query in candidate_lower:
        return (5, len(candidate_normalized), candidate_lower)
    return None


def build_search_result(
    query: str,
    scope: str,
    max_entries: int | None,
    candidates: Iterable[tuple[str, Path, dict[str, Any]]],
) -> dict[str, Any]:
    """候補集合から検索結果ペイロードを構築する。"""
    normalized_query = normalize_hint_path(query)
    if not normalized_query:
        raise SystemExit("Model requested find_file without a query")
    limit = normalize_search_limit(max_entries)
    ranked = sorted(
        (
            (score, payload)
            for rel_path, _, payload in candidates
            if (score := score_path_match(rel_path, normalized_query)) is not None
        ),
        key=lambda item: item[0],
    )
    return {
        "scope": scope,
        "query": normalized_query,
        "matchCount": min(len(ranked), limit),
        "truncated": len(ranked) > limit,
        "matches": [item[1] for item in ranked[:limit]],
    }


def find_workspace_files(
    workspace: Path,
    selected_skill: Skill,
    query: str,
    max_entries: int | None = None,
) -> dict[str, Any]:
    """workspace 配下の workspace ファイルを探索する。"""
    ensure_skill_allows_workspace_path(selected_skill, ".")
    return build_search_result(
        query,
        "workspace",
        max_entries,
        (
            (rel_path, path, {"path": rel_path, "filePath": str(path)})
            for rel_path, path in iter_searchable_files(
                workspace,
                workspace,
                include_skill_md=True,
            )
            if skill_allows_workspace_path(selected_skill, rel_path)
        ),
    )


def build_ambiguous_path_error(
    scope_label: str,
    query: str,
    matches: Iterable[str],
) -> str:
    """曖昧なパス指定に対する説明メッセージを作る。"""
    items = list(matches)
    preview = ", ".join(items[:5])
    suffix = "" if len(items) <= 5 else f" (+{len(items) - 5} more)"
    normalized_query = normalize_hint_path(query) or query
    return (
        f"Requested {scope_label} is ambiguous for '{normalized_query}'. "
        f"Matches: {preview}{suffix}. Provide a more specific path."
    )


def resolve_workspace_file_request(
    workspace: Path,
    selected_skill: Skill,
    rel_path: str,
    allow_search: bool = True,
) -> tuple[str, Path, bool]:
    """workspace 内のファイル要求を実ファイルへ解決する。"""
    normalized, path = normalize_workspace_path(workspace, rel_path)
    if path.exists() and path.is_file():
        ensure_skill_allows_workspace_path(selected_skill, normalized)
        return normalized, path, False
    if not allow_search:
        ensure_skill_allows_workspace_path(selected_skill, normalized)
        raise SystemExit(
            f"Requested workspace file does not exist or is not a file: {normalized}"
        )
    matches = find_workspace_files(
        workspace,
        selected_skill,
        normalized,
        max_entries=6,
    )["matches"]
    if len(matches) == 1:
        match = matches[0]
        return str(match["path"]), Path(str(match["filePath"])), True
    if len(matches) > 1:
        raise SystemExit(
            build_ambiguous_path_error(
                "workspace path",
                rel_path,
                [str(item["path"]) for item in matches],
            )
        )
    if "/" in normalized or "\\" in normalized:
        ensure_skill_allows_workspace_path(selected_skill, normalized)
    raise SystemExit(
        f"Requested workspace file does not exist or is not a file: {normalized}"
    )


def read_workspace_file(
    workspace: Path,
    rel_path: str,
    selected_skill: Skill | None = None,
    max_chars_per_file: int = 16000,
    start_line: int | None = None,
    end_line: int | None = None,
    allow_search: bool = True,
) -> dict[str, Any]:
    """workspace のテキストまたは画像ファイルを読み込む。"""
    from .skill_files import read_text_resource

    if selected_skill is None:
        normalized, path = normalize_workspace_path(workspace, rel_path)
        resolved_by_search = False
        if not path.exists() or not path.is_file():
            raise SystemExit(
                f"Requested workspace file does not exist or is not a file: {normalized}"
            )
    else:
        normalized, path, resolved_by_search = resolve_workspace_file_request(
            workspace,
            selected_skill,
            rel_path,
            allow_search=allow_search,
        )
    try:
        input_image = load_input_image(path, display_path=normalized)
    except SystemExit:
        input_image = None
    if input_image is not None:
        return {
            "scope": "workspace",
            "filePath": str(path),
            "path": normalized,
            "size_bytes": path.stat().st_size,
            "resolvedBySearch": resolved_by_search,
            "contentKind": "image",
            "mime_type": input_image.mime_type,
            "content": f"[image file: {normalized}]",
            "_input_image": input_image,
        }
    return read_text_resource(
        path,
        normalized,
        "workspace",
        max_chars_per_file,
        "Workspace file is not readable as UTF-8 text",
        start_line=start_line,
        end_line=end_line,
        resolvedBySearch=resolved_by_search,
    )


def list_workspace_directory(
    workspace: Path,
    rel_path: str = "",
    recursive: bool = False,
    max_depth: int | None = None,
    max_entries: int | None = None,
) -> dict[str, Any]:
    """workspace ディレクトリの内容を制限付きで列挙する。"""
    normalized, path = normalize_workspace_path(
        workspace,
        rel_path,
        kind="directory",
        default=".",
    )
    if not path.exists() or not path.is_dir():
        raise SystemExit(
            f"Requested workspace directory does not exist or is not a directory: "
            f"{normalized}"
        )
    entry_limit = 80 if max_entries is None else max(1, min(max_entries, 500))
    depth_limit = 2 if max_depth is None else max(0, min(max_depth, 10))
    entries: list[str] = []
    truncated = False
    root_depth = len(path.relative_to(workspace).parts)
    for candidate in sorted(path.rglob("*") if recursive else path.iterdir()):
        rel = candidate.relative_to(workspace)
        if should_skip(rel.parts):
            continue
        current_depth = len(rel.parts) - root_depth
        if recursive and current_depth > depth_limit:
            continue
        suffix = "/" if candidate.is_dir() else ""
        entries.append(str(rel).replace("\\", "/") + suffix)
        if len(entries) >= entry_limit:
            truncated = True
            break
    return {
        "scope": "workspace",
        "path": normalized,
        "directoryPath": str(path),
        "recursive": recursive,
        "maxDepth": depth_limit if recursive else 0,
        "maxEntries": entry_limit,
        "entryCount": len(entries),
        "truncated": truncated,
        "entries": entries,
    }


def workspace_file_result(
    path: Path,
    normalized: str,
    content: str,
    max_chars_per_file: int = 16000,
    **payload: Any,
) -> dict[str, Any]:
    """workspace ファイル操作結果を共通形式へ整える。"""
    return {
        "scope": "workspace",
        "filePath": str(path),
        "path": normalized,
        "size_bytes": path.stat().st_size,
        "truncated": len(content) > max_chars_per_file,
        "content": truncate_text(content, max_chars_per_file),
        **payload,
    }


def read_existing_workspace_text(
    workspace: Path,
    rel_path: str,
) -> tuple[str, Path, str]:
    """既存の workspace テキストファイルを厳密に読み込む。"""
    normalized, path = normalize_workspace_path(workspace, rel_path)
    if not path.exists() or not path.is_file():
        raise SystemExit(
            f"Requested workspace file does not exist or is not a file: {normalized}"
        )
    try:
        return normalized, path, read_utf8_text_file(path)
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"Workspace file is not readable as UTF-8 text: {normalized}"
        ) from exc


def write_workspace_file(
    workspace: Path,
    rel_path: str,
    content: str,
    max_chars_per_file: int = 16000,
) -> dict[str, Any]:
    """workspace のテキストファイルを書き込み、結果を返す。"""
    normalized, path = normalize_workspace_path(workspace, rel_path)
    if path.exists() and path.is_dir():
        raise SystemExit(
            f"Requested workspace path is a directory, not a file: {normalized}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    write_utf8_text_file(path, content)
    return workspace_file_result(
        path,
        normalized,
        content,
        max_chars_per_file,
        created=not existed,
    )


def edit_workspace_file(
    workspace: Path,
    rel_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    max_chars_per_file: int = 16000,
) -> dict[str, Any]:
    """workspace の既存テキストに対して文字列置換を行う。"""
    if not old_text:
        raise SystemExit("Model requested edit_workspace_file without old_text")
    normalized, path, text = read_existing_workspace_text(workspace, rel_path)
    match_count = text.count(old_text)
    if match_count == 0:
        raise SystemExit(f"Could not find old_text in workspace file: {normalized}")
    if match_count > 1 and not replace_all:
        raise SystemExit(
            f"old_text matched {match_count} times in workspace file: {normalized}. "
            "Use replace_all=true or provide a more specific snippet."
        )
    updated = text.replace(old_text, new_text, -1 if replace_all else 1)
    write_utf8_text_file(path, updated)
    return workspace_file_result(
        path,
        normalized,
        updated,
        max_chars_per_file,
        created=False,
        replacements=match_count if replace_all else 1,
    )


def read_file_for_action(
    workspace: Path,
    selected_skill: Skill,
    file_path: str,
    action_scope: str = "",
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """アクション指定に応じて skill または workspace を読む。"""
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


def create_file(
    workspace: Path,
    rel_path: str,
    content: str,
    max_chars_per_file: int = 16000,
) -> dict[str, Any]:
    """workspace に新しいテキストファイルを作成する。"""
    normalized, path = normalize_workspace_path(workspace, rel_path)
    if path.exists():
        raise SystemExit(f"Refusing to create a file that already exists: {normalized}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_text_file(path, content)
    return workspace_file_result(
        path,
        normalized,
        content,
        max_chars_per_file,
        created=True,
    )


def replace_string_in_file(
    workspace: Path,
    rel_path: str,
    string_to_replace: str,
    replacement_string: str,
    replace_all: bool = False,
    max_chars_per_file: int = 16000,
) -> dict[str, Any]:
    """workspace ファイル内の文字列を置換する。"""
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
            raise SystemExit("Invalid start/end line range for insert_edit_into_file")
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


def run_skill_script(
    selected_skill: Skill,
    rel_script: str,
    args: list[str],
    workspace: Path,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    """スキル同梱の Python スクリプトを実行する。"""
    rel_script, args = normalize_script_request(selected_skill, rel_script, args)
    rel_script, script_path, resolved_by_search = resolve_skill_file_request(
        selected_skill,
        rel_script,
        allow_search=True,
        kind="scripts",
    )
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


def extract_action_args(action: dict[str, Any]) -> list[str]:
    """アクション辞書から引数配列を取り出す。"""
    raw_args = action.get("args")
    if raw_args is None or raw_args == "":
        return []
    if isinstance(raw_args, list):
        return [str(item) for item in raw_args]
    return [str(raw_args)]


def infer_run_script_path(
    skill: Skill,
    action_path: str,
    args: list[str],
) -> tuple[str, list[str]]:
    """run_script 用のスクリプトパス候補を推定する。"""
    from .skill_files import find_skill_files, is_script_path, normalize_skill_path

    if action_path.strip():
        return action_path, args
    if args:
        offset = 1 if looks_like_python_invocation(args[0]) else 0
        if len(args) > offset:
            candidate = normalize_skill_path(skill, args[offset])
            if candidate and is_script_path(candidate):
                return candidate, args[:offset] + args[offset + 1 :]
    available_scripts = find_skill_files(
        skill,
        "scripts/",
        max_entries=2,
        kind="scripts",
    )["matches"]
    if len(available_scripts) == 1:
        return str(available_scripts[0]["path"]), args
    return action_path, args


def normalize_script_request(
    selected_skill: Skill,
    rel_script: str,
    args: list[str],
) -> tuple[str, list[str]]:
    """スクリプト実行要求を実行しやすい形へ正規化する。"""
    from .skill_files import normalize_skill_path

    text = rel_script.strip()
    if not text:
        return text, args
    tokens = shlex.split(text, posix=False)
    if tokens and looks_like_python_invocation(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return "", args
    script = normalize_skill_path(selected_skill, tokens[0])
    extra_args = tokens[1:]
    return script, args or extra_args


def normalize_hint_path(value: str) -> str:
    """検索や解決に使うヒントパスを正規化する。"""
    path = value.strip().strip("`'\"()[]{}.,:;").replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    return path


def extract_action_file_path(action: dict[str, Any]) -> str:
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


def extract_action_directory_path(action: dict[str, Any]) -> str:
    """アクション辞書からディレクトリパス候補を抽出する。"""
    directory_path = action.get("directoryPath")
    if isinstance(directory_path, str) and directory_path.strip():
        return directory_path
    file_path = action.get("path")
    if isinstance(file_path, str):
        return file_path
    return ""


def extract_action_scope(action: dict[str, Any]) -> str:
    """アクション辞書から読み込みスコープ指定を抽出する。"""
    value = action.get("scope")
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    return normalized if normalized in {"workspace", "skill"} else ""


def extract_action_text_field(action: dict[str, Any], field_name: str) -> str:
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


def extract_action_text_alias(
    action: dict[str, Any],
    field_names: tuple[str, ...],
) -> str:
    """複数候補名から最初に見つかった文字列フィールドを返す。"""
    for field_name in field_names:
        if field_name in action:
            return extract_action_text_field(action, field_name)
    joined = ", ".join(field_names)
    action_name = str(action.get("action") or "tool action")
    raise SystemExit(f"Model requested {action_name} without any of: {joined}")


def extract_action_int_field(
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


def extract_action_bool_field(
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


def looks_like_python_invocation(token: str) -> bool:
    """トークンが Python 実行コマンドらしいか判定する。"""
    normalized = Path(token).name.lower()
    return normalized in {"python", "python.exe", "py", "py.exe"}


def normalize_workspace_path(
    workspace: Path,
    rel_path: str,
    kind: str = "file",
    default: str = "",
) -> tuple[str, Path]:
    """workspace 内に限定した安全な相対パスへ正規化する。"""
    path = normalize_hint_path(rel_path) or default
    if not path:
        raise SystemExit(f"Model requested a workspace {kind} action without a path")
    path_obj = Path(path)
    resolved = (
        path_obj.resolve()
        if path_obj.is_absolute()
        else (workspace / path_obj).resolve()
    )
    if not is_relative_to(resolved, workspace):
        raise SystemExit(f"Refusing to access {kind} outside the workspace: {path}")
    normalized = "." if resolved == workspace else str(
        resolved.relative_to(workspace)
    ).replace("\\", "/")
    return normalized, resolved


def read_utf8_text_file(path: Path) -> str:
    """UTF-8 テキストファイルを改行維持で読み込む。"""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_utf8_text_file(path: Path, content: str) -> None:
    """UTF-8 テキストファイルを改行維持で書き込む。"""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def build_read_file_payload(
    path: Path,
    text: str,
    max_chars_per_file: int,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """read_file 応答用の本文と行情報を構築する。"""
    line_payload = slice_text_by_lines(
        text,
        start_line=start_line,
        end_line=end_line,
    )
    selected = line_payload["content"]
    return {
        "size_bytes": path.stat().st_size,
        "truncated": len(selected) > max_chars_per_file,
        "content": truncate_text(selected, max_chars_per_file),
        "totalLineCount": line_payload["totalLineCount"],
        "startLineNumberBaseZero": line_payload["startLineNumberBaseZero"],
        "endLineNumberBaseZero": line_payload["endLineNumberBaseZero"],
        "returnedLineCount": line_payload["returnedLineCount"],
    }


def slice_text_by_lines(
    text: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """テキストを行番号ベースで切り出して返す。"""
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    if start_line is None and end_line is None:
        return {
            "content": text,
            "totalLineCount": total_lines,
            "startLineNumberBaseZero": 0 if total_lines else None,
            "endLineNumberBaseZero": total_lines - 1 if total_lines else None,
            "returnedLineCount": total_lines,
        }
    start = 0 if start_line is None else start_line
    end = total_lines - 1 if end_line is None else end_line
    if start < 0 or end < start:
        raise SystemExit("Invalid start/end line range for read_file")
    if total_lines == 0:
        if start == 0 and end in {0, -1}:
            return {
                "content": "",
                "totalLineCount": 0,
                "startLineNumberBaseZero": None,
                "endLineNumberBaseZero": None,
                "returnedLineCount": 0,
            }
        raise SystemExit("read_file line range is out of range for an empty file")
    if end >= total_lines:
        raise SystemExit(
            "read_file line range is out of range: "
            f"start={start}, end={end}, total_lines={total_lines}"
        )
    selected_lines = lines[start : end + 1]
    return {
        "content": "".join(selected_lines),
        "totalLineCount": total_lines,
        "startLineNumberBaseZero": start,
        "endLineNumberBaseZero": end,
        "returnedLineCount": len(selected_lines),
    }


def should_skip(parts: tuple[str, ...]) -> bool:
    """探索対象から除外すべきディレクトリか判定する。"""
    skip_names = {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "build",
        "target",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
    }
    return any(part in skip_names for part in parts)


def is_relative_to(path: Path, root: Path) -> bool:
    """パスが指定ルート配下に収まるかを返す。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
