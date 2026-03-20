"""skill 配下のファイル探索とリソース読み込み。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .skills import Skill
from .workspace import (
    build_ambiguous_path_error,
    build_read_file_payload,
    build_search_result,
    is_relative_to,
    iter_searchable_files,
    normalize_hint_path,
    read_utf8_text_file,
)


def classify_skill_file(rel_path: str) -> str:
    """スキル配下ファイルの大まかな種別を返す。"""
    parts = Path(rel_path).parts
    first_part = parts[0].lower() if parts else ""
    if first_part in {"references", "scripts", "assets"}:
        return first_part
    return "resource"


def is_script_path(rel_path: str) -> bool:
    """対象パスが実行可能なスクリプト配置かを判定する。"""
    return (
        classify_skill_file(rel_path) == "scripts"
        and Path(rel_path).suffix.lower() == ".py"
    )


def normalize_skill_path(selected_skill: Skill, rel_path: str) -> str:
    """スキル配下の相対パス表現を正規化する。"""
    path = normalize_hint_path(rel_path)
    if not path:
        return ""
    prefixes = (
        f"skills/{selected_skill.root.name}/",
        f"{selected_skill.root.name}/",
        f"skills/{selected_skill.name}/",
        f"{selected_skill.name}/",
    )
    lowered = path.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            path = path[len(prefix) :]
            break
    path_obj = Path(path)
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
        if is_relative_to(resolved, selected_skill.root):
            path = str(resolved.relative_to(selected_skill.root))
    return path.replace("\\", "/")


def find_skill_files(
    selected_skill: Skill,
    query: str,
    max_entries: int | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """スキル配下のファイルを検索条件付きで探索する。"""
    return build_search_result(
        query,
        "skill",
        max_entries,
        (
            (
                rel_path,
                path,
                {
                    "path": rel_path,
                    "filePath": str(path),
                    "kind": classify_skill_file(rel_path),
                },
            )
            for rel_path, path in iter_searchable_files(
                selected_skill.root,
                selected_skill.root,
            )
            if kind is None
            or (
                is_script_path(rel_path)
                if kind == "scripts"
                else classify_skill_file(rel_path) == kind
            )
        ),
    )


def resolve_skill_file_request(
    selected_skill: Skill,
    rel_path: str,
    allow_search: bool = True,
    kind: str | None = None,
) -> tuple[str, Path, bool]:
    """スキル配下のファイル要求を実ファイルへ解決する。"""
    normalized = normalize_skill_path(selected_skill, rel_path)
    if not normalized:
        if kind == "scripts":
            raise SystemExit("Model requested run_script without a script path")
        raise SystemExit("Model requested read_resource without a path")
    path = (selected_skill.root / normalized).resolve()
    if not is_relative_to(path, selected_skill.root):
        if kind == "scripts":
            raise SystemExit(
                f"Refusing to execute script outside the skill root: {normalized}"
            )
        raise SystemExit(
            f"Refusing to read resource outside the skill root: {normalized}"
        )
    if path.exists() and path.is_file():
        if kind == "scripts" and not is_script_path(normalized):
            raise SystemExit(
                f"Only Python scripts under scripts/ can be executed: {normalized}"
            )
        return normalized, path, False
    if not allow_search:
        if kind == "scripts":
            raise SystemExit(
                f"Requested script does not exist or is not a file: {normalized}"
            )
        raise SystemExit(
            f"Requested resource does not exist or is not a file: {normalized}"
        )
    matches = find_skill_files(
        selected_skill,
        normalized,
        max_entries=6,
        kind=kind,
    )["matches"]
    if len(matches) == 1:
        match = matches[0]
        return str(match["path"]), Path(str(match["filePath"])), True
    if len(matches) > 1:
        raise SystemExit(
            build_ambiguous_path_error(
                "skill path",
                rel_path,
                [str(item["path"]) for item in matches],
            )
        )
    if kind == "scripts":
        raise SystemExit(
            f"Requested script does not exist or is not a file: {normalized}"
        )
    raise SystemExit(
        f"Requested resource does not exist or is not a file: {normalized}"
    )


def read_text_resource(
    path: Path,
    normalized: str,
    scope: str,
    max_chars_per_file: int,
    decode_error: str,
    start_line: int | None = None,
    end_line: int | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """UTF-8 テキストを読み込み、共通の応答形式へ整える。"""
    try:
        text = read_utf8_text_file(path)
    except UnicodeDecodeError as exc:
        raise SystemExit(f"{decode_error}: {normalized}") from exc
    return {
        "scope": scope,
        "filePath": str(path),
        "path": normalized,
        **payload,
        **build_read_file_payload(
            path,
            text,
            max_chars_per_file=max_chars_per_file,
            start_line=start_line,
            end_line=end_line,
        ),
    }


def read_skill_resource(
    selected_skill: Skill,
    rel_path: str,
    max_chars_per_file: int = 8000,
    start_line: int | None = None,
    end_line: int | None = None,
    allow_search: bool = True,
) -> dict[str, Any]:
    """スキル配下のテキストリソースを読み込む。"""
    normalized, path, resolved_by_search = resolve_skill_file_request(
        selected_skill,
        rel_path,
        allow_search=allow_search,
    )
    return read_text_resource(
        path,
        normalized,
        "skill",
        max_chars_per_file,
        "Resource is not readable as UTF-8 text",
        start_line=start_line,
        end_line=end_line,
        kind=classify_skill_file(normalized),
        resolvedBySearch=resolved_by_search,
    )
