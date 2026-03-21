---
name: pdf-to-markdown
description: Use this skill when the user asks to convert a PDF file into Markdown. The file path may be explicit, partial, or omitted if the target PDF can be inferred from the workspace. Use it for text-based .pdf files and create or return Markdown output by running the bundled pdfplumber-based script.
compatibility: Python 3.10+ recommended. Bundled Python script uses PEP 723 inline metadata and pdfplumber via uv run.
allowed-tools:
  - read
  - write
  - shell
---
# PDF to Markdown

Use this skill only for PDF to Markdown conversion.
For every conversion request, you must use the bundled script `scripts/pdf_to_markdown.py`.
Do not convert PDF files manually in your own reasoning or by writing the Markdown yourself.

## Supported files

- `.pdf`

Use this skill for text PDFs.
If the PDF appears to be image-only or scanned, say that plain text extraction may be limited because this skill does not perform OCR.

## Do This

1. Find the target PDF file.
2. Run `uv run scripts/pdf_to_markdown.py` once. This step is mandatory.
3. If the user asked for a file, use `--output`.
4. If the user did not ask for a file, return the Markdown result.
5. After the conversion result is available, stop.

Workspace discovery and output paths must stay inside the workspace scope provided by the host runner.

## Do Not Do This

- Do not think in loops.
- Do not repeat the same judgment.
- Do not output self-talk.
- Do not run the script more than once unless the first run clearly failed.
- Do not do extra formatting passes.
- Do not answer from memory instead of running the script.
- Do not inspect PDF bytes and then compose the Markdown by hand.
- Do not skip the script even if the expected output seems obvious.

## Commands

Basic:

`uv run scripts/pdf_to_markdown.py --input <path>`

Write file:

`uv run scripts/pdf_to_markdown.py --input <path> --output <path-to-markdown>`

If the file path is missing, use workspace discovery:

`uv run scripts/pdf_to_markdown.py --kind pdf`

If the file path is vague, use a query:

`uv run scripts/pdf_to_markdown.py --kind pdf --query "quarterly report"`

Optional:

- `--title <title>`
- `--template <path>`
- `--kind <pdf>`
- `--query <text>`

The host runner prepends `--workspace <path>` automatically.

## Templates

Default template:

- `assets/pdf-template.md`

Use a custom template only if the user asks for a specific layout.

## Output Rules

- Preserve the extracted structure page by page.
- Keep page headings, paragraphs, and tables when possible.
- If a page has no extractable text, say so plainly.
- If the whole PDF has little or no extractable text, say so plainly.

## Final Response

If you created a file, say which file you created.
If you did not create a file, return the converted Markdown.
Do not add analysis before or after the result.
Before the final response, confirm that the script was run and use its result.
