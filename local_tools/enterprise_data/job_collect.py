"""招聘平台采集（Ego Lite 驱动，只读）。

调用 ego_jobs 包装器，在用户已登录的 TaskSpace 中打开招聘页面并提取职位，
输出与 import-jobs 兼容的 JSON。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

WRAPPER = Path(__file__).with_name("ego_jobs")

PLATFORM_URLS = {
    "boss-search": "https://www.zhipin.com/web/geek/job?query={query}",
    "zhaopin-search": "https://sou.zhaopin.com/?kw={query}",
    "liepin-search": "https://www.liepin.com/zhaopin/?key={query}",
}


def build_command(
    *,
    taskspace: int,
    url: str,
    platform: str = "generic",
    page: str = "p1",
    scrolls: int = 3,
    max_jobs: int = 60,
) -> list[str]:
    if taskspace <= 0:
        raise ValueError("collect-jobs 必须显式提供 --taskspace")
    return [
        str(WRAPPER),
        "--taskspace", str(taskspace),
        "--page", page,
        "--url", url,
        "--platform", platform,
        "--scrolls", str(scrolls),
        "--max-jobs", str(max_jobs),
    ]


def parse_collector_output(stdout: str, company_id: str) -> dict:
    """ego-browser 会把脚本输出写到 stderr，这里同时兼容 stdout/stderr。"""
    start = stdout.find('{"jobs"')
    if start < 0:
        start = stdout.find("{")
    if start < 0:
        raise ValueError(f"采集器未输出 JSON：{stdout[:200]}")
    payload = json.loads(stdout[start:])
    jobs = payload.get("jobs") or []
    return {
        "company_id": company_id,
        "jobs": jobs,
        "_extraction": payload.get("_extraction") or {},
    }


def collect_jobs(
    *,
    company_id: str,
    url: str,
    taskspace: int,
    platform: str = "generic",
    page: str = "p1",
    scrolls: int = 3,
    max_jobs: int = 60,
    employer_filter: str = "",
    output: Path | None = None,
    runner=subprocess.run,
) -> dict:
    command = build_command(taskspace=taskspace, url=url, platform=platform, page=page, scrolls=scrolls, max_jobs=max_jobs)
    completed = runner(command, capture_output=True, text=True, timeout=180)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined = stdout + "\n" + stderr
    if completed.returncode != 0 and '{"jobs"' not in combined:
        raise RuntimeError(f"采集器退出码 {completed.returncode}：{(stderr or stdout)[-300:]}")
    payload = parse_collector_output(combined, company_id)
    if employer_filter:
        kept = []
        dropped = []
        for job in payload["jobs"]:
            employer = str(job.get("employer_name") or "")
            if employer and employer_filter not in employer:
                dropped.append(employer)
            else:
                kept.append(job)
        payload["_extraction"].setdefault("warnings", [])
        if dropped:
            payload["_extraction"]["warnings"].append(f"按雇主过滤剔除 {len(dropped)} 条非目标雇主职位")
        payload["_extraction"]["employer_filter"] = employer_filter
        payload["_extraction"]["dropped_employers"] = sorted(set(dropped))[:10]
        payload["jobs"] = kept
    if output:
        Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="招聘平台职位采集（Ego Lite，只读）")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--url", help="职位列表 URL（与 --search 二选一）")
    parser.add_argument("--search", choices=sorted(PLATFORM_URLS), help="内置平台搜索模板")
    parser.add_argument("--query", help="搜索关键词（公司名），配合 --search 使用")
    parser.add_argument("--platform", default="generic", help="平台标识：boss/zhaopin/liepin/moka/generic")
    parser.add_argument("--taskspace", type=int, required=True)
    parser.add_argument("--page", default="p1")
    parser.add_argument("--scrolls", type=int, default=3)
    parser.add_argument("--max-jobs", type=int, default=60)
    parser.add_argument("--employer-filter", default="", help="只保留雇主名或标题包含该关键词的职位（如公司简称）")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    url = args.url
    if not url and args.search:
        if not args.query:
            parser.error("--search 需要 --query")
        from urllib.parse import quote

        url = PLATFORM_URLS[args.search].format(query=quote(args.query))
    if not url:
        parser.error("需要 --url 或 --search")

    payload = collect_jobs(
        company_id=args.company_id, url=url, taskspace=args.taskspace, platform=args.platform,
        page=args.page, scrolls=args.scrolls, max_jobs=args.max_jobs,
        employer_filter=args.employer_filter,
        output=Path(args.output) if args.output else None,
    )
    print(json.dumps({
        "output": args.output,
        "jobs": len(payload["jobs"]),
        "url": payload["_extraction"].get("url"),
        "warnings": payload["_extraction"].get("warnings"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
