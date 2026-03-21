# Playbook outline

Use this file when deciding how to turn a software-design markdown document into a reference-backed implementation Skill for writing or modifying code in a software development company.

## Default split

Use this split unless the source document is very small:

1. `SKILL.md`
2. `references/overview.md`
3. `references/acceptance-criteria.md`

Add more references only when the source material actually contains them.

## What belongs in `SKILL.md`

- the operating procedure for the future agent
- the expected install destination convention when it matters to generated output
- the rule for checking existing standard skill directories before choosing that destination
- what to inspect first
- how to use bundled references
- how to move from design to code safely
- what not to do
- output and verification rules

Keep `SKILL.md` short enough that another agent can load it quickly and act.

## What belongs in references

Create targeted reference files for stable detailed facts:

- domain model and entities
- API endpoints and payload fields
- database schema notes
- module boundaries and integration points
- workflow and state transitions
- UI states and edge cases
- acceptance criteria
- implementation constraints
- rollout constraints

Prefer one concern per file when possible.

## Suggested reference file names

- `references/overview.md`
- `references/domain-model.md`
- `references/api-contracts.md`
- `references/data-model.md`
- `references/ui-flows.md`
- `references/business-rules.md`
- `references/implementation-notes.md`
- `references/acceptance-criteria.md`
- `references/open-questions.md`

Do not create empty placeholders. Only create the files supported by the source design markdown.

## Compression rules

- keep exact identifiers and invariants
- compress prose explanations
- preserve lists of constraints, non-goals, and edge cases
- rewrite long sections into compact bullets when meaning is unchanged
- keep unresolved decisions explicit

## Extraction checklist

- main objective
- actors or users
- core flows
- error cases
- interfaces and contracts
- code touch points or ownership boundaries
- dependencies
- test or acceptance expectations
- rollout notes
