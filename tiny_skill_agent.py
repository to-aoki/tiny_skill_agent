#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:
    yaml = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

SYSTEM_SELECTOR_PROMPT = """You are a skill selector for a coding agent.
Your job is to decide which installed Agent Skills should be activated for the user's task.

Rules:
- Use the skill adherence block in the user message as the primary policy.
- Select every skill whose description materially overlaps with the task.
- Prefer none if the task is generic and does not need specialized workflow knowledge.
- Use an empty list when no skill applies.
- Do not invent skills.
- Return strict JSON only.

Schema:
{
  \"skills\": [\"skill-name-1\", \"skill-name-2\"],
  \"reason\": \"brief explanation\"
}
"""

SYSTEM_ACTOR_PROMPT = """You are a local coding agent that can use activated Agent Skills.
Follow the loaded skill instructions carefully.
Keep working until the user's task is complete or you cannot make further progress.

Only the selected SKILL.md instructions are injected up front.
Bundled skill resources are available on demand and should be read only when they are relevant.

You may either:
1. respond directly when the task is complete or blocked,
2. request one bundled resource read for the current turn if you need to inspect a referenced file, or
3. request one bundled script execution for the current turn if it would materially improve the answer.

You may request multiple resource reads and script executions across multiple turns.
Do not stop early just because one resource has been read or one script has finished.

Return strict JSON only.

Schema:
{
  \"action\": \"respond\" | \"read_resource\" | \"run_script\",
  \"message\": \"final answer when action=respond; otherwise short status or empty string\",
  \"skill\": \"skill-name when action=read_resource/run_script, otherwise null or empty string\",
  \"path\": \"relative/path/from/the-named-skill/root when action=read_resource/run_script\",
  \"args\": [\"arg1\", \"arg2\"],
  \"reason\": \"why this action helps\"
}
"""

SYSTEM_FINALIZER_PROMPT = """You are a local coding agent. Produce the final answer for the user.
Use the loaded skill instructions, any resource contents that were read, action history, and any script output.
Be concrete and concise.
If the session ended because a safety limit was reached, say what remains uncertain.
"""

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
STRICT_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
YAML_COLON_VALUE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+):(?P<space>\s+)(?P<value>.+)$")
SKILL_PATH_HINT_RE = re.compile(r"(?P<path>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)")
THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

@dataclass(slots=True)
class SkillDiagnostic:
    severity: str
    code: str
    message: str
    violates_spec: bool = False
    blocks_loading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            'severity': self.severity,
            'code': self.code,
            'message': self.message,
            'violates_spec': self.violates_spec,
            'blocks_loading': self.blocks_loading,
        }

@dataclass(slots=True)
class SkillValidationReport:
    skill_root: Path
    skill_md: Path
    skill: 'Skill | None' = None
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)

    @property
    def loadable(self) -> bool:
        return self.skill is not None and not any(item.blocks_loading for item in self.diagnostics)

    @property
    def valid(self) -> bool:
        return self.skill is not None and not any(item.violates_spec for item in self.diagnostics)

    @property
    def warnings(self) -> list[SkillDiagnostic]:
        return [item for item in self.diagnostics if item.severity == 'warning']

    @property
    def errors(self) -> list[SkillDiagnostic]:
        return [item for item in self.diagnostics if item.severity == 'error']

    def to_dict(self) -> dict[str, Any]:
        return {
            'skill_root': str(self.skill_root),
            'skill_md': str(self.skill_md),
            'name': self.skill.name if self.skill is not None else '',
            'description': self.skill.description if self.skill is not None else '',
            'loadable': self.loadable,
            'valid': self.valid,
            'warnings': [item.to_dict() for item in self.warnings],
            'errors': [item.to_dict() for item in self.errors],
        }

