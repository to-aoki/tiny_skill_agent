---
name: repo-map
description: Use this skill when the user asks for a quick repository overview, asks where code lives, wants likely entry points, or wants a first-pass map of a codebase before implementation. Activate even if the user does not explicitly say "repository map".
compatibility: Python 3.10+ recommended. Optional bundled script can inspect a local workspace.
allowed-tools:
  - read-files
  - run-local-scripts
metadata:
  author: Toshihiko Aoki
  version: "0.1"
---
# Repository map skill

When this skill is activated, first inspect the workspace snapshot the host agent already provided.
If that snapshot is enough, answer directly.
If you need a better repository map, you may request execution of `scripts/repo_map.py`.

## Goals

- Identify likely app entry points.
- Identify important folders and what they contain.
- Point out test locations if present.
- Keep the summary short and actionable.

## Output shape

Use the guidance in `references/output-format.md`.

## Script usage

If the current task is asking for a repository overview or architecture sketch, you may request:

`python scripts/repo_map.py --max-files 80 --max-depth 4`

The host runner will prepend `--workspace <path>` automatically.
