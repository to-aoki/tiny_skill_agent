---
name: skills-bundler
description: Use this skill when the user wants to browse a directory that contains many Agent Skills, choose a subset that matches a request, and export the selected skill folders as one `<group-name>.zip` archive. Use it for cloned skill collections such as `awesome-copilot/skills`, for packaging up to a requested count of skills at a time, and for saving the archive into a target workspace directory.
compatibility: Python 3.10+ recommended. Bundled Python script catalogs skills, recommends matches from a query, and writes zip archives.
allowed-tools:
  - read
  - write
  - shell
metadata:
  author: Toshihiko Aoki
  version: "0.1"
---
# Skills bundler

Use this skill only for selecting and packaging skill folders.
For every packaging request, use the bundled script `scripts/skills_bundler.py`.
Do not build zip files manually.

## Do This

1. Identify the source directory that contains multiple skill folders.
2. Run the catalog command to inspect available skills.
3. If the user described what they want but did not name exact skills, run the recommend command with the user request and a limit. The default limit is `5`.
4. The script first does a loose filter using only skill `name` and `description`.
5. Treat the script output as a shortlist only.
6. Use this SKILL's instructions in the outer LLM to re-evaluate the shortlisted `name` and `description` values against the user's actual query.
7. Read individual candidate `SKILL.md` files only when the shortlist is ambiguous, when two skills look very similar, or when the user asks why a skill was chosen.
8. Select the final candidates in the outer LLM, not inside the script.
9. Run the archive command once with the final selected skill names.
10. Save the zip file into the requested output directory. If none is specified, use the workspace root.
11. Report the created archive path and the included skill names.

Source inspection and archive output must stay inside the workspace scope provided by the host runner.

## Do Not Do This

- Do not select more skills than the user requested.
- Do not exceed `5` skills unless the user explicitly asks for a larger number.
- Do not write outside the workspace unless the user explicitly asks for it and the host allows it.
- Do not create ad-hoc copies of the skill folders outside the zip archive.
- Do not guess skill contents without inspecting the catalog or the relevant `SKILL.md`.
- Do not implement LLM selection inside the script itself.
- Do not treat the shortlist returned by the script as the final answer without outer-LLM review.

## Commands

Catalog:

`python scripts/skills_bundler.py catalog --source-dir <skills-directory>`

Online catalog:

`python scripts/skills_bundler.py catalog --source-url https://github.com/github/awesome-copilot`

Recommend:

`python scripts/skills_bundler.py recommend --source-dir <skills-directory> --query "<user request>" --limit 5`

Online recommend:

`python scripts/skills_bundler.py recommend --source-url https://github.com/github/awesome-copilot --query "<user request>" --limit 5`

Archive:

`python scripts/skills_bundler.py archive --source-dir <skills-directory> --skills <skill-a> <skill-b> --limit 5`

Optional archive arguments:

- `--group-name <name>`
- `--output-dir <dir>`

The host runner prepends `--workspace <path>` automatically.

## Selection Rules

- Use `recommend` to produce a loose shortlist from `name` and `description`.
- Then let the outer LLM select the best candidates from that shortlist using this SKILL.md.
- Prefer a smaller, precise bundle over a broad one.
- If the user names exact skills, skip recommendation and archive those skills directly.
- If the user asks for a count but no exact names, use that count as `--limit`.
- If the user gives no count, use `5`.

## Output Rules

- Keep the zip filename as `<group-name>.zip`.
- If `--group-name` is omitted, rely on the script's generated group name.
- Preserve each selected skill as its own directory inside the archive.

## Final Response

If the archive was created, say which zip file was created and list the included skills.
Do not add a long explanation after the result.
