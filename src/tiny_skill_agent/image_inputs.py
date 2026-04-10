"""画像入力の収集と OpenAI 送信用フォーマット変換。"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import mimetypes
from pathlib import Path
from typing import Any

SUPPORTED_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@dataclass(slots=True)
class InputImage:
    """OpenAI へ渡す 1 枚分の画像入力。"""

    path: str
    mime_type: str
    data_url: str
    size_bytes: int

    def to_metadata(self) -> dict[str, Any]:
        """セッション共有用の軽量メタデータへ変換する。"""
        return {
            "path": self.path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
        }

    def to_openai_content_part(self) -> dict[str, Any]:
        """Chat Completions の user content part へ変換する。"""
        return {
            "type": "image_url",
            "image_url": {"url": self.data_url},
        }


def _guess_image_mime_type(path: Path) -> str | None:
    normalized_suffix = path.suffix.lower()
    explicit = SUPPORTED_IMAGE_MIME_TYPES.get(normalized_suffix)
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    return None
def load_input_image(path: Path, display_path: str | None = None) -> InputImage:
    """単一画像ファイルを読み込む。"""
    resolved_path = path.resolve()
    if not resolved_path.exists() or not resolved_path.is_file():
        raise SystemExit(f"image file was not found: {resolved_path}")
    mime_type = _guess_image_mime_type(resolved_path)
    if not mime_type:
        raise SystemExit(f"unsupported image file: {resolved_path}")
    raw = resolved_path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return InputImage(
        path=display_path or resolved_path.name,
        mime_type=mime_type,
        data_url=f"data:{mime_type};base64,{encoded}",
        size_bytes=len(raw),
    )


def build_openai_user_content(text: str, images: list[InputImage]) -> str | list[dict[str, Any]]:
    """OpenAI Chat Completions 用の user content を構築する。"""
    if not images:
        return text
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content.extend(image.to_openai_content_part() for image in images)
    return content