@dataclass(slots=True)
class Skill:
    root: Path
    name: str
    description: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)

    @property
    def location(self) -> Path:
        return self.root / 'SKILL.md'

    def validate(self) -> list[SkillDiagnostic]:
        diagnostics: list[SkillDiagnostic] = []
        if len(self.name) > 64:
            diagnostics.append(SkillDiagnostic('warning', 'name-too-long', f"Skill name '{self.name}' exceeds the 64 character limit.", violates_spec=True))
        if not STRICT_SKILL_NAME_RE.fullmatch(self.name):
            diagnostics.append(SkillDiagnostic('warning', 'name-invalid-format', f"Skill name '{self.name}' must use lowercase letters, numbers, and single hyphens only.", violates_spec=True))
        if self.root.name != self.name:
            diagnostics.append(SkillDiagnostic('warning', 'name-directory-mismatch', f"Skill name '{self.name}' does not match the parent directory '{self.root.name}'.", violates_spec=True))
        if not self.description.strip():
            diagnostics.append(SkillDiagnostic('error', 'description-missing', 'Skill description must be non-empty.', violates_spec=True, blocks_loading=True))
        elif len(self.description) > 1024:
            diagnostics.append(SkillDiagnostic('warning', 'description-too-long', 'Skill description exceeds the 1024 character limit.', violates_spec=True))

        compatibility = self.frontmatter.get('compatibility')
        if compatibility is not None:
            if not isinstance(compatibility, str):
                diagnostics.append(SkillDiagnostic('warning', 'compatibility-invalid-type', "Frontmatter field 'compatibility' must be a string.", violates_spec=True))
            elif len(compatibility) > 500:
                diagnostics.append(SkillDiagnostic('warning', 'compatibility-too-long', "Frontmatter field 'compatibility' exceeds the 500 character limit.", violates_spec=True))

        license_value = self.frontmatter.get('license')
        if license_value is not None and not isinstance(license_value, str):
            diagnostics.append(SkillDiagnostic('warning', 'license-invalid-type', "Frontmatter field 'license' must be a string.", violates_spec=True))

        metadata = self.frontmatter.get('metadata')
        if metadata is not None and not isinstance(metadata, dict):
            diagnostics.append(SkillDiagnostic('warning', 'metadata-invalid-type', "Frontmatter field 'metadata' must be a mapping.", violates_spec=True))

        allowed_tools = self.frontmatter.get('allowed-tools')
        if allowed_tools is not None and not (
            isinstance(allowed_tools, str) or
            (isinstance(allowed_tools, list) and all(isinstance(item, str) for item in allowed_tools))
        ):
            diagnostics.append(SkillDiagnostic('warning', 'allowed-tools-invalid-type', "Frontmatter field 'allowed-tools' must be a string or a list of strings.", violates_spec=True))

        return diagnostics

    @classmethod
    def parse_and_validate(cls, root: Path) -> SkillValidationReport:
        skill_md = resolve_skill_md_path(root)
        report = SkillValidationReport(skill_root=skill_md.parent, skill_md=skill_md)

        if not skill_md.exists() or not skill_md.is_file():
            report.diagnostics.append(SkillDiagnostic('error', 'skill-md-missing', f'SKILL.md was not found at {skill_md}.', violates_spec=True, blocks_loading=True))
            return report

        try:
            raw = skill_md.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            report.diagnostics.append(SkillDiagnostic('error', 'skill-md-not-utf8', f'SKILL.md at {skill_md} is not readable as UTF-8 text.', violates_spec=True, blocks_loading=True))
            return report

        match = FRONTMATTER_RE.match(raw)
        if not match:
            report.diagnostics.append(SkillDiagnostic('error', 'frontmatter-missing', f'SKILL.md in {skill_md.parent} must start with YAML frontmatter delimited by --- lines.', violates_spec=True, blocks_loading=True))
            return report

        if yaml is None:
            report.diagnostics.append(SkillDiagnostic('error', 'pyyaml-missing', 'pyyaml is required to parse SKILL.md frontmatter.', violates_spec=True, blocks_loading=True))
            return report

        frontmatter_text, body = match.groups()
        frontmatter, used_fallback, yaml_error = parse_skill_frontmatter(frontmatter_text)
        if yaml_error is not None:
            report.diagnostics.append(SkillDiagnostic('error', 'yaml-unparseable', f'Could not parse SKILL.md frontmatter: {yaml_error}', violates_spec=True, blocks_loading=True))
            return report
        if used_fallback:
            report.diagnostics.append(SkillDiagnostic('warning', 'yaml-fallback-used', 'Applied a compatibility fallback to parse YAML values containing colons.'))

        name = frontmatter.get('name')
        description = frontmatter.get('description')
        if not isinstance(name, str) or not name.strip():
            report.diagnostics.append(SkillDiagnostic('error', 'name-missing', "Skill frontmatter is missing a non-empty 'name'.", violates_spec=True, blocks_loading=True))
            return report
        if not isinstance(description, str) or not description.strip():
            report.diagnostics.append(SkillDiagnostic('error', 'description-missing', "Skill frontmatter is missing a non-empty 'description'.", violates_spec=True, blocks_loading=True))
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

class SkillParseError(RuntimeError):
    pass

def resolve_skill_md_path(root: Path) -> Path:
    candidate = root.resolve()
    if candidate.is_file():
        return candidate if candidate.name == 'SKILL.md' else candidate.parent / 'SKILL.md'
    return candidate / 'SKILL.md'

