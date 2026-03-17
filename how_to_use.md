# How To Use `SkillAgent`

`tiny_skill_agent.py` は CLI だけでなく、通常の Python module として import して使えます。

## 前提

- `tiny_skill_agent.py` が import できる場所にあること
- `openai` と `pyyaml` が install 済みであること
- skill の場所は呼び出し側で明示的に渡すこと

## 最小例

```python
from pathlib import Path
import json
import os

from tiny_skill_agent import SkillAgent, SkillRegistry, make_client


def main() -> None:
    workspace = Path(".").resolve()

    registry = SkillRegistry([
        Path("./skills"),
        # 単一 skill を使うならこちらでもよい:
        # Path("./skills/repo-map"),
        # Path("./skills/repo-map/SKILL.md"),
    ])

    client = make_client(
        base_url=os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"),
        api_key=os.getenv("OPENAI_API_KEY", "dummy"),
    )

    agent = SkillAgent(
        client=client,
        model=os.getenv("OPENAI_MODEL", "your-model-name"),
        registry=registry,
        workspace=workspace,
        allow_scripts=True,
        max_skill_turns=8,
    )

    result = agent.run("このリポジトリの概要を教えて")

    print("selected_skills:", result["selected_skills"])
    print("final:")
    print(result["final"])
    print()
    print("full result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

## ポイント

- CLI の `--skills` に相当するものは `SkillRegistry([...])` に渡す `Path` 一覧です
- `Path("./skills")` を渡すと、その配下の `*/SKILL.md` を走査します
- `Path("./skills/repo-map")` や `Path("./skills/repo-map/SKILL.md")` を渡すと単一 skill だけを登録できます
- `allow_scripts=True` のときだけ `scripts/` 配下の `.py` を実行できます
- `agent.run(...)` の戻り値は dict で、`final`, `selected_skills`, `script_runs`, `resource_reads`, `session_steps` などを含みます

## Web アプリや別モジュールから呼ぶ例

```python
from pathlib import Path

from tiny_skill_agent import SkillAgent, SkillRegistry, make_client


registry = SkillRegistry([Path("./skills")])
client = make_client("http://127.0.0.1:8000/v1", "dummy")

agent = SkillAgent(
    client=client,
    model="your-model-name",
    registry=registry,
    workspace=Path("."),
    allow_scripts=False,
)


def run_agent(task: str) -> str:
    result = agent.run(task)
    return result["final"]
```

## 注意

- `tiny_skill_agent.py` を import しても CLI は実行されません。`main()` は `if __name__ == "__main__":` のときだけ動きます
- `agent.run(...)` はモデル API を呼び出します。offline では完走しません
- skill が 1 つも見つからないと `SkillRegistry` 自体は作れますが、実行時には skill なしとして扱われるか、CLI ではエラーになります
