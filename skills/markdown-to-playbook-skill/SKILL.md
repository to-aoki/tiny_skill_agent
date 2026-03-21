---
name: markdown-to-playbook-skill
description: Use this skill when the user wants to turn one or more Markdown design, requirements, architecture, API, schema, ADR, or implementation-plan files into a new Agent Skill for a software development company. The generated Skill must help an agent read Markdown source material and then write or modify production code using a reference-backed implementation playbook, especially when the result should separate operational guidance in SKILL.md from detailed engineering references.
---
# Markdown to playbook skill

Use this skill only for creating or updating a Skill whose source of truth is a software design Markdown file.
The generated Skill must help another Codex instance move from design to code inside a software development workflow, not merely summarize the document.

## Goals

- Convert software design markdown into a coding-oriented Skill.
- Keep the generated `SKILL.md` concise and procedural.
- Move detailed design content into `references/` files when it would bloat `SKILL.md`.
- Preserve engineering constraints that matter while writing code.
- Bundle templates or scripts only when they remove repeated engineering work.

## Workflow

1. Read the design markdown file the user provided or pointed to.
2. Extract the implementation-critical items:
   - product or feature goal
   - user-visible behavior
   - existing-system context
   - constraints and non-goals
   - architecture decisions
   - API, schema, event, and data contracts
   - testing, rollout, and backward-compatibility expectations
3. Decide the reusable contents for the generated Skill:
   - `SKILL.md` for the operating procedure
   - `references/` for detailed engineering specs, schemas, flows, acceptance criteria, or copied excerpts from the design
   - `assets/` for templates that the future agent should copy or adapt
   - `scripts/` only when repeated deterministic processing is clearly useful
4. Determine the generated Skill destination before writing files:
   - first check whether `.github/skills` and `.claude/skills` already exist in the workspace
   - if the user explicitly requested GitHub Copilot-style placement, use `.github/skills/<skill-name>`
   - if the user explicitly requested Claude-style placement, use `.claude/skills/<skill-name>`
   - if only one of `.github/skills` or `.claude/skills` exists, use the existing standard directory
   - if both exist and the user did not specify, prefer `.github/skills/<skill-name>`
   - if neither exists and the user did not specify, default to `.github/skills/<skill-name>`
   - treat `github/skills/<skill-name>` without the leading dot as invalid and correct it to `.github/skills/<skill-name>`
   - do not invent another default destination such as a top-level `skills/` directory
5. Name the generated Skill with a short hyphen-case action phrase under 64 characters.
6. Write the generated `SKILL.md` in imperative form.
7. Make the generated `description` do the trigger work:
   - say what the Skill does
   - say what kinds of source documents or user requests should activate it
   - include likely task phrases
8. Keep the generated `SKILL.md` focused on execution:
   - what to inspect first
   - what code constraints to preserve from the design
   - which bundled resources to read and when
   - implementation and verification rules
9. Put detailed reference material into `references/` instead of duplicating it in `SKILL.md`.
10. If the design markdown is incomplete, call out the missing engineering inputs plainly before generating the final Skill contents.

## Resource selection rules

- Create a `references/overview.md` file when the design document is long or covers multiple engineering concerns.
- Split references by concern when that helps selective loading:
  - `references/domain-model.md`
  - `references/api-contracts.md`
  - `references/implementation-notes.md`
  - `references/ui-flows.md`
  - `references/acceptance-criteria.md`
- Preserve exact field names, endpoint names, event names, table names, config keys, and invariants in references.
- Do not copy large narrative sections into `SKILL.md`.
- Do not create `scripts/` unless the same transformation would otherwise be rewritten repeatedly.
- Prefer references that help safe code changes: existing interfaces, migration constraints, compatibility notes, and testing expectations.

## How to map design markdown into the generated Skill

Use `assets/generated-skill-template.md` as the structural baseline for the generated `SKILL.md`.
Use `references/playbook-outline.md` to decide how to split the source design into references.

Apply this mapping:

- problem statement -> generated Skill purpose and goals
- requirements and user stories -> execution rules and acceptance references
- architecture notes -> implementation constraints and reference files
- repository or module notes -> implementation entry points and inspection order
- API, schema, or event details -> dedicated reference files
- test strategy -> verification rules and acceptance references
- open questions -> explicit unresolved-items section or a blocking note to the user

## Output expectations

The generated Skill should usually contain:

- `SKILL.md`
- `references/` with only the reference files that are actually useful

Optional:

- `assets/` for templates or starter files used during implementation
- `scripts/` for deterministic helpers

The generated Skill should make a future agent more reliable at writing code that matches the design, especially in repositories with existing conventions or integration constraints.
The generated Skill directory should follow the same destination convention as `skills-bundler`: prefer `.github/skills` by default and use `.claude/skills` when that target is explicitly requested.
Before finalizing any generated path, explicitly check that GitHub-style destinations begin with `.github/skills/` and not `github/skills/`.
If a standard install directory decision is needed, inspect the workspace first instead of guessing.

## Do not do this

- Do not produce a summary-only Skill.
- Do not leave the generated Skill without a strong trigger description.
- Do not stuff all design details into one oversized `SKILL.md`.
- Do not invent missing implementation details as if they were confirmed facts.
- Do not ignore existing-code integration constraints found in the design.
- Do not add extra docs such as `README.md` or `CHANGELOG.md`.

## Final response

When you create the new Skill, report:

- the created Skill path
- the included reference files
- any gaps or assumptions taken from the source design markdown