def iter_skill_roots(base: Path) -> list[Path]:
    target = base.resolve()
    if target.is_file():
        return [target.parent] if target.name == 'SKILL.md' else []
    direct_skill = target / 'SKILL.md'
    if direct_skill.is_file():
        return [target]
    return [skill_md.parent for skill_md in sorted(target.glob('*/SKILL.md'))]

def parse_skill_frontmatter(frontmatter_text: str) -> tuple[dict[str, Any], bool, str | None]:
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(frontmatter, dict):
            return {}, False, 'Frontmatter must decode to a mapping.'
        return frontmatter, False, None
    except yaml.YAMLError as exc:
        repaired = repair_colon_values_in_yaml(frontmatter_text)
        if repaired == frontmatter_text:
            return {}, False, str(exc)
        try:
            frontmatter = yaml.safe_load(repaired) or {}
        except yaml.YAMLError as fallback_exc:
            return {}, True, str(fallback_exc)
        if not isinstance(frontmatter, dict):
            return {}, True, 'Frontmatter must decode to a mapping.'
        return frontmatter, True, None

def repair_colon_values_in_yaml(frontmatter_text: str) -> str:
    repaired_lines: list[str] = []
    changed = False
    for line in frontmatter_text.splitlines():
        match = YAML_COLON_VALUE_RE.match(line)
        if not match:
            repaired_lines.append(line)
            continue
        value = match.group('value').strip()
        if ':' not in value or value.startswith(('"', "'", '|', '>', '[', '{')):
            repaired_lines.append(line)
            continue
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        repaired_lines.append(f"{match.group('indent')}{match.group('key')}:{match.group('space')}\"{escaped}\"")
        changed = True
    return '\n'.join(repaired_lines) if changed else frontmatter_text

class SkillRegistry:
    def __init__(self, roots: Iterable[Path]) -> None:
        self.roots = [r.resolve() for r in roots]
        self.skills: dict[str, Skill] = {}
        self.validation_reports: list[SkillValidationReport] = []
        self._scan()

    def _scan(self) -> None:
        for base in self.roots:
            if not base.exists():
                continue
            for skill_root in iter_skill_roots(base):
                report = Skill.parse_and_validate(skill_root)
                self.validation_reports.append(report)
                if report.loadable and report.skill is not None:
                    self._register_skill(report.skill)

    def _register_skill(self, skill: Skill) -> None:
        existing = self.skills.get(skill.name)
        if existing is not None:
            return
        self.skills[skill.name] = skill

    def catalog_text(self) -> str:
        if not self.skills:
            return '(no skills found)'
        return '\n'.join(f"- {s.name}: {s.description}" for s in sorted(self.skills.values(), key=lambda s: s.name))

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

def build_task_context_input(task: str, workspace_snapshot: dict[str, Any]) -> str:
    sections = [
        'User task:',
        task,
        '',
        'Workspace snapshot:',
        json.dumps(workspace_snapshot, ensure_ascii=False, indent=2),
    ]
    return '\n'.join(sections)

def build_skill_adherence_block(skills: Iterable[Skill]) -> str:
    ordered_skills = sorted(skills, key=lambda s: s.name)
    if not ordered_skills:
        return ''
    entries = [
        'Skills provide specialized capabilities, domain knowledge, and workflows that can enhance your ability to perform specific tasks. Skills enable deeper expertise and more efficient task execution.',
        'Each skill is a folder containing a SKILL.md file, and optionally other resources. These resources may include scripts, templates, or additional content to support the skill.',
        'BLOCKING REQUIREMENT: If the user\'s request matches any available skill, you MUST read and use it by activating that skill so the host can load the linked SKILL.md file.',
        'This requirement is NOT optional for matching tasks. It is a mandatory part of fulfilling the user\'s request accurately and completely.',
        'NEVER respond without using a matching skill. Never answer from general knowledge when a relevant skill exists.',
        'Prefer using skills whenever there is even moderate uncertainty. When a skill matches, activate it and then follow the instructions in that file.',
        'Only the SKILL.md instructions are injected immediately. Any bundled resources can be read later on demand after the skill is activated.',
        'How to determine if a skill applies:',
        '1. Review the available skills and their descriptions',
        '2. Determine if the user\'s task falls within any skill\'s domain',
        '3. If yes, activate that skill so its SKILL.md file is loaded before proceeding',
        '4. If multiple skills apply, activate all relevant skills',
        'Examples:',
        '- "Help me write unit tests for this module" -> Activate the testing skill FIRST, then proceed',
        '- "Optimize this slow function" -> Activate the performance-profiling skill FIRST, then proceed',
        '- "Add a discount code field to checkout" -> Activate both the checkout-flow and form-validation skills FIRST',
        'Available skills:',
    ]
    for skill in ordered_skills:
        entries.extend(['', skill.name, skill.description, str(skill.root / 'SKILL.md'), ''])
    return '\n'.join(entries).strip()

