from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "skills" / "pdf-to-markdown" / "scripts" / "pdf_to_markdown.py"
SKILL_MD_PATH = ROOT / "skills" / "pdf-to-markdown" / "SKILL.md"
TEMPLATE_PATH = ROOT / "skills" / "pdf-to-markdown" / "assets" / "pdf-template.md"


def load_script_module():
    spec = importlib.util.spec_from_file_location("pdf_to_markdown_skill_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pdf_to_markdown = load_script_module()


def test_skill_files_exist():
    assert SKILL_MD_PATH.is_file()
    assert SCRIPT_PATH.is_file()
    assert TEMPLATE_PATH.is_file()


def test_script_declares_pep_723_metadata():
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "# /// script" in text
    assert '"pdfplumber>=' in text


def test_build_markdown_uses_extracted_pages(workspace_dir: Path):
    pdf_path = workspace_dir / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mock\n")

    markdown = pdf_to_markdown.build_markdown(
        pdf_path,
        TEMPLATE_PATH,
        extractor=lambda _: [
            pdf_to_markdown.PageContent(
                index=1,
                heading="Page 1",
                text="Quarterly report\n\nRevenue increased.",
                tables=["| Metric | Value |\n| --- | --- |\n| Revenue | 120 |"],
            ),
            pdf_to_markdown.PageContent(
                index=2,
                heading="Page 2",
                text="Next steps",
                tables=[],
            ),
        ],
    )

    assert "# report" in markdown
    assert "PDF Source:" in markdown
    assert "Source Type: PDF (.pdf)" in markdown
    assert "## Page 1" in markdown
    assert "Revenue increased." in markdown
    assert "| Revenue | 120 |" in markdown
    assert "## Page 2" in markdown


def test_resolve_input_file_matches_partial_workspace_path(workspace_dir: Path):
    target = workspace_dir / "docs" / "quarterly-report-final.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"%PDF-1.4\n%mock\n")

    resolved = pdf_to_markdown.resolve_input_file(
        workspace_dir,
        "quarterly report",
        kind="pdf",
        query="pdfをマークダウンに変換して",
    )

    assert resolved == target.resolve()
