"""CLI 入口の引数解析と起動処理。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI

from .agent import SkillAgent
from .skills import (
    SkillRegistry,
    build_validation_payload,
    summarize_blocking_skill_errors,
    validate_skill_roots,
)


def cli() -> argparse.Namespace:
    """CLI 引数を定義して解析結果を返す。"""
    parser = argparse.ArgumentParser(
        description="Minimal Agent Skills runner for OpenAI-compatible local LLMs"
    )
    parser.add_argument("task", nargs="?")
    parser.add_argument("--skills", nargs="+", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL", "http://192.168.1.12:8000/v1"),
    )
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "dummy"))
    parser.add_argument(
        "--model",
        default=(
            os.getenv("OPENAI_MODEL_NAME")
            or os.getenv("OPENAI_MODEL")
            or "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
        ),
    )
    parser.add_argument(
        "--openai-log-file",
        default=os.getenv("OPENAI_API_LOG_FILE"),
        help="Append OpenAI API request/response logs as JSONL.",
    )
    parser.add_argument("--allow-scripts", action="store_true")
    parser.add_argument(
        "--max-skill-turns",
        type=int,
        default=10,
        help="Maximum number of skill turns before forcing a best-effort final answer",
    )
    parser.add_argument("--show-catalog", action="store_true")
    parser.add_argument(
        "--validate-skills",
        action="store_true",
        help="Parse SKILL.md files and report validation results",
    )
    return parser.parse_args()


def main() -> None:
    """CLI 入口として設定解決と実行制御を行う。"""
    args = cli()
    workspace = Path(args.workspace)
    skill_roots = [Path(path) for path in args.skills]

    if args.show_catalog and args.validate_skills:
        raise SystemExit("Use either --show-catalog or --validate-skills, not both.")
    if args.validate_skills:
        payload = build_validation_payload(validate_skill_roots(skill_roots))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload["ok"]:
            raise SystemExit(1)
        return

    registry = SkillRegistry(skill_roots)
    if args.show_catalog:
        print(registry.catalog_text())
        return
    if not args.task:
        raise SystemExit(
            "task is required unless --show-catalog or --validate-skills is used."
        )
    if not registry.skills:
        blocking_errors = summarize_blocking_skill_errors(
            registry.validation_reports
        )
        if blocking_errors:
            raise SystemExit(f"No loadable skills were found.\n{blocking_errors}")
        raise SystemExit("No skills were found. Add a ./skills/<skill-name>/SKILL.md folder.")

    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    openai_log_file = Path(args.openai_log_file) if args.openai_log_file else None
    agent = SkillAgent(
        client=client,
        model=args.model,
        registry=registry,
        workspace=workspace,
        allow_scripts=args.allow_scripts,
        max_skill_turns=args.max_skill_turns,
        openai_log_file=openai_log_file,
    )
    print(json.dumps(agent.run(args.task), ensure_ascii=False, indent=2))
