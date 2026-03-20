#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

PLACEHOLDERS = {
    "{{title}}",
    "{{source_path}}",
    "{{source_type}}",
    "{{content}}",
    "{{document_content}}",
    "{{workbook_content}}",
    "{{presentation_content}}",
    "{{#document_paragraphs}}",
    "{{/document_paragraphs}}",
    "{{#workbook_sheets}}",
    "{{/workbook_sheets}}",
    "{{#presentation_slides}}",
    "{{/presentation_slides}}",
}
DEFAULT_TEMPLATE_NAMES = {
    ".docx": "docx-template.md",
    ".xlsx": "excel-template.md",
    ".pptx": "pptx-template.md",
}
SUPPORTED_FAMILY_SUFFIXES = {
    "word": (".docx", ".doc"),
    "excel": (".xlsx", ".xls"),
    "powerpoint": (".pptx", ".ppt"),
}
SUPPORTED_SUFFIXES = {suffix for suffixes in SUPPORTED_FAMILY_SUFFIXES.values() for suffix in suffixes}
KIND_ALIASES = {
    "docx": "word",
    "word": "word",
    "msword": "word",
    "ワード": "word",
    "xlsx": "excel",
    "excel": "excel",
    "エクセル": "excel",
    "pptx": "powerpoint",
    "ppt": "powerpoint",
    "powerpoint": "powerpoint",
    "power-point": "powerpoint",
    "パワーポイント": "powerpoint",
    "スライド": "powerpoint",
}
SKIP_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_kind(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_whitespace(value).lower()
    if not normalized:
        return None
    return KIND_ALIASES.get(normalized)


def infer_kind_from_text(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for alias, family in KIND_ALIASES.items():
        if alias in lowered:
            return family
    return None


def should_skip_relative_path(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIRECTORY_NAMES for part in parts[:-1])


def xml_tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def read_xml_from_zip(archive: zipfile.ZipFile, member: str) -> ET.Element | None:
    try:
        with archive.open(member) as handle:
            return ET.fromstring(handle.read())
    except KeyError:
        return None


def normalize_target(base: str, target: str) -> str:
    base_parts = [part for part in base.split("/") if part]
    stack = base_parts[:-1]
    for part in target.replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)
    return "/".join(stack)


def escape_markdown_table_cell(text: str) -> str:
    return text.replace("|", r"\|").replace("\n", "<br>")


def workspace_office_candidates(workspace: Path, kind: str | None = None) -> list[Path]:
    family = normalize_kind(kind)
    allowed_suffixes = set(SUPPORTED_FAMILY_SUFFIXES[family]) if family else SUPPORTED_SUFFIXES
    candidates: list[Path] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(workspace).parts
        if should_skip_relative_path(rel_parts):
            continue
        if path.suffix.lower() in allowed_suffixes:
            candidates.append(path.resolve())
    return candidates


def extract_query_terms(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower().replace("\\", "/")
    tokens = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._-]{1,}", lowered)
        if token not in {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "word", "excel", "powerpoint", "markdown", "md"}
    }
    return sorted(tokens, key=len, reverse=True)


def candidate_match_score(path: Path, workspace: Path, query_text: str, query_terms: list[str]) -> int:
    rel_path = str(path.relative_to(workspace)).replace("\\", "/").lower()
    stem = path.stem.lower()
    score = 0
    if path.suffix.lower() in {".docx", ".xlsx", ".pptx"}:
        score += 5
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


def render_markdown_table(rows: list[list[str]]) -> str:
    normalized_rows = [[escape_markdown_table_cell(cell) for cell in row] for row in rows if any(cell.strip() for cell in row)]
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


def extract_docx_paragraph(paragraph: ET.Element) -> str:
    text = normalize_whitespace("".join(node.text or "" for node in paragraph.findall(".//w:t", NS)))
    if not text:
        return ""
    style = paragraph.find("./w:pPr/w:pStyle", NS)
    if style is not None:
        style_value = style.attrib.get(f"{{{NS['w']}}}val", "")
        match = re.fullmatch(r"Heading([1-6])", style_value)
        if match:
            return f"{'#' * int(match.group(1))} {text}"
    return text


