from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .runner import analyze_store, collect, ingest_existing_run, report_store
from .pipeline import enrich_store, prefilter_store, review_store


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
    for name in ("collect", "ingest", "analyze", "report", "prefilter", "enrich", "review", "pipeline"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", required=True)
        if name != "collect" and name != "pipeline":
            sub.add_argument("--run-id", required=True)
        if name == "report":
            sub.add_argument("--output-suffix", default="", help="报告文件名后缀，例如 fixed")
    collect_parser = subparsers.choices["collect"]
    collect_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    collect_parser.add_argument("--platform", action="append", help="只运行指定平台，可重复传入")
    collect_parser.add_argument("--keyword", action="append", help="只运行指定关键词，可重复传入")
    collect_parser.add_argument("--max-contents", type=int)
    collect_parser.add_argument("--max-comments", type=int)
    collect_parser.add_argument("--task-timeout-seconds", type=int)
    prefilter_parser = subparsers.choices["prefilter"]
    prefilter_parser.add_argument("--max-candidates", type=int, default=50)
    enrich_parser = subparsers.choices["enrich"]
    enrich_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    review_parser = subparsers.choices["review"]
    review_parser.add_argument("--codex", default="codex")
    pipeline_parser = subparsers.choices["pipeline"]
    pipeline_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    pipeline_parser.add_argument("--run-id")
    pipeline_parser.add_argument("--max-candidates", type=int, default=50)
    pipeline_parser.add_argument("--codex", default="codex")
    pipeline_parser.add_argument("--skip-crawl", action="store_true")
    pipeline_parser.add_argument("--max-contents", type=int)
    pipeline_parser.add_argument("--max-comments", type=int)
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
    elif args.command == "prefilter":
        leads = prefilter_store(config, args.run_id, args.max_candidates)
        payload = {"run_id": args.run_id, "prefilter_count": len(leads)}
    elif args.command == "enrich":
        result = enrich_store(config, Path(args.repo_root), args.run_id)
        payload = {"run_id": args.run_id, **result}
    elif args.command == "review":
        result = review_store(config, args.run_id, codex=args.codex)
        payload = {"run_id": args.run_id, **result}
    elif args.command == "pipeline":
        from .ego_crawl_all import run_ego_crawlers

        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if args.max_contents is not None or args.max_comments is not None:
            updates = {}
            if args.max_contents is not None:
                updates["max_contents"] = args.max_contents
            if args.max_comments is not None:
                updates["max_comments"] = args.max_comments
            config = replace(config, **updates)
        if not args.skip_crawl:
            run_ego_crawlers(run_id, config.platforms, config, Path(args.repo_root), config.data_root)
        ingest_existing_run(config, run_id)
        prefilter_store(config, run_id, args.max_candidates)
        enrich_store(config, Path(args.repo_root), run_id)
        review_result = review_store(config, run_id, codex=args.codex)
        report_path = report_store(config, run_id, "pipeline")
        payload = {"run_id": run_id, "report_path": str(report_path), **review_result}
    else:
        path = report_store(config, args.run_id, args.output_suffix)
        payload = {"run_id": args.run_id, "report_path": str(path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
