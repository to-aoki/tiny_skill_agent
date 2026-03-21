#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve
from zipfile import ZipFile

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required to run this script.") from exc


SKIP_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
}
DEFAULT_LIMIT = 5
SHORTLIST_MULTIPLIER = 4
BROAD_TERMS = {
    "build",
    "builder",
    "help",
    "helper",
    "tool",
    "tools",
    "utility",
    "utilities",
    "general",
    "common",
    "generic",
    "workflow",
    "workflows",
}
INSTALL_TARGET_DIRS = {
    "github": Path(".github/skills"),
    "claude": Path(".claude/skills"),
}


@dataclass(frozen=True)
class SkillSummary:
    directory: Path
    name: str
    description: str

    @property
    def skill_md(self) -> Path:
        return self.directory / "SKILL.md"

    def to_dict(self, workspace: Path | None = None) -> dict[str, str]:
        source_dir = workspace or self.directory.parent
        return {
            "name": self.name,
            "description": self.description,
            "directory": to_posix(self.directory.relative_to(source_dir)),
            "skill_md": to_posix(self.skill_md.relative_to(source_dir)),
        }


def to_posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text: str) -> str:
    lowered = normalize_text(text).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "skill-bundle"


def load_frontmatter(skill_md: Path) -> dict[str, object]:
    raw = skill_md.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    parsed = yaml.safe_load(parts[1]) or {}
    return parsed if isinstance(parsed, dict) else {}


def discover_skill_dirs(source_dir: Path) -> list[Path]:
    direct_skill = source_dir / "SKILL.md"
    if direct_skill.is_file():
        return [source_dir.resolve()]
    return sorted(path.parent.resolve() for path in source_dir.glob("*/SKILL.md") if path.is_file())


def load_skill_summaries(source_dir: Path) -> list[SkillSummary]:
    source_dir = source_dir.resolve()
    summaries: list[SkillSummary] = []
    for skill_dir in discover_skill_dirs(source_dir):
        frontmatter = load_frontmatter(skill_dir / "SKILL.md")
        name = normalize_text(str(frontmatter.get("name") or skill_dir.name))
        description = normalize_text(str(frontmatter.get("description") or ""))
        summaries.append(SkillSummary(directory=skill_dir, name=name, description=description))
    return summaries


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+-]{1,}", normalize_text(text).lower())


def score_skill(skill: SkillSummary, query: str) -> tuple[int, int, int, int, str]:
    query_tokens = set(tokenize(query))
    name_tokens = set(tokenize(skill.name))
    description_tokens = set(tokenize(skill.description))
    directory_tokens = set(tokenize(skill.directory.name))
    all_tokens = name_tokens | description_tokens | directory_tokens
    compact_query = normalize_text(query).lower()
    query_in_name = int(bool(compact_query and compact_query in skill.name.lower()))
    query_in_description = int(
        bool(compact_query and compact_query in skill.description.lower())
    )
    name_hits = len(query_tokens & name_tokens)
    description_hits = len(query_tokens & description_tokens)
    directory_hits = len(query_tokens & directory_tokens)
    total_hits = len(query_tokens & all_tokens)
    broad_penalty = len(description_tokens & BROAD_TERMS)
    score = (
        query_in_name * 500
        + query_in_description * 250
        + name_hits * 120
        + description_hits * 40
        + directory_hits * 20
        + total_hits * 15
        - broad_penalty * 10
    )
    return score, name_hits, total_hits, -broad_penalty, skill.name


def build_recommendation_shortlist(
    skills: list[SkillSummary],
    query: str,
    limit: int,
) -> list[SkillSummary]:
    shortlist_limit = max(limit, limit * SHORTLIST_MULTIPLIER)
    ranked = sorted(skills, key=lambda item: score_skill(item, query), reverse=True)
    shortlisted: list[SkillSummary] = []
    for item in ranked:
        _, name_hits, total_hits, _, _ = score_skill(item, query)
        if name_hits == 0 and total_hits < 1:
            continue
        shortlisted.append(item)
        if len(shortlisted) >= shortlist_limit:
            break
    return shortlisted


