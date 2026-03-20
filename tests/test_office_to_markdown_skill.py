from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import textwrap
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "skills" / "office-to-markdown" / "scripts" / "office_to_markdown.py"
SKILL_MD_PATH = ROOT / "skills" / "office-to-markdown" / "SKILL.md"
TEMPLATE_PATH = ROOT / "skills" / "office-to-markdown" / "assets" / "markdown-template.md"
DOCX_TEMPLATE_PATH = ROOT / "skills" / "office-to-markdown" / "assets" / "docx-template.md"
EXCEL_TEMPLATE_PATH = ROOT / "skills" / "office-to-markdown" / "assets" / "excel-template.md"
PPTX_TEMPLATE_PATH = ROOT / "skills" / "office-to-markdown" / "assets" / "pptx-template.md"


def load_script_module():
    spec = importlib.util.spec_from_file_location("office_to_markdown_skill_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


office_to_markdown = load_script_module()


def write_zip(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for member, content in members.items():
            archive.writestr(member, textwrap.dedent(content).strip())


def test_skill_files_exist():
    assert SKILL_MD_PATH.is_file()
    assert SCRIPT_PATH.is_file()
    assert TEMPLATE_PATH.is_file()
    assert DOCX_TEMPLATE_PATH.is_file()
    assert EXCEL_TEMPLATE_PATH.is_file()
    assert PPTX_TEMPLATE_PATH.is_file()


def test_default_template_path_uses_docx_template():
    assert office_to_markdown.default_template_path(Path("sample.docx")) == DOCX_TEMPLATE_PATH


def test_default_template_path_uses_excel_template():
    assert office_to_markdown.default_template_path(Path("sample.xlsx")) == EXCEL_TEMPLATE_PATH


def test_default_template_path_uses_pptx_template():
    assert office_to_markdown.default_template_path(Path("sample.pptx")) == PPTX_TEMPLATE_PATH


def test_default_template_path_falls_back_to_generic_template():
    assert office_to_markdown.default_template_path(Path("sample.txt")) == TEMPLATE_PATH


def test_convert_docx_to_markdown(workspace_dir: Path):
    docx_path = workspace_dir / "sample.docx"
    write_zip(
        docx_path,
        {
            "word/document.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p>
                      <w:pPr><w:pStyle w:val="Heading1" /></w:pPr>
                      <w:r><w:t>Quarterly Report</w:t></w:r>
                    </w:p>
                    <w:p>
                      <w:r><w:t>Overview paragraph.</w:t></w:r>
                    </w:p>
                    <w:tbl>
                      <w:tr>
                        <w:tc><w:p><w:r><w:t>Metric</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>
                      </w:tr>
                      <w:tr>
                        <w:tc><w:p><w:r><w:t>Revenue</w:t></w:r></w:p></w:tc>
                        <w:tc><w:p><w:r><w:t>120</w:t></w:r></w:p></w:tc>
                      </w:tr>
                    </w:tbl>
                  </w:body>
                </w:document>
            """,
        },
    )

    markdown = office_to_markdown.build_markdown(docx_path, TEMPLATE_PATH)

    assert "# sample" in markdown
    assert "Microsoft Word (.docx)" in markdown
    assert "# Quarterly Report" in markdown
    assert "Overview paragraph." in markdown
    assert "| Metric | Value |" in markdown
    assert "| Revenue | 120 |" in markdown


def test_docx_repeat_template_blocks(workspace_dir: Path):
    docx_path = workspace_dir / "repeat.docx"
    template_path = workspace_dir / "docx-repeat.md"
    write_zip(
        docx_path,
        {
            "word/document.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Second paragraph.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
            """,
        },
    )
    template_path.write_text(
        "{{#document_paragraphs}}P{{document_paragraph_index}}={{document_paragraph_content}}\n{{/document_paragraphs}}",
        encoding="utf-8",
    )

    markdown = office_to_markdown.build_markdown(docx_path, template_path)

    assert "P1=First paragraph." in markdown
    assert "P2=Second paragraph." in markdown


def test_convert_xlsx_to_markdown(workspace_dir: Path):
    xlsx_path = workspace_dir / "book.xlsx"
    write_zip(
        xlsx_path,
        {
            "xl/workbook.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets>
                    <sheet name="Summary" sheetId="1" r:id="rId1" />
                  </sheets>
                </workbook>
            """,
            "xl/_rels/workbook.xml.rels": """
                <?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                    Target="worksheets/sheet1.xml" />
                </Relationships>
            """,
            "xl/sharedStrings.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
                  <si><t>Name</t></si>
                  <si><t>Amount</t></si>
                </sst>
            """,
            "xl/worksheets/sheet1.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1">
                      <c r="A1" t="s"><v>0</v></c>
                      <c r="B1" t="s"><v>1</v></c>
                    </row>
                    <row r="2">
                      <c r="A2" t="inlineStr"><is><t>Revenue</t></is></c>
                      <c r="B2"><v>120</v></c>
                    </row>
                  </sheetData>
                </worksheet>
            """,
        },
    )

    markdown = office_to_markdown.build_markdown(xlsx_path, TEMPLATE_PATH, title="Workbook Export")

    assert "# Workbook Export" in markdown
    assert "Microsoft Excel (.xlsx)" in markdown
    assert "## Sheet: Summary" in markdown
    assert "| Name | Amount |" in markdown
    assert "| Revenue | 120 |" in markdown


def test_xlsx_repeat_template_blocks(workspace_dir: Path):
    xlsx_path = workspace_dir / "repeat.xlsx"
    template_path = workspace_dir / "xlsx-repeat.md"
    write_zip(
        xlsx_path,
        {
            "xl/workbook.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets>
                    <sheet name="Alpha" sheetId="1" r:id="rId1" />
                    <sheet name="Beta" sheetId="2" r:id="rId2" />
                  </sheets>
                </workbook>
            """,
            "xl/_rels/workbook.xml.rels": """
                <?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                    Target="worksheets/sheet1.xml" />
                  <Relationship Id="rId2"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                    Target="worksheets/sheet2.xml" />
                </Relationships>
            """,
            "xl/worksheets/sheet1.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1"><c r="A1" t="inlineStr"><is><t>A</t></is></c></row>
                  </sheetData>
                </worksheet>
            """,
            "xl/worksheets/sheet2.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1"><c r="A1" t="inlineStr"><is><t>B</t></is></c></row>
                  </sheetData>
                </worksheet>
            """,
        },
    )
    template_path.write_text(
        "{{#workbook_sheets}}S{{sheet_index}}={{sheet_name}}\n{{sheet_content}}\n{{/workbook_sheets}}",
        encoding="utf-8",
    )

    markdown = office_to_markdown.build_markdown(xlsx_path, template_path)

    assert "S1=Alpha" in markdown
    assert "S2=Beta" in markdown


def test_convert_pptx_to_markdown(workspace_dir: Path):
    pptx_path = workspace_dir / "slides.pptx"
    write_zip(
        pptx_path,
        {
            "ppt/presentation.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst>
                    <p:sldId id="256" r:id="rId1" />
                  </p:sldIdLst>
                </p:presentation>
            """,
            "ppt/_rels/presentation.xml.rels": """
                <?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
                    Target="slides/slide1.xml" />
                </Relationships>
            """,
            "ppt/slides/slide1.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
                  <p:cSld>
                    <p:spTree>
                      <p:sp>
                        <p:nvSpPr>
                          <p:nvPr><p:ph type="title" /></p:nvPr>
                        </p:nvSpPr>
                        <p:txBody>
                          <a:p><a:r><a:t>Roadmap</a:t></a:r></a:p>
                        </p:txBody>
                      </p:sp>
                      <p:sp>
                        <p:txBody>
                          <a:p><a:r><a:t>Launch beta</a:t></a:r></a:p>
                          <a:p><a:r><a:t>Collect feedback</a:t></a:r></a:p>
                        </p:txBody>
                      </p:sp>
                    </p:spTree>
                  </p:cSld>
                </p:sld>
            """,
        },
    )

    markdown = office_to_markdown.build_markdown(pptx_path, TEMPLATE_PATH)

    assert "# slides" in markdown
    assert "Microsoft PowerPoint (.pptx)" in markdown
    assert "## Slide 1: Roadmap" in markdown
    assert "Launch beta" in markdown
    assert "Collect feedback" in markdown
    assert "- Launch beta" not in markdown
    assert "- Collect feedback" not in markdown


def test_pptx_repeat_template_blocks(workspace_dir: Path):
    pptx_path = workspace_dir / "repeat.pptx"
    template_path = workspace_dir / "pptx-repeat.md"
    write_zip(
        pptx_path,
        {
            "ppt/presentation.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst>
                    <p:sldId id="256" r:id="rId1" />
                    <p:sldId id="257" r:id="rId2" />
                  </p:sldIdLst>
                </p:presentation>
            """,
            "ppt/_rels/presentation.xml.rels": """
                <?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
                    Target="slides/slide1.xml" />
                  <Relationship Id="rId2"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
                    Target="slides/slide2.xml" />
                </Relationships>
            """,
            "ppt/slides/slide1.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
                  <p:cSld><p:spTree>
                    <p:sp>
                      <p:nvSpPr><p:nvPr><p:ph type="title" /></p:nvPr></p:nvSpPr>
                      <p:txBody><a:p><a:r><a:t>One</a:t></a:r></a:p></p:txBody>
                    </p:sp>
                  </p:spTree></p:cSld>
                </p:sld>
            """,
            "ppt/slides/slide2.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
                  <p:cSld><p:spTree>
                    <p:sp>
                      <p:nvSpPr><p:nvPr><p:ph type="title" /></p:nvPr></p:nvSpPr>
                      <p:txBody><a:p><a:r><a:t>Two</a:t></a:r></a:p></p:txBody>
                    </p:sp>
                  </p:spTree></p:cSld>
                </p:sld>
            """,
        },
    )
    template_path.write_text(
        "{{#presentation_slides}}SLIDE {{slide_index}}={{slide_title}}\n{{/presentation_slides}}",
        encoding="utf-8",
    )

    markdown = office_to_markdown.build_markdown(pptx_path, template_path)

    assert "SLIDE 1=One" in markdown
    assert "SLIDE 2=Two" in markdown


def test_cli_writes_output_file(workspace_dir: Path):
    docx_path = workspace_dir / "meeting.docx"
    output_path = workspace_dir / "meeting.md"
    write_zip(
        docx_path,
        {
            "word/document.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Meeting notes.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
            """,
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "--input",
            str(docx_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    saved_markdown = output_path.read_text(encoding="utf-8")
    assert saved_markdown.startswith("# meeting")
    assert "Document Source:" in saved_markdown


def test_cli_discovers_single_pptx_by_kind(workspace_dir: Path):
    pptx_path = workspace_dir / "deck.pptx"
    write_zip(
        pptx_path,
        {
            "ppt/presentation.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst>
                    <p:sldId id="256" r:id="rId1" />
                  </p:sldIdLst>
                </p:presentation>
            """,
            "ppt/_rels/presentation.xml.rels": """
                <?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
                    Target="slides/slide1.xml" />
                </Relationships>
            """,
            "ppt/slides/slide1.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
                  <p:cSld>
                    <p:spTree>
                      <p:sp>
                        <p:nvSpPr>
                          <p:nvPr><p:ph type="title" /></p:nvPr>
                        </p:nvSpPr>
                        <p:txBody>
                          <a:p><a:r><a:t>Auto Discovery</a:t></a:r></a:p>
                        </p:txBody>
                      </p:sp>
                    </p:spTree>
                  </p:cSld>
                </p:sld>
            """,
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace_dir),
            "--kind",
            "pptx",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0
    assert "# deck" in completed.stdout
    assert "Presentation Source:" in completed.stdout
    assert "## Slide 1: Auto Discovery" in completed.stdout


def test_resolve_input_file_matches_partial_workspace_path(workspace_dir: Path):
    target = workspace_dir / "reports" / "quarterly-roadmap-final.pptx"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_zip(
        target,
        {
            "ppt/presentation.xml": """
                <?xml version="1.0" encoding="UTF-8"?>
                <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <p:sldIdLst />
                </p:presentation>
            """,
        },
    )

    resolved = office_to_markdown.resolve_input_file(
        workspace_dir,
        "quarterly roadmap",
        kind="pptx",
        query="pptxをマークダウンに変換して",
    )

    assert resolved == target.resolve()


def test_legacy_binary_format_is_rejected(workspace_dir: Path):
    path = workspace_dir / "legacy.doc"
    path.write_bytes(b"not-ooxml")

    try:
        office_to_markdown.build_markdown(path, TEMPLATE_PATH)
    except SystemExit as exc:
        assert "Legacy Office binary formats are not supported" in str(exc)
    else:
        raise AssertionError("SystemExit was not raised")
