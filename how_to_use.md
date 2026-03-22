# How To Use `SkillAgent`

`tiny_skill_agent` は CLI だけでなく、通常の Python package として import して使えます。

## 前提

- `src` レイアウトの package が import できること
- `openai` と `PyYAML` が install 済みであること
- skill の場所は呼び出し側で `Path` として明示すること

## 最小例

```python
from pathlib import Path
import json
import os

from openai import OpenAI

from tiny_skill_agent import (
    SkillAgent,
    SkillRegistry,
    build_openai_telemetry_emitter,
)


def main() -> None:
    workspace = Path(".").resolve()

    registry = SkillRegistry(
        [
            Path("./skills"),
            # 単一 skill を使うならこちらでもよい:
            # Path("./skills/office-to-markdown"),
            # Path("./skills/office-to-markdown/SKILL.md"),
        ]
    )

    client = OpenAI(
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
        openai_telemetry=build_openai_telemetry_emitter(
            file_path=Path("./logs/openai-telemetry.jsonl"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
        ),
    )

    result = agent.run("pptxをマークダウンに変換して")

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
- `Path("./skills/office-to-markdown")` や `Path("./skills/office-to-markdown/SKILL.md")` を渡すと単一 skill だけを登録できます
- `allow_scripts=True` のときだけ `scripts/` 配下の `.py` を実行できます
- workspace のルートパスや内容は最初からモデルに送りません
- 必要なときだけ `list_directory` と `read_file` で取得します
- `openai_telemetry=build_openai_telemetry_emitter(...)` を渡すと OpenTelemetry をローカル JSONL や OTLP endpoint へ出力できます
- `agent.run(...)` の戻り値は dict で、`final`, `selected_skills`, `script_runs`, `resource_reads`, `workspace_reads`, `workspace_writes`, `session_steps` などを含みます

## workspace の扱い

workspace を読む・書くアクションは、`SkillAgent(..., workspace=Path(...))` または CLI `--workspace` で渡したルート配下を対象に行います。

## `allowed-tools` の扱い

`allowed-tools` は読み取りますが、この実装では権限制御には使いません。実際の制御は次だけです。

- `allow_scripts`

## 別モジュールから呼ぶ例

```python
from pathlib import Path

from openai import OpenAI

from tiny_skill_agent import SkillAgent, SkillRegistry


registry = SkillRegistry([Path("./skills")])
client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="dummy",
)

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

## CLI から使う

```bash
uv run tiny-skill-agent "このリポジトリの概要を教えて" --workspace . --skills ./skills --allow-scripts
```

```bash
uv run tiny-skill-agent "このリポジトリの概要を教えて" --workspace . --skills ./skills --allow-scripts --otel-endpoint http://127.0.0.1:4318/v1/traces
```

## wheel を作成する

`dist/` に wheel を出力するには、プロジェクトルートで次を実行します。

```bash
uv build
```

`python -m build` を使う場合は、事前に `build` を install してから実行します。

```bash
pip install build
python -m build --wheel
```

生成物は `dist/*.whl` に出力されます。

作成した wheel を install するには、対象の仮想環境で次を実行します。

```bash
pip install dist/tiny_skill_agent-0.1.0-py3-none-any.whl
```

バージョン番号を固定したくない場合は、シェルに応じて `dist` 配下の wheel を指定してください。

## 注意

- package を import しても CLI は実行されません
- CLI 入口は `tiny_skill_agent.cli:main` と `python -m tiny_skill_agent` です
- `agent.run(...)` はモデル API を呼び出します
- skill が 1 つも見つからないと、CLI ではエラーになります