def derive_group_name(query: str | None, skill_names: list[str]) -> str:
    if query:
        query_slug = slugify(query)
        if query_slug and query_slug != "skill-bundle":
            return query_slug
    if skill_names:
        stem = "-".join(skill_names[:3])
        if len(skill_names) > 3:
            stem = f"{stem}-{len(skill_names)}-skills"
        return slugify(stem)
    return "skill-bundle"


def iter_skill_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if any(part in SKIP_PARTS for part in relative.parts[:-1]):
            continue
        files.append(path)
    return files


def copy_skills_to_directory(
    destination_dir: Path,
    selected_skills: list[SkillSummary],
) -> tuple[list[Path], list[Path]]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_paths: list[Path] = []
    skipped_paths: list[Path] = []
    for skill in selected_skills:
        target_dir = destination_dir / skill.directory.name
        if target_dir.exists():
            skipped_paths.append(target_dir)
            continue
        shutil.copytree(skill.directory, target_dir, ignore=shutil.ignore_patterns(*SKIP_PARTS))
        copied_paths.append(target_dir)
    return copied_paths, skipped_paths


def validate_source_dir(source_dir: Path) -> Path:
    resolved = source_dir.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise SystemExit(f"Source directory was not found: {source_dir}")
    return resolved


def normalize_repo_url(source_url: str) -> str:
    text = source_url.strip().rstrip("/")
    if not text:
        raise SystemExit("Source URL must be non-empty.")
    return text


def build_archive_download_url(source_url: str) -> str:
    normalized = normalize_repo_url(source_url)
    parsed = urlparse(normalized)
    if parsed.netloc.lower() != "github.com":
        return normalized
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SystemExit(f"Unsupported GitHub repository URL: {source_url}")
    owner, repo = parts[:2]
    branch = "main"
    if len(parts) >= 5 and parts[2] == "tree":
        branch = parts[3]
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"


def build_cache_key(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]


def create_runtime_cache_dir(workspace: Path, source_url: str) -> Path:
    return workspace / ".tiny-skill-agent-skills-bundler-cache" / build_cache_key(source_url)


def download_source_archive(cache_dir: Path, source_url: str) -> Path:
    local_path = Path(source_url)
    if local_path.exists() and local_path.is_file():
        return local_path.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / "source.zip"
    download_url = build_archive_download_url(source_url)
    try:
        urlretrieve(download_url, archive_path)
    except Exception as exc:
        raise SystemExit(
            f"Could not download skill source archive from {source_url}: {exc}"
        ) from exc
    return archive_path


def extract_source_archive(cache_dir: Path, archive_path: Path) -> Path:
    extract_root = cache_dir / "extracted"
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(archive_path) as archive:
            archive.extractall(extract_root)
    except Exception as exc:
        raise SystemExit(f"Could not extract archive {archive_path}: {exc}") from exc
    roots = [path for path in extract_root.iterdir() if path.is_dir()]
    if len(roots) == 1:
        return roots[0]
    return extract_root


def resolve_downloaded_source_dir(cache_dir: Path, source_url: str) -> Path:
    archive_path = download_source_archive(cache_dir, source_url)
    extracted_root = extract_source_archive(cache_dir, archive_path)
    skills_dir = extracted_root / "skills"
    if skills_dir.is_dir():
        return skills_dir.resolve()
    if discover_skill_dirs(extracted_root):
        return extracted_root.resolve()
    raise SystemExit(
        f"Downloaded source from {source_url} does not contain a skills directory."
    )


def resolve_source_dir(
    workspace: Path,
    source_dir: str | None,
    source_url: str | None,
    cache_dir: Path | None = None,
) -> Path:
    if source_dir:
        candidate = Path(source_dir)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        return validate_source_dir(candidate)
    if source_url:
        if cache_dir is None:
            raise SystemExit("Internal error: cache_dir is required for --source-url.")
        return resolve_downloaded_source_dir(cache_dir, source_url)
    raise SystemExit("Either --source-dir or --source-url is required.")


def resolve_workspace_dir(workspace: Path, directory: str) -> Path:
    candidate = Path(directory)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (workspace / candidate).resolve()
    )
    if not resolved.is_relative_to(workspace):
        raise SystemExit(
            "Refusing target directory outside the workspace: "
            f"{directory}"
        )
    return resolved


