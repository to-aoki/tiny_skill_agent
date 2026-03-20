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


def test_archive_creates_zip_with_selected_skill_directories(workspace_dir: Path):
    source_dir = workspace_dir / "archive"
    output_dir = workspace_dir / "bundles"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")
    write_skill(source_dir / "python-testing", "python-testing", "Write pytest suites.")

    completed = run_script(
        workspace_dir,
        "archive",
        "--source-dir",
        str(source_dir),
        "--skills",
        "repo-map",
        "python-testing",
        "--group-name",
        "engineering-pack",
        "--output-dir",
        str(output_dir),
        "--limit",
        "2",
    )
    payload = json.loads(completed.stdout)
    archive_path = output_dir / payload["archive"]

    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "engineering-pack/repo-map/SKILL.md" in names
    assert "engineering-pack/python-testing/scripts/run.py" in names


def test_archive_rejects_more_skills_than_limit(workspace_dir: Path):
    source_dir = workspace_dir / "limit"
    write_skill(source_dir / "one", "one", "First.")
    write_skill(source_dir / "two", "two", "Second.")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "archive",
            "--source-dir",
            str(source_dir),
            "--skills",
            "one",
            "two",
            "--limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "limit is 1" in completed.stderr or "limit is 1" in completed.stdout


def test_archive_rejects_output_dir_that_duplicates_workspace_name(workspace_dir: Path):
    source_dir = workspace_dir / "duplicate-output"
    write_skill(source_dir / "repo-map", "repo-map", "Map repositories.")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "archive",
            "--source-dir",
            str(source_dir),
            "--skills",
            "repo-map",
            "--output-dir",
            workspace_dir.name,
            "--limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "duplicates the workspace name" in completed.stderr or (
        "duplicates the workspace name" in completed.stdout
    )
