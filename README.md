# tiny-skill

`SKILL.md` を読む最小 Python サンプルです。GitHub Copilot / Agent Skills の考え方に寄せて、以下の流れで動きます。

1. 起動時に `name` / `description` を読み、Copilot 風の skill adherence block を作る
2. タスクに合う skill があるときだけ、その `SKILL.md` 本文を読み込む
3. skill 配下の bundled files は inventory として渡し、必要になったファイルだけをターンごとに読む
4. `--allow-scripts` が有効なら、`scripts/` 配下の Python script をターンごとに複数回実行できる
5. 複数 skill が当てはまる場合はまとめて有効化し、`respond` が返るか上限ターンに達するまでセッションを継続する

> GitHub Copilot の内部実装そのものではありません

## セットアップ

### uv

```bash
uv sync
```

以降の実行は `uv run` を使えば、作成された仮想環境上でそのまま動きます。

### pip / venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 実行

```bash
uv run python tiny_skill_agent.py "リポジトリの内容を説明して" --workspace . --skills ./skills/ --allow-scripts
```

`--skills` には skill 一覧ディレクトリだけでなく、`./skills/repo-map` や `./skills/repo-map/SKILL.md` のような単一 skill パスも渡せます。
runner は `--skills` で明示的に渡されたパスだけを確認します。

## SKILL.md の検証

`SKILL.md` の frontmatter をパースし、形式が正しいかを検証できます。

```bash
uv run python tiny_skill_agent.py --skills ./skills --validate-skills
```

検証結果は JSON で出力され、spec 違反があると終了コードは `1` になります。

## 推論ソフトウェア定義例

### Ollama

```bash
export OPENAI_BASE_URL=http://localhost:11434/v1
```

### LM Studio

```bash
export OPENAI_BASE_URL=http://localhost:1234/v1
```

### vLLM

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1
```

## セッション継続上限

セッションは `respond` が返るまで続きます。上限は `--max-skill-turns` で設定できます。

```bash
uv run python tiny_skill_agent.py "このリポジトリの概要を教えて" --workspace . --skills ./skills --allow-scripts --max-skill-turns 8
```

## オーケストレーションの挙動

- `SKILL.md` 本文だけを先にモデルへ渡します
- skill 配下のファイル内容は必要になった時点で `read_resource` として 1 ファイルずつ読み込みます
- script 実行は `run_script` として 1 ターンに 1 本ずつ行います
- 実行対象は `scripts/` 配下の `.py` のみです
- 読み込んだ resource 内容と script 出力は以降のターンに履歴として保持されます
