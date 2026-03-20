from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for candidate in (str(SRC), str(ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import tiny_skill_agent


@pytest.fixture
def data_dir() -> Path:
    return Path(__file__).parent / "data"


@pytest.fixture
def skills_dir(data_dir: Path) -> Path:
    return data_dir / "skills"


@pytest.fixture
def valid_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "valid-skill"


@pytest.fixture
def colon_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "colon-skill"


@pytest.fixture
def missing_description_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "missing-description"


@pytest.fixture
def bad_name_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "bad-name-format"


@pytest.fixture
def duplicate_one_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "duplicate-one"


@pytest.fixture
def duplicate_two_skill_dir(skills_dir: Path) -> Path:
    return skills_dir / "duplicate-two"


@pytest.fixture
def valid_skill(valid_skill_dir: Path) -> tiny_skill_agent.Skill:
    return tiny_skill_agent.load_skill(valid_skill_dir)


@pytest.fixture
def workspace_dir(data_dir: Path) -> Path:
    root = data_dir.parent / ".tmp_workspaces"
    root.mkdir(exist_ok=True)
    path = root / uuid4().hex
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)
