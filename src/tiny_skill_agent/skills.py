"""スキル定義、検証、登録、選択に関する処理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .action import ACTION_NAMES, WORKSPACE_ACTION_NAMES

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
STRICT_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(slots=True)
class SkillDiagnostic:
    severity: str
    code: str
    message: str
    violates_spec: bool = False
    blocks_loading: bool = False

    def to_dict(self) -> dict[str, Any]:
        """診断情報をシリアライズしやすい辞書へ変換する。"""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "violates_spec": self.violates_spec,
            "blocks_loading": self.blocks_loading,
        }


@dataclass(slots=True)
class SkillValidationReport:
    skill_root: Path
    skill_md: Path
    skill: "Skill | None" = None
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)

    @property
    def loadable(self) -> bool:
        """読み込み可能な診断状態かを返す。"""
        return self.skill is not None and not any(
            item.blocks_loading for item in self.diagnostics
        )

    @property
    def valid(self) -> bool:
        """仕様違反がないかを返す。"""
        return self.skill is not None and not any(
            item.violates_spec for item in self.diagnostics
        )

    @property
    def warnings(self) -> list[SkillDiagnostic]:
        """警告レベルの診断だけを抽出する。"""
        return [item for item in self.diagnostics if item.severity == "warning"]

    @property
    def errors(self) -> list[SkillDiagnostic]:
        """エラーレベルの診断だけを抽出する。"""
        return [item for item in self.diagnostics if item.severity == "error"]

    def to_dict(self) -> dict[str, Any]:
        """検証レポート全体を辞書へ変換する。"""
        return {
            "skill_root": str(self.skill_root),
            "skill_md": str(self.skill_md),
            "name": self.skill.name if self.skill is not None else "",
            "description": self.skill.description if self.skill is not None else "",
            "loadable": self.loadable,
            "valid": self.valid,
            "warnings": [item.to_dict() for item in self.warnings],
            "errors": [item.to_dict() for item in self.errors],
        }


@dataclass(slots=True)
class Skill:
    root: Path
    name: str
    description: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)

    def validate(self) -> list[SkillDiagnostic]:
        """スキルの frontmatter と基本制約を検証する。"""
        diagnostics: list[SkillDiagnostic] = []
        if len(self.name) > 64:
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "name-too-long",
                    (
                        f"Skill name '{self.name}' exceeds the 64 character limit."
                    ),
                    violates_spec=True,
                )
            )
        if not STRICT_SKILL_NAME_RE.fullmatch(self.name):
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "name-invalid-format",
                    (
                        f"Skill name '{self.name}' must use lowercase letters, "
                        "numbers, and single hyphens only."
                    ),
                    violates_spec=True,
                )
            )
        if self.root.name != self.name:
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "name-directory-mismatch",
                    (
                        f"Skill name '{self.name}' does not match the parent "
                        f"directory '{self.root.name}'."
                    ),
                    violates_spec=True,
                )
            )
        if not self.description.strip():
            diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "description-missing",
                    "Skill description must be non-empty.",
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
        elif len(self.description) > 1024:
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "description-too-long",
                    "Skill description exceeds the 1024 character limit.",
                    violates_spec=True,
                )
            )

        compatibility = self.frontmatter.get("compatibility")
        if compatibility is not None:
            if not isinstance(compatibility, str):
                diagnostics.append(
                    SkillDiagnostic(
                        "warning",
                        "compatibility-invalid-type",
                        "Frontmatter field 'compatibility' must be a string.",
                        violates_spec=True,
                    )
                )
            elif len(compatibility) > 500:
                diagnostics.append(
                    SkillDiagnostic(
                        "warning",
                        "compatibility-too-long",
                        "Frontmatter field 'compatibility' exceeds the 500 character limit.",
                        violates_spec=True,
                    )
                )

        license_value = self.frontmatter.get("license")
        if license_value is not None and not isinstance(license_value, str):
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "license-invalid-type",
                    "Frontmatter field 'license' must be a string.",
                    violates_spec=True,
                )
            )

        metadata = self.frontmatter.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "metadata-invalid-type",
                    "Frontmatter field 'metadata' must be a mapping.",
                    violates_spec=True,
                )
            )

        allowed_tools = self.frontmatter.get("allowed-tools")
        valid_allowed_tools = isinstance(allowed_tools, str) or (
            isinstance(allowed_tools, list)
            and all(isinstance(item, str) for item in allowed_tools)
        )
        if allowed_tools is not None and not valid_allowed_tools:
            diagnostics.append(
                SkillDiagnostic(
                    "warning",
                    "allowed-tools-invalid-type",
                    (
                        "Frontmatter field 'allowed-tools' must be a string "
                        "or a list of strings."
                    ),
                    violates_spec=True,
                )
            )

        return diagnostics

    @classmethod
    def parse_and_validate(cls, root: Path) -> SkillValidationReport:
        """SKILL.md を読み込み、解析結果と検証結果を返す。"""
        skill_md = resolve_skill_md_path(root)
        report = SkillValidationReport(skill_root=skill_md.parent, skill_md=skill_md)

        if not skill_md.exists() or not skill_md.is_file():
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "skill-md-missing",
                    f"SKILL.md was not found at {skill_md}.",
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report

        try:
            raw = skill_md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "skill-md-not-utf8",
                    (
                        f"SKILL.md at {skill_md} is not readable as UTF-8 text."
                    ),
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report

        match = FRONTMATTER_RE.match(raw)
        if not match:
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "frontmatter-missing",
                    (
                        f"SKILL.md in {skill_md.parent} must start with YAML "
                        "frontmatter delimited by --- lines."
                    ),
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report

        frontmatter_text, body = match.groups()
        frontmatter, yaml_error = parse_skill_frontmatter(frontmatter_text)
        if yaml_error is not None:
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "yaml-unparseable",
                    f"Could not parse SKILL.md frontmatter: {yaml_error}",
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report

        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "name-missing",
                    "Skill frontmatter is missing a non-empty 'name'.",
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report
        if not isinstance(description, str) or not description.strip():
            report.diagnostics.append(
                SkillDiagnostic(
                    "error",
                    "description-missing",
                    "Skill frontmatter is missing a non-empty 'description'.",
                    violates_spec=True,
                    blocks_loading=True,
                )
            )
            return report

        skill = cls(
            root=skill_md.parent.resolve(),
            name=name.strip(),
            description=description.strip(),
            body=body.strip(),
            frontmatter=frontmatter,
        )
        skill.diagnostics.extend(report.diagnostics)
        skill.diagnostics.extend(skill.validate())
        report.skill = skill
        report.diagnostics = list(skill.diagnostics)
        return report


class SkillRegistry:
    """利用可能スキルの収集と参照を管理する。"""

    def __init__(self, roots: Iterable[Path]) -> None:
        """複数のスキルルートを走査してレジストリを初期化する。"""
        self.roots = [root.resolve() for root in roots]
        self.skills: dict[str, Skill] = {}
        self.validation_reports: list[SkillValidationReport] = []
        self._scan()

    def _scan(self) -> None:
        """スキル候補を検出し、読み込み可能なものを登録する。"""
        for base in self.roots:
            if not base.exists():
                continue
            for skill_root in iter_skill_roots(base):
                report = Skill.parse_and_validate(skill_root)
                self.validation_reports.append(report)
                if report.loadable and report.skill is not None:
                    self._register_skill(report.skill)

    def _register_skill(self, skill: Skill) -> None:
        """重複名を避けながらスキルを登録する。"""
        if skill.name in self.skills:
            return
        self.skills[skill.name] = skill

    def catalog_text(self) -> str:
        """利用可能スキルの一覧を表示用テキストへ整形する。"""
        if not self.skills:
            return "(no skills found)"
        return "\n".join(
            f"- {skill.name}: {skill.description}"
            for skill in sorted(self.skills.values(), key=lambda item: item.name)
        )

    def get(self, name: str) -> Skill | None:
        """名前に対応するスキルを返す。"""
        return self.skills.get(name)


def resolve_skill_md_path(root: Path) -> Path:
    """スキル指定から対応する SKILL.md のパスを導く。"""
    candidate = root.resolve()
    if candidate.is_file():
        if candidate.name == "SKILL.md":
            return candidate
        return candidate.parent / "SKILL.md"
    return candidate / "SKILL.md"


def iter_skill_roots(base: Path) -> list[Path]:
    """指定パス配下のスキルルート候補を列挙する。"""
    target = base.resolve()
    if target.is_file():
        return [target.parent] if target.name == "SKILL.md" else []
    direct_skill = target / "SKILL.md"
    if direct_skill.is_file():
        return [target]
    return [skill_md.parent for skill_md in sorted(target.glob("*/SKILL.md"))]


def parse_skill_frontmatter(
    frontmatter_text: str,
) -> tuple[dict[str, Any], str | None]:
    """YAML frontmatter を辞書へ変換し、失敗時はエラー文字列を返す。"""
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        return {}, str(exc)
    if not isinstance(frontmatter, dict):
        return {}, "Frontmatter must decode to a mapping."
    return frontmatter, None


def build_task_context_input(task: str) -> str:
    """モデルへ渡すタスク文脈の共通部分を組み立てる。"""
    return "\n".join(
        (
            "User request:",
            task,
            "",
            "Start from the request and available skill metadata only.",
            "Workspace files are not preloaded. Inspect only what you need.",
        )
    )


def build_skill_adherence_block(skills: Iterable[Skill]) -> str:
    """スキル選択用に候補スキル一覧の説明文を生成する。"""
    ordered_skills = sorted(skills, key=lambda skill: skill.name)
    if not ordered_skills:
        return ""
    entries = [
        "Agent Skills are optional task-specific instructions.",
        "If a skill clearly matches the request, activate it before proceeding.",
        "Use only skill names and descriptions for selection.",
        "Activate all relevant skills, otherwise return none.",
        "Available skills:",
    ]
    for skill in ordered_skills:
        entries.extend(["", skill.name, skill.description, ""])
    return "\n".join(entries).strip()


def build_selection_input(task: str, skills: Iterable[Skill]) -> str:
    """スキル選択モデル向けの入力文字列を生成する。"""
    return "\n\n".join(
        filter(None, (build_task_context_input(task), build_skill_adherence_block(skills)))
    )


def normalize_selected_skill_names(selection: dict[str, Any]) -> list[str]:
    """モデル応答から重複のないスキル名一覧を抽出する。"""
    raw_names = selection.get("skills")
    if not isinstance(raw_names, list):
        return []
    names: list[str] = []
    for raw_name in raw_names:
        if isinstance(raw_name, str) and raw_name and raw_name not in names:
            names.append(raw_name)
    return names


def resolve_action_skill(
    skills: list[Skill],
    action_skill_name: str,
    rel_path: str,
) -> Skill:
    """ツールアクションに対応するスキルを確定する。"""
    if action_skill_name:
        matched = next(
            (skill for skill in skills if skill.name == action_skill_name),
            None,
        )
        if matched:
            return matched
        raise SystemExit(
            f"Unknown skill requested for tool action: {action_skill_name}"
        )
    if len(skills) == 1:
        return skills[0]
    normalized_script = rel_path.replace("\\", "/").lstrip("./")
    for skill in skills:
        normalized_root_name = skill.root.name.replace("\\", "/")
        normalized_skill_name = skill.name.replace("\\", "/")
        prefixes = {
            f"{normalized_root_name}/",
            f"skills/{normalized_root_name}/",
            f"{normalized_skill_name}/",
            f"skills/{normalized_skill_name}/",
        }
        if any(normalized_script.startswith(prefix) for prefix in prefixes):
            return skill
    raise SystemExit(
        "Model requested a tool action without specifying which activated "
        "skill owns the path"
    )


def skill_allows_workspace_path(skill: Skill, rel_path: str) -> bool:
    """workspace 配下の相対パスなら常に許可する。"""
    del skill, rel_path
    return True


def ensure_skill_allows_workspace_path(skill: Skill, rel_path: str) -> None:
    """workspace 配下のパスは常に許可する。"""
    del skill, rel_path


def list_allowed_actions_for_skill(skill: Skill, allow_scripts: bool) -> list[str]:
    """スキルに許可されるアクション一覧を返す。"""
    return [
        action
        for action in ACTION_NAMES
        if (allow_scripts or action != "run_script")
        and (action not in WORKSPACE_ACTION_NAMES or skill_allows_workspace_path(skill, "."))
    ]


def ensure_skill_allows_action(
    skill: Skill,
    action_name: str,
    allow_scripts: bool,
) -> None:
    """要求されたアクションが利用可能かを検証する。"""
    if action_name == "run_script" and not allow_scripts:
        raise SystemExit("Bundled skill scripts are disabled by the host runner.")
    if action_name in ACTION_NAMES:
        return
    raise SystemExit(
        f"Skill '{skill.name}' requested unsupported action '{action_name}'."
    )


def find_explicit_skill_mentions(task: str, skills: Iterable[Skill]) -> list[Skill]:
    """タスク文中の明示的なスキル指定を検出する。"""
    lowered = task.lower()
    matches: list[Skill] = []
    for skill in sorted(skills, key=lambda item: item.name):
        name = skill.name.lower()
        tokens = (f"/{name}", f"`{name}`", f'"{name}"', f"'{name}'")
        if any(token in lowered for token in tokens):
            matches.append(skill)
    return matches


def load_skill(root: Path) -> Skill:
    """単一スキルを読み込み、失敗時は例外化する。"""
    report = Skill.parse_and_validate(root)
    if report.loadable and report.skill is not None:
        return report.skill
    errors = [
        item.message
        for item in report.diagnostics
        if item.blocks_loading or item.severity == "error"
    ]
    raise RuntimeError(
        "\n".join(errors) or f"Could not load skill at {resolve_skill_md_path(root)}"
    )


def validate_skill_roots(roots: Iterable[Path]) -> list[SkillValidationReport]:
    """指定されたスキルパス群を検証してレポート化する。"""
    reports: list[SkillValidationReport] = []
    for root in roots:
        candidate = root.resolve()
        if not candidate.exists():
            missing_path = resolve_skill_md_path(candidate)
            reports.append(
                SkillValidationReport(
                    skill_root=missing_path.parent,
                    skill_md=missing_path,
                    diagnostics=[
                        SkillDiagnostic(
                            "error",
                            "path-not-found",
                            f"Path does not exist: {candidate}",
                            violates_spec=True,
                            blocks_loading=True,
                        )
                    ],
                )
            )
            continue

        skill_roots = iter_skill_roots(candidate)
        if not skill_roots:
            missing_path = resolve_skill_md_path(candidate)
            reports.append(
                SkillValidationReport(
                    skill_root=missing_path.parent,
                    skill_md=missing_path,
                    diagnostics=[
                        SkillDiagnostic(
                            "error",
                            "skill-not-found",
                            f"No SKILL.md was found under {candidate}",
                            violates_spec=True,
                            blocks_loading=True,
                        )
                    ],
                )
            )
            continue

        for skill_root in skill_roots:
            reports.append(Skill.parse_and_validate(skill_root))

    seen: dict[str, Path] = {}
    for report in reports:
        if report.skill is None:
            continue
        existing = seen.get(report.skill.name)
        if existing is None:
            seen[report.skill.name] = report.skill.root
            continue
        report.diagnostics.append(
            SkillDiagnostic(
                "warning",
                "duplicate-name",
                (
                    f"Skill name '{report.skill.name}' is duplicated. "
                    f"First seen at {existing}."
                ),
                violates_spec=True,
            )
        )

    return reports


def build_validation_payload(
    reports: Iterable[SkillValidationReport],
) -> dict[str, Any]:
    """検証レポートを CLI 出力向けの辞書へまとめる。"""
    items = list(reports)
    return {
        "ok": bool(items) and all(item.valid for item in items),
        "reports": [item.to_dict() for item in items],
    }


def summarize_blocking_skill_errors(
    reports: Iterable[SkillValidationReport],
    max_items: int = 5,
) -> str:
    """読み込みを妨げる主要なエラーを短く要約する。"""
    messages: list[str] = []
    for report in reports:
        blocking = [
            item.message
            for item in report.diagnostics
            if item.blocks_loading or item.severity == "error"
        ]
        if not blocking:
            continue
        messages.append(f"- {report.skill_md}: {blocking[0]}")
        if len(messages) >= max_items:
            break
    return "\n".join(messages)
