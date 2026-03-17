#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def should_skip(path: Path) -> bool:
    skip_names = {'.git','.venv','node_modules','dist','build','target','__pycache__','.mypy_cache','.pytest_cache','.idea','.vscode'}
    return any(part in skip_names for part in path.parts)


def infer_role(path: Path) -> str | None:
    name = path.name.lower()
    if name in {'src','app','server','backend','frontend','web'}:
        return 'application code'
    if name in {'tests','test','spec','specs'}:
        return 'tests'
    if name in {'docs','doc'}:
        return 'documentation'
    if name in {'scripts','bin','tools'}:
        return 'scripts and tooling'
    if name in {'migrations','alembic'}:
        return 'database migrations'
    return None


def detect_entry_points(files: list[Path]) -> list[str]:
    preferred = {'main.py','app.py','manage.py','server.py','cli.py','index.js','main.ts','package.json','pyproject.toml','Cargo.toml','go.mod'}
    return [str(path) for path in files if path.name in preferred][:12]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--max-files', type=int, default=80)
    parser.add_argument('--max-depth', type=int, default=4)
    args = parser.parse_args()

    root = Path(args.workspace).resolve()
    all_files: list[Path] = []
    directories: dict[str, dict[str, object]] = {}

    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if should_skip(rel) or len(rel.parts) > args.max_depth:
            continue
        if path.is_dir():
            directories[str(rel)] = {'role': infer_role(rel), 'children_sample': []}
            continue
        all_files.append(rel)
        parent = '' if str(rel.parent) == '.' else str(rel.parent)
        directory = directories.setdefault(parent, {'role': infer_role(rel.parent), 'children_sample': []})
        sample = directory['children_sample']
        if isinstance(sample, list) and len(sample) < 8:
            sample.append(rel.name)
        if len(all_files) >= args.max_files:
            break

    print(json.dumps({
        'workspace': str(root),
        'file_count_sampled': len(all_files),
        'directories': directories,
        'entry_points': detect_entry_points(all_files),
        'sample_files': [str(p) for p in all_files[:args.max_files]],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
