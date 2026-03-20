---
name: office-to-markdown
description: Use this skill when the user asks to convert a Microsoft Word, Excel, or PowerPoint file into Markdown. The file path may be explicit, partial, or omitted if the target Office file can be inferred from the workspace. Use it for .docx, .xlsx, and .pptx files, and create or return Markdown output.
compatibility: Python 3.10+ recommended. Bundled Python script converts OOXML Office files to Markdown without extra dependencies.
allowed-tools:
  - read
  - write
  - shell
metadata:
  author: Toshihiko Aoki
  version: "0.1"
---
# Office to Markdown

Use this skill only for Office to Markdown conversion.
For every conversion request, you must use the bundled script `scripts/office_to_markdown.py`.
Do not convert Office files manually in your own reasoning or by writing the Markdown yourself.

## Supported files

- `.docx`
- `.xlsx`
- `.pptx`

Do not use this skill for `.doc`, `.xls`, or `.ppt`.
If the user gives one of those old formats, tell them to save it as `.docx`, `.xlsx`, or `.pptx`.

## Do This

1. Find the target Office file.
2. Run `scripts/office_to_markdown.py` once. This step is mandatory.
3. If the user asked for a file, use `--output`.
4. If the user did not ask for a file, return the Markdown result.
5. After the conversion result is available, stop.

Workspace discovery and output paths must stay inside the workspace scope provided by the host runner.

## Do Not Do This

- Do not think in loops.
- Do not repeat the same judgment.
- Do not output self-talk.
- Do not output filler such as `Yes.`, `Ok.`, `The end.`
- Do not run the script more than once unless the first run clearly failed.
- Do not do extra formatting passes.
- Do not answer from memory instead of running the script.
- Do not inspect Office XML and then compose the Markdown by hand.
- Do not skip the script even if the expected output seems obvious.

## Commands

Basic:

`python scripts/office_to_markdown.py --input <path>`

Write file:

`python scripts/office_to_markdown.py --input <path> --output <path-to-markdown>`

If the file path is missing, use workspace discovery:

`python scripts/office_to_markdown.py --kind pptx`

If the file path is vague, use a query:

`python scripts/office_to_markdown.py --kind pptx --query "quarterly roadmap"`

Optional:

- `--title <title>`
- `--template <path>`
- `--kind <word|excel|powerpoint|docx|xlsx|pptx>`
- `--query <text>`

The host runner prepends `--workspace <path>` automatically.

## Templates

Default template:

- `assets/markdown-template.md`

Format-specific templates:

- `assets/docx-template.md`
- `assets/excel-template.md`
- `assets/pptx-template.md`

Use a format-specific template only if the user asks for a specific layout.

## Output Rules

- Preserve the extracted structure.
- Word: keep headings, paragraphs, and tables when possible.
- Excel: output one section per sheet.
- PowerPoint: output one section per slide.
- If there is little or no text, say so plainly.

## Final Response

If you created a file, say which file you created.
If you did not create a file, return the converted Markdown.
Do not add analysis before or after the result.
Before the final response, confirm that the script was run and use its result.
