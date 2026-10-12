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
from .dispatch import (
    build_dispatch_queue,
    dispatch_queue,
    filter_previously_queued,
    load_dispatch_queue,
    write_dispatch_audit,
    write_dispatch_queue,
    write_dispatch_results,
)
from .storage import RadarStore
from .antigravity_import import import_antigravity
from .approval import approve_lead
from .daily import run_daily
from .cleaning import clean_store
from .manual_candidates import build_manual_candidates, write_manual_candidate_artifacts
from .qna_batch import build_locator_rows, collect_qna_pool, write_locator_queue, write_qna_pool
from .handoff import export_handoff
from .takeover import write_takeover
from .zigo_discovery import read_raw, run_discovery, screen_record
from .zigo_keywords import build_keyword_registry
from .zigo_store import ZigoStore
from .reply_signals import append_reply_signal


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
        platform_keywords = {platform: dict(values) for platform, values in config.platform_keywords.items()}
        for platform in (args.platform or config.platforms):
            platform_keywords[platform] = dict(keywords)
        updates["platform_keywords"] = platform_keywords
        # An explicit --keyword is a focused run. Taxonomy expansion can
        # be re-enabled explicitly with --taxonomy-tier.
        updates["taxonomy_enabled"] = False
    taxonomy_tiers = getattr(args, "taxonomy_tier", None)
    if taxonomy_tiers:
        updates["taxonomy_enabled"] = True
        updates["taxonomy_tiers"] = tuple(taxonomy_tiers)
        if config.taxonomy_snapshot:
            updates["taxonomy_keywords"] = config.taxonomy_snapshot.query_map(taxonomy_tiers)
    if getattr(args, "no_taxonomy", False):
        updates["taxonomy_enabled"] = False
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
    for name in ("collect", "ingest", "analyze", "report", "prefilter", "manual-candidates", "enrich", "review", "pipeline"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", required=True)
        if name != "collect" and name != "pipeline":
            sub.add_argument("--run-id", required=True)
        if name == "report":
            sub.add_argument("--output-suffix", default="", help="报告文件名后缀，例如 fixed")
            sub.add_argument("--taskspace", type=int, required=True)
    collect_parser = subparsers.choices["collect"]
    collect_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    collect_parser.add_argument("--platform", action="append", help="只运行指定平台，可重复传入")
    collect_parser.add_argument("--keyword", action="append", help="只运行指定关键词，可重复传入")
    collect_parser.add_argument("--max-contents", type=int)
    collect_parser.add_argument("--max-comments", type=int)
    collect_parser.add_argument("--task-timeout-seconds", type=int)
    collect_parser.add_argument("--collector", choices=("ego",))
    collect_parser.add_argument("--taskspace", type=int, required=True, help="用户已登录的 Ego Lite TaskSpace")
    collect_parser.add_argument("--taxonomy-tier", action="append", choices=("tier1_primary", "tier2_verify_demand", "tier3_experimental"), help="启用 Antigravity 词库层级，可重复传入")
    collect_parser.add_argument("--no-taxonomy", action="store_true", help="关闭内置 Antigravity 词库扩展")
    prefilter_parser = subparsers.choices["prefilter"]
    prefilter_parser.add_argument("--max-candidates", type=int, default=50)
    manual_parser = subparsers.choices["manual-candidates"]
    manual_parser.add_argument("--max-candidates", type=int, default=50)
    qna_parser = subparsers.add_parser("qna-batch")
    qna_parser.add_argument("--config", required=True)
    qna_parser.add_argument("--run-id", required=True, help="本轮Q&A批次标识，不要求已存在SQLite runs记录")
    qna_parser.add_argument("--target", type=int, default=50)
    qna_parser.add_argument("--pool-size", type=int, default=80)
    enrich_parser = subparsers.choices["enrich"]
    enrich_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    enrich_parser.add_argument("--taskspace", type=int, required=True)
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
    pipeline_parser.add_argument("--taxonomy-tier", action="append", choices=("tier1_primary", "tier2_verify_demand", "tier3_experimental"), help="覆盖 Antigravity 词库层级，可重复传入")
    pipeline_parser.add_argument("--no-taxonomy", action="store_true", help="关闭内置 Antigravity 词库扩展")
    benchmark_parser = subparsers.add_parser("benchmark")
    benchmark_parser.add_argument("--config", required=True)
    benchmark_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    benchmark_parser.add_argument("--platform", required=True, choices=("dy", "xhs", "bili", "zhihu"))
    benchmark_parser.add_argument("--keyword", action="append", help="覆盖默认基准关键词，可重复传入")
    urls_parser = subparsers.add_parser("validate-urls")
    urls_parser.add_argument("--config", required=True)
    urls_parser.add_argument("--run-id", required=True)
    urls_parser.add_argument("--taskspace", type=int, required=True)
    locate_parser = subparsers.add_parser("locate")
    locate_parser.add_argument("--config", required=True)
    locate_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    locate_parser.add_argument("--run-id", required=True)
    locate_parser.add_argument("--taskspace", type=int, required=True)
    locate_parser.add_argument("--max-candidates", type=int, default=80)
    clean_parser = subparsers.add_parser("clean")
    clean_parser.add_argument("--config", required=True)
    clean_parser.add_argument("--run-id", required=True)
    clean_parser.add_argument("--reply-evidence")
    clean_parser.add_argument("--output-suffix", default="send-cleaned")
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
    hunt_parser.add_argument("--taxonomy-tier", action="append", choices=("tier1_primary", "tier2_verify_demand", "tier3_experimental"), help="覆盖 Antigravity 词库层级，可重复传入")
    prepare_dispatch_parser = subparsers.add_parser("prepare-dispatch")
    prepare_dispatch_parser.add_argument("--config", required=True)
    prepare_dispatch_parser.add_argument("--run-id", required=True)
    prepare_dispatch_parser.add_argument("--selection", choices=("manual", "model"), default="manual")
    prepare_dispatch_parser.add_argument("--output")
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--config", required=True)
    dispatch_parser.add_argument("--queue", required=True)
    dispatch_parser.add_argument("--taskspace", type=int, required=True)
    dispatch_parser.add_argument("--page", default="p1", help="Ego Lite TaskSpace 内的页面标签，例如 p2")
    dispatch_parser.add_argument("--submit", action="store_true", help="真实发送；省略时仅执行 Dry-Run")
    dispatch_parser.add_argument("--own-account", default="", help="真实发送使用的已核实我方账号")
    dispatch_parser.add_argument("--max-sends", type=int, default=0, help="最多发送条数；0表示不设任务条数上限")
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
    approve_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    approve_parser.add_argument("--taskspace", type=int, help="使用同一 Ego Lite TaskSpace 校验内容URL")
    daily_parser = subparsers.add_parser("daily")
    daily_parser.add_argument("--config", required=True)
    daily_parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    daily_parser.add_argument("--taskspace", type=int, required=True)
    daily_parser.add_argument("--run-id")
    daily_parser.add_argument("--skip-crawl", action="store_true")
    daily_parser.add_argument("--submit-approved", action="store_true", help="仅发送已人工批准且已定位/验链的公开楼中楼")
    daily_parser.add_argument("--max-candidates", type=int, default=50)
    daily_parser.add_argument("--codex", default="codex")
    handoff_parser = subparsers.add_parser("handoff-export")
    handoff_parser.add_argument("--config", required=True)
    handoff_parser.add_argument("--campaign", required=True, help="交接批次名，例如 polyv-100")
    handoff_parser.add_argument("--queue", help="严格发送队列；省略时按 campaign 唯一匹配")
    handoff_parser.add_argument("--results", help="发送结果 JSONL；省略时使用匹配的 live 结果")
    handoff_parser.add_argument("--quality-review", help="质量复核 JSONL；省略时读取数据目录 review/<campaign>-quality-review.jsonl")
    handoff_parser.add_argument("--dry-run", action="store_true", help="只计算基线和哈希，不写入快照")
    takeover_parser = subparsers.add_parser("takeover-sync")
    takeover_parser.add_argument("--config", required=True)
    takeover_parser.add_argument("--campaign", default="polyv-100")
    signal_parser = subparsers.add_parser("record-reply-signal")
    signal_parser.add_argument("--config", required=True)
    signal_parser.add_argument("--data-root")
    signal_parser.add_argument("--platform", required=True)
    signal_parser.add_argument("--url", required=True)
    signal_parser.add_argument("--author", required=True)
    signal_parser.add_argument("--quote", required=True)
    signal_parser.add_argument("--wave", type=int, default=1)
    signal_parser.add_argument("--observed-at", default="")
    obsidian_parser = subparsers.add_parser("export-obsidian", help="导出累计发送大板为 Obsidian Base + 线索笔记")
    obsidian_parser.add_argument("--config", required=True)
    obsidian_parser.add_argument("--vault", default="/Users/sexpistole111/Documents/claude學習/bugbg", help="Obsidian Vault 根目录")
    obsidian_parser.add_argument("--folder", default="Poly/雷达", help="Vault 内输出目录")
    obsidian_parser.add_argument("--data-root", help="覆盖配置里的数据目录")
    obsidian_parser.add_argument("--force-layout", action="store_true", help="覆盖已存在的 base 与索引布局文件")
    zigo_keywords_parser = subparsers.add_parser("zigo-keywords")
    zigo_keywords_parser.add_argument("--config", required=True)
    zigo_keywords_parser.add_argument("--knowledge-root", required=True)
    zigo_keywords_parser.add_argument("--output")
    zigo_keywords_parser.add_argument("--persist", action="store_true")
    zigo_ingest_parser = subparsers.add_parser("zigo-ingest")
    zigo_ingest_parser.add_argument("--config", required=True)
    zigo_ingest_parser.add_argument("--run-id", required=True)
    zigo_ingest_parser.add_argument("--checks")
    zigo_ingest_parser.add_argument("--keyword-registry")
    zigo_discover_parser = subparsers.add_parser("zigo-discover")
    zigo_discover_parser.add_argument("--config", required=True)
    zigo_discover_parser.add_argument("--product", choices=("sales_agent", "geo"), required=True)
    zigo_discover_parser.add_argument("--run-id", required=True)
    zigo_discover_parser.add_argument("--taskspace", type=int)
    zigo_discover_parser.add_argument("--platform", action="append", choices=("xhs", "dy", "bili", "zhihu"))
    zigo_discover_parser.add_argument("--keyword", action="append")
    zigo_discover_parser.add_argument("--collect", action="store_true")
    zigo_discover_parser.add_argument("--checks", type=Path)
    zigo_discover_parser.add_argument("--keyword-registry", type=Path)
    zigo_discover_parser.add_argument("--query-limit", type=int)
    zigo_discover_parser.add_argument(
        "--query-kind", action="append",
        choices=("base", "practice_scenario", "buyer_demand", "purchase_intent"),
        help="只运行指定类型的注册表 query，可重复传入",
    )
    zigo_discover_parser.add_argument("--target", type=int, default=10)
    zigo_discover_parser.add_argument("--product-root", type=Path, default=Path('/Volumes/GameSSD-Dev/CodexProjects/home/Users/sexpistole111/Documents/GOODS/ZIgoAI'))
    campaign_parser = subparsers.add_parser("customer-campaign", help="POLYV 企业客户作业账本")
    campaign_parser.add_argument("--config", required=True)
    campaign_parser.add_argument("--campaign-id", required=True)
    campaign_parser.add_argument("--action", choices=("init", "import", "report", "exchange"), default="report")
    campaign_parser.add_argument("--sector", default="企业管理培训与内训服务机构")
    campaign_parser.add_argument("--input", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    if args.command == "customer-campaign":
        from .customer_campaign_artifacts import run_customer_campaign
        payload = run_customer_campaign(config, args)
    elif args.command == "collect":
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
    elif args.command == "manual-candidates":
        store = RadarStore(config.data_root / "radar.sqlite3")
        store.initialize()
        candidates = build_manual_candidates(
            store.iter_contents(args.run_id),
            store.iter_comments(args.run_id),
            max_candidates=args.max_candidates,
            recent_days=config.recent_days,
            max_age_days=config.max_lead_age_days,
            excluded_author_names=config.excluded_author_names,
            negative_terms=config.taxonomy_negative_terms,
        )
        artifacts = write_manual_candidate_artifacts(config.data_root, args.run_id, candidates)
        store.close()
        payload = {
            "run_id": args.run_id,
            "manual_candidate_count": len(candidates),
            **{key: str(value) for key, value in artifacts.items()},
        }
    elif args.command == "qna-batch":
        rows = collect_qna_pool(config, target=args.target, pool_size=max(args.pool_size, args.target))
        artifacts = write_qna_pool(config.data_root, args.run_id, rows)
        locator_input = write_locator_queue(config.data_root, args.run_id, build_locator_rows(rows))
        payload = {
            "run_id": args.run_id,
            "target": args.target,
            "pool_count": len(rows),
            "locator_input": str(locator_input),
            **{key: str(value) for key, value in artifacts.items()},
        }
    elif args.command == "enrich":
        result = enrich_store(config, Path(args.repo_root), args.run_id, taskspace=args.taskspace)
        payload = {"run_id": args.run_id, **result}
    elif args.command == "review":
        result = review_store(config, args.run_id, codex=args.codex)
        payload = {"run_id": args.run_id, **result}
    elif args.command == "pipeline":
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        taxonomy_tiers = getattr(args, "taxonomy_tier", None)
        if taxonomy_tiers:
            config = replace(
                config,
                taxonomy_enabled=True,
                taxonomy_tiers=tuple(taxonomy_tiers),
                taxonomy_keywords=config.taxonomy_snapshot.query_map(taxonomy_tiers) if config.taxonomy_snapshot else {},
            )
        elif getattr(args, "no_taxonomy", False):
            config = replace(config, taxonomy_enabled=False)
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
        if args.taskspace is None:
            parser.error("pipeline 进行主页/公开背景调查时必须提供 --taskspace")
        enrich_store(config, Path(args.repo_root), run_id, taskspace=args.taskspace)
        review_result = review_store(config, run_id, codex=args.codex)
        report_path = report_store(config, run_id, "pipeline", taskspace=args.taskspace)
        payload = {"run_id": run_id, "report_path": str(report_path), **review_result}
    elif args.command == "benchmark":
        parser.error("benchmark 已停用：当前规则要求所有页面操作仅使用 Ego Lite。")
    elif args.command == "validate-urls":
        report_path = report_store(config, args.run_id, "url-validated", taskspace=args.taskspace)
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
        report_path = report_store(config, args.run_id, "located", taskspace=args.taskspace)
        payload = {
            "run_id": args.run_id,
            "report_path": str(report_path),
            "locator_checks_path": str(config.data_root / "reports" / f"{args.run_id}-locator-checks.json"),
            **result,
        }
    elif args.command == "clean":
        payload = clean_store(
            config,
            args.run_id,
            reply_evidence_path=Path(args.reply_evidence) if args.reply_evidence else None,
            output_suffix=args.output_suffix,
        )
    elif args.command == "hunt":
        taxonomy_tiers = getattr(args, "taxonomy_tier", None)
        if taxonomy_tiers:
            config = replace(
                config,
                taxonomy_enabled=True,
                taxonomy_tiers=tuple(taxonomy_tiers),
                taxonomy_keywords=config.taxonomy_snapshot.query_map(taxonomy_tiers) if config.taxonomy_snapshot else {},
            )
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
        payload = approve_lead(
            config,
            args.run_id,
            args.lead_id,
            approved_by=args.approved_by,
            draft_text=args.draft_text,
            repo_root=Path(args.repo_root),
            taskspace=args.taskspace,
        )
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
    elif args.command == "handoff-export":
        payload = export_handoff(
            config.data_root,
            args.campaign,
            Path(__file__).resolve().parents[2],
            queue_path=Path(args.queue) if args.queue else None,
            results_path=Path(args.results) if args.results else None,
            quality_review_path=Path(args.quality_review) if args.quality_review else None,
            write=not args.dry_run,
        )
    elif args.command == "takeover-sync":
        json_path, markdown_path, result = write_takeover(config.data_root, args.campaign)
        payload = {
            "campaign": args.campaign,
            "ready": result["ready"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
            "counts": result["counts"],
            "priority_counts": result["priority_counts"],
        }
    elif args.command == "record-reply-signal":
        if args.wave < 1:
            parser.error("--wave 必须大于等于 1")
        data_root = Path(args.data_root) if args.data_root else config.data_root
        payload = append_reply_signal(
            data_root,
            {
                "platform": args.platform,
                "target_url": args.url,
                "target_author": args.author,
                "quote": args.quote,
                "wave": args.wave,
                "observed_at": args.observed_at,
            },
        )
        from .cumulative_dashboard import render_from_sources

        ledger = data_root / "reply_history.jsonl"
        board = data_root / "reports" / "all-sent-leads-dashboard.html"
        if ledger.is_file():
            html, view = render_from_sources(ledger, data_root)
            board.parent.mkdir(parents=True, exist_ok=True)
            board.write_text(html, encoding="utf-8")
            payload["dashboard"] = str(board)
            payload["unique_targets"] = view.target_count
    elif args.command == "export-obsidian":
        from .obsidian_export import export_to_vault

        data_root = Path(args.data_root) if args.data_root else config.data_root
        ledger = data_root / "reply_history.jsonl"
        if not ledger.is_file():
            parser.error(f"找不到发送账本: {ledger}")
        payload = export_to_vault(
            ledger,
            data_root,
            vault_root=Path(args.vault),
            folder=args.folder,
            force_layout=args.force_layout,
        )
    elif args.command == "zigo-discover":
        if args.collect and (not args.taskspace or args.taskspace <= 0):
            parser.error("zigo-discover --collect 需要显式提供已登录的 Ego Lite TaskSpace")
        payload = run_discovery(
            Path(args.config),
            args.product,
            args.run_id,
            taskspace=args.taskspace,
            platforms=args.platform,
            keywords=args.keyword,
            collect=args.collect,
            checks_path=args.checks,
            keyword_registry=args.keyword_registry,
            product_root=args.product_root,
            query_limit=args.query_limit,
            query_kinds=args.query_kind,
            target=args.target,
        )
    elif args.command == "zigo-keywords":
        output = Path(args.output) if args.output else config.data_root.parent / "keyword-registry.json"
        result = build_keyword_registry(Path(args.knowledge_root), output)
        if args.persist:
            registry = json.loads(output.read_text(encoding="utf-8"))
            store = ZigoStore(config.data_root.parent / "radar.sqlite3")
            result["persisted"] = store.save_keyword_sources(registry.get("keywords", []))
            store.close()
        payload = result
    elif args.command == "zigo-ingest":
        if config.product_profile not in {"zigo_sales", "zigo_geo"}:
            parser.error("zigo-ingest 需要 zigo_sales 或 zigo_geo 配置")
        product = "sales_agent" if config.product_profile == "zigo_sales" else "geo"
        raw_path = config.data_root / "raw" / args.run_id
        records = read_raw(raw_path)
        screened = [screen_record(row, product) for row in records]
        checks = json.loads(Path(args.checks).read_text(encoding="utf-8")) if args.checks else []
        store = ZigoStore(config.data_root.parent / "radar.sqlite3")
        keyword_rows = []
        if args.keyword_registry:
            keyword_rows = json.loads(Path(args.keyword_registry).read_text(encoding="utf-8")).get("keywords", [])
        payload = store.ingest_run(args.run_id, product, records, screened, checks, keyword_rows)
        store.close()
    elif args.command == "prepare-dispatch":
        store = RadarStore(config.data_root / "radar.sqlite3")
        store.initialize()
        items = build_dispatch_queue(store.load_leads(args.run_id), args.selection)
        store.close()
        output = Path(args.output) if args.output else config.data_root / "dispatch" / f"{args.run_id}-{args.selection}.jsonl"
        items, skipped = filter_previously_queued(items, config.data_root)
        write_dispatch_queue(output, items)
        audit_path = config.data_root / "dispatch" / f"audit-{args.run_id}-{args.selection}-duplicates.jsonl"
        write_dispatch_audit(audit_path, skipped)
        payload = {
            "run_id": args.run_id,
            "selection": args.selection,
            "queue_path": str(output),
            "count": len(items),
            "skipped_duplicates": len(skipped),
            "duplicates_path": str(audit_path),
        }
    elif args.command == "dispatch":
        queue_path = Path(args.queue)
        items = load_dispatch_queue(queue_path)
        results = dispatch_queue(
            items,
            taskspace=args.taskspace,
            submit=args.submit,
            max_sends=None if args.max_sends == 0 else args.max_sends,
            cooldown_seconds=args.cooldown_seconds,
            page=args.page,
            own_account=args.own_account,
        )
        output = Path(args.output) if args.output else config.data_root / "dispatch" / f"dispatch-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"
        write_dispatch_results(output, results)
        payload = {
            "queue_path": str(queue_path),
            "result_path": str(output),
            "mode": "submit" if args.submit else "dry_run",
            "submitted": sum(item["status"] == "submitted_verified" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
        }
    else:
        path = report_store(config, args.run_id, args.output_suffix, taskspace=args.taskspace)
        payload = {"run_id": args.run_id, "report_path": str(path)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
