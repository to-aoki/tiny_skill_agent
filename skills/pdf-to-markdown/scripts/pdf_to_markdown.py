#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pdfplumber>=0.11.0",
# ]
# ///
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATE_PATH = SKILL_DIR / "assets" / "pdf-template.md"
SUPPORTED_SUFFIXES = {".pdf"}
SKIP_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
}
PLACEHOLDERS = {
    "{{title}}",
    "{{source_path}}",
    "{{source_type}}",
    "{{content}}",
    "{{#pages}}",
    "{{/pages}}",
}


@dataclass(slots=True)
class PageContent:
    index: int
    heading: str
    text: str
    tables: list[str]

    @property
    def content(self) -> str:
        parts: list[str] = []
        if self.text:
            parts.append(self.text)
        parts.extend(self.tables)
        if not parts:
            return "_No extractable text on this page._"
        return "\n\n".join(parts)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_kind(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_whitespace(value).lower()
    if not normalized:
        return None
    if normalized == "pdf":
        return "pdf"
    return None


def should_skip_relative_path(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIRECTORY_NAMES for part in parts[:-1])


def workspace_pdf_candidates(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(workspace).parts
        if should_skip_relative_path(rel_parts):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            candidates.append(path.resolve())
    return candidates


def extract_query_terms(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower().replace("\\", "/")
    tokens = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._-]{1,}", lowered)
        if token not in {"pdf", "markdown", "md"}
    }
    return sorted(tokens, key=len, reverse=True)


def candidate_match_score(path: Path, workspace: Path, query_text: str, query_terms: list[str]) -> int:
    rel_path = str(path.relative_to(workspace)).replace("\\", "/").lower()
    stem = path.stem.lower()
    score = 0
    if query_text:
        if query_text in rel_path:
            score += 120
        if query_text in stem:
            score += 160
    for term in query_terms:
        if term == stem:
            score += 120
        elif term in stem:
            score += 60 + len(term)
        elif term in rel_path:
            score += 20 + len(term)
    return score


def format_candidate_list(candidates: list[Path], workspace: Path, limit: int = 8) -> str:
    items = [str(path.relative_to(workspace)).replace("\\", "/") for path in candidates[:limit]]
    suffix = "" if len(candidates) <= limit else f", ... ({len(candidates)} files total)"
    return ", ".join(items) + suffix


def resolve_input_file(
    workspace: Path,
    input_hint: str | None = None,
    *,
    kind: str | None = None,
    query: str | None = None,
) -> Path:
    normalized_kind = normalize_kind(kind)
    if normalized_kind not in {None, "pdf"}:
        raise SystemExit(f"Unsupported kind: {kind}")
    if input_hint:
        candidate = Path(input_hint)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (workspace / candidate).resolve()
        if resolved.is_file():
            return resolved
    candidates = workspace_pdf_candidates(workspace)
    if not candidates:
        raise SystemExit("Could not find any PDF files in the workspace.")
    if input_hint:
        lowered_hint = normalize_whitespace(input_hint).lower().replace("\\", "/")
        query_terms = extract_query_terms(lowered_hint)
        ranked = sorted(
            candidates,
            key=lambda path: candidate_match_score(path, workspace, lowered_hint, query_terms),
            reverse=True,
        )
        if ranked and candidate_match_score(ranked[0], workspace, lowered_hint, query_terms) > 0:
            if len(ranked) == 1 or candidate_match_score(ranked[1], workspace, lowered_hint, query_terms) < candidate_match_score(ranked[0], workspace, lowered_hint, query_terms):
                return ranked[0]
    if query:
        lowered_query = normalize_whitespace(query).lower()
        query_terms = extract_query_terms(lowered_query)
        ranked = sorted(
            candidates,
            key=lambda path: candidate_match_score(path, workspace, lowered_query, query_terms),
            reverse=True,
        )
        if ranked and candidate_match_score(ranked[0], workspace, lowered_query, query_terms) > 0:
            if len(ranked) == 1 or candidate_match_score(ranked[1], workspace, lowered_query, query_terms) < candidate_match_score(ranked[0], workspace, lowered_query, query_terms):
                return ranked[0]
    if len(candidates) == 1:
        return candidates[0]
    raise SystemExit(
        "Input PDF is ambiguous. Provide --input or --query. Candidates: "
        + format_candidate_list(candidates, workspace)
    )


def escape_markdown_table_cell(text: str) -> str:
    return text.replace("|", r"\|").replace("\n", "<br>")


def render_markdown_table(rows: list[list[str]]) -> str:
    normalized_rows = [
        [escape_markdown_table_cell(normalize_whitespace(cell)) for cell in row]
        for row in rows
        if any(normalize_whitespace(cell) for cell in row)
    ]
    if not normalized_rows:
        return "_Empty table_"
    width = max(len(row) for row in normalized_rows)
    padded_rows = [row + [""] * (width - len(row)) for row in normalized_rows]
    header = padded_rows[0]
    separator = ["---"] * width
    body = padded_rows[1:] or [[""] * width]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def normalize_page_text(text: str) -> str:
    if not text:
        return ""
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = normalize_whitespace(raw_line)
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def load_pdfplumber() -> Any:
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit(
            "pdfplumber is required. Run this script with 'uv run' so PEP 723 dependencies are installed."
        ) from exc
    return pdfplumber


def extract_pdf_content(pdf_path: Path) -> list[PageContent]:
    pdfplumber = load_pdfplumber()
    pages: list[PageContent] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = normalize_page_text(page.extract_text() or "")
            tables = [render_markdown_table(table) for table in (page.extract_tables() or [])]
            pages.append(
                PageContent(
                    index=index,
                    heading=f"Page {index}",
                    text=text,
                    tables=tables,
                )
            )
    return pages


def render_repeat_block(template: str, block_name: str, items: list[dict[str, str]]) -> str:
    pattern = re.compile(
        re.escape(f"{{{{#{block_name}}}}}") + r"(.*?)" + re.escape(f"{{{{/{block_name}}}}}"),
        re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        chunk = match.group(1)
        rendered_chunks: list[str] = []
        for item in items:
            rendered = chunk
            for key, value in item.items():
                rendered = rendered.replace(f"{{{{{key}}}}}", value)
            rendered_chunks.append(rendered)
        return "".join(rendered_chunks)

    return pattern.sub(replace, template)


def render_template(template_text: str, variables: dict[str, str], pages: list[PageContent]) -> str:
    rendered = render_repeat_block(
        template_text,
        "pages",
        [
            {
                "page_index": str(page.index),
                "page_heading": page.heading,
                "page_content": page.content,
            }
            for page in pages
        ],
    )
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    leftovers = [placeholder for placeholder in PLACEHOLDERS if placeholder in rendered]
    if leftovers:
        raise SystemExit(f"Template contains unsupported placeholders after rendering: {', '.join(sorted(leftovers))}")
    return rendered.strip() + "\n"


def build_markdown(
    pdf_path: Path,
    template_path: Path,
    *,
    title: str | None = None,
    extractor: Callable[[Path], list[PageContent]] | None = None,
) -> str:
    if pdf_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise SystemExit(f"Unsupported file type: {pdf_path.suffix}")
    template_text = template_path.read_text(encoding="utf-8")
    pages = (extractor or extract_pdf_content)(pdf_path)
    content = "\n\n".join(f"## {page.heading}\n\n{page.content}" for page in pages)
    if not content.strip():
        content = "_No extractable text found in the PDF._"
    variables = {
        "title": title or pdf_path.stem,
        "source_path": str(pdf_path),
        "source_type": "PDF (.pdf)",
        "content": content,
    }
    return render_template(template_text, variables, pages)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown with pdfplumber.")
    parser.add_argument("--workspace", required=True, help="Workspace root path.")
    parser.add_argument("--input", help="Input PDF path.")
    parser.add_argument("--output", help="Output Markdown path.")
    parser.add_argument("--template", help="Custom Markdown template path.")
    parser.add_argument("--title", help="Override title in the Markdown output.")
    parser.add_argument("--kind", help="Document kind for discovery. Only 'pdf' is supported.")
    parser.add_argument("--query", help="Query text for workspace discovery.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"Workspace does not exist: {workspace}")
    pdf_path = resolve_input_file(
        workspace,
        args.input,
        kind=args.kind,
        query=args.query,
    )
    template_path = Path(args.template).resolve() if args.template else DEFAULT_TEMPLATE_PATH
    markdown = build_markdown(pdf_path, template_path, title=args.title)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (workspace / output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        return 0
    sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