def build_selection_input(task: str, workspace_snapshot: dict[str, Any], skills: Iterable[Skill]) -> str:
    sections = [build_task_context_input(task, workspace_snapshot)]
    skill_block = build_skill_adherence_block(skills)
    if skill_block:
        sections.append(skill_block)
    return '\n\n'.join(section for section in sections if section)

def normalize_selected_skill_names(selection: dict[str, Any]) -> list[str]:
    raw_names = selection.get('skills')
    names: list[str] = []
    if isinstance(raw_names, list):
        for raw_name in raw_names:
            if isinstance(raw_name, str) and raw_name and raw_name not in names:
                names.append(raw_name)
    elif selection.get('use_skill') and isinstance(selection.get('skill'), str):
        name = str(selection['skill'])
        if name:
            names.append(name)
    return names

def resolve_action_skill(skills: list[Skill], action_skill_name: str, rel_path: str) -> Skill:
    if action_skill_name:
        matched = next((skill for skill in skills if skill.name == action_skill_name), None)
        if matched:
            return matched
        raise SystemExit(f'Unknown skill requested for tool action: {action_skill_name}')
    if len(skills) == 1:
        return skills[0]
    normalized_script = rel_path.replace('\\', '/').lstrip('./')
    for skill in skills:
        prefixes = {
            f'{skill.root.name.replace("\\", "/")}/',
            f'skills/{skill.root.name.replace("\\", "/")}/',
            f'{skill.name.replace("\\", "/")}/',
            f'skills/{skill.name.replace("\\", "/")}/',
        }
        if any(normalized_script.startswith(prefix) for prefix in prefixes):
            return skill
    raise SystemExit('Model requested a tool action without specifying which activated skill owns the path')

