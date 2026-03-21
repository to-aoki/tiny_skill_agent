---
name: <generated-skill-name>
description: Use this skill when <what the generated skill does for software implementation>. Activate it for requests involving <likely trigger phrases, software design documents, implementation plans, feature specs, or code-change situations>.
---
# <Generated skill title>

Use this skill only for <narrow software implementation job to be done>.

## Goals

- <goal 1>
- <goal 2>

## Workflow

1. Read the relevant inputs first.
2. Read only the referenced files needed for the current subtask.
3. Check whether `.github/skills` and `.claude/skills` already exist in the workspace before choosing the generated Skill path.
4. Confirm the generated Skill path uses a standard install directory: use the explicitly requested standard target when provided, otherwise prefer the existing standard directory, otherwise default to `.github/skills/<generated-skill-name>`, and never `github/skills/<generated-skill-name>`.
5. Inspect the existing code touch points before changing implementation.
6. Preserve the implementation constraints defined by the source design.
7. Produce the requested code, configuration, migration, or test change.
8. Verify the result against the acceptance criteria.

## References

- Read `references/overview.md` first for the condensed design context.
- Read other reference files only when the subtask needs them.

## Rules

- Preserve exact contracts and identifiers from the references.
- Surface missing information before making irreversible assumptions.
- Keep outputs aligned with the documented non-goals and constraints.
- Prefer safe integration with the existing codebase over speculative redesign.

## Final response

Report the produced files or decisions, plus any remaining gaps.