def extract_docx_table(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall("./w:tr", NS):
        cells: list[str] = []
        for cell in row.findall("./w:tc", NS):
            parts: list[str] = []
            for paragraph in cell.findall(".//w:p", NS):
                value = extract_docx_paragraph(paragraph)
                if value:
                    parts.append(value.strip())
            cells.append("<br>".join(parts))
        if any(cell.strip() for cell in cells):
            rows.append(cells)
    return render_markdown_table(rows)


def docx_blocks(body: ET.Element) -> list[str]:
    blocks: list[str] = []
    for child in list(body):
        tag = xml_tag_name(child)
        if tag == "p":
            paragraph = extract_docx_paragraph(child)
            if paragraph:
                blocks.append(paragraph)
        elif tag == "tbl":
            blocks.append(extract_docx_table(child))
    return blocks


def extract_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    shared_strings_xml = read_xml_from_zip(archive, "xl/sharedStrings.xml")
    if shared_strings_xml is None:
        return []
    values: list[str] = []
    for item in shared_strings_xml.findall("./s:si", NS):
        texts = [node.text or "" for node in item.findall(".//s:t", NS)]
        values.append(normalize_whitespace("".join(texts)))
    return values


def spreadsheet_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return normalize_whitespace("".join(node.text or "" for node in cell.findall(".//s:t", NS)))
    value_node = cell.find("./s:v", NS)
    if value_node is None or value_node.text is None:
        return ""
    raw_value = value_node.text
    if cell_type == "s":
        index = int(raw_value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return normalize_whitespace(raw_value)


def column_letters_to_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha()).upper()
    total = 0
    for character in letters:
        total = total * 26 + (ord(character) - ord("A") + 1)
    return max(total - 1, 0)


def workbook_sheet_members(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = read_xml_from_zip(archive, "xl/workbook.xml")
    workbook_rels = read_xml_from_zip(archive, "xl/_rels/workbook.xml.rels")
    if workbook is None or workbook_rels is None:
        fallback_members = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        return [(Path(name).stem, name) for name in fallback_members]
    relationships = {
        rel.attrib["Id"]: normalize_target("xl/workbook.xml", rel.attrib["Target"])
        for rel in workbook_rels.findall("./rel:Relationship", NS)
        if "Id" in rel.attrib and "Target" in rel.attrib
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("./s:sheets/s:sheet", NS):
        name = sheet.attrib.get("name", "Sheet")
        rel_id = sheet.attrib.get(f"{{{NS['r']}}}id", "")
        target = relationships.get(rel_id)
        if target:
            sheets.append((name, target))
    return sheets


def xlsx_sections(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    shared_strings = extract_shared_strings(archive)
    sections: list[dict[str, str]] = []
    for sheet_name, member in workbook_sheet_members(archive):
        sheet = read_xml_from_zip(archive, member)
        if sheet is None:
            continue
        rows: list[list[str]] = []
        max_width = 0
        for row in sheet.findall("./s:sheetData/s:row", NS):
            values_by_index: dict[int, str] = {}
            for cell in row.findall("./s:c", NS):
                cell_reference = cell.attrib.get("r", "")
                index = column_letters_to_index(cell_reference) if cell_reference else len(values_by_index)
                values_by_index[index] = spreadsheet_cell_value(cell, shared_strings)
            if not values_by_index:
                continue
            row_width = max(values_by_index) + 1
            max_width = max(max_width, row_width)
            rows.append([values_by_index.get(index, "") for index in range(row_width)])
        if rows and max_width:
            normalized_rows = [row + [""] * (max_width - len(row)) for row in rows]
            body = render_markdown_table(normalized_rows)
        else:
            body = "_Empty sheet_"
        sections.append(
            {
                "sheet_index": str(len(sections) + 1),
                "sheet_name": sheet_name,
                "sheet_content": body,
            }
        )
    return sections


def presentation_slide_members(archive: zipfile.ZipFile) -> list[str]:
    presentation = read_xml_from_zip(archive, "ppt/presentation.xml")
    presentation_rels = read_xml_from_zip(archive, "ppt/_rels/presentation.xml.rels")
    if presentation is None or presentation_rels is None:
        return sorted(name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
    relationships = {
        rel.attrib["Id"]: normalize_target("ppt/presentation.xml", rel.attrib["Target"])
        for rel in presentation_rels.findall("./rel:Relationship", NS)
        if "Id" in rel.attrib and "Target" in rel.attrib
    }
    members: list[str] = []
    for slide_id in presentation.findall("./p:sldIdLst/p:sldId", NS):
        rel_id = slide_id.attrib.get(f"{{{NS['r']}}}id", "")
        target = relationships.get(rel_id)
        if target:
            members.append(target)
    return members


def extract_slide_shape_text(shape: ET.Element) -> tuple[bool, str]:
    texts = [normalize_whitespace(node.text or "") for node in shape.findall(".//a:t", NS)]
    content = "\n".join(text for text in texts if text)
    if not content:
        return False, ""
    placeholder = shape.find("./p:nvSpPr/p:nvPr/p:ph", NS)
    placeholder_type = ""
    if placeholder is not None:
        placeholder_type = placeholder.attrib.get("type", "")
    is_title = placeholder_type in {"title", "ctrTitle"}
    return is_title, content


def pptx_slides(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for index, member in enumerate(presentation_slide_members(archive), start=1):
        slide = read_xml_from_zip(archive, member)
        if slide is None:
            continue
        title = ""
        bullets: list[str] = []
        for shape in slide.findall(".//p:sp", NS):
            is_title, text = extract_slide_shape_text(shape)
            if not text:
                continue
            if is_title and not title:
                title = text
                continue
            bullets.extend(line for line in text.splitlines() if line)
        heading = f"## Slide {index}: {title}" if title else f"## Slide {index}"
        if bullets:
            body = "\n".join(bullets)
        else:
            body = "_No text content extracted._"
        sections.append(
            {
                "slide_index": str(index),
                "slide_title": title,
                "slide_heading": heading,
                "slide_content": body,
            }
        )
    return sections


def detect_source_type(path: Path) -> str:
    suffix = path.suffix.lower()
    source_types = {
        ".docx": "Microsoft Word (.docx)",
        ".xlsx": "Microsoft Excel (.xlsx)",
        ".pptx": "Microsoft PowerPoint (.pptx)",
    }
    if suffix in source_types:
        return source_types[suffix]
    if suffix in {".doc", ".xls", ".ppt"}:
        raise SystemExit(
            f"Legacy Office binary formats are not supported: {path}"
        )
    raise SystemExit(f"Unsupported Office file type: {path}")


def resolve_input_file(workspace: Path, raw_input: str | None, kind: str | None = None, query: str | None = None) -> Path:
    explicit_kind = normalize_kind(kind)
    inferred_kind = explicit_kind or infer_kind_from_text(raw_input) or infer_kind_from_text(query)
    if raw_input:
        candidate = Path(raw_input).expanduser()
        if not candidate.is_absolute():
            candidate = (workspace / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    search_text = normalize_whitespace(" ".join(part for part in (raw_input or "", query or "") if part))
    search_terms = extract_query_terms(search_text)
    candidates = workspace_office_candidates(workspace, inferred_kind)
    if not candidates:
        family_label = inferred_kind or "Office"
        raise SystemExit(f"No matching {family_label} files were found under the workspace: {workspace}")
    if len(candidates) == 1 and not raw_input:
        return candidates[0]
    if not search_text and len(candidates) == 1:
        return candidates[0]
    ranked = sorted(
        ((candidate_match_score(path, workspace, search_text.lower(), search_terms), path) for path in candidates),
        key=lambda item: (-item[0], str(item[1]).lower()),
    )
    best_score, best_path = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else None
    if best_score > 0 and (second_score is None or best_score > second_score):
        return best_path
    descriptor = f" for query {search_text!r}" if search_text else ""
    candidate_list = format_candidate_list([path for _, path in ranked], workspace)
    raise SystemExit(f"Could not uniquely resolve an Office file{descriptor}. Candidates: {candidate_list}")


def default_template_path(input_path: Path | None = None) -> Path:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    if input_path is not None:
        template_name = DEFAULT_TEMPLATE_NAMES.get(input_path.suffix.lower())
        if template_name:
            candidate = assets_dir / template_name
            if candidate.is_file():
                return candidate
    return assets_dir / "markdown-template.md"


def render_repeat_blocks(template: str, repeated_sections: dict[str, list[dict[str, str]]], base_replacements: dict[str, str]) -> str:
    rendered = template
    for section_name, items in repeated_sections.items():
        pattern = re.compile(r"{{#" + re.escape(section_name) + r"}}(.*?){{/" + re.escape(section_name) + r"}}", re.DOTALL)

        def replace_block(match: re.Match[str]) -> str:
            block_template = match.group(1)
            rendered_items: list[str] = []
            for item in items:
                item_rendered = block_template
                for placeholder, value in {**base_replacements, **item}.items():
                    item_rendered = item_rendered.replace("{{" + placeholder + "}}", value)
                rendered_items.append(item_rendered)
            return "".join(rendered_items)

        rendered = pattern.sub(replace_block, rendered)
    return rendered


def render_with_template(
    template: str,
    title: str,
    source_path: Path,
    source_type: str,
    content: str,
    repeated_sections: dict[str, list[dict[str, str]]] | None = None,
) -> str:
    rendered = template
    normalized_content = content.strip() or "_No content extracted._"
    base_replacements = {
        "title": title,
        "source_path": str(source_path),
        "source_type": source_type,
        "content": normalized_content,
        "document_content": normalized_content,
        "workbook_content": normalized_content,
        "presentation_content": normalized_content,
    }
    if repeated_sections:
        rendered = render_repeat_blocks(rendered, repeated_sections, base_replacements)
    replacements = {"{{" + key + "}}": value for key, value in base_replacements.items()}
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered.strip() + "\n"


def resolve_output_path(raw_path: str, workspace: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def resolve_template_path(raw_path: str, workspace: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists() or not candidate.is_file():
        raise SystemExit(f"Template file does not exist or is not a file: {candidate}")
    return candidate


def load_template(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not any(placeholder in text for placeholder in PLACEHOLDERS):
        raise SystemExit(f"Template file does not contain any supported placeholders: {path}")
    return text


def extract_office_content(path: Path) -> tuple[str, dict[str, list[dict[str, str]]]]:
    suffix = path.suffix.lower()
    if suffix in {".doc", ".xls", ".ppt"}:
        raise SystemExit("Legacy Office binary formats are not supported. Save the file as .docx, .xlsx, or .pptx and retry.")
    if suffix not in {".docx", ".xlsx", ".pptx"}:
        raise SystemExit(f"Unsupported Office file type: {path.suffix or '<none>'}")
    try:
        with zipfile.ZipFile(path) as archive:
            if suffix == ".docx":
                document = read_xml_from_zip(archive, "word/document.xml")
                if document is None:
                    raise SystemExit("DOCX file does not contain word/document.xml")
                body = document.find("./w:body", NS)
                blocks = docx_blocks(body) if body is not None else []
                content = "\n\n".join(blocks).strip() or "_No content extracted._"
                return content, {
                    "document_paragraphs": [
                        {
                            "document_paragraph_index": str(index),
                            "document_paragraph_content": block,
                        }
                        for index, block in enumerate(blocks, start=1)
                    ]
                }
            if suffix == ".xlsx":
                sections = xlsx_sections(archive)
                content = "\n\n".join(
                    f"## Sheet: {section['sheet_name']}\n\n{section['sheet_content']}" for section in sections
                ).strip() or "_No content extracted._"
                return content, {"workbook_sheets": sections}
            slides = pptx_slides(archive)
            content = "\n\n".join(
                f"{slide['slide_heading']}\n\n{slide['slide_content']}" for slide in slides
            ).strip() or "_No content extracted._"
            return content, {"presentation_slides": slides}
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"Office file is not a valid OOXML zip archive: {path}") from exc


def build_markdown(input_path: Path, template_path: Path, title: str | None = None) -> str:
    template = load_template(template_path)
    document_title = normalize_whitespace(title or input_path.stem) or input_path.stem
    source_type = detect_source_type(input_path)
    content, repeated_sections = extract_office_content(input_path)
    return render_with_template(template, document_title, input_path, source_type, content, repeated_sections)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert .docx, .xlsx, or .pptx files to Markdown.")
    parser.add_argument("--workspace", default=".", help="Workspace root used for relative paths.")
    parser.add_argument("--input", help="Path or partial path to the source Office file.")
    parser.add_argument("--output", help="Optional path to write the Markdown output.")
    parser.add_argument("--template", help="Optional Markdown template path.")
    parser.add_argument("--title", help="Optional Markdown title override.")
    parser.add_argument("--kind", help="Optional Office type hint: word, excel, powerpoint, docx, xlsx, or pptx.")
    parser.add_argument("--query", help="Optional fuzzy filename hint used when --input is omitted or partial.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    workspace = Path(args.workspace).resolve()
    input_path = resolve_input_file(workspace, args.input, kind=args.kind, query=args.query)
    template_path = resolve_template_path(args.template, workspace) if args.template else default_template_path(input_path)
    rendered_output = build_markdown(input_path, template_path, title=args.title)
    if args.output:
        output_path = resolve_output_path(args.output, workspace)
        output_path.write_text(rendered_output, encoding="utf-8")
    else:
        sys.stdout.write(rendered_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
