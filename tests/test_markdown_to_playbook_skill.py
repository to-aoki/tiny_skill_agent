from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL_MD_PATH = ROOT / "skills" / "markdown-to-playbook-skill" / "SKILL.md"


def test_markdown_to_playbook_skill_uses_standard_install_directories():
    skill_md = SKILL_MD_PATH.read_text(encoding="utf-8")

    assert "first check whether `.github/skills` and `.claude/skills` already exist in the workspace" in skill_md
    assert "if only one of `.github/skills` or `.claude/skills` exists, use the existing standard directory" in skill_md
    assert "if both exist and the user did not specify, prefer `.github/skills/<skill-name>`" in skill_md
    assert ".github/skills/<skill-name>" in skill_md
    assert ".claude/skills/<skill-name>" in skill_md
    assert "prefer `.github/skills` by default" in skill_md
    assert "do not invent another default destination such as a top-level `skills/` directory" in skill_md
    assert "treat `github/skills/<skill-name>` without the leading dot as invalid" in skill_md


def test_markdown_to_playbook_template_rejects_dotless_github_dir():
    template_path = ROOT / "skills" / "markdown-to-playbook-skill" / "assets" / "generated-skill-template.md"
    template = template_path.read_text(encoding="utf-8")

    assert "Check whether `.github/skills` and `.claude/skills` already exist in the workspace" in template
    assert ".github/skills/<generated-skill-name>" in template
    assert "never `github/skills/<generated-skill-name>`" in template
