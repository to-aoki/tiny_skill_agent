---
name: skills-bundler
description: Use this skill when the user wants to browse a directory that contains many Agent Skills, choose a subset that matches a request, and install the selected skill folders into workspace directories such as `.github/skills` or `.claude/skills`. Use it for cloned skill collections such as `awesome-copilot/skills` and for copying up to a requested count of skills at a time.
compatibility: Python 3.10+ recommended. Bundled Python script catalogs skills, recommends matches from a query, and copies selected skills into workspace directories.
allowed-tools:
  - read
  - write
  - shell
metadata:
  author: Toshihiko Aoki
  version: "0.1"
---
# Skills bundler

Use this skill only for selecting and copying skill folders.
For every packaging request, use the bundled script `scripts/skills_bundler.py`.
Do not copy skill folders manually.

## Do This

1. Identify the source directory that contains multiple skill folders.
2. Run the catalog command to inspect available skills.
3. If the user described what they want but did not name exact skills, run the recommend command with the user request and a limit. The default limit is `5`.
4. The script first does a loose filter using only skill `name` and `description`.
5. Treat the script output as a shortlist only.
6. Use this SKILL's instructions in the outer LLM to re-evaluate the shortlisted `name` and `description` values against the user's actual query.
7. Read individual candidate `SKILL.md` files only when the shortlist is ambiguous, when two skills look very similar, or when the user asks why a skill was chosen.
8. Select the final candidates in the outer LLM, not inside the script.
9. Run the copy command once with the final selected skill names.
10. Prefer `--target github` or `--target claude` when the user wants those standard destinations. If the user does not specify which standard destination to use, prefer GitHub-style placement in `.github/skills`. Use `--target-dir <workspace-relative-dir>` only when the user asked for another workspace path.
11. Report the copied target directory and the included skill names.
12. If a target skill directory already exists, leave it untouched and report it as skipped.

Source inspection and archive output must stay inside the workspace scope provided by the host runner.

## Do Not Do This

- Do not select more skills than the user requested.
- Do not exceed `5` skills unless the user explicitly asks for a larger number.
- Do not write outside the workspace unless the user explicitly asks for it and the host allows it.
- Do not create ad-hoc copies of the skill folders outside the script-managed copy command.
- Do not overwrite an existing target skill directory.
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

Copy into `.github/skills`:

`python scripts/skills_bundler.py copy --source-dir <skills-directory> --skills <skill-a> <skill-b> --target github --limit 5`

Copy into `.claude/skills`:

`python scripts/skills_bundler.py copy --source-dir <skills-directory> --skills <skill-a> <skill-b> --target claude --limit 5`

Optional copy argument:

- `--target-dir <workspace-relative-dir>`

The host runner prepends `--workspace <path>` automatically.

## Selection Rules

- Use `recommend` to produce a loose shortlist from `name` and `description`.
- Then let the outer LLM select the best candidates from that shortlist using this SKILL.md.
- Prefer a smaller, precise bundle over a broad one.
- If the user names exact skills, skip recommendation and copy those skills directly.
- If the user asks for a count but no exact names, use that count as `--limit`.
- If the user gives no count, use `5`.

## Output Rules

- Preserve each selected skill as its own directory under the chosen target directory.
- If a target skill directory already exists, skip it and report that it was skipped.

## Final Response

If skills were copied, say which path was created or updated, list the included skills, and mention any skipped existing directories.
Do not add a long explanation after the result.