def resolve_install_dir(
    workspace: Path,
    target: str | None,
    target_dir: str | None,
) -> Path:
    if target:
        return resolve_workspace_dir(workspace, str(INSTALL_TARGET_DIRS[target]))
    if target_dir:
        return resolve_workspace_dir(workspace, target_dir)
    raise SystemExit("Either --target or --target-dir is required.")


def find_selected_skills(all_skills: list[SkillSummary], names: list[str]) -> list[SkillSummary]:
    by_name = {skill.name: skill for skill in all_skills}
    selected: list[SkillSummary] = []
    missing: list[str] = []
    for name in names:
        skill = by_name.get(name)
        if skill is None:
            missing.append(name)
            continue
        selected.append(skill)
    if missing:
        raise SystemExit(f"Requested skills were not found: {', '.join(missing)}")
    return selected


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Catalog, recommend, and copy Agent Skills.")
    parser.add_argument("--workspace", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command_name in ("catalog", "recommend", "copy"):
        command = subparsers.add_parser(command_name)
        source_group = command.add_mutually_exclusive_group(required=True)
        source_group.add_argument("--source-dir")
        source_group.add_argument("--source-url")

    recommend = subparsers.choices["recommend"]
    recommend.add_argument("--query", required=True)
    recommend.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    copy = subparsers.choices["copy"]
    copy.add_argument("--skills", nargs="+", required=True)
    copy_target = copy.add_mutually_exclusive_group(required=True)
    copy_target.add_argument("--target", choices=sorted(INSTALL_TARGET_DIRS))
    copy_target.add_argument("--target-dir")
    copy.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args(argv)


def command_catalog(workspace: Path, source_dir: Path) -> None:
    skills = load_skill_summaries(source_dir)
    print(
        json.dumps(
            {
                "source_dir": to_posix(source_dir.relative_to(workspace) if source_dir.is_relative_to(workspace) else source_dir),
                "count": len(skills),
                "skills": [skill.to_dict(source_dir) for skill in skills],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_recommend(
    workspace: Path,
    source_dir: Path,
    query: str,
    limit: int,
) -> None:
    if limit < 1:
        raise SystemExit("--limit must be at least 1.")
    skills = load_skill_summaries(source_dir)
    shortlisted = build_recommendation_shortlist(skills, query, limit)
    print(
        json.dumps(
            {
                "source_dir": to_posix(source_dir.relative_to(workspace) if source_dir.is_relative_to(workspace) else source_dir),
                "query": query,
                "limit": limit,
                "shortlist_count": len(shortlisted),
                "group_name": derive_group_name(query, [skill.name for skill in shortlisted[:limit]]),
                "skills": [skill.to_dict(source_dir) for skill in shortlisted],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_copy(
    workspace: Path,
    source_dir: Path,
    requested_names: list[str],
    destination_dir: Path,
    limit: int,
) -> None:
    if limit < 1:
        raise SystemExit("--limit must be at least 1.")
    if len(requested_names) > limit:
        raise SystemExit(f"Requested {len(requested_names)} skills but the limit is {limit}.")
    skills = load_skill_summaries(source_dir)
    selected = find_selected_skills(skills, requested_names)
    copied_paths, skipped_paths = copy_skills_to_directory(destination_dir, selected)
    print(
        json.dumps(
            {
                "target_dir": to_posix(destination_dir.relative_to(workspace)),
                "skills": [skill.name for skill in selected],
                "copied": [
                    to_posix(path.relative_to(workspace))
                    for path in copied_paths
                ],
                "skipped": [
                    to_posix(path.relative_to(workspace))
                    for path in skipped_paths
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])
    workspace = Path(args.workspace).resolve()
    cache_dir: Path | None = None
    source_url = getattr(args, "source_url", None)
    if source_url:
        cache_dir = create_runtime_cache_dir(workspace, source_url)
    source_dir = resolve_source_dir(
        workspace,
        getattr(args, "source_dir", None),
        source_url,
        cache_dir,
    )

    if args.command == "catalog":
        command_catalog(workspace, source_dir)
        return
    if args.command == "recommend":
        command_recommend(workspace, source_dir, args.query, args.limit)
        return
    if args.command == "copy":
        destination_dir = resolve_install_dir(workspace, args.target, args.target_dir)
        command_copy(workspace, source_dir, args.skills, destination_dir, args.limit)
        return
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
