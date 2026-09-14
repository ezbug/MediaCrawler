from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .runner import analyze_store, collect, ingest_existing_run, report_store


def apply_collect_overrides(config, args):
    updates = {}
    if args.platform:
        updates["platforms"] = args.platform
    if args.keyword:
        original_categories = {keyword: category for category, keyword in config.keywords.items()}
        keywords = {}
        for index, keyword in enumerate(args.keyword, start=1):
            category = original_categories.get(keyword, f"自定义{index}")
            keywords[category] = keyword
        updates["keywords"] = keywords
    for name in ("max_contents", "max_comments", "task_timeout_seconds"):
        value = getattr(args, name)
        if value is not None:
            updates[name] = value
    return replace(config, **updates) if updates else config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local POLYV demand radar.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "ingest", "analyze", "report"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", required=True)
        if name != "collect":
            sub.add_argument("--run-id", required=True)
    collect_parser = subparsers.choices["collect"]
    collect_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    collect_parser.add_argument("--platform", action="append", help="只运行指定平台，可重复传入")
    collect_parser.add_argument("--keyword", action="append", help="只运行指定关键词，可重复传入")
    collect_parser.add_argument("--max-contents", type=int)
    collect_parser.add_argument("--max-comments", type=int)
    collect_parser.add_argument("--task-timeout-seconds", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    if args.command == "collect":
        config = apply_collect_overrides(config, args)
        result = collect(config, Path(args.repo_root))
        payload = {"run_id": result.run_id, "store_path": str(result.store_path), "failures": result.failures}
    elif args.command == "ingest":
        result = ingest_existing_run(config, args.run_id)
        payload = {"run_id": result.run_id, "store_path": str(result.store_path), "failures": result.failures}
    elif args.command == "analyze":
        leads = analyze_store(config, args.run_id)
        payload = {"run_id": args.run_id, "review_count": len(leads)}
    else:
        path = report_store(config, args.run_id)
        payload = {"run_id": args.run_id, "report_path": str(path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
