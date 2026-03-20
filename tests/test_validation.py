import tiny_skill_agent


def test_parse_and_validate_valid_skill(valid_skill_dir):
    report = tiny_skill_agent.Skill.parse_and_validate(valid_skill_dir)

    assert report.loadable is True
    assert report.valid is True
    assert report.skill is not None
    assert report.skill.name == "valid-skill"
    assert report.errors == []


def test_parse_and_validate_rejects_unquoted_colon_yaml(colon_skill_dir):
    report = tiny_skill_agent.Skill.parse_and_validate(colon_skill_dir)
    codes = {item.code for item in report.errors}

    assert report.loadable is False
    assert report.valid is False
    assert report.skill is None
    assert "yaml-unparseable" in codes


def test_parse_and_validate_missing_description_blocks_loading(missing_description_skill_dir):
    report = tiny_skill_agent.Skill.parse_and_validate(missing_description_skill_dir)
    codes = {item.code for item in report.errors}

    assert report.loadable is False
    assert report.valid is False
    assert report.skill is None
    assert "description-missing" in codes


def test_parse_and_validate_bad_name_is_loadable_but_invalid(bad_name_skill_dir):
    report = tiny_skill_agent.Skill.parse_and_validate(bad_name_skill_dir)
    codes = {item.code for item in report.diagnostics}

    assert report.loadable is True
    assert report.valid is False
    assert report.skill is not None
    assert report.skill.name == "bad_skill"
    assert {"name-invalid-format", "name-directory-mismatch"} <= codes


def test_validate_skill_roots_reports_duplicate_names(duplicate_one_skill_dir, duplicate_two_skill_dir):
    reports = tiny_skill_agent.validate_skill_roots([duplicate_one_skill_dir, duplicate_two_skill_dir])
    payload = tiny_skill_agent.build_validation_payload(reports)
    duplicate_report = next(report for report in reports if report.skill is not None and report.skill.root.name == "duplicate-two")
    codes = {item.code for item in duplicate_report.diagnostics}

    assert payload["ok"] is False
    assert "duplicate-name" in codes


def test_registry_skips_blocking_invalid_skills_and_keeps_first_duplicate(skills_dir):
    registry = tiny_skill_agent.SkillRegistry([skills_dir])

    assert registry.get("valid-skill") is not None
    assert registry.get("colon-skill") is None
    assert registry.get("bad_skill") is not None
    assert registry.get("missing-description") is None
    assert registry.get("shared-skill") is not None
    assert registry.get("shared-skill").root.name == "duplicate-one"
