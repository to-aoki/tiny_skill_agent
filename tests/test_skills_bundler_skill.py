from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "skills" / "skills-bundler" / "scripts" / "skills_bundler.py"
SKILL_MD_PATH = ROOT / "skills" / "skills-bundler" / "SKILL.md"


def write_skill(skill_dir: Path, name: str, description: str) -> None:
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "# Skill",
                "",
                "body",
            ]
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")


def run_script(
    workspace_dir: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--workspace", str(workspace_dir), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def build_repo_archive(archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "awesome-copilot-main/skills/python-testing/SKILL.md",
            "\n".join(
                [
                    "---",
                    "name: python-testing",
                    "description: Write pytest and test strategy for Python projects.",
                    "---",
                    "# Skill",
                    "",
                    "body",
                ]
            ),
        )
        archive.writestr(
            "awesome-copilot-main/skills/slides-builder/SKILL.md",
            "\n".join(
                [
                    "---",
                    "name: slides-builder",
                    "description: Build presentation decks.",
                    "---",
                    "# Skill",
                    "",
                    "body",
                ]
            ),
        )



def test_skill_files_exist():
    assert SKILL_MD_PATH.is_file()
    assert SCRIPT_PATH.is_file()


def test_catalog_lists_direct_child_skills(workspace_dir: Path):
    source_dir = workspace_dir / "catalog"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")
    write_skill(source_dir / "sql-helper", "sql-helper", "Help with SQL queries.")
    (source_dir / "notes").mkdir(parents=True)

    completed = run_script(workspace_dir, "catalog", "--source-dir", str(source_dir))
    payload = json.loads(completed.stdout)

    assert payload["count"] == 2
    assert [skill["name"] for skill in payload["skills"]] == ["repo-map", "sql-helper"]


def test_recommend_prefers_matching_descriptions(workspace_dir: Path):
    source_dir = workspace_dir / "recommend"
    write_skill(source_dir / "python-testing", "python-testing", "Write pytest and test strategy for Python projects.")
    write_skill(source_dir / "slides-builder", "slides-builder", "Build presentation decks.")
    write_skill(source_dir / "sql-helper", "sql-helper", "Write SQL queries for analytics.")
    completed = run_script(
        workspace_dir,
        "recommend",
        "--source-dir",
        str(source_dir),
        "--query",
        "python test skill",
        "--limit",
        "2",
    )
    payload = json.loads(completed.stdout)

    assert payload["limit"] == 2
    assert payload["skills"][0]["name"] == "python-testing"
    assert payload["shortlist_count"] >= 1


def test_recommend_prefers_narrow_match_over_generic_skill(workspace_dir: Path):
    source_dir = workspace_dir / "narrow-recommend"
    write_skill(
        source_dir / "python-testing",
        "python-testing",
        "Write pytest and test strategy for Python projects.",
    )
    write_skill(
        source_dir / "developer-workflow",
        "developer-workflow",
        "General workflow helper for common development tasks.",
    )

    completed = run_script(
        workspace_dir,
        "recommend",
        "--source-dir",
        str(source_dir),
        "--query",
        "python pytest tests",
        "--limit",
        "2",
    )
    payload = json.loads(completed.stdout)

    assert payload["skills"][0]["name"] == "python-testing"


def test_recommend_downloads_and_reads_online_archive(workspace_dir: Path):
    remote_dir = workspace_dir / "remote"
    remote_dir.mkdir()
    archive_path = remote_dir / "awesome-copilot.zip"
    build_repo_archive(archive_path)
    completed = run_script(
        workspace_dir,
        "recommend",
        "--source-url",
        str(archive_path),
        "--query",
        "python test skill",
        "--limit",
        "1",
    )

    payload = json.loads(completed.stdout)

    assert payload["skills"][0]["name"] == "python-testing"
    assert (
        workspace_dir
        / payload["source_dir"]
        / "python-testing"
        / "SKILL.md"
    ).is_file()


def test_copy_copies_selected_skills_into_claude_directory(workspace_dir: Path):
    source_dir = workspace_dir / "copy-source"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")
    write_skill(source_dir / "python-testing", "python-testing", "Write pytest suites.")

    completed = run_script(
        workspace_dir,
        "copy",
        "--source-dir",
        str(source_dir),
        "--skills",
        "repo-map",
        "python-testing",
        "--target",
        "claude",
        "--limit",
        "2",
    )
    payload = json.loads(completed.stdout)

    assert payload["target_dir"] == ".claude/skills"
    assert sorted(payload["skills"]) == ["python-testing", "repo-map"]
    assert payload["skipped"] == []
    assert (workspace_dir / ".claude" / "skills" / "repo-map" / "SKILL.md").is_file()
    assert (workspace_dir / ".claude" / "skills" / "python-testing" / "scripts" / "run.py").is_file()


def test_skill_md_prefers_github_standard_destination():
    skill_md = SKILL_MD_PATH.read_text(encoding="utf-8")

    assert "Prefer `--target github` or `--target claude`" in skill_md
    assert "prefer GitHub-style placement in `.github/skills`" in skill_md


def test_copy_skips_existing_skill_directory(workspace_dir: Path):
    source_dir = workspace_dir / "copy-replace-source"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")
    target_skill_dir = workspace_dir / ".github" / "skills" / "repo-map"
    target_skill_dir.mkdir(parents=True)
    (target_skill_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    completed = run_script(
        workspace_dir,
        "copy",
        "--source-dir",
        str(source_dir),
        "--skills",
        "repo-map",
        "--target",
        "github",
        "--limit",
        "1",
    )
    payload = json.loads(completed.stdout)

    assert payload["copied"] == []
    assert payload["skipped"] == [".github/skills/repo-map"]
    assert (target_skill_dir / "stale.txt").is_file()
    assert not (target_skill_dir / "SKILL.md").exists()


def test_copy_rejects_target_dir_outside_workspace(workspace_dir: Path):
    source_dir = workspace_dir / "copy-outside-source"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")
    outside_dir = workspace_dir.parent / "outside-skills"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "copy",
            "--source-dir",
            str(source_dir),
            "--skills",
            "repo-map",
            "--target-dir",
            str(outside_dir),
            "--limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "outside the workspace" in completed.stderr or (
        "outside the workspace" in completed.stdout
    )


def test_cleanup_runtime_cache_after_failed_source_url(workspace_dir: Path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "catalog",
            "--source-url",
            str(workspace_dir / "missing.zip"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert (
        workspace_dir / ".tiny-skill-agent-skills-bundler-cache"
    ).is_dir()


def test_copy_accepts_source_dir_relative_to_workspace(workspace_dir: Path):
    source_dir = workspace_dir / "copy-source"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")

    completed = run_script(
        workspace_dir,
        "copy",
        "--source-dir",
        "copy-source",
        "--skills",
        "repo-map",
        "--target",
        "claude",
        "--limit",
        "1",
    )
    payload = json.loads(completed.stdout)

    assert payload["skills"] == ["repo-map"]
    assert (workspace_dir / ".claude" / "skills" / "repo-map" / "SKILL.md").is_file()