class SkillAgent:
    def __init__(self, client: OpenAI, model: str, registry: SkillRegistry, workspace: Path, allow_scripts: bool = False, max_skill_turns: int = 8) -> None:
        self.client = client
        self.model = model
        self.registry = registry
        self.workspace = workspace.resolve()
        self.allow_scripts = allow_scripts
        self.max_skill_turns = max(1, max_skill_turns)

    def run(self, task: str) -> dict[str, Any]:
        workspace_snapshot = build_workspace_snapshot(self.workspace)
        available_skills = sorted(self.registry.skills.values(), key=lambda x: x.name)
        explicitly_requested = find_explicit_skill_mentions(task, available_skills)
        auto_selectable_skills = [skill for skill in available_skills if not bool(skill.frontmatter.get('disable-model-invocation'))]
        selector_input = build_selection_input(task, workspace_snapshot, auto_selectable_skills)
        selection = self._json_chat(SYSTEM_SELECTOR_PROMPT, selector_input)
        selected_skills: list[Skill] = []
        for skill in explicitly_requested:
            if skill not in selected_skills:
                selected_skills.append(skill)
        for name in normalize_selected_skill_names(selection):
            skill = self.registry.get(name)
            if skill is not None and skill not in selected_skills:
                selected_skills.append(skill)
        if not selected_skills:
            final_text = self._plain_chat('You are a concise coding assistant. No specialized skill has been activated.', build_task_context_input(task, workspace_snapshot))
            return {'selection': selection, 'selected_skill': None, 'selected_skills': [], 'loaded_resources': [], 'resource_reads': [], 'script_run': None, 'script_runs': [], 'session_steps': [], 'final': final_text}
        skill_files = {skill.name: list_skill_files(skill) for skill in selected_skills}
        skill_hints = {skill.name: extract_referenced_skill_files(skill.body, skill_files[skill.name]) for skill in selected_skills}
        loaded_resources = {skill.name: {} for skill in selected_skills}
        final_text, resource_reads, script_runs, session_steps = self._run_skill_session(task, selected_skills, workspace_snapshot, skill_files, skill_hints, loaded_resources)
        script_run = script_runs[-1] if script_runs else None
        return {
            'selection': selection,
            'selected_skill': selected_skills[0].name if len(selected_skills) == 1 else None,
            'selected_skills': [skill.name for skill in selected_skills],
            'loaded_resources': [{'skill': skill_name, 'path': path} for skill_name, resources in loaded_resources.items() for path in resources],
            'resource_reads': resource_reads,
            'script_run': script_run,
            'script_runs': script_runs,
            'session_steps': session_steps,
            'final': final_text,
        }

    def _plain_chat(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(model=self.model, messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], temperature=0)
        text = extract_response_text(response)
        cleaned = strip_thinking(text)
        if cleaned:
            return cleaned
        if text:
            return text
        if hasattr(response, 'model_dump'):
            dumped = response.model_dump()
            dumped_text = json.dumps(dumped, ensure_ascii=False, indent=2)
            raise SystemExit(f'Could not extract assistant text from model response:\n{truncate_text(dumped_text, 4000)}')
        raise SystemExit(f'Could not extract assistant text from model response: {response!r}')

    def _json_chat(self, system: str, user: str) -> dict[str, Any]:
        text = self._plain_chat(system, user).strip()
        parsed = parse_json_from_text(text)
        if not isinstance(parsed, dict):
            raise SystemExit(f'Model did not return a JSON object:\n{text}')
        return parsed

    def _run_skill_session(self, task: str, skills: list[Skill], workspace_snapshot: dict[str, Any], skill_files: dict[str, list[str]], skill_hints: dict[str, list[str]], loaded_resources: dict[str, dict[str, str]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        resource_reads: list[dict[str, Any]] = []
        script_runs: list[dict[str, Any]] = []
        session_steps: list[dict[str, Any]] = []

        for turn in range(1, self.max_skill_turns + 1):
            actor_payload = {
                'task': task,
                'turn': turn,
                'remaining_turns_after_this': self.max_skill_turns - turn,
                'workspace_snapshot': workspace_snapshot,
                'skills': [
                    {
                        'name': skill.name,
                        'description': skill.description,
                        'frontmatter': skill.frontmatter,
                        'instructions': skill.body,
                        'available_files': skill_files.get(skill.name, []),
                        'suggested_files': skill_hints.get(skill.name, []),
                        'available_scripts': [path for path in skill_files.get(skill.name, []) if is_script_path(path)],
                        'loaded_resources': [{'path': p, 'content': c} for p, c in loaded_resources.get(skill.name, {}).items()],
                    }
                    for skill in skills
                ],
                'session_history': session_steps,
                'tool_policy': {
                    'read_resource': 'Bundled skill files may be read repeatedly, one file per turn. When action=read_resource, set "skill" to the owning skill name and "path" to the file you need.',
                    'run_script': 'Bundled Python scripts under scripts/ may be requested repeatedly, one per turn. When action=run_script, set "skill" to the owning skill name and "path" to the script.' if self.allow_scripts else 'Bundled skill scripts are disabled. Respond directly or read a resource instead.',
                },
            }
            action = self._json_chat(SYSTEM_ACTOR_PROMPT, json.dumps(actor_payload, ensure_ascii=False, indent=2))
            session_steps.append({'turn': turn, 'type': 'assistant_action', 'data': action})
            action_name = str(action.get('action') or '')
            action_path = extract_action_path(action)

            if action_name == 'respond':
                return str(action.get('message') or ''), resource_reads, script_runs, session_steps

            if action_name == 'read_resource':
                try:
                    resource_skill = resolve_action_skill(skills, str(action.get('skill') or ''), action_path)
                    read_result = read_skill_resource(resource_skill, action_path)
                    read_result['skill'] = resource_skill.name
                    loaded_resources.setdefault(resource_skill.name, {})[read_result['path']] = read_result['content']
                except SystemExit as exc:
                    read_result = {
                        'skill': str(action.get('skill') or ''),
                        'path': action_path,
                        'returncode': None,
                        'content': '',
                        'error': str(exc),
                    }
                resource_reads.append(read_result)
                session_steps.append({
                    'turn': turn,
                    'type': 'tool_result',
                    'tool': 'read_resource',
                    'status': 'ok' if not read_result.get('error') else 'error',
                    'data': read_result,
                })
                continue

            if action_name != 'run_script':
                session_steps.append({
                    'turn': turn,
                    'type': 'tool_result',
                    'tool': 'tool_dispatch',
                    'status': 'error',
                    'data': {'error': f'Unknown action: {action_name or "(missing)"}'},
                })
                continue

            if not self.allow_scripts:
                session_steps.append({
                    'turn': turn,
                    'type': 'tool_result',
                    'tool': 'run_script',
                    'status': 'error',
                    'data': {'error': 'Bundled skill scripts are disabled by the host runner.'},
                })
                continue

            try:
                script_skill = resolve_action_skill(skills, str(action.get('skill') or ''), action_path)
                script_result = run_skill_script(script_skill, action_path, [str(a) for a in action.get('args', [])], self.workspace)
                script_result['skill'] = script_skill.name
            except SystemExit as exc:
                script_result = {
                    'skill': str(action.get('skill') or ''),
                    'path': action_path,
                    'args': [str(a) for a in action.get('args', [])],
                    'returncode': None,
                    'stdout': '',
                    'stderr': str(exc),
                    'error': str(exc),
                }

            script_runs.append(script_result)
            session_steps.append({
                'turn': turn,
                'type': 'tool_result',
                'tool': 'run_script',
                'status': 'ok' if script_result.get('returncode') == 0 else 'error',
                'data': script_result,
            })
            workspace_snapshot = build_workspace_snapshot(self.workspace)

        final_payload = {
            'task': task,
            'workspace_snapshot': workspace_snapshot,
            'skills': [{'name': skill.name, 'description': skill.description, 'instructions': skill.body} for skill in skills],
            'loaded_resources': [{'skill': skill_name, 'path': path} for skill_name, resources in loaded_resources.items() for path in resources],
            'session_history': session_steps,
            'limit_reached': True,
            'max_skill_turns': self.max_skill_turns,
        }
        final_text = self._plain_chat(SYSTEM_FINALIZER_PROMPT, json.dumps(final_payload, ensure_ascii=False, indent=2))
        return final_text, resource_reads, script_runs, session_steps

def parse_json_from_text(text: str) -> Any:
    text = strip_thinking(text) or text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    for candidate in iter_json_candidates(text):
        return candidate
    raise SystemExit(f'Could not parse JSON from model output:\n{text}')

def iter_json_candidates(text: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    seen: list[tuple[bool, int, int, Any]] = []
    for i, ch in enumerate(text):
        if ch not in '{[':
            continue
        try:
            parsed, end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        trailing = text[i + end:].strip()
        seen.append((not trailing, i + end, -i, parsed))
    for _, _, _, parsed in sorted(seen, reverse=True):
        yield parsed

def load_skill(root: Path) -> Skill:
    report = Skill.parse_and_validate(root)
    if report.loadable and report.skill is not None:
        return report.skill
    errors = [item.message for item in report.diagnostics if item.blocks_loading or item.severity == 'error']
    raise SkillParseError('\n'.join(errors) or f'Could not load skill at {resolve_skill_md_path(root)}')

def validate_skill_roots(roots: Iterable[Path]) -> list[SkillValidationReport]:
    reports: list[SkillValidationReport] = []
    for root in roots:
        candidate = root.resolve()
        if not candidate.exists():
            missing_path = resolve_skill_md_path(candidate)
            reports.append(SkillValidationReport(
                skill_root=missing_path.parent,
                skill_md=missing_path,
                diagnostics=[SkillDiagnostic('error', 'path-not-found', f'Path does not exist: {candidate}', violates_spec=True, blocks_loading=True)],
            ))
            continue

        skill_roots = iter_skill_roots(candidate)
        if not skill_roots:
            missing_path = resolve_skill_md_path(candidate)
            reports.append(SkillValidationReport(
                skill_root=missing_path.parent,
                skill_md=missing_path,
                diagnostics=[SkillDiagnostic('error', 'skill-not-found', f'No SKILL.md was found under {candidate}', violates_spec=True, blocks_loading=True)],
            ))
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
        report.diagnostics.append(SkillDiagnostic(
            'warning',
            'duplicate-name',
            f"Skill name '{report.skill.name}' is duplicated. First seen at {existing}.",
            violates_spec=True,
        ))

    return reports

def build_validation_payload(reports: Iterable[SkillValidationReport]) -> dict[str, Any]:
    items = list(reports)
    return {
        'ok': bool(items) and all(item.valid for item in items),
        'reports': [item.to_dict() for item in items],
    }

def list_skill_files(skill: Skill, max_files: int = 200) -> list[str]:
    files: list[str] = []
    for path in sorted(skill.root.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(skill.root)
        if rel.name == 'SKILL.md' or should_skip(rel.parts) or rel.suffix.lower() == '.pyc':
            continue
        files.append(str(rel).replace('\\', '/'))
        if len(files) >= max_files:
            break
    return files

def extract_referenced_skill_files(text: str, available_files: Iterable[str]) -> list[str]:
    available = {normalize_hint_path(path): path for path in available_files}
    refs: set[str] = set()
    for match in SKILL_PATH_HINT_RE.finditer(text):
        normalized = normalize_hint_path(match.group('path'))
        matched = available.get(normalized)
        if matched:
            refs.add(matched)
    return sorted(refs)

def read_skill_resource(selected_skill: Skill, rel_path: str, max_chars_per_file: int = 8000) -> dict[str, Any]:
    normalized = normalize_skill_path(selected_skill, rel_path)
    if not normalized:
        raise SystemExit('Model requested read_resource without a path')
    path = (selected_skill.root / normalized).resolve()
    if not is_relative_to(path, selected_skill.root):
        raise SystemExit(f'Refusing to read resource outside the skill root: {normalized}')
    if not path.exists() or not path.is_file():
        raise SystemExit(f'Requested resource does not exist or is not a file: {normalized}')
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        raise SystemExit(f'Resource is not readable as UTF-8 text: {normalized}') from exc
    return {
        'path': normalized,
        'kind': classify_skill_file(normalized),
        'size_bytes': path.stat().st_size,
        'truncated': len(text) > max_chars_per_file,
        'content': truncate_text(text, max_chars_per_file),
    }

def run_skill_script(selected_skill: Skill, rel_script: str, args: list[str], workspace: Path, timeout_sec: int = 30) -> dict[str, Any]:
    rel_script, args = normalize_script_request(selected_skill, rel_script, args)
    if not rel_script:
        raise SystemExit('Model requested run_script without a script path')
    if not is_script_path(rel_script):
        raise SystemExit(f'Only Python scripts under scripts/ can be executed: {rel_script}')
    script_path = (selected_skill.root / rel_script).resolve()
    if not is_relative_to(script_path, selected_skill.root):
        raise SystemExit(f'Refusing to execute script outside the skill root: {rel_script}')
    if not script_path.exists() or not script_path.is_file():
        raise SystemExit(f'Requested script does not exist or is not a file: {rel_script}')
    cmd = [sys.executable, str(script_path), '--workspace', str(workspace), *args]
    completed = subprocess.run(cmd, cwd=str(workspace), env={**os.environ, 'PYTHONUTF8':'1'}, capture_output=True, text=True, timeout=timeout_sec, check=False)
    return {'cmd': cmd, 'path': rel_script, 'returncode': completed.returncode, 'stdout': truncate_text(completed.stdout, 12000), 'stderr': truncate_text(completed.stderr, 8000)}

def normalize_script_request(selected_skill: Skill, rel_script: str, args: list[str]) -> tuple[str, list[str]]:
    text = rel_script.strip()
    if not text:
        return text, args
    tokens = shlex.split(text, posix=False)
    if tokens and looks_like_python_invocation(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return '', args
    script = normalize_skill_path(selected_skill, tokens[0])
    extra_args = tokens[1:]
    return script, args or extra_args

def normalize_skill_path(selected_skill: Skill, rel_path: str) -> str:
    path = normalize_hint_path(rel_path)
    if not path:
        return ''
    prefixes = (
        f'skills/{selected_skill.root.name}/',
        f'{selected_skill.root.name}/',
        f'skills/{selected_skill.name}/',
        f'{selected_skill.name}/',
    )
    lowered = path.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            path = path[len(prefix):]
            break
    path_obj = Path(path)
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
        if is_relative_to(resolved, selected_skill.root):
            path = str(resolved.relative_to(selected_skill.root))
    return path.replace('\\', '/')

def normalize_hint_path(value: str) -> str:
    path = value.strip().strip('`\'"()[]{}.,:;').replace('\\', '/')
    if path.startswith('./'):
        path = path[2:]
    return path

def classify_skill_file(rel_path: str) -> str:
    first_part = Path(rel_path).parts[0].lower() if Path(rel_path).parts else ''
    if first_part in {'references', 'scripts', 'assets'}:
        return first_part
    return 'resource'

def is_script_path(rel_path: str) -> bool:
    return classify_skill_file(rel_path) == 'scripts' and Path(rel_path).suffix.lower() == '.py'

def extract_action_path(action: dict[str, Any]) -> str:
    path = action.get('path')
    if isinstance(path, str) and path.strip():
        return path
    script = action.get('script')
    if isinstance(script, str):
        return script
    return ''

def find_explicit_skill_mentions(task: str, skills: Iterable[Skill]) -> list[Skill]:
    lowered = task.lower()
    matches: list[Skill] = []
    for skill in sorted(skills, key=lambda item: item.name):
        name = skill.name.lower()
        if any(token in lowered for token in (f'/{name}', f'`{name}`', f'"{name}"', f"'{name}'")):
            matches.append(skill)
    return matches

def looks_like_python_invocation(token: str) -> bool:
    normalized = Path(token).name.lower()
    return normalized in {'python', 'python.exe', 'py', 'py.exe'}

def build_workspace_snapshot(workspace: Path, max_entries: int = 80) -> dict[str, Any]:
    entries = []
    total = 0
    for path in sorted(workspace.rglob('*')):
        rel = path.relative_to(workspace)
        if should_skip(rel.parts):
            continue
        entries.append(str(rel) + ('/' if path.is_dir() else ''))
        total += 1
        if len(entries) >= max_entries:
            break
    return {'workspace': str(workspace), 'sample_paths': entries, 'sampled_entry_count': len(entries), 'total_entries_scanned_before_cutoff': total}

def should_skip(parts: tuple[str, ...]) -> bool:
    skip_names = {'.git','.venv','node_modules','dist','build','target','__pycache__','.mypy_cache','.pytest_cache','.idea','.vscode'}
    return any(part in skip_names for part in parts)

def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def truncate_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + '\n... [truncated]'

def strip_thinking(text: str) -> str:
    if not text:
        return ''
    return THINK_TAG_RE.sub('', text).strip()

def extract_response_text(response: Any) -> str:
    output_text = get_field(response, 'output_text')
    if isinstance(output_text, str) and output_text:
        return output_text
    choices = get_field(response, 'choices')
    if isinstance(choices, list) and choices:
        message = get_field(choices[0], 'message')
        text = flatten_text_content(get_field(message, 'content'))
        if text:
            return text
        refusal = get_field(message, 'refusal')
        if isinstance(refusal, str) and refusal:
            return refusal
    output = get_field(response, 'output')
    if isinstance(output, list):
        for item in output:
            text = flatten_text_content(get_field(item, 'content'))
            if text:
                return text
    if hasattr(response, 'model_dump'):
        dumped = response.model_dump()
        if dumped is not response:
            return extract_response_text(dumped)
    return ''

def flatten_text_content(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [flatten_text_content(item) for item in content]
        return ''.join(part for part in parts if part)
    if isinstance(content, dict):
        text = content.get('text')
        if isinstance(text, str):
            return text
        for key in ('content', 'message'):
            nested = content.get(key)
            nested_text = flatten_text_content(nested)
            if nested_text:
                return nested_text
        return ''
    text = get_field(content, 'text')
    if isinstance(text, str):
        return text
    for key in ('content', 'message'):
        nested = get_field(content, key)
        nested_text = flatten_text_content(nested)
        if nested_text:
            return nested_text
    return ''

def get_field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

def make_client(base_url: str, api_key: str) -> OpenAI:
    if OpenAI is None:
        raise SystemExit("Missing dependency: openai. Install with: pip install openai pyyaml")
    return OpenAI(base_url=base_url, api_key=api_key)

def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Minimal Agent Skills runner for OpenAI-compatible local LLMs')
    p.add_argument('task', nargs='?')
    p.add_argument('--skills', nargs='+', required=True)
    p.add_argument('--workspace', default='.')
    p.add_argument('--base-url', default=os.getenv('OPENAI_BASE_URL', 'http://192.168.1.12:8000/v1'))
    p.add_argument('--api-key', default=os.getenv('OPENAI_API_KEY', 'dummy'))
    p.add_argument('--model', default=os.getenv('OPENAI_MODEL_NAME') or os.getenv('OPENAI_MODEL') or 'Qwen/Qwen3.5-35B-A3B-GPTQ-Int4')
    p.add_argument('--allow-scripts', action='store_true')
    p.add_argument('--max-skill-turns', type=int, default=8, help='Maximum number of skill turns before forcing a best-effort final answer')
    p.add_argument('--show-catalog', action='store_true')
    p.add_argument('--validate-skills', action='store_true', help='Parse SKILL.md files and report validation results')
    return p.parse_args()

def main() -> None:
    args = cli()
    workspace = Path(args.workspace)
    skill_roots = [Path(p) for p in args.skills]

    if args.show_catalog and args.validate_skills:
        raise SystemExit('Use either --show-catalog or --validate-skills, not both.')
    if args.validate_skills:
        payload = build_validation_payload(validate_skill_roots(skill_roots))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload['ok']:
            raise SystemExit(1)
        return

    registry = SkillRegistry(skill_roots)
    if args.show_catalog:
        print(registry.catalog_text()); return
    if not args.task:
        raise SystemExit('task is required unless --show-catalog or --validate-skills is used.')
    if not registry.skills:
        raise SystemExit('No skills were found. Add a ./skills/<skill-name>/SKILL.md folder.')
    client = make_client(args.base_url, args.api_key)
    agent = SkillAgent(client=client, model=args.model, registry=registry, workspace=workspace, allow_scripts=args.allow_scripts, max_skill_turns=args.max_skill_turns)
    print(json.dumps(agent.run(args.task), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
