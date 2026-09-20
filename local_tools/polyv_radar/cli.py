from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .runner import analyze_store, collect, ingest_existing_run, report_store
from .pipeline import enrich_store, prefilter_store, review_store
from .benchmark import run_benchmark
from .hunt import run_hunt
from .locator import locate_store
from .dispatch import build_dispatch_queue, dispatch_queue, load_dispatch_queue, write_dispatch_queue, write_dispatch_results
from .storage import RadarStore
from .antigravity_import import import_antigravity
from .approval import approve_lead
from .daily import run_daily


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
        if args.platform:
            platform_keywords = {platform: dict(values) for platform, values in config.platform_keywords.items()}
            for platform in args.platform:
                platform_keywords[platform] = dict(keywords)
            updates["platform_keywords"] = platform_keywords
    for name in ("max_contents", "max_comments", "task_timeout_seconds"):
        value = getattr(args, name)
        if value is not None:
            updates[name] = value
    if getattr(args, "collector", None):
        updates["collector_backend"] = args.collector
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
    collect_parser.add_argument("--collector", choices=("ego",))
    collect_parser.add_argument("--taskspace", type=int, required=True, help="用户已登录的 Ego Lite TaskSpace")
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
    pipeline_parser.add_argument("--collector", choices=("ego",))
    pipeline_parser.add_argument("--taskspace", type=int, help="采集和定位时使用的用户 Ego Lite TaskSpace")
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--config", required=True)
    benchmark_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    benchmark_parser.add_argument("--platform", required=True, choices=("dy", "xhs", "bili", "zhihu"))
    benchmark_parser.add_argument("--keyword", action="append", help="覆盖默认基准关键词，可重复传入")
    urls_parser = subparsers.add_parser("validate-urls")
    urls_parser.add_argument("--config", required=True)
    urls_parser.add_argument("--run-id", required=True)
    locate_parser = subparsers.add_parser("locate")
    locate_parser.add_argument("--config", required=True)
    locate_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    locate_parser.add_argument("--run-id", required=True)
    locate_parser.add_argument("--taskspace", type=int, required=True)
    locate_parser.add_argument("--max-candidates", type=int, default=80)
    hunt_parser = subparsers.add_parser("hunt")
    hunt_parser.add_argument("--config", required=True)
    hunt_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    hunt_parser.add_argument("--collector", choices=("ego",), default="ego")
    hunt_parser.add_argument("--taskspace", type=int, required=True)
    hunt_parser.add_argument("--target-leads", type=int, default=20)
    hunt_parser.add_argument("--max-candidates", type=int, default=80)
    hunt_parser.add_argument("--max-batches", type=int, default=2)
    hunt_parser.add_argument("--run-id")
    hunt_parser.add_argument("--codex", default="codex")
    prepare_dispatch_parser = subparsers.add_parser("prepare-dispatch")
    prepare_dispatch_parser.add_argument("--config", required=True)
    prepare_dispatch_parser.add_argument("--run-id", required=True)
    prepare_dispatch_parser.add_argument("--selection", choices=("manual", "model"), default="manual")
    prepare_dispatch_parser.add_argument("--output")
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--config", required=True)
    dispatch_parser.add_argument("--queue", required=True)
    dispatch_parser.add_argument("--taskspace", type=int, required=True)
    dispatch_parser.add_argument("--submit", action="store_true", help="真实发送；省略时仅执行 Dry-Run")
    dispatch_parser.add_argument("--max-sends", type=int, default=5)
    dispatch_parser.add_argument("--cooldown-seconds", type=float, default=30)
    dispatch_parser.add_argument("--output")
    import_parser = subparsers.add_parser("import-antigravity")
    import_parser.add_argument("--config", required=True)
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--session-id", required=True)
    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("--config", required=True)
    approve_parser.add_argument("--run-id", required=True)
    approve_parser.add_argument("--lead-id", required=True)
    approve_parser.add_argument("--approved-by", default="user")
    approve_parser.add_argument("--draft-text", default="")
    daily_parser = subparsers.add_parser("daily")
    daily_parser.add_argument("--config", required=True)
    daily_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    daily_parser.add_argument("--taskspace", type=int, required=True)
    daily_parser.add_argument("--run-id")
    daily_parser.add_argument("--skip-crawl", action="store_true")
    daily_parser.add_argument("--submit-approved", action="store_true", help="仅发送已人工批准且已定位/验链的公开楼中楼")
    daily_parser.add_argument("--max-candidates", type=int, default=50)
    daily_parser.add_argument("--codex", default="codex")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    if args.command == "collect":
        config = apply_collect_overrides(config, args)
        result = collect(config, Path(args.repo_root), collector=args.collector, taskspace=args.taskspace)
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
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if args.max_contents is not None or args.max_comments is not None:
            updates = {}
            if args.max_contents is not None:
                updates["max_contents"] = args.max_contents
            if args.max_comments is not None:
                updates["max_comments"] = args.max_comments
            config = replace(config, **updates)
        if not args.skip_crawl:
            if args.taskspace is None:
                parser.error("pipeline 进行采集时必须提供 --taskspace")
            collect(config, Path(args.repo_root), collector=args.collector, run_id=run_id, taskspace=args.taskspace)
        else:
            ingest_existing_run(config, run_id)
        prefilter_store(config, run_id, args.max_candidates)
        enrich_store(config, Path(args.repo_root), run_id)
        review_result = review_store(config, run_id, codex=args.codex)
        report_path = report_store(config, run_id, "pipeline")
        payload = {"run_id": run_id, "report_path": str(report_path), **review_result}
    elif args.command == "benchmark":
        parser.error("benchmark 已停用：当前规则要求所有页面操作仅使用 Ego Lite。")
    elif args.command == "validate-urls":
        report_path = report_store(config, args.run_id, "url-validated")
        payload = {
            "run_id": args.run_id,
            "report_path": str(report_path),
            "url_checks_path": str(report_path.with_name(f"{args.run_id}-url-validated-url-checks.json")),
        }
    elif args.command == "locate":
        result = locate_store(
            config,
            Path(args.repo_root),
            args.run_id,
            max_candidates=args.max_candidates,
            taskspace=args.taskspace,
        )
        report_path = report_store(config, args.run_id, "located")
        payload = {
            "run_id": args.run_id,
            "report_path": str(report_path),
            "locator_checks_path": str(config.data_root / "reports" / f"{args.run_id}-locator-checks.json"),
            **result,
        }
    elif args.command == "hunt":
        payload = run_hunt(
            config,
            Path(args.repo_root),
            collector=args.collector,
            taskspace=args.taskspace,
            target_leads=args.target_leads,
            max_candidates=args.max_candidates,
            max_batches=args.max_batches,
            run_id=args.run_id,
            codex=args.codex,
        )
    elif args.command == "import-antigravity":
        payload = import_antigravity(Path(args.source), config.data_root, args.session_id)
    elif args.command == "approve":
        payload = approve_lead(config, args.run_id, args.lead_id, approved_by=args.approved_by, draft_text=args.draft_text)
    elif args.command == "daily":
        payload = run_daily(
            config,
            Path(args.repo_root),
            taskspace=args.taskspace,
            submit_approved=args.submit_approved,
            run_id=args.run_id,
            skip_crawl=args.skip_crawl,
            codex=args.codex,
            max_candidates=args.max_candidates,
        )
    elif args.command == "prepare-dispatch":
        store = RadarStore(config.data_root / "radar.sqlite3")
        store.initialize()
        items = build_dispatch_queue(store.load_leads(args.run_id), args.selection)
        store.close()
        output = Path(args.output) if args.output else config.data_root / "dispatch" / f"{args.run_id}-{args.selection}.jsonl"
        write_dispatch_queue(output, items)
        payload = {"run_id": args.run_id, "selection": args.selection, "queue_path": str(output), "count": len(items)}
    elif args.command == "dispatch":
        queue_path = Path(args.queue)
        items = load_dispatch_queue(queue_path)
        results = dispatch_queue(
            items,
            taskspace=args.taskspace,
            submit=args.submit,
            max_sends=args.max_sends,
            cooldown_seconds=args.cooldown_seconds,
        )
        output = Path(args.output) if args.output else config.data_root / "dispatch" / f"dispatch-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"
        write_dispatch_results(output, results)
        payload = {
            "queue_path": str(queue_path),
            "result_path": str(output),
            "mode": "submit" if args.submit else "dry_run",
            "submitted": sum(item["status"] == "submitted" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
        }
    else:
        path = report_store(config, args.run_id, args.output_suffix)
        payload = {"run_id": args.run_id, "report_path": str(path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
