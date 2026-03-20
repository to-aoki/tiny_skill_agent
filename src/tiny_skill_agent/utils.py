"""テキスト処理とログ出力の共通ユーティリティ。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def parse_json_from_text(text: str) -> Any:
    """テキスト中から最も妥当な JSON を抽出して返す。"""
    text = strip_thinking(text) or text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    best: tuple[tuple[bool, int, int], Any] | None = None
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            parsed, end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        rank = (not text[i + end:].strip(), i + end, -i)
        if best is None or rank > best[0]:
            best = (rank, parsed)
    if best is not None:
        return best[1]
    raise SystemExit(f"Could not parse JSON from model output:\n{text}")


def truncate_text(text: Any, limit: int) -> str:
    """長い文字列を上限文字数で切り詰める。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def strip_thinking(text: str) -> str:
    """モデル出力から think タグを除去する。"""
    if not text:
        return ""
    return THINK_TAG_RE.sub("", text).strip()


def extract_response_text(response: Any) -> str:
    """OpenAI 互換レスポンスから本文テキストを抽出する。"""
    if hasattr(response, "model_dump"):
        response = response.model_dump()
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    if not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    return flatten_text_content(message.get("content")) or str(
        message.get("refusal") or ""
    )


def flatten_text_content(content: Any) -> str:
    """入れ子の content 表現をプレーンテキストへ平坦化する。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(filter(None, (flatten_text_content(item) for item in content)))
    if isinstance(content, dict):
        return str(content.get("text") or "") or flatten_text_content(
            content.get("content")
        )
    return ""


def current_timestamp_iso() -> str:
    """UTC 現在時刻を ISO 8601 形式で返す。"""
    return datetime.now(timezone.utc).isoformat()


def serialize_openai_response(response: Any) -> Any:
    """OpenAI 応答をログ保存しやすい形へ変換する。"""
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()
        except Exception:
            pass
    if isinstance(response, dict):
        return response
    return {"repr": repr(response)}


def append_jsonl_log(path: Path, payload: dict[str, Any]) -> None:
    """JSONL ログへ 1 レコード追記する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
