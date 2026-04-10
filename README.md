# tiny-skill-agent

`SKILL.md` を読み、必要な skill だけを有効化してタスクを進める最小の Agent Skills ランナーです。

## セットアップ

### uv

```bash
uv sync
```

### pip / venv

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 実行

### カタログ表示

```bash
uv run tiny-skill-agent --skills ./skills --show-catalog
```

### 通常実行

```bash
uv run tiny-skill-agent "pptxをマークダウンに変換して" --workspace . --skills ./skills --allow-scripts
```

### OpenTelemetry をローカルファイルへ出力

```bash
uv run tiny-skill-agent "pptxをマークダウンに変換して" --workspace . --skills ./skills --allow-scripts --openai-telemetry-file ./logs/openai-telemetry.jsonl
```

### OpenTelemetry を OTLP endpoint へ送信

```bash
uv run tiny-skill-agent "pptxをマークダウンに変換して" --workspace . --skills ./skills --allow-scripts --otel-endpoint http://127.0.0.1:4318/v1/traces
```

### SKILL.md の検証

```bash
uv run tiny-skill-agent --skills ./skills --validate-skills
```

`--skills` には次を渡せます。

- skill 一覧ディレクトリ
  - `./skills`
- 単一 skill ディレクトリ
  - `./skills/office-to-markdown`
- 単一 `SKILL.md`
  - `./skills/office-to-markdown/SKILL.md`

## 主な挙動

- 起動時に `name` と `description` を読み、候補 skill を作ります
- タスクに合う skill だけを有効化します
- skill 本文や skill 配下ファイルは必要なときだけ読みます
- workspace のルートや内容は最初からモデルに渡しません
- workspace 操作は `--workspace` で渡したルート配下を対象に行えます
- `--allow-scripts` を付けたときだけ `scripts/` 配下の `.py` を実行できます
- セッションは `respond` が返るか `--max-skill-turns` に達するまで続きます

## workspace

workspace を読む・書くアクションは、CLI の `--workspace` または `SkillAgent(..., workspace=...)` で渡したルート配下を対象に行います。

workspace 内に画像ファイルがある場合も同様です。画像は起動時に自動投入されず、skill が `read_file` で対象画像を読んだときだけ後続のモデル入力へ追加されます。

たとえば画像比較系 skill では、まず workspace から 2 枚の画像を `read_file` で読み、その後に `input_images` として比較に使います。

## `allowed-tools`

`allowed-tools` は読み取りますが、現実装では権限制御には使っていません。実際の制御に使うのは次だけです。

- `--allow-scripts`

## Python から使う

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
    registry = SkillRegistry([Path("./skills")])
    client = OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"),
        api_key=os.getenv("OPENAI_API_KEY", "dummy"),
    )

    agent = SkillAgent(
        client=client,
        model=os.getenv("OPENAI_MODEL", "your-model-name"),
        registry=registry,
        workspace=Path(".").resolve(),
        allow_scripts=True,
        max_skill_turns=8,
        openai_telemetry=build_openai_telemetry_emitter(
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
        ),
    )

    result = agent.run("このリポジトリの概要を教えて")
    print(result["selected_skills"])
    print(result["final"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

`openai_telemetry` は省略できます。ローカル保存したい場合は `file_path=Path("./logs/openai-telemetry.jsonl")`、OTLP 送信したい場合は `otlp_endpoint="http://127.0.0.1:4318/v1/traces"` を渡します。

## 環境変数

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL_NAME`
- `OPENAI_MODEL`
- `OPENAI_TELEMETRY_FILE`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- `OTEL_EXPORTER_OTLP_ENDPOINT`

## 補足

- OpenAI 互換 API は `chat.completions` を使います
- `agent.run(...)` の戻り値は dict です
- 主なキーは `final`, `selected_skills`, `resource_reads`, `workspace_reads`, `workspace_writes`, `script_runs`, `session_steps`, `input_images` です
