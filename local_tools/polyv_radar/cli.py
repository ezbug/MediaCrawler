from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .runner import analyze_store, collect, ingest_existing_run, report_store


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(Path(args.config))
    if args.command == "collect":
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
